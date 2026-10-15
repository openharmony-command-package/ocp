#!/usr/bin/env python3
"""Build an extensible OpenHarmony native package using the official SDK tools."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
MACHINES = {"arm64-v8a": 183, "x86_64": 62, "armeabi-v7a": 40}


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def validate_tool_hap(path, entry, tap):
    """Check the actual install payload against the published tool identity."""
    suffix = entry['name'] if tap == 'core' else f"{tap}.{entry['name']}"
    expected_bundle = f'com.richerfu.ocp.pkg.{suffix}'
    hnp_name = entry['hnp_name']
    with zipfile.ZipFile(path) as archive:
        config = json.loads(archive.read('module.json'))
        forbidden = ('abilities','extensionAbilities','requestPermissions','definePermissions')
        if config['app']['bundleName'] != expected_bundle or config['app']['versionName'] != entry['version'] or any(config['module'].get(key) for key in forbidden):
            raise ValueError('Tool HAP identity, version or UI mismatch')
        packages = config['module'].get('hnpPackages', [])
        if packages != [{'package':hnp_name+'.hnp','type':'public'}]:
            raise ValueError('Unexpected HNP declaration')
        with zipfile.ZipFile(io.BytesIO(archive.read(f"hnp/{entry['abi']}/{hnp_name}.hnp"))) as native:
            native_config = json.loads(native.read(hnp_name+'/hnp.json'))
            if native_config['name'] != hnp_name or native_config['version'] != entry['version']:
                raise ValueError('HNP identity mismatch')
            links = native_config['install']['links']
            commands = [link['target'] for link in links]
            if len(commands) != len(set(commands)) or set(commands) != set(entry['commands']) or {'ocp','ocp-maker','ocp-bm'}.intersection(commands):
                raise ValueError('HNP command declarations disagree with the registry')
            for link in links:
                source = relative_path(link['source'])
                with native.open(hnp_name+'/'+str(source)) as stream:
                    header = stream.read(20)
                if header.startswith(b'#!/system/bin/sh\n'):
                    continue
                if len(header) < 20 or header[:4] != b'\x7fELF' or int.from_bytes(header[18:20],'little') != MACHINES[entry['abi']]:
                    raise ValueError('HNP command ABI mismatch')


def manifest():
    data = json.loads((ROOT / "ocp.json").read_text())
    for value in (data["name"], data["version"]):
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value):
            raise ValueError(f"Invalid HNP name or version: {value}")
    return data


def sdk_path():
    for variable in ("OCP_SDK", "OHOS_SDK_HOME", "OHOS_NDK_HOME"):
        if os.environ.get(variable):
            path = Path(os.environ[variable]).expanduser()
            if (path / "toolchains/hnpcli").is_file():
                return path
            raise ValueError(f"{variable} must point to the openharmony SDK directory")
    candidates = list(Path.home().glob(".meat/ide/DevEco-Studio-*.app/Contents/sdk/default/openharmony"))
    candidates += [Path("/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony")]
    for path in sorted(candidates, reverse=True):
        if (path / "toolchains/hnpcli").is_file():
            return path
    raise ValueError("Set OCP_SDK to the SDK directory containing toolchains/hnpcli")


def java_tool(sdk, name):
    java = os.environ.get("OCP_JAVA")
    if not java:
        bundled = sdk.parents[2] / "jbr/Contents/Home/bin/java"
        java = str(bundled) if bundled.is_file() else shutil.which("java")
    if not java:
        raise ValueError("Java is required; set OCP_JAVA or add java to PATH")
    return [java, "-jar", sdk / "toolchains/lib" / name]


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Expected a package-relative path: {value}")
    return path


def component_source(component, abi):
    if "source_dir" in component:
        directory = Path(component["source_dir"].format(abi=abi)).expanduser()
        if not directory.is_absolute():
            directory = ROOT / directory
        if not directory.is_dir():
            raise ValueError(f"Missing component source: {directory}")
        return directory, {"source_dir": str(directory)}
    asset = component["assets"][abi]
    filename = asset["url"].rsplit("/", 1)[-1]
    archive = ROOT / ".cache/downloads" / asset["sha256"] / filename
    archive.parent.mkdir(parents=True, exist_ok=True)
    for cached in (ROOT / ".cache/downloads" / filename, ROOT / ".cache/downloads" / component["version"] / filename):
        if not archive.is_file() and cached.is_file() and digest(cached) == asset["sha256"]:
            shutil.copy2(cached, archive)
    if not archive.is_file() or digest(archive) != asset["sha256"]:
        temporary = archive.with_suffix(archive.suffix + ".part")
        run(["curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "20",
             "--output", temporary, asset["url"]])
        if digest(temporary) != asset["sha256"]:
            temporary.unlink()
            raise ValueError(f"SHA-256 mismatch: {filename}")
        temporary.replace(archive)
    extraction = ROOT / ".cache/sources" / asset["sha256"]
    source = extraction / relative_path(asset["root"])
    if not (extraction / ".complete").is_file():
        if extraction.exists():
            shutil.rmtree(extraction)
        extraction.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            # Toolchain archives contain only regular files and directories.
            for member in tar.getmembers():
                relative_path(member.name)
                if not (member.isfile() or member.isdir()):
                    raise ValueError(f"Unsupported archive member: {member.name}")
            tar.extractall(extraction)
        (extraction / ".complete").touch()
    return source, asset


def check_elf(path, abi):
    with path.open("rb") as stream:
        header = stream.read(20)
    if header[:4] != b"\x7fELF" or header[5] != 1:
        raise ValueError(f"Command must be a little-endian ELF executable: {path}")
    if int.from_bytes(header[18:20], "little") != MACHINES[abi]:
        raise ValueError(f"Command architecture does not match {abi}: {path}")
    if not path.stat().st_mode & 0o111:
        raise ValueError(f"Command lacks executable permission: {path}")


def check_command(path, abi, kind="elf"):
    if kind == "elf":
        return check_elf(path, abi)
    if kind != "script" or not path.read_bytes().startswith(b"#!/system/bin/sh\n"):
        raise ValueError(f"Unsupported command type: {path}")
    if not path.stat().st_mode & 0o111:
        raise ValueError(f"Script lacks executable permission: {path}")


def components():
    return [json.loads(path.read_text()) for path in sorted((ROOT / "installer").glob("*/component.json"))
            if (path.parent / "assemble.sh").is_file()]


def configuration_digest():
    checksum = hashlib.sha256()
    paths = [ROOT / "ocp.json"]
    paths += [path for path in sorted((ROOT / "installer").rglob("*"))
              if path.is_file() and path.suffix in (".sh", ".json", ".py", ".patch", ".pem", ".cpp", ".h")]
    for path in paths:
        checksum.update(str(path.relative_to(ROOT)).encode())
        checksum.update(path.read_bytes())
    return checksum.hexdigest()


def prepare(abi):
    stage = ROOT / "build" / abi / manifest()["name"]
    fragments = stage.parent / "components"
    for directory in (stage, fragments):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    return stage


def assemble_component(config, abi, stage, fragments):
    component = json.loads(config.read_text())
    name, version = component["name"], component["version"]
    for value in (name, version):
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value):
            raise ValueError(f"Invalid component name or version: {value}")
    if (fragments / f"{name}.json").exists():
        raise ValueError(f"Duplicate component name: {name}")
    source, provenance = component_source(component, abi)
    prefix = PurePosixPath("tools") / name / version
    destination = stage / prefix
    print(f"Assembling {name} {version} ({abi})", flush=True)
    shutil.copytree(source, destination, symlinks=True)
    for path in destination.rglob("*"):
        if path.is_symlink():
            resolved = path.resolve()
            if not resolved.is_relative_to(destination.resolve()) or resolved.is_dir():
                raise ValueError(f"Unsupported component symlink: {path}")
        else:
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    links = []
    for command, executable in component["commands"].items():
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.+-]*", command):
            raise ValueError(f"Invalid command name: {command}")
        executable = relative_path(executable)
        check_command(destination / executable, abi, component.get("command_types", {}).get(command, "elf"))
        links.append({"source": str(prefix / executable), "target": command})
    write_json(fragments / f"{name}.json", {"name": name, "version": version,
        "commands": component["commands"], "command_types": component.get("command_types", {}),
        "links": links, "provenance": provenance})


def pack(abi, data=None, stage=None, output=None):
    data = manifest() if data is None else data
    stage = ROOT / "build" / abi / data["name"] if stage is None else stage
    fragments = stage.parent / "components"
    inventory = [json.loads(path.read_text()) for path in sorted(fragments.glob("*.json"))]
    if not inventory:
        raise ValueError("No installer registered a component")
    unexpected = [path.name for path in stage.iterdir() if path.name != "tools"]
    if unexpected:
        raise ValueError(f"Installers must assemble under tools/; unexpected: {unexpected}")
    links = []
    commands = set()
    for component in inventory:
        for link in component.pop("links"):
            if link["target"] in commands:
                raise ValueError(f"Duplicate exported command: {link['target']}")
            commands.add(link["target"])
            check_command(stage / relative_path(link["source"]), abi,
                          component.get("command_types", {}).get(link["target"], "elf"))
            links.append(link)
    write_json(stage / "hnp.json", {"type": "hnp-config", "name": data["name"],
                                  "version": data["version"], "install": {"links": links}})
    write_json(stage / "ocp-manifest.json", {"name": data["name"], "version": data["version"],
        "abi": abi, "assembly_sha256": configuration_digest(), "components": inventory})
    output = ROOT / "dist" / abi if output is None else output
    output.mkdir(parents=True, exist_ok=True)
    run([sdk_path() / "toolchains/hnpcli", "pack", "-i", stage, "-o", output])
    package = output / f"{data['name']}.hnp"
    with zipfile.ZipFile(package) as archive:
        if len(archive.infolist()) > 65535 or archive.testzip() is not None:
            raise ValueError("Invalid HNP archive")
        for link in links:
            archive.getinfo(f"{stage.name}/{link['source']}")
    if package.stat().st_size >= 2 ** 32:
        raise ValueError("HNP exceeds the 4 GiB format limit")
    (output / f"{package.name}.sha256").write_text(f"{digest(package)}  {package.name}\n")
    print(f"Built {package} ({package.stat().st_size / 1024 / 1024:.1f} MiB)", flush=True)
    return package


def bottle(formula, version, abi, tap, config, debug_udid=None, signed_hap=None):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", tap):
        raise ValueError("Invalid tap namespace")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", formula):
        raise ValueError("Invalid formula name")
    config = config.resolve()
    directory = config.parent
    current = json.loads(config.read_text())
    if version != current["version"]:
        config = directory / "versions" / f"{version}.json"
    component = json.loads(config.read_text())
    if component["name"] != formula or component["version"] != version:
        raise ValueError("Formula identity mismatch")
    qualified = formula if tap == "core" else f"{tap}_{formula}"
    bundle_suffix = formula if tap == "core" else f"{tap}.{formula}"
    data = {"name": f"ocp_{qualified}", "version": version,
            "bundle_name": f"{manifest()['bundle_name']}.pkg.{bundle_suffix}",
            "version_code": sum(int(v) * m for v, m in zip(version.split('.'), [1000000, 1000, 1])) * 100 + 1}
    work = ROOT / "build/bottles" / tap / abi / formula / version
    if work.exists():
        shutil.rmtree(work)
    stage = work / data["name"]
    stage.mkdir(parents=True)
    (work / "components").mkdir()
    env = os.environ.copy()
    env.update(OCP_ROOT=str(ROOT), OCP_ABI=abi, OCP_STAGE=str(stage), OCP_METADATA_DIR=str(work / "components"),
               OCP_COMPONENT_CONFIG=str(config))
    run([directory / "assemble.sh"], env=env)
    base = ROOT / "dist/bottles" if tap == "core" else ROOT / "dist/bottles" / tap
    output = base / abi / formula / version
    package = pack(abi, data, stage, output)
    installer = wrap_hap(package, data, abi, work / "hap", output / f"{formula}.hap")
    if debug_udid:
        from sign_debug import DebugSigner
        installer.rename(work / 'unsigned.hap')
        installer = DebugSigner(debug_udid).sign(work/'unsigned.hap', installer)
    elif signed_hap:
        # A trusted release job supplies its platform-approved signed HAP.
        # System BMS performs the actual certificate/profile verification.
        shutil.copy2(signed_hap, installer)
    receipt = {"name": formula, "tap": tap, "version": version, "abi": abi, "bundle": data["bundle_name"],
               "hnp_name": data["name"], "commands": list(component["commands"]),
               "hap_sha256": digest(installer), "upstream": component.get("release", "")}
    if component.get("publisher"):
        receipt['publisher'] = component['publisher']
    receipt['signing'] = 'emulator-debug' if debug_udid else 'provided-signed-hap' if signed_hap else 'unsigned-development'
    validate_tool_hap(installer, receipt, tap)
    write_json(output / "receipt.json", receipt)
    archive = output / f"{formula}-{version}-{abi}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
        zipped.write(installer, arcname=f"bottle/{formula}.hap")
        zipped.write(output / "receipt.json", arcname="bottle/receipt.json")
    (output / f"{archive.name}.sha256").write_text(f"{digest(archive)}  {archive.name}\n")
    print(f"Built bottle {archive}", flush=True)
    return archive


def publish(tap, base_url, output):
    """Publish a static, versioned registry snapshot from verified tool bottles."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", tap):
        raise ValueError("Invalid tap namespace")
    if not re.fullmatch(r"https?://[^\s]+", base_url):
        raise ValueError("Invalid repository base URL")
    source = ROOT / "dist/bottles" if tap == "core" else ROOT / "dist/bottles" / tap
    entries = []
    previous = {}
    if (output / 'catalog/registry.json').is_file():
        previous = {(entry['name'],entry['version'],entry['abi']):entry['hap_sha256']
                    for entry in json.loads((output/'catalog/registry.json').read_text())['packages']}
    for path in sorted(source.glob("*/*/*/receipt.json")):
        entry = json.loads(path.read_text())
        if entry.get("tap", "core") != tap:
            continue
        expected = f"com.richerfu.ocp.pkg.{entry['name']}" if tap == "core" else f"com.richerfu.ocp.pkg.{tap}.{entry['name']}"
        if entry["bundle"] != expected or digest(path.parent / f"{entry['name']}.hap") != entry["hap_sha256"]:
            raise ValueError(f"Bottle identity or checksum mismatch: {path}")
        validate_tool_hap(path.parent / f"{entry['name']}.hap", entry, tap)
        if {'ocp','ocp-maker','ocp-bm'}.intersection(entry['commands']):
            raise ValueError('Tool exports a reserved OCP command')
        old_sha = previous.get((entry['name'],entry['version'],entry['abi']))
        if old_sha and old_sha != entry['hap_sha256']:
            raise ValueError('Published versions are immutable; publish a new version')
        destination = output / "bottles" / entry["abi"] / entry["name"] / entry["version"]
        destination.mkdir(parents=True, exist_ok=True)
        for artifact in path.parent.iterdir():
            if artifact.suffix in (".zip", ".hap", ".json"):
                shutil.copy2(artifact, destination / artifact.name)
        entry = dict(entry, tap=tap, bottle_path=f"bottles/{entry['abi']}/{entry['name']}/{entry['version']}/{entry['name']}-{entry['version']}-{entry['abi']}.zip")
        entries.append(entry)
    if not entries:
        raise ValueError("No bottles found for this tap")
    latest = {}
    for entry in entries:
        key = entry["name"], entry["abi"]
        if key not in latest or tuple(map(int, entry["version"].split('.'))) > tuple(map(int, latest[key].split('.'))):
            latest[key] = entry["version"]
    rows = []
    for entry in entries:
        rows.append("\t".join([entry["name"], entry["version"], entry["abi"], entry["bundle"], entry["hap_sha256"],
                             base_url.rstrip('/') + '/' + entry["bottle_path"],
                             "1" if latest[entry["name"],entry["abi"]] == entry["version"] else "0", ','.join(entry["commands"])]))
    metadata = {"schema_version":2, "tap":tap, "packages":entries}
    payload = output / "catalog"
    payload.mkdir(parents=True, exist_ok=True)
    write_json(payload / "registry.json", metadata)
    (payload / "registry.tsv").write_text(f"2\t{tap}\n")
    (payload / "index.tsv").write_text('\n'.join(rows) + '\n')
    archive = output / "index.tar.gz"
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(payload.iterdir()):
            tar.add(path, arcname='catalog/' + path.name)
    (output / 'index.tar.gz.sha256').write_text(f'{digest(archive)}  index.tar.gz\n')
    print(f"Published registry {tap}: {archive}", flush=True)
    return archive


