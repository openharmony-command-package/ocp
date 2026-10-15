#!/usr/bin/env python3
"""Emulator-only debug signing using the SDK's public OpenHarmony test keys."""
import argparse
import json
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from ocp import ROOT, digest, java_tool, run, sdk_path, write_json

class DebugSigner:
    def __init__(self, udid):
        if not re.fullmatch(r'[0-9A-Fa-f]{32,128}', udid):
            raise ValueError('Expected an emulator UDID, not an HDC host:port target')
        self.udid = udid
        self.sdk = sdk_path()
        self.work = ROOT / '.cache/debug-signing'
        self.work.mkdir(parents=True, exist_ok=True)
        self.keystore = self.work / 'debug-keys.p12'
        self.chain = self.work / 'app-cert-chain.cer'
        libraries = self.sdk / 'toolchains/lib'
        if not self.keystore.is_file():
            shutil.copy2(libraries / 'OpenHarmony.p12', self.keystore)
        self.keystore.chmod(0o600)
        if not self.chain.is_file():
            keytool = Path(java_tool(self.sdk, 'hap-sign-tool.jar')[0]).with_name('keytool')
            for alias, output in [('openharmony application ca','ca.cer'),('openharmony application root ca','root.cer')]:
                run([keytool,'-exportcert','-rfc','-alias',alias,'-keystore',self.keystore,'-storepass','123456','-file',self.work/output])
            run(java_tool(self.sdk,'hap-sign-tool.jar') + ['generate-app-cert',
                '-keyAlias','openharmony application release','-keyPwd','123456',
                '-issuer','C=CN,O=OpenHarmony,OU=OpenHarmony Team,CN=OpenHarmony Application CA',
                '-issuerKeyAlias','openharmony application ca','-issuerKeyPwd','123456',
                '-subject','C=CN,O=OpenHarmony,OU=OCP Development,CN=OCP Emulator Debug',
                '-validity','30','-signAlg','SHA256withECDSA','-rootCaCertFile',self.work/'root.cer',
                '-subCaCertFile',self.work/'ca.cer','-keystoreFile',self.keystore,'-keystorePwd','123456',
                '-outForm','certChain','-outFile',self.chain])
        self.leaf = re.search(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', self.chain.read_text(), re.S).group(0) + '\n'

    def sign(self, source, output, bm=False, hide_desktop=None):
        with zipfile.ZipFile(source) as archive:
            module = json.loads(archive.read('module.json'))
        bundle = module['app']['bundleName']
        profile = json.loads((self.sdk/'toolchains/lib/UnsgnedDebugProfileTemplate.json').read_text())
        now = int(time.time())
        profile.update(uuid=str(uuid.uuid4()), validity={'not-before':now-3600,'not-after':now+30*86400})
        profile['bundle-info'].update({'bundle-name':bundle,'development-certificate':self.leaf,
                                       'apl':'normal','app-feature':'hos_normal_app'})
        requested = {entry['name'] for entry in module['module'].get('requestPermissions', [])}
        acls = ['ohos.permission.ALLOW_USE_BM','ohos.permission.ALLOW_EXTERNAL_NATIVE_CODE'] if bm else []
        if not set(acls).issubset(requested):
            raise ValueError('Debug host must declare every requested ACL permission')
        profile['acls'] = {'allowed-acls':acls}
        headless_hnp = bool(module['module'].get('hnpPackages')) and not module['module'].get('abilities')
        if hide_desktop is None:
            hide_desktop = headless_hnp
        profile['app-privilege-capabilities'] = ['AllowAppDesktopIconHide'] if hide_desktop else []
        profile['permissions'] = {'restricted-permissions':[]}
        profile['debug-info'] = {'device-id-type':'udid','device-ids':[self.udid]}
        profile_json = self.work / (bundle+'.json'); provision = profile_json.with_suffix('.p7b')
        write_json(profile_json, profile)
        run(java_tool(self.sdk,'hap-sign-tool.jar')+['sign-profile','-mode','localSign',
            '-keyAlias','openharmony application profile debug','-keyPwd','123456',
            '-profileCertFile',self.sdk/'toolchains/lib/OpenHarmonyProfileDebug.pem',
            '-inFile',profile_json,'-signAlg','SHA256withECDSA','-keystoreFile',self.keystore,
            '-keystorePwd','123456','-outFile',provision])
        output = output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
        run(java_tool(self.sdk,'hap-sign-tool.jar')+['sign-app','-mode','localSign',
            '-keyAlias','openharmony application release','-keyPwd','123456','-appCertFile',self.chain,
            '-profileFile',provision,'-inFile',source,'-signAlg','SHA256withECDSA','-keystoreFile',self.keystore,
            '-keystorePwd','123456','-outFile',output,'-compatibleVersion','24'])
        (output.parent/(output.name+'.sha256')).write_text(f'{digest(output)}  {output.name}\n')
        return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hap', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--udid', required=True)
    parser.add_argument('--bm', action='store_true')
    args = parser.parse_args()
    DebugSigner(args.udid).sign(args.hap.resolve(), args.output, args.bm)
