# 第三方配方维护与协作

第三方可以独立维护 `ocp-<tap>` Git 仓库，贡献配方与发布预编译工具包，无需修改 OCP CLI 或管理应用。OCP 的主仓库维护协议和打包器；tap 维护者负责工具来源、适配、许可证、版本更新和发布物。

## 仓库结构

```text
ocp-community/
  README.md
  LICENSE
  CODEOWNERS
  installer/
    tool/
      component.json
      assemble.sh
      versions/1.2.2.json
  .github/workflows/
    validate.yml
    release.yml
```

README 必须声明 tap 名称、索引地址、支持的 ABI、维护者、工具用途和安装示例。LICENSE 覆盖配方代码，工具上游许可证随工具包保留。CODEOWNERS 指定能审核配方与发布配置的维护者。

配方还可声明 `publisher.name` 和可选的 `publisher.url`，提供包维护者信息；`release` 指向上游项目/版本。这些字段将出现在管理表格和来源详情中，包发布者与上游作者分别展示。它们是仓库声明的信息，不授予权限，也不替代签名校验。

## 贡献流程

1. 贡献者 fork 仓库，为新工具或版本修改配方，固定上游 URL 与 SHA-256，并提交 PR。
2. PR 的 CI 校验名称、版本、ABI、命令清单与校验字段；构建与发布权限不得提供给外部 PR。
3. 维护者审核实际修改的 commit。构建使用该 commit；PR 更新后必须重新审核。
4. 在具有 DevEco SDK 的可信环境生成 HNP 和无 UI HAP，使用获批准的开发签名材料签名，随后生成带最终 HAP hash 的 Bottle，在 DevEco 模拟器验证设备安装与命令。当前 BM 普通应用路径只接受 debug profile，适配设备集合必须明确。
5. 维护者发布不可变的版本文件，再运行 `ocp.py publish` 生成索引。索引引用已经可下载的 Bottle，最后切换索引地址。

格式定义位于 `schemas/formula.schema.json` 与 `schemas/registry.schema.json`。PR 可执行 `python3 scripts/check-formulas.py --root /path/to/tap`，只读取 JSON，不下载资源或执行组装脚本。`example/tap/.github/workflows/validate.yml` 是可复制的 PR 校验模板，需要维护者配置 OCP 工具仓库地址与审核过的 commit SHA。

可信发布任务可以先用平台批准的签名工具签署 HAP，再向 `ocp.py bottle` 传入 `--signed-hap /path/to/tool-signed.hap`。构建器复核其 bundle、版本、HNP、命令和 ABI，随后计算最终 hash 和封装 Bottle；BMS 在安装时验证证书和 profile。`--signed-hap` 与模拟器专用的 `--debug-udid` 互斥。未指定签名参数仅生成组装产物；通过设备 BMS 安装前必须使用适配目标设备的有效签名。

示例 `example/tap/installer/hello` 提供一个完整的第三方验证配方，可以按以下命令复现：

```sh
python3 scripts/ocp.py bottle hello --tap community --version 0.1.0 \
  --config example/tap/installer/hello/component.json --abi arm64-v8a \
  --debug-udid "$OCP_EMULATOR_UDID"
python3 scripts/ocp.py publish --tap community \
  --base-url http://127.0.0.1:18090/taps/community \
  --output example/build/native-repository/taps/community
python3 example/static_repository.py --directory example/build/native-repository
```

设备执行 `ocp tap add community http://127.0.0.1:18090/taps/community/index.tar.gz`，更新后可安装 `community/hello`，其导出命令为 `ocp-hello`。服务只提供静态文件，安装由设备 BMS 完成，无需修改 CLI 的工具列表。loopback 需要 HDC reverse 转发用于下载测试，正式静态仓库使用可从设备直接访问的 HTTPS URL。

## 版本与问题处理

命令工具的签名 profile 必须具备 `AllowAppDesktopIconHide`，避免系统为无 home Ability 的 HAP 补充桌面入口。模拟器 debug 签名器会添加这一能力；正式签名任务使用平台批准的能力配置，不能只写 `module.json` 的隐藏字段。管理 UI 的 profile 不配置这一能力。详见 [桌面入口与签名要求](ui.md#桌面入口)。

发布后的版本与校验值保持不可变。修复使用新的版本号；删除索引条目不会自动卸载设备已有工具。兼容性变更在 PR 与 Release 中说明。工具提供多个命令时，完整声明所有命令；需要共存的变体必须改用不同命令名，避免覆盖其他 tap 已安装的命令。

依赖自动解析、索引签名与撤回列表属于后续协议能力；当前第三方配方须发布完整且能独立运行的资源。设备宿主需要 BM 授权，工具需要有效 debug profile；发布仓库不替代权限和系统签名检查。SDK 公共测试密钥仅用于指定模拟器的调试，不能用于正式发行。

协作约定参考 [Homebrew 维护 Tap 的流程](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)。OCP 采用 JSON 配方、shell 组装与 HNP/HAP Bottle，遵循 [OCP 仓库协议](repositories.md)。