def ensure_hnp(abi):
    data = manifest()
    package = ROOT / "dist" / abi / f"{data['name']}.hnp"
    current = False
    if package.is_file():
        with zipfile.ZipFile(package) as archive:
            path = f"{data['name']}/ocp-manifest.json"
            if path in archive.namelist():
                current = json.loads(archive.read(path)).get("assembly_sha256") == configuration_digest()
    if not current:
        run([ROOT / "scripts/build-hnp.sh", "--abi", abi])
    return package


def wrap_hap(package, data, abi, work, unsigned):
    if work.exists():
        shutil.rmtree(work)
    hnp_directory = work / "hnp" / abi
    hnp_directory.mkdir(parents=True)
    shutil.copy2(package, hnp_directory / package.name)
    write_json(work / "module.json", {
        "app": {"bundleName": data["bundle_name"], "vendor": "ocp", "versionCode": data["version_code"],
                "versionName": data["version"], "minAPIVersion": 18, "targetAPIVersion": 24,
                "apiReleaseType": "Release", "debug": True, "bundleType": "app",
                "label": "OCP" if data["bundle_name"] == manifest()["bundle_name"] else data["name"].removeprefix("ocp_"),
                "icon": "", "hideDesktopIcon": True},
        "module": {"name": "entry", "type": "entry", "packageName": "entry",
                   "deviceTypes": ["2in1", "tablet", "phone"], "deliveryWithInstall": True,
                   "installationFree": False, "hnpPackages": [{"package": package.name, "type": "public"}]}
    })
    run(java_tool(sdk_path(), "app_packing_tool.jar") + ["--mode", "hap", "--json-path", work / "module.json",
        "--hnp-path", work / "hnp", "--out-path", unsigned, "--force", "true"])
    with zipfile.ZipFile(unsigned) as archive:
        if set(archive.namelist()) != {"module.json", f"hnp/{abi}/{package.name}"}:
            raise ValueError("The installation HAP must contain only metadata and HNP")
    (unsigned.parent / f"{unsigned.name}.sha256").write_text(f"{digest(unsigned)}  {unsigned.name}\n")
    print(f"Built headless installation package {unsigned}", flush=True)
    return unsigned


