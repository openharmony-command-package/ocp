#!/usr/bin/env python3
"""Optional application PTY diagnostics; never included in the OCP HNP."""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent
ROOT = EXAMPLE.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ocp import MACHINES, digest, hdc, java_tool, manifest, run, sdk_path, write_json

def hap(abi, debug_udid=None, zig_version='0.17.0'):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',zig_version):
        raise ValueError('Expected a three-part Zig smoke-test version')
    data = manifest()
    data["bundle_name"] += ".example"
    sdk = sdk_path()
    work = EXAMPLE / "build" / abi
    work.mkdir(parents=True, exist_ok=True)
    config = json.loads((EXAMPLE / "module.json").read_text())
    config["app"]["bundleName"] = data["bundle_name"]
    config["app"]["versionName"] = data["version"]
    write_json(work / "module.json", config)
    target = {"arm64-v8a": "aarch64-linux-ohos", "x86_64": "x86_64-linux-ohos",
              "armeabi-v7a": "arm-linux-ohos"}[abi]
    native = sdk / "native"
    libraries = work / "libs" / abi
    libraries.mkdir(parents=True, exist_ok=True)
    run([native / "llvm/bin/clang", f"--target={target}", f"--sysroot={native / 'sysroot'}",
         "-fPIC", "-shared", "-O2", "-Wall", "-Wextra", EXAMPLE / "src/ocp_probe.c",
         f'-DOCP_ZIG_TARGET="{target if abi != "armeabi-v7a" else "arm-linux-ohoseabi"}"',
         f'-DOCP_ZIG_VERSION="{zig_version}"',
         "-lace_napi.z", "-lhilog_ndk.z", "-o", libraries / "libocp_probe.so"])
    ets = work / "ets"
    ets.mkdir(parents=True, exist_ok=True)
    records = [("OcpAbility.js", "ets/entryability/OcpAbility"), ("Index.js", "ets/pages/Index")]
    (work / "filesInfo.txt").write_text("".join(
        f"{EXAMPLE / 'src' / filename};{data['bundle_name']}/entry/{record};esm;{record}.js;entry\n"
        for filename, record in records))
    es2abc = sdk / "ets/build-tools/ets-loader/bin/ark/build-mac/bin/es2abc"
    run([es2abc, "--module", "--merge-abc", "--target-api-version", "24",
         "--output", ets / "modules.abc", "@" + str(work / "filesInfo.txt")])
    resources = work / "res"
    resources.mkdir(parents=True, exist_ok=True)
    run([sdk / "toolchains/restool", "-i", EXAMPLE, "-j", work / "module.json",
         "-p", data["bundle_name"], "-o", resources, "-r", work / "ResourceTable.h", "-f"])
    unsigned = work / "ocp-example-unsigned.hap"
    run(java_tool(sdk, "app_packing_tool.jar") + ["--mode", "hap", "--json-path", resources / "module.json",
        "--resources-path", resources / "resources", "--index-path", resources / "resources.index",
        "--ets-path", ets, "--lib-path", work / "libs",
        "--out-path", unsigned, "--force", "true"])
    print(f"Built {unsigned}", flush=True)
    (unsigned.parent / f"{unsigned.name}.sha256").write_text(f"{digest(unsigned)}  {unsigned.name}\n")
    if debug_udid:
        from sign_debug import DebugSigner
        return DebugSigner(debug_udid).sign(unsigned, work/'ocp-example-debug.hap', bm=True, hide_desktop=True)
    return unsigned


