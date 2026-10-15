# 第三方 tap 示例

这是可复制为独立 Git 仓库的 `community` 示例，提供 `community/hello` 和 `ocp-hello` 命令。构建、发布和设备注册步骤见 [贡献指南](../../docs/contributing-taps.md)。

独立使用时，替换配方和 README，并补充配方 LICENSE 与维护者 CODEOWNERS。GitHub 的仓库变量 `OCP_TOOLS_REPOSITORY` 指向维护者选用的 OCP 工具仓库，`OCP_TOOLS_REV` 必须固定为已审核的 40 位 commit SHA。该仓库尚未发布远程地址，因此模板不虚构默认地址。

PR 工作流只读取与验证 JSON，不执行贡献者的 assemble.sh，也不授予发布权限。正式构建在有 DevEco SDK 的可信环境中运行；索引发布跟随已审核的版本提交，发布文件保持不可变。
