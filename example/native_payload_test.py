#!/usr/bin/env python3
"""Host regression checks for the device adapter's archive trust boundary."""
import copy
import io
import json
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    with tempfile.TemporaryDirectory(prefix='ocp-payload-') as temporary:
        work = Path(temporary)
        harness = work/'validate.cpp'
        harness.write_text('''#include <fcntl.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
[[noreturn]] void fail(const std::string &s) { std::fprintf(stderr,"%s\\n",s.c_str()); std::exit(1); }
#include "payload.h"
int main(int argc,char **argv) {
 if(argc!=2)return 2;
 payload::validate(argv[1],"com.richerfu.ocp.pkg.test","1.0.0","arm64-v8a","ocp_test","ocp-test");
}
''')
        binary = work/'validate'
        subprocess.run(['clang++','-std=c++17','-DJSON_NOEXCEPTION','-fno-exceptions','-O2',
                        '-I'+str(ROOT/'installer/ocp/native'),'-I'+str(ROOT/'.cache/native-deps'),harness,'-lz','-o',binary],check=True)
        base = {'app':{'bundleName':'com.richerfu.ocp.pkg.test','versionName':'1.0.0'},
                'module':{'hnpPackages':[{'package':'ocp_test.hnp','type':'public'}]}}
        native = {'name':'ocp_test','version':'1.0.0','install':{'links':[{'source':'bin/test','target':'ocp-test'}]}}
        elf = bytearray(20);elf[:4]=b'\x7fELF';elf[4:6]=bytes([2,1]);struct.pack_into('<H',elf,18,183)
        cases = [('valid stored metadata',{},True),('valid deflated command',{'compressed':True},True),
                 ('wrong bundle',{'bundle':'com.other.app'},False),('wrong version',{'version':'2.0.0'},False),
                 ('UI ability',{'abilities':[{'name':'UI'}]},False),('extra permissions',{'permissions':[{'name':'ohos.permission.INTERNET'}]},False),
                 ('wrong ABI',{'machine':62},False),('wrong command',{'command':'zig'},False),
                 ('reserved command',{'command':'ocp-bm'},False),('traversal entry',{'traversal':True},False),
                 ('duplicate ZIP entry',{'duplicate':True},False),('duplicate JSON key',{'duplicate_json':True},False),
                 ('truncated archive',{'truncate':True},False)]
        for index,(label,options,expected) in enumerate(cases):
            module=copy.deepcopy(base);hnp=copy.deepcopy(native);command=bytearray(elf)
            if 'bundle' in options:module['app']['bundleName']=options['bundle']
            if 'version' in options:module['app']['versionName']=options['version']
            if 'abilities' in options:module['module']['abilities']=options['abilities']
            if 'permissions' in options:module['module']['requestPermissions']=options['permissions']
            if 'machine' in options:struct.pack_into('<H',command,18,options['machine'])
            if 'command' in options:hnp['install']['links'][0]['target']=options['command']
            native_bytes=io.BytesIO()
            with zipfile.ZipFile(native_bytes,'w',compression=zipfile.ZIP_DEFLATED if options.get('compressed') else zipfile.ZIP_STORED) as archive:
                archive.writestr('ocp_test/hnp.json',json.dumps(hnp))
                archive.writestr('ocp_test/bin/test',command)
                if options.get('traversal'):archive.writestr('../escape',b'unsafe')
            path=work/f'{index}.hap'
            metadata=json.dumps(module)
            if options.get('duplicate_json'):metadata=metadata.replace('"bundleName":','"bundleName":"com.bad", "bundleName":')
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('module.json',metadata)
                archive.writestr('hnp/arm64-v8a/ocp_test.hnp',native_bytes.getvalue())
                if options.get('duplicate'):archive.writestr('module.json',metadata)
            if options.get('truncate'):path.write_bytes(path.read_bytes()[:-8])
            result=subprocess.run([binary,path],capture_output=True,text=True)
            if (result.returncode==0)!=expected:raise AssertionError(f'{label}: {result.returncode}: {result.stderr}')
            print(f'PASS: {label}')
        print(f'{len(cases)} native payload checks passed')

if __name__=='__main__':main()
