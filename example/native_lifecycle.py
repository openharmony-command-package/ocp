#!/usr/bin/env python3
"""Verify OCP's device BMS backend from a real simulator application PTY."""
import argparse
import re
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from ocp import digest,hdc,manifest,write_json

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',required=True)
    parser.add_argument('--server',default='127.0.0.1:8710')
    parser.add_argument('--port',type=int,default=18090)
    parser.add_argument('--repository-base-url',help='Static test repository root containing core/ and taps/')
    parser.add_argument('--timeout',type=int,default=900)
    args=parser.parse_args()
    bundle=manifest()['bundle_name']+'.example'
    work=ROOT/'example/build/native-lifecycle';work.mkdir(parents=True,exist_ok=True)
    env=work/'native.env'
    base=(args.repository_base_url or f'http://127.0.0.1:{args.port}').rstrip('/')
    values={'OCP_NATIVE_CATALOG':base+'/core/index.tar.gz',
            'OCP_NATIVE_COMMUNITY':base+'/taps/community/index.tar.gz'}
    env.write_text(''.join(f'{key}={shlex.quote(value)}\n' for key,value in values.items()))
    remote='data/storage/el2/base/haps/entry/files/ocp-smoke/'
    for source in [env,ROOT/'example/native-lifecycle.sh']:
        output=hdc(args,'file','send','-b',bundle,source,remote+source.name)
        if 'FileTransfer finish' not in output:raise ValueError(output)
    forwards=hdc(args,'fport','ls')
    if f'tcp:{args.port} tcp:{args.port}' not in forwards:hdc(args,'rport',f'tcp:{args.port}',f'tcp:{args.port}')
    previous=set(re.findall(r'OCP_SMOKE_BEGIN=([\d-]+)',hdc(args,'shell','hilog','-x','-T','OCP')))
    hdc(args,'shell','aa','force-stop',bundle)
    output=hdc(args,'shell','aa','start','-a','OcpAbility','-b',bundle,'--pb','nativeLifecycle','true')
    if 'start ability successfully' not in output:raise ValueError(output)
    markers=['OCP_NATIVE_INSTALL_016_OK','OCP_NATIVE_UPGRADE_017_OK','OCP_NATIVE_UNINSTALL_OK',
             'OCP_NATIVE_CACHED_REINSTALL_OK','OCP_NATIVE_CROSS_HOST_SYNC_OK','OCP_NATIVE_THIRD_PARTY_OK',
             'OCP_NATIVE_INDEX_TRANSACTION_OK','OCP_NATIVE_NAMESPACE_GUARD_OK','OCP_NATIVE_LIFECYCLE_OK']
    seen=set();current=None;log='';deadline=time.monotonic()+args.timeout
    print('True application PTY: native BMS install → upgrade → uninstall → offline reinstall',flush=True)
    while time.monotonic()<deadline:
        output=hdc(args,'shell','hilog','-x','-T','OCP')
        runs=[run for run in re.findall(r'OCP_SMOKE_BEGIN=([\d-]+)',output) if run not in previous]
        if runs:current=runs[-1]
        if current:
            log=output.split(f'OCP_SMOKE_BEGIN={current}',1)[-1]
            for marker in markers:
                if marker in log and marker not in seen:seen.add(marker);print(marker,flush=True)
            if 'OCP_PTY_EXIT=' in log:break
        time.sleep(2)
    destination=work/(current or time.strftime('%Y%m%d-%H%M%S'));destination.mkdir(parents=True,exist_ok=True)
    (destination/'pty.log').write_text(log)
    if seen!=set(markers) or 'OCP_PTY_EXIT=0' not in log:
        print(log,flush=True);raise ValueError(f'Native lifecycle failed: {destination / "pty.log"}')
    report={'target':args.target,'caller_bundle':bundle,'run':current,'version':manifest()['version'],
            'installation_backend':'device BMS with caller ALLOW_USE_BM token',
            'host_role':'read-only static downloads, setup/observation through HDC',
            'host_installation_endpoints':False,'cached_reinstall_network':False,
            'steps':markers,'hnp_sha256':digest(ROOT/'dist/arm64-v8a/ocp.hnp'),
            'manager_hap_sha256':digest(ROOT/'dist/arm64-v8a/ocp-manager-debug.hap')}
    write_json(destination/'report.json',report);write_json(ROOT/'dist/arm64-v8a/native-lifecycle.json',report)
    print(f'Native device lifecycle passed: {destination / "report.json"}',flush=True)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:print(f'native-lifecycle: {error}',file=sys.stderr);sys.exit(1)
