#!/usr/bin/env python3
"""Offline PR validation; never downloads or executes contributor scripts."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys


def validate(path):
    formula = json.loads(path.read_text())
    if 'publisher' in formula:
        publisher = formula['publisher']
        name = publisher['name']
        if not isinstance(name,str) or not name.strip() or len(name)>128 or any(ord(c)<32 or ord(c)==127 for c in name):
            raise ValueError(f'{path}: invalid publisher name')
        if 'url' in publisher and not re.fullmatch(r'https?://[^\s]+',publisher['url']):
            raise ValueError(f'{path}: invalid publisher URL')
    for field, pattern in [('name',r'[A-Za-z0-9_-]+'), ('version',r'[0-9]+\.[0-9]+\.[0-9]+')]:
        if not re.fullmatch(pattern,formula[field]):
            raise ValueError(f'{path}: invalid {field}')
    if bool('assets' in formula) == bool('source_dir' in formula):
        raise ValueError(f'{path}: select assets or source_dir')
    if not formula['commands']:
        raise ValueError(f'{path}: no exported commands')
    for command, executable in formula['commands'].items():
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*',command):
            raise ValueError(f'{path}: invalid command name')
        if command in ['ocp','ocp-maker','ocp-bm'] and formula['name'] != 'ocp':
            raise ValueError(f'{path}: reserved OCP command')
        resource=PurePosixPath(executable)
        if resource.is_absolute() or '..' in resource.parts:
            raise ValueError(f'{path}: command escapes package')
    for abi, asset in formula.get('assets',{}).items():
        if abi not in ['arm64-v8a','x86_64','armeabi-v7a'] or not re.fullmatch(r'[0-9a-f]{64}',asset['sha256']):
            raise ValueError(f'{path}: invalid ABI or SHA-256')
        if not re.fullmatch(r'https?://[^\s]+',asset['url']):
            raise ValueError(f'{path}: invalid source URL')
        resource=PurePosixPath(asset['root'])
        if resource.is_absolute() or '..' in resource.parts:
            raise ValueError(f'{path}: archive root escapes package')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    paths=sorted((args.root/'installer').glob('*/component.json')) + sorted((args.root/'installer').glob('*/versions/*.json'))
    if not paths:
        raise ValueError('No formulas found')
    for path in paths:
        validate(path)
    print(f'{len(paths)} formulas validated without executing build scripts')


if __name__=='__main__':
    try: main()
    except (ValueError, KeyError, OSError) as error:
        print(error,file=sys.stderr);sys.exit(1)
