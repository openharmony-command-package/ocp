#!/usr/bin/env python3
"""Build the thin API 26 BMS adapter against pinned official platform headers."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from ocp import digest, run, sdk_path

PLATFORM = {
    'platform-ipc': ('communication_ipc', '5903fd5f7332a427cb3f6915b0202ee5c76c63b5',
                     ['interfaces/innerkits/ipc_core/include', 'interfaces/innerkits/c_api/include']),
    'platform-c-utils': ('commonlibrary_c_utils', '7a9af76276aca8f53347fb89c07850e014905521', ['base/include']),
}
JSON_SHA = '9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6'

def prepare(abi):
    includes = []
    for name, (repository, revision, directories) in PLATFORM.items():
        cache = ROOT / '.cache' / name
        if not (cache / '.git').is_dir():
            run(['git', 'clone', '--filter=blob:none', '--no-checkout', f'https://gitcode.com/openharmony/{repository}.git', cache])
            run(['git', 'sparse-checkout', 'set', *directories], cwd=cache)
            run(['git', 'checkout', revision], cwd=cache)
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=cache, text=True).strip()
        if actual != revision:
            raise ValueError(f'{name}: expected pinned platform revision {revision}, found {actual}')
        includes.extend(cache / directory for directory in directories)
    dependency = ROOT / '.cache/native-deps/nlohmann'
    dependency.mkdir(parents=True, exist_ok=True)
    header = dependency / 'json.hpp'
    if not header.is_file() or digest(header) != JSON_SHA:
        run(['curl', '--fail', '--location', '--output', header,
             'https://raw.githubusercontent.com/nlohmann/json/v3.11.3/single_include/nlohmann/json.hpp'])
    if digest(header) != JSON_SHA:
        raise ValueError('JSON dependency checksum mismatch')
    includes.append(dependency.parent)
    sdk = sdk_path()
    output = ROOT / 'build/runtime' / abi
    output.mkdir(parents=True, exist_ok=True)
    target = {'arm64-v8a':'aarch64-linux-ohos','x86_64':'x86_64-linux-ohos','armeabi-v7a':'arm-linux-ohos'}[abi]
    run([sdk/'native/llvm/bin/clang++', f'--target={target}', f'--sysroot={sdk / "native/sysroot"}',
         '-std=c++17', '-fno-exceptions', '-fno-rtti', '-DJSON_NOEXCEPTION', '-O2', '-Wall', '-Wextra', '-Werror',
         *[f'-I{path}' for path in includes], Path(__file__).with_name('native')/'ocp_bm.cpp',
         '-lipc_capi', '-lability_access_control', '-ldl', '-lz', '-o', output/'ocp-bm'])
    (output/'LICENSE-JSON').write_text(header.read_text().split('#ifndef')[0])
    for name in PLATFORM:
        shutil.copy2(ROOT/'.cache'/name/'LICENSE', output/f'LICENSE-{name}')
    return output/'ocp-bm'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--abi', required=True, choices=['arm64-v8a','x86_64','armeabi-v7a'])
    args = parser.parse_args()
    prepare(args.abi)
