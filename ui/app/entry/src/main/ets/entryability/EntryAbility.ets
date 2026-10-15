import { NativeAbility } from '@ohos-rs/ability';
import window from '@ohos.window';
import { configure } from 'libocp_ui.so';

export default class EntryAbility extends NativeAbility {
  public moduleName: string = 'ocp_ui';
  public defaultPage: boolean = false;
  protected async loadWindowStageContent(stage: window.WindowStage): Promise<void> {
    configure(this.context.filesDir);
    await stage.loadContent('pages/Index');
  }
}
