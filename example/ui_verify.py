#!/usr/bin/env python3
"""Exercise actual Arkit/shadcn controls through DevEco's device UI automation."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from ocp import digest,hdc,manifest,write_json


class DeviceUI:
    def __init__(self,args):
        self.args=args
        self.bundle=manifest()['bundle_name']
        self.work=ROOT/'example/build/ui'/time.strftime('%Y%m%d-%H%M%S')
        self.work.mkdir(parents=True)
        self.steps=[]

    def layout(self,bundle=None):
        remote='/data/local/tmp/ocp-ui-test.json'
        arguments=['shell','uitest','dumpLayout','-m','false']
        if bundle:arguments+=['-b',bundle]
        hdc(self.args,*arguments,'-p',remote)
        local=self.work/'layout.json'
        hdc(self.args,'file','recv',remote,local)
        text=local.read_text()
        local.write_text(text)
        nodes=[]
        def walk(node):
            attributes=node.get('attributes',{})
            if attributes.get('visible')!='false': nodes.append(attributes)
            for child in node.get('children',[]):walk(child)
        walk(json.loads(text))
        return nodes

    def snapshot(self):
        return self.layout(self.bundle)

    def find(self,nodes,label,kind=None):
        matches=[node for node in nodes if label in (node.get('text'),node.get('originalText')) and (kind is None or node.get('type')==kind)]
        if not matches: raise ValueError(f'UI control is missing: {label}')
        return next((node for node in matches if node.get('clickable')=='true'),matches[0])

    def point(self,node):
        numbers=list(map(int,re.findall(r'-?\d+',node['bounds'])))
        x=(numbers[0]+numbers[2])//2;y=(numbers[1]+numbers[3])//2
        if node.get('enabled')=='false':raise ValueError('UI control is disabled')
        return str(x),str(y),node.get('displayId') or '0'

    def click(self,label,kind='Button'):
        node=self.find(self.snapshot(),label,kind)
        hdc(self.args,'shell','uitest','uiInput','click',*self.point(node))

    def wait(self,text,timeout=180):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            nodes=self.snapshot()
            if any(text in node.get('text','') for node in nodes):return nodes
            failure=next((node['text'] for node in nodes if node.get('type')=='Text' and '：失败' in node.get('text','')),None)
            if failure:raise ValueError(failure)
            time.sleep(0.5)
        raise ValueError(f'UI timed out waiting for: {text}')

    def enter_debug(self):
        self.click('关于')
        label='版本 '+manifest()['version']
        nodes=self.wait(label)
        button=self.find(nodes,label,'Button')
        for _ in range(6):hdc(self.args,'shell','uitest','uiInput','click',*self.point(button))
        assert not any(node.get('text')=='环境诊断' for node in self.snapshot()),'Debug opened before seven clicks'
        hdc(self.args,'shell','uitest','uiInput','click',*self.point(button))
        self.wait('环境诊断')

    def select(self,label,value):
        nodes=self.snapshot()
        candidates=[node for node in nodes if node.get('type') in ('Row','Button') and node.get('clickable')=='true' and label in node.get('text','')]
        if not candidates:
            # Locate the actual trigger above its selected-value text.
            values=[node for node in nodes if node.get('type')=='Text' and re.fullmatch(r'0\.\d+\.\d+|zig|ocp-hello',node.get('text',''))]
            candidates=[]
            for node in nodes:
                if node.get('type') not in ('Row','Button') or node.get('clickable')!='true':continue
                bounds=list(map(int,re.findall(r'-?\d+',node['bounds'])))
                for selected in values:
                    child=list(map(int,re.findall(r'-?\d+',selected['bounds'])))
                    if bounds[0]<=child[0] and bounds[1]<=child[1] and bounds[2]>=child[2] and bounds[3]>=child[3]:
                        candidates.append(node);break
        if len(candidates)!=1:raise ValueError(f'Cannot identify Select trigger: {label} ({len(candidates)})')
        hdc(self.args,'shell','uitest','uiInput','click',*self.point(candidates[0]))
        option=self.find(self.snapshot(),value)
        hdc(self.args,'shell','uitest','uiInput','click',*self.point(option))

    def installed_version(self,bundle):
        output=hdc(self.args,'shell','bm','dump','-n',bundle)
        if '{\n' not in output:return None
        return json.loads(output[output.index('{\n'):])['versionName']

    def hidden_tool(self,bundle):
        output=hdc(self.args,'shell','bm','dump','-n',bundle)
        data=json.loads(output[output.index('{\n'):])
        assert data['applicationInfo']['hideDesktopIcon'] is True, f'Tool creates a desktop icon: {bundle}'

    def navigation(self):
        labels=['工具','已安装','仓库','设置','关于']
        for mode in ['light','dark']:
            for label in labels:
                self.click(label)
                buttons=[node for node in self.snapshot() if node.get('type')=='Button' and node.get('text') in labels]
                assert [node['text'] for node in buttons if node.get('selected')=='true']==[label]
                selected=self.find(buttons,label,'Button')
                assert selected['backgroundColor'] not in ('','#00000000'),selected
            self.screenshot('navigation-'+mode)
            self.click('设置');self.click('切换明暗主题')
        self.enter_debug()
        assert self.find(self.snapshot(),'关于','Button')['selected']=='true'
        self.click('已安装');self.manage('core/zig')
        assert self.find(self.snapshot(),'已安装','Button')['selected']=='true'
        self.click('工具')
        self.passed('NAVIGATION_SELECTION_LIGHT_DARK_AND_NESTED_OK')

    def error_scope(self):
        self.click('仓库')
        self.type_input(0,'errorprobe');self.type_input(1,'invalidurl')
        self.click('添加并更新')
        message='服务地址必须使用 HTTP 或 HTTPS'
        nodes=self.wait(message)
        errors=[node for node in nodes if node.get('type')=='Text' and node.get('text')==message]
        assert len(errors)==1,errors
        assert int(re.findall(r'-?\d+',errors[0]['bounds'])[1]) < int(re.findall(r'-?\d+',self.find(nodes,'core')['bounds'])[1])
        self.screenshot('error-page-top')
        self.click('工具')
        assert not any(message in node.get('text','') for node in self.snapshot())
        self.click('仓库')
        assert not any(message in node.get('text','') for node in self.snapshot())
        self.click('工具')
        self.passed('ERROR_ALERT_TOP_AND_PAGE_ISOLATION_OK')

    def desktop(self):
        output=hdc(self.args,'shell','bm','dump','-n',self.bundle)
        app=json.loads(output[output.index('{\n'):])['applicationInfo']
        assert app['needAppDetail'] is False and app['hideDesktopIcon'] is False,app
        hdc(self.args,'shell','aa','force-stop',self.bundle)
        nodes=self.layout('com.ohos.sceneboard')
        ids={node.get('id','') for node in nodes}
        for bundle in ['com.richerfu.ocp.pkg.zig','com.richerfu.ocp.pkg.community.hello']:
            assert 'AppName_text_'+bundle not in ids,f'Unexpected desktop icon: {bundle}'
        icon=next(node for node in nodes if node.get('id')=='AppName_text_'+self.bundle)
        self.screenshot('desktop-icon')
        for mode in ['cold','warm','repeated']:
            hdc(self.args,'shell','uitest','uiInput','doubleClick',*self.point(icon))
            self.wait('工具')
            time.sleep(1)
            roots=[node for node in self.layout() if node.get('type')=='root' and node.get('bundleName')==self.bundle]
            assert len(roots)==1 and roots[0].get('abilityName')=='EntryAbility',roots
            self.screenshot('desktop-'+mode)
        self.passed('DESKTOP_UI_ONLY_SINGLE_WINDOW_AND_NO_TOOL_ICONS_OK')

    def type_input(self,index,value):
        switched=False
        try:
            for attempt in range(2):
                inputs=[node for node in self.snapshot() if node.get('type')=='TextInput']
                if index >= len(inputs):raise ValueError('Input field disappeared during UI automation')
                node=inputs[index]
                hdc(self.args,'shell','uitest','uiInput','click',*self.point(node))
                time.sleep(0.3)
                if attempt==1:
                    # Ctrl+Period switches this IME between Chinese/ASCII punctuation.
                    hdc(self.args,'shell','uitest','uiInput','keyEvent','2072','2044');switched=True
                    time.sleep(0.3)
                hdc(self.args,'shell','uitest','uiInput','keyEvent','2072','2017')
                time.sleep(0.2)
                hdc(self.args,'shell','uitest','uiInput','keyEvent','2055')
                time.sleep(0.2)
                hdc(self.args,'shell','uitest','uiInput','text',value)
                time.sleep(0.3)
                hdc(self.args,'shell','uitest','uiInput','keyEvent','2054')
                time.sleep(0.3)
                inputs=[node for node in self.snapshot() if node.get('type')=='TextInput']
                if index >= len(inputs):raise ValueError('Input field disappeared during UI automation')
                if inputs[index].get('text')==value:return
            raise ValueError('IME did not commit the requested input text')
        finally:
            if switched:
                inputs=[node for node in self.snapshot() if node.get('type')=='TextInput']
                hdc(self.args,'shell','uitest','uiInput','click',*self.point(inputs[index]))
                hdc(self.args,'shell','uitest','uiInput','keyEvent','2072','2044')

    def manage(self,name):
        nodes=self.snapshot();label=self.find(nodes,name)
        line_y=list(map(int,re.findall(r'-?\d+',label['bounds'])))[1]
        controls=[node for node in nodes if node.get('type')=='Button' and node.get('text')=='管理']
        control=min(controls,key=lambda node:abs(int(re.findall(r'-?\d+',node['bounds'])[1])-line_y))
        hdc(self.args,'shell','uitest','uiInput','click',*self.point(control))

    def screenshot(self,name):
        remote='/data/local/tmp/ocp-ui-test.png'
        hdc(self.args,'shell','uitest','screenCap','-p',remote)
        hdc(self.args,'file','recv',remote,self.work/f'{name}.png')

    def passed(self,name):
        self.steps.append(name);print(name,flush=True)

    def run(self):
        if self.installed_version('com.richerfu.ocp.pkg.zig')!='0.17.0':
            raise ValueError('Run native_lifecycle.py first to restore Zig through the device backend')
        hdc(self.args,'shell','aa','force-stop',self.bundle)
        hdc(self.args,'shell','aa','start','-a','EntryAbility','-b',self.bundle)
        self.wait('core/zig')
        deadline=time.monotonic()+120
        while self.find(self.snapshot(),'刷新','Button').get('enabled')=='false':
            if time.monotonic()>deadline:raise ValueError('Initial catalog refresh did not finish')
            time.sleep(.5)
        self.click('刷新')
        self.wait('刷新工具与安装状态：成功')
        # Reset this test-owned tap so its registration form remains reproducible.
        self.click('仓库')
        nodes=self.snapshot()
        labels=[node for node in nodes if node.get('type')=='Text' and node.get('text')=='community']
        if labels:
            y=int(re.findall(r'-?\d+',labels[0]['bounds'])[1])
            buttons=[node for node in nodes if node.get('type')=='Button' and node.get('text')=='移除仓库' and int(re.findall(r'-?\d+',node['bounds'])[1])>y]
            button=min(buttons,key=lambda node:int(re.findall(r'-?\d+',node['bounds'])[1]))
            hdc(self.args,'shell','uitest','uiInput','click',*self.point(button))
            self.wait('移除仓库 community：成功')
        self.click('工具')
        self.screenshot('tools')
        self.navigation()
        self.error_scope()
        nodes=self.snapshot()
        for label in ['已安装','最新版本','来源仓库','包发布者','上游项目','操作','RicherFu','openharmony-zig/zig-patch']:
            self.find(nodes,label)
        self.passed('PACKAGE_TABLE_AND_PROVENANCE_OK')
        self.passed('SHADCN_UI_READY')
        self.manage('core/zig')
        self.wait('core/zig')
        self.click('卸载');self.wait('确认卸载');self.click('取消')
        assert self.installed_version('com.richerfu.ocp.pkg.zig')=='0.17.0'
        self.passed('UNINSTALL_CANCEL_OK')
        self.click('卸载');self.click('确认卸载');self.wait('卸载 core/zig：成功')
        assert self.installed_version('com.richerfu.ocp.pkg.zig') is None
        self.select('安装版本','0.16.0')
        self.click('安装所选版本');self.wait('安装 core/zig 0.16.0：成功')
        assert self.installed_version('com.richerfu.ocp.pkg.zig')=='0.16.0'
        self.hidden_tool('com.richerfu.ocp.pkg.zig')
        self.passed('UI_INSTALL_016_OK')
        self.click('更新到最新版本');self.wait('更新 core/zig：成功')
        assert self.installed_version('com.richerfu.ocp.pkg.zig')=='0.17.0'
        self.hidden_tool('com.richerfu.ocp.pkg.zig')
        self.screenshot('details');self.passed('UI_UPGRADE_017_OK')
        self.click('仓库');self.wait('添加仓库')
        self.type_input(0,'community')
        base=self.args.repository_base_url or f'http://127.0.0.1:{self.args.port}'
        self.type_input(1,base.rstrip('/')+'/taps/community/index.tar.gz')
        self.click('添加并更新');self.wait('注册仓库 community：成功')
        self.screenshot('repositories');self.passed('THIRD_PARTY_TAP_ADD_OK')
        self.click('工具');self.wait('community/hello')
        # Find the manage button in the same native row as community/hello.
        self.manage('community/hello')
        self.wait('community/hello');self.click('安装所选版本');self.wait('安装 community/hello 0.1.0：成功')
        assert self.installed_version('com.richerfu.ocp.pkg.community.hello')=='0.1.0'
        self.hidden_tool('com.richerfu.ocp.pkg.community.hello')
        self.passed('TOOL_DESKTOP_ICONS_HIDDEN_OK')
        self.passed('THIRD_PARTY_INSTALL_OK')
        self.enter_debug();self.select('测试命令','ocp-hello');self.click('运行命令测试');self.wait('OCP_TAP_HELLO_OK')
        self.passed('THIRD_PARTY_COMMAND_OK')
        self.click('Zig 命令测试');self.wait('Zig 命令测试：成功');self.wait('0.17.0')
        self.passed('DEBUG_SEVEN_CLICKS_AND_ZIG_OK')
        self.click('Zig 编译测试');self.wait('Zig 编译测试：成功',300)
        binary=self.work/'ocp-debug'
        hdc(self.args,'file','recv','-b',self.bundle,'data/storage/el2/base/haps/entry/files/ocp/ocp-debug',binary)
        remote='/data/local/tmp/ocp-ui-debug'
        hdc(self.args,'file','send',binary,remote)
        output=hdc(self.args,'shell',f'chmod 755 {remote}; {remote}')
        assert 'OCP_UI_COMPILE_OK' in output,output
        self.screenshot('debug');self.passed('DEBUG_COMPILE_RUN_OK')
        self.click('工具');self.click('刷新');self.wait('刷新工具与安装状态：成功')
        self.desktop()
        report={'target':self.args.target,'framework':'Arkit shadcn','bundle':self.bundle,'steps':self.steps,
                'hnp_sha256':digest(ROOT/'dist/arm64-v8a/ocp.hnp'),
                'hap_sha256':digest(ROOT/'dist/arm64-v8a'/'ocp-manager-debug.hap'),
                'compile_run':output.strip(),'installation_backend':'device BMS with ordinary app BM permission',
                'host_tool_installation':False,
                'screenshots':[str(path) for path in sorted(self.work.glob('*.png'))]}
        write_json(self.work/'report.json',report)
        write_json(ROOT/'dist/arm64-v8a/ui-verification.json',report)
        print(f'UI verification passed: {self.work / "report.json"}',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',required=True);parser.add_argument('--server',default='127.0.0.1:8710');parser.add_argument('--port',type=int,default=18090)
    parser.add_argument('--repository-base-url',help='Static test repository root containing core/ and taps/')
    DeviceUI(parser.parse_args()).run()


if __name__=='__main__':
    try:main()
    except (ValueError,AssertionError,OSError) as error:print(f'ui-test: {error}',file=sys.stderr);sys.exit(1)
