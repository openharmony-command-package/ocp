#!/usr/bin/env python3
"""Restore the conditional CUSTOM_SANDBOX flag bridge in one audited emulator build.

This is an isolated DevEco guest-image diagnostic, not a device patch. It
preserves the AppMgr permission check and existing SELinux domain rules.
The SDK library omitted the CUSTOM_SANDBOX conditional in upstream
modules/common/appspawn_adapter.cpp::SetHapDomainInfo.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path


SOURCE_SHA256 = "d69ad3b508dac94941587e2bc1459ee95795d7dc83067424b221083b2fee63a3"
BRIDGE_ADDRESS = 0xEAE0
TAIL_ADDRESS = 0xEB34
CHECK_FLAG_PLT = 0x21D90


def file_offset(data: bytes, address: int, size: int) -> int:
    if data[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError("Expected a little-endian ELF64 library")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    if header[2] != 183:
        raise ValueError("Expected ARM64")
    for index in range(header[10]):
        segment = struct.unpack_from("<IIQQQQQQ", data, header[5] + index * header[9])
        kind, flags, offset, vaddr, _, file_size, _, _ = segment
        if kind == 1 and flags & 1 and vaddr <= address and address + size <= vaddr + file_size:
            return offset + address - vaddr
    raise ValueError("Patch is outside an executable segment")


def branch(source: int, target: int, link: bool = False) -> int:
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError("Branch is out of range")
    return (0x94000000 if link else 0x14000000) | ((delta // 4) & 0x3FFFFFF)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    if output.exists() or output == source:
        raise ValueError("Output must be a new file")
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unrecognized SDK library; audit this build before patching")
    data = bytearray(original)
    bridge_offset = file_offset(data, BRIDGE_ADDRESS, 84)
    tail_offset = file_offset(data, TAIL_ADDRESS, 4)
    if struct.unpack_from("<I", data, tail_offset)[0] != 0xAA1503E0:
        raise ValueError("Unexpected function tail")

    # Reuse one verbose logging block. All paths to the common tail are
    # redirected here, then resume after its displaced mov x0,x21 instruction.
    # Message flag 31 is set only after AppMgr verifies CUSTOM_SANDBOX.
    skip = BRIDGE_ADDRESS + 36
    instructions = [
        0xF9402A80,  # ldr x0,[x20,#80]: property->message
        0xB4000000 | (((skip - (BRIDGE_ADDRESS + 4)) // 4) << 5),
        0x52800021,  # mov w1,#1: TLV_APP_FLAGS
        0x528003E2,  # mov w2,#31: APP_FLAGS_CUSTOM_SANDBOX
        branch(BRIDGE_ADDRESS + 16, CHECK_FLAG_PLT, link=True),
        0x34000000 | (((skip - (BRIDGE_ADDRESS + 20)) // 4) << 5),
        0xF9402668,  # ldr x8,[x19,#72]: hapDomainInfo->hapFlags
        0xB27C0108,  # orr x8,x8,#16: SELINUX_HAP_CUSTOM_SANDBOX
        0xF9002668,  # str x8,[x19,#72]
        0xAA1503E0,  # displaced mov x0,x21
        branch(BRIDGE_ADDRESS + 40, TAIL_ADDRESS + 4),
    ]
    instructions.extend([0xD503201F] * (21 - len(instructions)))
    data[bridge_offset:bridge_offset + 84] = struct.pack("<21I", *instructions)
    struct.pack_into("<I", data, tail_offset, branch(TAIL_ADDRESS, BRIDGE_ADDRESS))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    report = {
        "source_sha256": SOURCE_SHA256,
        "output_sha256": hashlib.sha256(data).hexdigest(),
        "patch_ranges": [{"offset": bridge_offset, "bytes": 84}, {"offset": tail_offset, "bytes": 4}],
        "permission_check_changed": False,
        "selinux_policy_changed": False,
        "unconditional_domain_override": False,
        "binary_security_manager_supplied": False,
        "seccomp_custom_branch_supplied": False,
        "scope": "audited emulator library only; full real-device parity is not established",
    }
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
