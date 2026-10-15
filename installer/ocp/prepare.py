#!/usr/bin/env python3
"""Prepare the shell CLI and a precompiled upstream Zig Maker adapter."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ocp import digest, run

HOST_SHA = "6b2ec8c3d11e65cdc037f658ab5f5690a3f84741aeb629a4e5ec49f29b8d544d"
CA_SHA = "a41b5d356aea97a529fe27e0f7316d2f9d946d75927476cf9cf1b90637d00505"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--abi", required=True)
    args = parser.parse_args()
    cache = ROOT / ".cache/host"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "zig-0.17.0-macos.tar.xz"
    if not archive.is_file() or digest(archive) != HOST_SHA:
        run(["curl", "--fail", "--location", "--output", archive,
             "https://github.com/openharmony-zig/zig-patch/releases/download/0.17.0/zig-aarch64-macos-none-baseline.tar.xz"])
    if digest(archive) != HOST_SHA:
        raise ValueError("Host compiler checksum mismatch")
    host = cache / "zig-aarch64-macos-none-baseline"
    if not host.is_dir():
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    raise ValueError("Unsafe host archive member")
            tar.extractall(cache)
    ca = cache / "cacert.pem"
    if not ca.is_file() or digest(ca) != CA_SHA:
        run(["curl", "--fail", "--location", "--output", ca, "https://curl.se/ca/cacert.pem"])
    if digest(ca) != CA_SHA:
        raise ValueError("CA bundle checksum mismatch; review and update the pinned CA revision")
    certificate = host / "lib/std/crypto/Certificate/Bundle.zig"
    source = certificate.read_text()
    marker = "pub fn rescan(cb: *Bundle, gpa: Allocator, io: Io, now: Io.Timestamp) RescanError!void {\n"
    old_adapter = '    if (builtin.link_libc) {\n        if (std.c.getenv("OCP_CA_BUNDLE")) |path| {\n            return rescanWithPath(cb, gpa, io, now, std.mem.span(path));\n        }\n    }\n'
    source = source.replace(old_adapter, "")
    if "ocp_ca_bundle" not in source:
        if marker not in source:
            raise ValueError("Upstream CA rescan interface changed")
        source = source.replace('const Bundle = @This();\n', 'const Bundle = @This();\npub var ocp_ca_bundle: ?[]const u8 = null;\n', 1).replace(marker, marker +
            '    if (ocp_ca_bundle) |path| {\n' +
            '        return rescanWithPath(cb, gpa, io, now, path);\n    }\n', 1)
    certificate.write_text(source)
    maker_source = host / "lib/compiler/Maker.zig"
    maker = maker_source.read_text()
    if "OCP_CA_BUNDLE" not in maker:
        marker = 'pub fn main(init: process.Init.Minimal) !void {\n'
        maker = maker.replace(marker, marker +
            '    std.crypto.Certificate.Bundle.ocp_ca_bundle = init.environ.getPosix("OCP_CA_BUNDLE");\n', 1)
        maker_source.write_text(maker)
    if "OCP materialized fetch" not in maker:
        marker = '    const local_storage_ptr = switch (save) {\n        .no => null,\n'
        replacement = '''    const local_storage_ptr = switch (save) {
        // OCP materialized fetch: retain verified resources for installation.
        .no => ls: {
            local_storage = .{
                .cache_root = .{ .root_dir = graph.global_cache_root, .sub_path = "" },
                .pkg_root = if (override_pkg_dir) |p| .initCwd(p) else .{
                    .root_dir = graph.global_cache_root, .sub_path = "p",
                },
            };
            break :ls &local_storage;
        },
'''
        if marker not in maker:
            raise ValueError("Upstream fetch storage interface changed")
        maker = maker.replace(marker, replacement, 1)
        maker_source.write_text(maker)
    output = ROOT / "build/runtime" / args.abi
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(source.encode() + maker.encode() + Path(__file__).read_bytes() + args.abi.encode()).hexdigest()
    stamp = output / "maker.build.sha256"
    binary = output / "ocp-maker"
    target = {"arm64-v8a": "aarch64-linux-musl", "x86_64": "x86_64-linux-musl",
              "armeabi-v7a": "arm-linux-musleabihf"}[args.abi]
    if not binary.is_file() or not stamp.is_file() or stamp.read_text() != fingerprint:
        run([os.environ.get("OCP_HOST_ZIG", str(host / "zig")), "build-exe", host / "lib/compiler/Maker.zig",
             "-target", target, "-O", "ReleaseFast", "-fstrip", f"-femit-bin={binary}"])
        stamp.write_text(fingerprint)
    shutil.copy2(Path(__file__).with_name("ocp.sh"), output / "ocp.sh")
    (output / "ocp.sh").chmod(0o755)
    shutil.copy2(ca, output / "cacert.pem")
    shutil.copy2(host / "LICENSE", output / "LICENSE-ZIG")


if __name__ == "__main__":
    main()
