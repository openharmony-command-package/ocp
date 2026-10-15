# OCP 仓库注册与发布协议

OCP 将命令运行时、配方仓库和已发布工具包分开。任何第三方都可以维护自己的配方 Git 仓库，发布静态索引和 Bottle；设备通过注册仓库安装其预编译 HNP。CLI 与 Arkit 管理应用使用相同协议和安装收据。最终 HNP 保持无 UI。

## 仓库身份

每个仓库拥有稳定的 tap 名称，例如 `core`、`community`。名称使用小写字母、数字和下划线，并以字母开头。工具身份为 `tap/tool`，例如 `core/zig`。短名称只在已注册仓库中唯一时解析；同名时必须使用完整身份。

注册记录保存 URL，不能通过更新索引静默修改来源。更换来源必须移除原注册后重新添加。注册下载索引，不会自动安装其中的工具。安装仍由用户的 CLI 命令或 UI 操作发起。

```sh
ocp tap add community https://packages.example.org/ocp/index.tar.gz
ocp tap list
ocp update
ocp install community/tool --version 1.2.3
ocp upgrade community/tool
ocp uninstall community/tool
ocp tap remove community
```

存在该仓库的本地安装收据时，移除注册会被拒绝，需先卸载工具。`OCP_REPOSITORY` 作为早期单仓库配置的迁移入口，注册到 `core`。

## 配方与发布物

配方源代码保留在 Git；设备只下载发布索引与 Bottle，不运行第三方组装脚本。配方目录包含 `component.json`、`assemble.sh` 和可选的 `versions/<version>.json`。每个版本按 ABI 声明上游归档 URL、SHA-256 和导出命令。组装脚本必须保留工具运行所需的库文件和许可证。

一个第三方工具的 bundle 必须为 `com.richerfu.ocp.pkg.<tap>.<tool>`，HNP 名称为 `ocp_<tap>_<tool>`。`core` 继续使用已有的 `com.richerfu.ocp.pkg.<tool>` 与 `ocp_<tool>`。同一工具的 bundle/HNP 名称保持稳定，版本递增。工具安装 HAP 必须没有 Ability；UI 只在 OCP 管理应用中存在。

```sh
python3 scripts/ocp.py bottle tool --tap community --version 1.2.3 \
  --config /path/to/ocp-community/installer/tool/component.json --abi arm64-v8a
python3 scripts/ocp.py publish --tap community \
  --base-url https://packages.example.org/ocp \
  --output dist/repositories/community
```

发布目录可以直接由静态网站或 Release 附件托管。索引包 `index.tar.gz` 只含 `catalog/registry.json`、`registry.tsv` 和 `index.tsv`；工具 Bottle 分别位于 `bottles/<abi>/<tool>/<version>/`。Bottle 是 ZIP，包含 `bottle/<tool>.hap` 与 `receipt.json`。

## 协议 2

配方可声明 `publisher: {"name": "发布者名称", "url": "https://…"}`，其中 URL 可省略；`release` 用于工具的上游项目/Release 地址。构建器将发布者写入 receipt 和 JSON 索引，将 release 写入 `upstream`。管理表格分别展示来源 tap、包发布者和上游项目，详情显示完整地址与可执行命令。核心 Zig 包发布者为 RicherFu，上游为 `openharmony-zig/zig-patch`；第三方自行提供这些字段，未提供时显示“未声明”。

发布者是仓库声明的展示信息，不是额外的签名身份认证。UI 只读取当前 generation 的 sources.tsv 指向的缓存索引，并核对 tap、工具、版本、ABI、bundle 和 HAP SHA 与活动 TSV 一致。已安装工具使用当前安装版本的来源信息，未安装工具使用最新版本；错误或缺失的可选 JSON 信息不替代实际安装身份检查。展示索引读取上限为 2 MiB。八字段 TSV 保持不变，旧仓库仍可安装。

`registry.json` 为工具链读取的 JSON 描述，包含 `schema_version: 2`、`tap` 和 `packages`。每个包包含名称、版本、ABI、bundle、HNP 名称、导出命令、HAP SHA-256 和 Bottle 相对路径。`registry.tsv` 是设备 shell 使用的等价协议头，一行两个字段：`2<TAB>tap`。

`index.tsv` 按以下顺序包含八个字段。字段不得含制表符或换行。

