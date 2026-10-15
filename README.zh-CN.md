# OCP

[English](README.md) · [简体中文](README.zh-CN.md)

**OpenHarmony Command Package**：通过原生应用或 CLI，在 OpenHarmony 上安装、更新和管理命令行工具。

## 功能

- 从已注册仓库安装、更新和卸载工具。
- 使用 Arkit 开发的 shadcn 风格管理界面。
- 查看已安装版本、包发布者和上游项目。
- 添加社区仓库，无需修改 OCP。
- 在兼容终端中使用已安装命令。工具包不包含 UI，也不新增桌面图标。

## 使用

打开 OCP，在“仓库”中添加来源，再从“工具”或“已安装”页面管理软件包。桌面 OCP 图标打开管理界面。

使用 CLI 时，先注册仓库维护者提供的索引地址，再执行：

```sh
ocp tap add core <仓库索引地址>
ocp update
ocp install core/zig
zig version
ocp upgrade core/zig
ocp uninstall core/zig
```

[OCP Repository](https://github.com/harmony-contrib/ocp-repo) 维护支持的工具配方，目前先提供 Zig。Git 仓库地址与可下载的软件包索引地址不同。

OCP 当前为开发预览版。设备验证使用 DevEco ARM64 2in1 模拟器，部署条件与平台要求见下方文档。

## 文档与贡献

- [构建和验证 OCP](example/README.md)
- [应用界面与交互](docs/ui.md)
- [仓库注册与存储](docs/repositories.md)
- [贡献工具包](https://github.com/harmony-contrib/ocp-repo/blob/main/CONTRIBUTING.zh-CN.md)
- [创建社区仓库](docs/contributing-taps.md)
- [设备安装条件](docs/device-backend.md)
- [鸿蒙模拟器本地编译与执行 Skill](skills/harmonyos-emulator-native-exec/SKILL.md)

工具配方和发布内容在 [ocp-repo](https://github.com/harmony-contrib/ocp-repo) 维护；应用、CLI、打包工具和仓库协议的改动在本仓库维护。

## 许可证

OCP 使用 [MIT 许可证](LICENSE)。第三方组件和工具遵循各自许可证，见 [第三方许可说明](THIRD_PARTY_NOTICES.zh-CN.md)。
