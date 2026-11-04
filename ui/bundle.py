#!/usr/bin/env python3
"""Bundle reviewed tool HNPs into an existing OCP manager installation HAP."""

import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ocp import digest, java_tool, manifest, relative_path, run, sdk_path, validate_tool_hap, write_json


def build(args):
    source = args.manager_hap.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.suffix != ".hap" or source == output:
        raise ValueError("Output must be a different .hap file")
    tools = []
    for directory in args.tool_bottle:
        directory = directory.expanduser().resolve()
        receipt = json.loads((directory / "receipt.json").read_text())
        tool = directory / (receipt["name"] + ".hap")
        if receipt["abi"] != args.abi or digest(tool) != receipt["hap_sha256"]:
            raise ValueError("Tool ABI or HAP checksum disagrees with its receipt")
        validate_tool_hap(tool, receipt, receipt["tap"])
        if output == tool:
            raise ValueError("Output must not overwrite a source tool HAP")
        tools.append((tool, receipt))

    output.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "build").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ocp-bundled-", dir=ROOT / "build") as temporary:
        work = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            if archive.testzip() is not None:
                raise ValueError("Invalid manager HAP")
            for member in archive.infolist():
                relative_path(member.filename)
            archive.extractall(work)
        config = json.loads((work / "module.json").read_text())
        if config["app"]["bundleName"] != manifest()["bundle_name"]:
            raise ValueError("Expected an OCP manager HAP")
        main = config["module"].get("mainElement")
        if main != "EntryAbility" or not any(
            ability["name"] == main and ability.get("launchType") == "singleton"
            for ability in config["module"].get("abilities", [])
        ):
            raise ValueError("Manager must retain its singleton UI entry")
        if args.no_permissions:
            # Filter the merged manifest so HAR dependencies cannot reintroduce
            # window permissions into the offline bundled-tool environment.
            config["module"].pop("requestPermissions", None)
        declarations = config["module"]["hnpPackages"]
        if declarations != [{"package": "ocp.hnp", "type": "public"}]:
            raise ValueError("Start with an ordinary manager containing only ocp.hnp")
        native = work / "hnp" / args.abi
        if not (native / "ocp.hnp").is_file():
            raise ValueError("Manager does not contain the selected ABI")
        names = {"ocp.hnp"}
        commands = {"ocp", "ocp-maker", "ocp-bm"}
        hashes = {"ocp.hnp": digest(native / "ocp.hnp")}
        for tool, receipt in tools:
            name = receipt["hnp_name"] + ".hnp"
            if name in names or commands.intersection(receipt["commands"]):
                raise ValueError("Duplicate HNP or exported command")
            with zipfile.ZipFile(tool) as archive:
                content = archive.read(f"hnp/{args.abi}/{name}")
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Invalid bundled HNP")
            (native / name).write_bytes(content)
            declarations.append({"package": name, "type": "public"})
            names.add(name)
            commands.update(receipt["commands"])
            hashes[name] = digest(native / name)
        write_json(work / "module.json", config)

        unsigned = work / "bundled-unsigned.hap"
        arguments = java_tool(sdk_path(), "app_packing_tool.jar") + [
            "--mode", "hap", "--json-path", work / "module.json",
            "--hnp-path", work / "hnp", "--out-path", unsigned, "--force", "true",
        ]
        for flag, resource in [("--resources-path", "resources"),
                               ("--index-path", "resources.index"), ("--ets-path", "ets"),
                               ("--lib-path", "libs"), ("--pkg-context-path", "pkgContextInfo.json"),
                               ("--pack-info-path", "pack.info")]:
            if (work / resource).exists():
                arguments += [flag, work / resource]
        run(arguments)
        if args.debug_udid:
            from sign_debug import DebugSigner
            DebugSigner(args.debug_udid).sign(unsigned, output, bm=not args.no_permissions)
        else:
            shutil.copy2(unsigned, output)
        with zipfile.ZipFile(output) as archive:
            actual = json.loads(archive.read("module.json"))
            if archive.testzip() is not None or actual["module"]["hnpPackages"] != declarations:
                raise ValueError("Bundled HAP verification failed")
            if args.no_permissions and actual["module"].get("requestPermissions"):
                raise ValueError("Permission-free bundle still requests permissions")
            for name in names:
                if archive.read(f"hnp/{args.abi}/{name}") != (native / name).read_bytes():
                    raise ValueError("Bundled HNP changed during HAP packaging")
        report = {"bundle": config["app"]["bundleName"], "version": config["app"]["versionName"],
                  "min_api_version": config["app"]["minAPIVersion"],
                  "target_api_version": config["app"]["targetAPIVersion"],
                  "abi": args.abi, "manager_source_sha256": digest(source),
                  "hap_sha256": digest(output), "bytes": output.stat().st_size,
                  "signing": "emulator-debug" if args.debug_udid else "unsigned-development",
                  "requested_permissions": [permission["name"] for permission in
                                            actual["module"].get("requestPermissions", [])],
                  "hnp_sha256": hashes, "commands": sorted(commands),
                  "bundled_tools": [receipt for _, receipt in tools],
                  "tool_lifecycle": "Bundled HNPs are installed and removed with the OCP application."}
        write_json(output.with_suffix(".json"), report)
        output.with_suffix(output.suffix + ".sha256").write_text(f"{digest(output)}  {output.name}\n")
        print(f"Built {output} ({output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-hap", type=Path, required=True)
    parser.add_argument("--tool-bottle", type=Path, action="append", required=True,
                        help="Reviewed bottle directory containing receipt.json and TOOL.hap; repeatable")
    parser.add_argument("--abi", choices=["arm64-v8a"], default="arm64-v8a")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--debug-udid", help="Sign for the selected emulator UDID")
    parser.add_argument("--no-permissions", action="store_true",
                        help="Omit all permissions for an offline bundled-tool environment")
    try:
        build(parser.parse_args())
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(f"ocp-bundle: {error}", file=sys.stderr)
        sys.exit(1)
