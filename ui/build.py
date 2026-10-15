#!/usr/bin/env python3
"""Build/install the Arkit manager while keeping UI outside the CLI HNP."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from ocp import digest, ensure_hnp, hdc, java_tool, manifest, run, sdk_path, write_json


def prepare(args):
    workspace = ROOT / 'build/ui/workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'ui/crates', workspace / 'crates', dirs_exist_ok=True)
    if (ROOT / 'ui/assets').is_dir():
        shutil.copytree(ROOT / 'ui/assets', workspace / 'assets', dirs_exist_ok=True)
    cargo = (ROOT / 'ui/Cargo.toml').read_text()
    arkit = args.arkit or os.environ.get('OCP_ARKIT')
    if not arkit:
        candidate = ROOT.parents[1] / 'ohos-rs/arkit'
        if candidate.is_dir():
            arkit = candidate
    if arkit:
        arkit = Path(arkit).expanduser().resolve()
        # Only this generated workspace gets the local dependency override.
        dependency = 'arkit = { path = ' + json.dumps(str(arkit / 'crates/arkit')) + ' }'
        cargo = '\n'.join(dependency if line.startswith('arkit = ') else line for line in cargo.splitlines()) + '\n'
    (workspace / 'Cargo.toml').write_text(cargo)
    return workspace


def build(args):
    if args.abi != 'arm64-v8a':
        raise ValueError('The Arkit manager currently targets the validated ARM64 simulator')
    sdk = sdk_path()
    workspace = prepare(args)
    env = os.environ.copy()
    env['OHOS_NDK_HOME'] = str(sdk)
    run(['ohrs', 'build', '--arch', 'aarch', '--release', '--target-dir', ROOT / '.cache/cargo-ui', '--package', 'ocp_ui'], cwd=workspace, env=env)
    metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--format-version', '1'], cwd=workspace))
    ability = next(Path(package['manifest_path']).parents[2] for package in metadata['packages'] if package['name'] == 'openharmony-ability')
    native_ability = ROOT / 'build/ui/native_ability'
    shutil.copytree(ability / 'native_ability', native_ability, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('build', 'oh_modules', 'node_modules', '.hvigor', '.idea'))
    app = ROOT / 'build/ui/app'
    for directory in (app/'AppScope', app/'entry/src/main'):
        if directory.exists():
            shutil.rmtree(directory)
    shutil.copytree(ROOT / 'ui/app', app, dirs_exist_ok=True)
    data = manifest()
    write_json(app / 'AppScope/app.json5', {'app': {'bundleName': data['bundle_name'], 'vendor':'ocp',
               'versionCode':data['version_code'], 'versionName':data['version'], 'icon':'$media:ocp', 'label':'$string:app_name'}})
    icon = ROOT / 'ui/assets/ocp.svg'
    for media in (app/'AppScope/resources/base/media', app/'entry/src/main/resources/base/media'):
        media.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon, media/'ocp.svg')
    libraries = app / 'entry/libs' / args.abi
    libraries.mkdir(parents=True, exist_ok=True)
    for library in (workspace / 'dist' / args.abi).glob('*.so'):
        shutil.copy2(library, libraries / library.name)
    types = app / 'entry/src/main/cpp/types/libocp_ui'
    types.mkdir(parents=True, exist_ok=True)
    shutil.copy2(workspace / 'dist/index.d.ts', types / 'index.d.ts')
    write_json(types / 'oh-package.json5', {'name':'libocp_ui.so','types':'./index.d.ts','version':data['version']})
    package = ensure_hnp(args.abi)
    contents = sdk.parents[2]
    env['DEVECO_SDK_HOME'] = str(contents / 'sdk')
    env['JAVA_HOME'] = str(contents / 'jbr/Contents/Home')
    env['PATH'] = str(contents / 'tools/node/bin') + os.pathsep + env['PATH']
    run([contents / 'tools/ohpm/bin/ohpm', 'install'], cwd=app, env=env)
    run([contents / 'tools/hvigor/bin/hvigorw', 'assembleHap', '--no-daemon', '--mode', 'module',
         '-p', 'product=default', '-p', 'buildMode=debug', '--no-hvigorw-daemon'], cwd=app, env=env)
    source = app / 'entry/build/default/outputs/default/entry-default-unsigned.hap'
    output = ROOT / 'dist' / args.abi / 'ocp-manager-unsigned.hap'
    packing = ROOT / 'build/ui/packing'
    if packing.exists():
        shutil.rmtree(packing)
    with zipfile.ZipFile(source) as archive:
        assert archive.testzip() is None
        archive.extractall(packing)
    hnp = packing / 'hnp' / args.abi
    hnp.mkdir(parents=True)
    shutil.copy2(package, hnp / package.name)
    run(java_tool(sdk, 'app_packing_tool.jar') + ['--mode', 'hap', '--json-path', packing/'module.json',
        '--resources-path', packing/'resources', '--index-path', packing/'resources.index',
        '--ets-path', packing/'ets', '--lib-path', packing/'libs', '--hnp-path', packing/'hnp',
        '--pkg-context-path', packing/'pkgContextInfo.json', '--pack-info-path', packing/'pack.info',
        '--out-path', output, '--force', 'true'])
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert archive.read(f'hnp/{args.abi}/ocp.hnp') == package.read_bytes(), 'UI HAP must embed the same CLI HNP'
        config = json.loads(archive.read('module.json'))
        assert config['app']['bundleName'] == data['bundle_name']
        assert config['module']['mainElement'] == 'EntryAbility'
        home = [ability for ability in config['module']['abilities'] if any(
            'action.system.home' in skill.get('actions',[]) and 'entity.system.home' in skill.get('entities',[])
            for skill in ability.get('skills',[]))]
        assert len(home) == 1 and home[0]['name'] == 'EntryAbility'
        assert home[0]['launchType'] == 'singleton'
    (output.parent / (output.name + '.sha256')).write_text(f'{digest(output)}  {output.name}\n')
    write_json(output.parent / 'ui-build.json', {'version':data['version'], 'bundle':data['bundle_name'],
               'abi':args.abi, 'hap_sha256':digest(output), 'hnp_sha256':digest(package), 'framework':'Arkit',
               'arkit_manifest':next(p['manifest_path'] for p in metadata['packages'] if p['name']=='arkit')})
    print(f'Built Arkit manager: {output}', flush=True)
    if args.debug_udid:
        from sign_debug import DebugSigner
        signed = DebugSigner(args.debug_udid).sign(output, output.with_name('ocp-manager-debug.hap'), bm=True)
        metadata_file = output.parent/'ui-build.json'
        metadata = json.loads(metadata_file.read_text())
        metadata.update(debug_hap_sha256=digest(signed), signing='sdk-emulator-debug',
                        host_acl=['ohos.permission.ALLOW_USE_BM','ohos.permission.ALLOW_EXTERNAL_NATIVE_CODE'])
        write_json(metadata_file, metadata)
        return signed
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare','build','install','configure','start'])
    parser.add_argument('--abi', default='arm64-v8a')
    parser.add_argument('--arkit', type=Path)
    parser.add_argument('--target')
    parser.add_argument('--server', default='127.0.0.1:8710')
    parser.add_argument('--port', type=int, default=18090)
    parser.add_argument('--debug-udid', help='Sign an ordinary BM-authorized app for the specified emulator UDID')
    parser.add_argument('--repository', help='Static core catalog URL; defaults to the local test repository')
    args = parser.parse_args()
    if args.action == 'prepare': print(prepare(args)); return
    if args.action == 'build': build(args); return
    if not args.target: parser.error('--target is required for device actions')
    if args.action == 'install':
        output = hdc(args, 'install', '-r', build(args))
        print(output, flush=True)
        if 'install bundle successfully' not in output:
            raise ValueError('Manager installation failed')
    elif args.action == 'configure':
        config = ROOT/'build/ui/settings.json'
        catalog = args.repository or f'http://127.0.0.1:{args.port}/core/index.tar.gz'
        write_json(config, {'repository':catalog})
        config.chmod(0o600)
        bundle = manifest()['bundle_name']
        # Start once to create the application-owned settings directory.
        hdc(args, 'shell', 'aa', 'start', '-a', 'EntryAbility', '-b', bundle)
        import time
        time.sleep(2)
        hdc(args, 'shell', 'aa', 'force-stop', bundle)
        print(hdc(args, 'file', 'send', '-b', bundle, config, 'data/storage/el2/base/haps/entry/files/ocp/settings.json').strip())
        forwards = hdc(args, 'fport', 'ls')
        if f'tcp:{args.port} tcp:{args.port}' not in forwards:
            hdc(args, 'rport', f'tcp:{args.port}', f'tcp:{args.port}')
        print(hdc(args, 'shell', 'aa', 'start', '-a', 'EntryAbility', '-b', bundle).strip())
    else:
        print(hdc(args, 'shell', 'aa', 'start', '-a', 'EntryAbility', '-b', manifest()['bundle_name']).strip())


if __name__ == '__main__':
    try: main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, AssertionError) as error:
        print(f'ocp-ui: {error}', file=sys.stderr)
        sys.exit(1)
