# 第三方许可说明

[English](THIRD_PARTY_NOTICES.md) · [简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

OCP 的 [MIT 许可证](LICENSE) 覆盖本仓库的原创代码与文档。第三方组件和工具保留各自的许可证与版权声明。

引导运行时使用适配后的 Zig Maker、nlohmann/json 和 OpenHarmony 平台接口。构建脚本会把对应的上游声明复制到运行时中，文件名为 `LICENSE-ZIG`、`LICENSE-JSON`、`LICENSE-platform-ipc` 和 `LICENSE-platform-c-utils`。

管理应用使用 Arkit 及 Rust 依赖，依赖声明见 [ui/Cargo.toml](ui/Cargo.toml)，固定版本见 [ui/Cargo.lock](ui/Cargo.lock)。各依赖的许可证与附加声明以其源码发行内容为准。运行时生成的许可文件并不是应用依赖的完整清单。

可下载工具的配方与上游许可信息在 [ocp-repo](https://github.com/harmony-contrib/ocp-repo) 单独维护。再分发工具或 OCP 构建产物时，需要保留实际包含组件所要求的声明；OCP 的 MIT 许可证不会重新授权这些组件。
