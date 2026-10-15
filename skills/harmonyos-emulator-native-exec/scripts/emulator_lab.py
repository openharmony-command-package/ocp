#!/usr/bin/env python3
"""Start or stop an already prepared, isolated DevEco development emulator."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--lab-root", type=Path, required=True)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    manifest = json.loads((lab / "manifest.json").read_text())
    runtime_dir = lab / "overlay-runtime"
    runtime = runtime_dir / "Emulator"
    record = json.loads((runtime_dir / "overlay-runtime.json").read_text())
    with runtime.open("rb") as stream:
        actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual_hash != record["runtime_sha256"]:
        raise RuntimeError("Isolated runtime hash differs from its audited build")
    instance = Path(manifest["instance_path"]).resolve()
    images = Path(manifest["image_root"]).resolve()
    if instance.parent != lab / "deployed" or images != lab / "images":
        raise RuntimeError("Instance and image paths must stay inside the isolated lab")
    if manifest["name"] != instance.name or manifest["target"] != "127.0.0.1:10091":
        raise RuntimeError("This fixture only handles the OCP development emulator on port 10091")
    hdc = Path(record["source"]).parents[2] / "sdk/default/openharmony/toolchains/hdc"
    if args.action in ("start", "status"):
        state = subprocess.run(
            [str(hdc), "-s", "127.0.0.1:8710", "-t", manifest["target"],
             "shell", "param", "get", "const.product.model"],
            capture_output=True, text=True, timeout=10,
        )
        online = state.returncode == 0 and state.stdout.strip() == "ocp-lab1"
        if args.action == "status" or online:
            print(json.dumps({"name": manifest["name"], "target": manifest["target"],
                              "online": online, "model": state.stdout.strip()}, indent=2))
            return
    for name in ("system", "vendor", "sys_prod", "userdata", "cache"):
        if not (instance / f"{name}.img.qcow2").is_file():
            raise RuntimeError(f"Missing prepared {name} overlay; refusing to recreate disks")
    command = [str(runtime), "-" + args.action, manifest["name"],
               "-instancePath", str(instance.parent)]
    if args.action == "stop":
        subprocess.run(command, check=True)
        print("Stop requested. Wait for the emulator process to exit before offline disk edits.")
        return
    command.extend(["-imageRoot", str(images), "-hdcPort", "10091", "-bootMode", "coldboot"])
    log = lab / "launcher.log"
    with log.open("ab") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    print(json.dumps({"name": manifest["name"], "target": manifest["target"],
                      "launcher_pid": process.pid, "log": str(log)}, indent=2))


if __name__ == "__main__":
    main()
