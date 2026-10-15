import UIAbility from '@ohos:app.ability.UIAbility';
import probe from '@app:com.richerfu.ocp.example/entry/ocp_probe';
import accessCtrl from '@ohos:abilityAccessCtrl';
import bundleManager from '@ohos:bundle.bundleManager';

export default class OcpAbility extends UIAbility {
  onCreate(want) {
    bundleManager.getBundleInfoForSelf(bundleManager.BundleFlag.GET_BUNDLE_INFO_WITH_APPLICATION).then((info) => {
      const manager = accessCtrl.createAtManager();
      for (const permission of ['ohos.permission.ALLOW_USE_BM', 'ohos.permission.INTERNET',
        'ohos.permission.ALLOW_EXTERNAL_NATIVE_CODE']) {
        console.info(`OCP_PERMISSION ${permission}=${manager.checkAccessTokenSync(info.appInfo.accessTokenId, permission)}`);
      }
    }).catch((error) => { console.error(`OCP_PERMISSION_ERROR ${JSON.stringify(error)}`); });
    if (want.parameters && want.parameters.nativeLifecycle === true) {
      probe.runSmoke(this.context.filesDir, 1);
    } else if (want.parameters && want.parameters.runSmoke === true) {
      probe.runSmoke(this.context.filesDir);
    }
  }

  onWindowStageCreate(stage) {
    stage.loadContent('pages/Index', (error) => {
      if (error && error.code) {
        console.error(`OCP page failed: ${error.code} ${error.message}`);
      }
    });
  }
}