| 字段 | 含义 |
| --- | --- |
| name | 仓库内的工具名称 |
| version | 不可变的版本号 |
| abi | arm64-v8a、x86_64 或 armeabi-v7a |
| bundle | 与 tap/tool 对应的固定 bundle |
| hap_sha256 | 解包后 HAP 的 SHA-256 |
| url | Bottle 的绝对 HTTP/HTTPS URL |
| latest | 该工具/ABI 的最新版本为 1，其他为 0 |
| commands | 逗号分隔的导出命令 |

设备合并索引时为 name 加 tap 前缀，校验 namespace、ABI、bundle、校验值、最新标记和重复版本。已安装其他工具占用相同命令时，安装被拒绝。正式发布使用 HTTPS；当前 loopback 开发仓库使用 HTTP。

## 更新与本地存储

`ocp update` 把所有已注册仓库下载到临时 generation，全部验证成功后原子替换 `catalogs/current` 指针。任一仓库更新失败，原来的活动 generation 继续使用。源注册、活动索引和安装状态分开保存。

```text
<OCP_STATE_DIR>/
  settings.json                 Arkit 宿主的服务配置，权限 0600
  taps/<tap>                    用户注册的索引 URL
  catalogs/current              活动 generation 的名称
  catalogs/generations/<id>/
    index.tsv                   已验证的合并索引
    sources.tsv                 tap、URL 与内容缓存 hash
  installed/<tap>@<tool>         版本、bundle、HAP hash、命令和完整工具身份
  cache/                        Maker 的内容寻址下载缓存
```

只有 BMS 成功回调后才更新收据；只有卸载成功后才删除收据。CLI 在不同 PTY 宿主中的状态目录各自独立。默认的 `ocp sync` 根据活动索引核对系统 HNP 可执行链接和版本，供 UI 识别其他 PTY 已安装的工具。它不枚举未注册工具，收据 hash 来自匹配的不可变索引项。

CLI 宿主应显式设置持久化的 `OCP_STATE_DIR`，例如可写 HOME 下的 `.ocp`；CLI 的默认状态在 TMPDIR/cache 下，缓存清理会删除其注册与收据。管理应用直接使用 filesDir/ocp，注册与设置不依赖应用缓存。缓存自动回收与旧状态迁移属于后续存储策略。

| 所有者 | 责任 |
| --- | --- |
| installer/ocp/ocp.sh | 设备仓库注册、索引事务、版本选择、命令冲突与收据 |
| installer/ocp/native/ | 使用宿主 BM 授权调用设备 BMS，校验实际工具 HAP |
| scripts/ocp.py | 主机配方组装、官方 SDK 打包与发布物验证 |
| ui/crates/ocp_client | 调用 CLI、读取活动快照和宿主配置 |
| ui/crates/ocp_ui | Arkit shadcn 页面与操作状态 |
| example/static_repository.py | 只提供静态索引和 Bottle 下载 |

当前接口保留版本与来源信息，但没有实现自动依赖解析、签名索引、旧 generation 自动回收或运行时包回滚。这些能力需要协议和迁移升级，不能用现有字段声称已经支持。版本发布必须新增版本号，禁止替换同一版本的已发布 HAP。

## 安装后端

统一使用设备 BMS，第三方仓库注册后可以直接通过设备安装路径使用。设备不会运行第三方配方脚本；只下载并校验带签名的预编译 HAP/HNP。设备适配器核对实际 bundle、版本、命令和无 UI 条件，BMS 保留自己的权限、签名和版本检查。

普通应用 BM 路径要求 API 26 2in1、开发者模式、宿主 BM 授权和 debug 工具 profile。当前验证用签名绑定指定模拟器 UDID，不能把这些调试 Bottle 当作适用于所有用户的发行包。第三方应使用获批准的开发签名流程，保留历史版本和签名身份，并按可安装设备集合发布适配产物。详见 [设备后端与权限](device-backend.md)。

签名完成后才能计算 HAP hash 和发布 Bottle。同一来源已经发布的版本禁止重新签名覆盖；换签名、换目标设备 profile 或重建内容时需要新的发行版本或明确隔离的新仓库来源。协议 2 没有 bottle revision 字段，不能隐式覆盖旧 hash。

协作流程见 [第三方贡献指南](contributing-taps.md)。本方案借鉴 [Homebrew Taps](https://docs.brew.sh/Taps) 的第三方来源与完整名称机制；设备侧采用静态发布快照，以适应当前鸿蒙运行环境。