def verify(args):
    data = manifest()
    distribution_bundle = data["bundle_name"]
    data["bundle_name"] += ".example"
    previous = hdc(args, "shell", "hilog", "-x", "-T", "OCP")
    previous_runs = set(re.findall(r"OCP_SMOKE_BEGIN=([\d-]+)", previous))
    hdc(args, "shell", "aa", "force-stop", data["bundle_name"])
    started = hdc(args, "shell", "aa", "start", "-a", "OcpAbility", "-b", data["bundle_name"],
                  "--pb", "runSmoke", "true")
    if "start ability successfully" not in started:
        raise ValueError(started.strip())
    print("Compiling C, Zig and C++ in the emulator's application PTY...", flush=True)
    deadline = time.monotonic() + args.timeout
    current = None
    log = ""
    while time.monotonic() < deadline:
        output = hdc(args, "shell", "hilog", "-x", "-T", "OCP")
        runs = re.findall(r"OCP_SMOKE_BEGIN=([\d-]+)", output)
        new_runs = [value for value in runs if value not in previous_runs]
        if new_runs:
            current = new_runs[-1]
        if current:
            log = output.split(f"OCP_SMOKE_BEGIN={current}", 1)[-1]
            if "OCP_PTY_EXIT=" in log:
                break
        time.sleep(2)
    else:
        raise ValueError("PTY compilation timed out; inspect hdc shell hilog -x -T OCP")
    destination = EXAMPLE / "build/device" / current
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "pty.log").write_text(log)
    if "OCP_COMPILE_OK" not in log or "OCP_PTY_EXIT=0" not in log:
        print(log, flush=True)
        raise ValueError(f"PTY compilation failed; log: {destination / 'pty.log'}")
    files = re.search(r"OCP_FILES_DIR=(/data/storage/[^\r\n]+)", log)
    if not files:
        raise ValueError("Missing application work directory in diagnostic log")
    remote = files[1].lstrip("/") + "/ocp-smoke"
    results = []
    # The production simulator's app domain denies executing newly written ELF
    # files. HDC provides the normal development path to run those same outputs.
    for language, filename, marker in [("C", "hello-c", "OCP_C_OK"), ("Zig", "hello-zig", "OCP_ZIG_OK"),
                                       ("C++", "hello-cxx", "OCP_CXX_OK")]:
        local = destination / filename
        hdc(args, "file", "recv", "-b", data["bundle_name"], remote + "/" + filename, local)
        if not local.is_file():
            raise ValueError(f"Could not retrieve {language} output")
        device_file = "/data/local/tmp/ocp-" + current + "-" + filename
        hdc(args, "file", "send", local, device_file)
        output = hdc(args, "shell", f"chmod 755 {device_file}; {device_file}; result=$?; echo OCP_RUN_EXIT=$result")
        (destination / f"{filename}.log").write_text(output)
        if marker not in output or "OCP_RUN_EXIT=0" not in output:
            raise ValueError(f"{language} output failed: {output.strip()}")
        results.append({"language": language, "sha256": digest(local), "output": output.strip(),
                        "execution_path": device_file})
        print(f"{language}: compile in app PTY + run in device debug shell passed", flush=True)
    report = {"target": args.target, "bundle": distribution_bundle, "verification_bundle": data["bundle_name"], "run": current,
              "platform": hdc(args, "shell", "param", "get", "const.product.software.version").strip(),
              "pty_compilation": "passed", "device_debug_execution": "passed",
              "app_generated_elf_execution": "permission denied on this simulator",
              "results": results}
    machine = hdc(args, "shell", "uname", "-m").strip()
    abi = {"aarch64": "arm64-v8a", "x86_64": "x86_64", "armv7l": "armeabi-v7a"}[machine]
    report["abi"] = abi
    for suffix in ("hnp", "hap"):
        name = f"{data['name']}.hnp" if suffix == "hnp" else "ocp-manager-debug.hap"
        artifact = ROOT / "dist" / abi / name
        if artifact.is_file():
            report[f"{suffix}_sha256"] = digest(artifact)
    write_json(destination / "report.json", report)
    write_json(ROOT / "dist" / abi / "verification.json", report)
    print(f"OCP_SMOKE_OK — {destination / 'report.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "install", "verify"))
    parser.add_argument("--abi", choices=MACHINES, default="arm64-v8a")
    parser.add_argument("--target")
    parser.add_argument("--server", default="127.0.0.1:8710")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--debug-udid", help="Sign the ordinary BM-authorized PTY host for this emulator")
    parser.add_argument("--zig-version",default='0.17.0',help='Expected Zig version for the compile fixture')
    args = parser.parse_args()
    if args.action == "build":
        hap(args.abi, args.debug_udid,args.zig_version)
        return
    if not args.target:
        parser.error("--target is required for install and verify")
    if args.action == "install":
        output = hdc(args, "install", "-r", hap(args.abi, args.debug_udid,args.zig_version))
        print(output.strip(), flush=True)
        if "install bundle successfully" not in output:
            raise ValueError("Example installation failed")
    else:
        verify(args)

if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"example: {error}", file=sys.stderr)
        sys.exit(1)