def hap(abi):
    data = manifest()
    package = ensure_hnp(abi)
    return wrap_hap(package, data, abi, ROOT / "build" / abi / "hap", package.parent / "ocp-unsigned.hap")


def hdc(args, *command):
    result = subprocess.run([os.environ.get("OCP_HDC", "hdc"), "-s", args.server, "-t", args.target,
                             *map(str, command)], check=True, capture_output=True, text=True,
                            timeout=180 if command and command[0] == "install" else 45)
    output = result.stdout + result.stderr
    if "[Fail]" in output or "Connect server failed" in output:
        raise ValueError(output.strip())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("build", "prepare", "pack", "hap", "component"):
        command = sub.add_parser(action)
        command.add_argument("--abi", choices=MACHINES, default="arm64-v8a")
        if action == "component":
            command.add_argument("--config", required=True, type=Path)
            command.add_argument("--stage", required=True, type=Path)
            command.add_argument("--metadata-dir", required=True, type=Path)
    command = sub.add_parser("bottle")
    command.add_argument("formula")
    command.add_argument("--version", required=True)
    command.add_argument("--abi", choices=MACHINES, default="arm64-v8a")
    command.add_argument("--tap", default="core")
    signing = command.add_mutually_exclusive_group()
    signing.add_argument("--debug-udid", help="Sign tools for this emulator using an SDK debug profile")
    signing.add_argument("--signed-hap", type=Path, help="Use a HAP already signed by the trusted release job")
    command.add_argument("--config", type=Path, required=True, help="Formula from the independent tool repository")
    command = sub.add_parser("publish")
    command.add_argument("--tap", required=True)
    command.add_argument("--base-url", required=True)
    command.add_argument("--output", type=Path, required=True)
    command = sub.add_parser("install")
    command.add_argument("--target", required=True)
    command.add_argument("--server", default="127.0.0.1:8710")
    args = parser.parse_args()
    if args.action == "build":
        run([ROOT / "scripts/build-hnp.sh", "--abi", args.abi])
    elif args.action == "prepare":
        print(prepare(args.abi))
    elif args.action == "component":
        assemble_component(args.config, args.abi, args.stage, args.metadata_dir)
    elif args.action == "pack":
        pack(args.abi)
    elif args.action == "hap":
        hap(args.abi)
    elif args.action == "bottle":
        bottle(args.formula, args.version, args.abi, args.tap, args.config, args.debug_udid, args.signed_hap)
    elif args.action == "publish":
        publish(args.tap, args.base_url, args.output)
    else:
        machine = hdc(args, "shell", "uname", "-m").strip()
        abi = {"aarch64": "arm64-v8a", "x86_64": "x86_64", "armv7l": "armeabi-v7a"}[machine]
        output = hdc(args, "install", "-r", hap(abi))
        print(output.strip(), flush=True)
        if "install bundle successfully" not in output:
            raise ValueError("Installation failed")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"ocp: {error}", file=sys.stderr)
        sys.exit(1)
