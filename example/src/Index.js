import probe from '@app:com.richerfu.ocp.example/entry/ocp_probe';

class Index extends ViewPU {
  constructor(parent, params, storage, id = -1, extraInfo) {
    super(parent, storage, id, extraInfo);
    this.__status = new ObservedPropertySimplePU(probe.getStatus(), this, 'status');
    this.finalizeConstruction();
  }

  get status() { return this.__status.get(); }
  set status(value) { this.__status.set(value); }

  aboutToAppear() {
    this.timer = setInterval(() => { this.status = probe.getStatus(); }, 500);
  }

  purgeVariableDependenciesOnElmtId(id) {
    this.__status.purgeDependencyOnElmtId(id);
  }

  initialRender() {
    this.observeComponentCreation2(() => {
      Column.create({space: 16});
      Column.width('100%');
      Column.height('100%');
      Column.justifyContent(FlexAlign.Center);
    }, Column);
    for (const [text, size] of [
      ['OCP', 36],
      ['OpenHarmony Command Package', 20],
      ['Zig 0.17.0', 24]
    ]) {
      this.observeComponentCreation2(() => {
        Text.create(text);
        Text.fontSize(size);
      }, Text);
      Text.pop();
    }
    this.observeComponentCreation2(() => {
      Text.create(this.status);
      Text.fontSize(18);
    }, Text);
    Text.pop();
    this.observeComponentCreation2(() => {
      Button.createWithLabel('验证 Zig 编译');
      Button.onClick(() => { probe.runSmoke(getContext(this).filesDir); });
    }, Button);
    Button.pop();
    Column.pop();
  }

  rerender() {
    this.updateDirtyElements();
  }

  aboutToBeDeleted() {
    clearInterval(this.timer);
    this.__status.aboutToBeDeleted();
    SubscriberManager.Get().delete(this.id__());
    this.aboutToBeDeletedInternal();
  }
}

loadDocument(new Index(undefined, {}));
