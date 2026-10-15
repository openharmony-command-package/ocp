import { DefaultXComponent } from '@ohos-rs/ability';
import { onBackPressIntercept } from 'libocp_ui.so';

@Entry
@Component
struct Index {
  onBackPress(): boolean { return onBackPressIntercept(); }
  build() {
    Column() {
      DefaultXComponent({ moduleName: 'ocp_ui' }).width('100%').height('100%')
    }.width('100%').height('100%')
  }
}
