#!/usr/bin/env python3
"""Host regression checks for verified toolchain archive extraction."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import ocp


def main():
    cases = [
        ('regular files', [], True),
        ('forward hard link', [('go/cc-arm', tarfile.LNKTYPE, 'go/cc')], True),
        ('nested hard link', [('go/wrappers/cc-arm', tarfile.LNKTYPE, 'go/cc')], True),
        ('traversal member', [('../escape', tarfile.LNKTYPE, 'go/cc')], False),
        ('absolute member', [('/tmp/escape', tarfile.LNKTYPE, 'go/cc')], False),
        ('traversal target', [('go/cc-arm', tarfile.LNKTYPE, '../escape')], False),
        ('absolute target', [('go/cc-arm', tarfile.LNKTYPE, '/tmp/escape')], False),
        ('missing target', [('go/cc-arm', tarfile.LNKTYPE, 'go/missing')], False),
        ('directory target', [('go/cc-arm', tarfile.LNKTYPE, 'go')], False),
        ('file parent', [('go/cc/nested', tarfile.LNKTYPE, 'go/cc')], False),
        ('link chain', [('go/cc-arm', tarfile.LNKTYPE, 'go/cc-other'),
                        ('go/cc-other', tarfile.LNKTYPE, 'go/cc')], False),
        ('symbolic link', [('go/cc-arm', tarfile.SYMTYPE, 'cc')], False),
        ('duplicate member', [('go/cc', tarfile.LNKTYPE, 'go/cc')], False),
    ]
    previous_root = ocp.ROOT
    try:
        with tempfile.TemporaryDirectory(prefix='ocp-source-') as temporary:
            ocp.ROOT = Path(temporary)
            downloads = ocp.ROOT / '.cache/downloads'
            downloads.mkdir(parents=True)
            for index, (label, links, expected) in enumerate(cases):
                path = downloads / f'{index}.tar.gz'
                with tarfile.open(path, 'w:gz') as archive:
                    directory = tarfile.TarInfo('go')
                    directory.type = tarfile.DIRTYPE
                    directory.mode = 0o755
                    archive.addfile(directory)
                    for name, kind, target in links:
                        member = tarfile.TarInfo(name)
                        member.type = kind
                        member.linkname = target
                        archive.addfile(member)
                    member = tarfile.TarInfo('go/cc')
                    member.size = len(b'compiler-wrapper')
                    member.mode = 0o755
                    archive.addfile(member, io.BytesIO(b'compiler-wrapper'))
                asset = {'url': f'https://example.invalid/{path.name}',
                         'sha256': ocp.digest(path), 'root': 'go'}
                try:
                    source, provenance = ocp.component_source(
                        {'version': '1.0.0', 'assets': {'arm64-v8a': asset}}, 'arm64-v8a')
                except ValueError:
                    if expected:
                        raise
                    assert not (ocp.ROOT / '.cache/sources' / asset['sha256'] / '.complete').exists()
                else:
                    if not expected:
                        raise AssertionError(label + ' was accepted')
                    assert provenance == asset
                    assert (source / 'cc').read_bytes() == b'compiler-wrapper'
                    for name, _, _ in links:
                        result = source.parent / name
                        assert result.read_bytes() == b'compiler-wrapper'
                        assert result.stat().st_mode & 0o111
                        assert result.stat().st_ino != (source / 'cc').stat().st_ino
                print('PASS:', label)
            print(f'{len(cases)} component source checks passed')
    finally:
        ocp.ROOT = previous_root


if __name__ == '__main__':
    main()
