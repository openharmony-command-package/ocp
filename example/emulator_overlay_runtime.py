#!/usr/bin/env python3
"""Build an isolated DevEco runtime that retains instance firmware overlays.

This is a macOS ARM64 / DevEco 26.0.0.821 development fixture. It skips
startup overlay deletion and disk recreation on a copied executable. All
instance disks must already exist. Base-image signature verification remains
enabled; the original SDK executable is not modified.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


SOURCE_SHA256 = "d48732884d6b2e9b81caff88e88de5533f900a154ba8f0ae0ccd5b8c92d3fdfd"
PATCHES = (
    ("__ZN15CheckRuntimeEnv10DeleteQcowEv", "ff0303d1f85f08a9", "20008052c0035fd6"),
    ("_create_qcow2", "ff0305d1fc6f12a9", "c0035fd61f2003d5"),
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def text_offset(path: Path, address: int) -> int:
    with path.open("rb") as stream:
        header = stream.read(32)
        magic, cpu, _, _, count, _, _, _ = struct.unpack("<8I", header)
        if magic != 0xFEEDFACF or cpu != 0x0100000C:
            raise RuntimeError("This fixture requires a thin ARM64 Mach-O executable")
        for _ in range(count):
            start = stream.tell()
            command, size = struct.unpack("<II", stream.read(8))
            if command == 0x19:
                name, vmaddr, vmsize, fileoff, filesize = struct.unpack(
                    "<16sQQQQ", stream.read(48)
                )
                if name.rstrip(b"\0") == b"__TEXT" and vmaddr <= address < vmaddr + filesize:
                    return fileoff + address - vmaddr
            stream.seek(start + size)
    raise RuntimeError("Patch symbol is outside the executable TEXT segment")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deveco-contents", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sdk = args.deveco_contents.resolve()
    source_dir = sdk / "tools/emulator"
    source = source_dir / "Emulator"
    llvm = sdk / "sdk/default/openharmony/native/llvm/bin/llvm-nm"
    original_hash = digest(source)
    if original_hash != SOURCE_SHA256:
        raise RuntimeError("SDK executable hash differs; this build must be audited before patching")
    listing = subprocess.check_output(
        [str(llvm), "--defined-only", str(source)], text=True
    )
    patches = []
    for symbol, expected_hex, patched_hex in PATCHES:
        matches = [line for line in listing.splitlines() if line.split() and line.split()[-1] == symbol]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one {symbol} symbol")
        address = int(matches[0].split()[0], 16)
        offset = text_offset(source, address)
        expected = bytes.fromhex(expected_hex)
        with source.open("rb") as stream:
            stream.seek(offset)
            if stream.read(len(expected)) != expected:
                raise RuntimeError(f"SDK function bytes differ for {symbol}")
        patches.append({"symbol": symbol, "file_offset": offset,
                        "original_bytes": expected_hex, "patched_bytes": patched_hex})

    output = args.output.resolve()
    if output.exists():
        raise RuntimeError("Output must be a new directory")
    output.mkdir(parents=True)
    target = output / "Emulator"
    subprocess.run(["/bin/cp", "-c", str(source), str(target)], check=True)
    subprocess.run(["/usr/bin/xattr", "-c", str(target)], check=True)
    for item in sorted(source_dir.iterdir()):
        if item.name != "Emulator":
            (output / item.name).symlink_to(item.resolve(), target_is_directory=item.is_dir())
    entitlements = subprocess.check_output(
        ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(source)]
    )
    entitlement_path = output / "emulator-entitlements.plist"
    entitlement_path.write_bytes(entitlements)
    with target.open("r+b") as stream:
        for patch in patches:
            stream.seek(patch["file_offset"])
            stream.write(bytes.fromhex(patch["patched_bytes"]))
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime",
         "--timestamp=none", "--entitlements", str(entitlement_path), str(target)],
        check=True,
    )
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(target)], check=True)
    if digest(source) != original_hash:
        raise RuntimeError("Original SDK executable changed during fixture creation")
    report = {
        "source": str(source), "source_sha256": original_hash,
        "runtime": str(target), "runtime_sha256": digest(target),
        "patches": patches,
        "purpose": "retain instance QCOW2 overlays across SDK startup",
        "image_signature_verification_patched": False,
        "guest_selinux_policy_patched": False,
        "source_executable_unchanged": True,
        "scope": "isolated development emulator; not a device or release solution",
    }
    (output / "overlay-runtime.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
