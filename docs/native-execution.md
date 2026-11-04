# 真机本地编译与执行方案

2026-10-15，依据此前提供的 MateBook 固件、固定提交的 OpenHarmony 源码、原版 DevEco 模拟器的真实 PTY 对照结果，以及用户反馈的真机手工自签名结果整理。本报告区分固件静态分析、直接运行验证和用户反馈，不将模拟器结果当作 API24 真机结论。

## 结论

真机固件包含第三方开发工具执行 ad-hoc 自签名 ELF 的处理链。对 OCP/Zig 而言，应补齐的是：终端获得合适的运行环境，Zig 在链接后为新生成的 ELF 添加 ad-hoc 签名，再由系统二进制安全服务完成管控、签名使能和文件标签转换。

用户已确认：在此前讨论的 API24 真机上，按上述思路对现场生成的缓存 Maker 手工自签名后，重新执行 `zig init` 可以成功。这确认了该设备和终端环境中这条执行路径可用。工具链尚未接入自动签名，仍需验证空缓存下无需手工干预的完整开发流程；仅凭这次反馈也不能确定原先拒绝的具体子系统或哪些宿主权限是必要条件。

给 OCP 工具安装包增加权限不能替代 OHOSTTY/IDE 宿主的授权。现有无权限 OCP HAP 可以继续承担分发 Zig 的职责，无需为这条方案恢复 BM 权限。

## 证据基线

- 固件来源：[用户提供的 MateBook 更新清单](https://update.dbankcdn.com/download/data/pub_13/HWHOTA_hota_900_9/43/v3/7iUm9qRlQgm4LTz5ut812A/full/filelist.xml)。已校验提取的 `/system` SHA-256：`8a4ec0bfd42ece76087e90d2a2cd43d5870b08d2712f525766bc3097b1d8ba38`。
- 固件 `libappspawn_common.z.so` SHA-256：`50054444e4efa6826e45caa3c8d9e675e4ed3bedc67b0dcecf5659915a0e3287`。
- 固件 `libsps_binary_security_service.z.so` SHA-256：`230d12ecc6889ac570b534e57ed54140c89ad8c8a0dad3feaac688096102a172`。
- 公共源码固定到 [hapsigner 24ef0c8](https://github.com/openharmony/developtools_hapsigner/tree/24ef0c843d94f68d16975cac42e377f31def48c6)、[code_signature f41e32b](https://github.com/openharmony/security_code_signature/tree/f41e32b1beca7913bd2c5d888a6ec74dfb5ffe20)、[selinux_adapter b8cc1cb](https://github.com/openharmony/security_selinux_adapter/tree/b8cc1cb5ab75f246b7ec0d8a5ef047b7c69e8c65)、[access_token 17d88bf](https://github.com/openharmony/security_access_token/tree/17d88bfb36bea6c9370ba919ac41a22d16dd66b3)。公共源码不是该商业固件的完整精确源码，因此关键商业行为另用固件反汇编核对。
- 本地完整证据在 `build/native-exec-source-analysis/`，厂商二进制仍位于 `build/zig-init-investigation/matebook-components/`，不随源码仓库分发。

## 宿主授权与执行域

[AppMgr 的启动实现](https://github.com/openharmony/ability_ability_runtime/blob/a0047a48162ef9b18dd403c14925058d506c3d0f/services/appmgr/src/app_mgr_service_inner.cpp)在 `SetStartMsgCustomSandboxFlag()` 中先检查产品能力，再校验宿主的 `CUSTOM_SANDBOX`，成功后设置 AppSpawn 消息标志索引 31。

固件的 `SetHapDomainInfo()` 在地址 `0x11614` 检查该消息标志，在 `0x11624` 执行 `orr x8, x8, #0x10`。这和 [SELinux 头文件](https://github.com/openharmony/security_selinux_adapter/blob/b8cc1cb5ab75f246b7ec0d8a5ef047b7c69e8c65/interfaces/policycoreutils/include/hap_restorecon.h)的 `SELINUX_HAP_CUSTOM_SANDBOX = 16` 一致。这里是掩码 `0x10`，不是位索引 16；此前 Skill 的文字记录已修正，辅助脚本原本使用的掩码正确。

固件 `sehap_contexts` 第 119–125 行明确区分：

| 宿主 | 满足 custom_sandbox 时的域 | 应用数据类型 |
| --- | --- | --- |
| 通用正式开发工具 | develop_tools_hap | appdat |
| 通用 debug 开发工具 | develop_tools_debug_hap | debug_hap_data_file |
| DevEco Studio | ide_hap / ide_debug_hap | appdat / debug_hap_data_file |
| CodeArts | codearts_hap / codearts_debug_hap | appdat / debug_hap_data_file |
| HiShell | hishell_hap / hishell_debug_hap | hishell_hap_data_file |

通用规则没有写死我们的 bundle，第三方不需要冒用华为包名。包名专用域的规则也不能用于宣称第三方获得了这些应用的全部能力。

固件基础 `appfwk.para` 中产品参数默认值仍为 false。产品分区和持久化配置可能覆盖它，单看该文件不能判断真机运行值。不能把模拟器中手工预置 true 的结果写成真机默认配置已经得到验证。

OHOSTTY 当前 PTY 源码 `crates/ohostty-pty/src/lib.rs::PtyProcess::start()` 使用 `openpty`、`Command::spawn()` 和 `setsid/TIOCSCTTY` 启动 shell；它没有取得新权限或设置弱沙箱执行域。应由宿主启动链路建立环境，而不是在 PTY 的 fork 回调中强行切换身份。

[权限定义](https://github.com/openharmony/security_access_token/blob/17d88bfb36bea6c9370ba919ac41a22d16dd66b3/services/accesstokenmanager/permission_definitions.json)中，两个权限均为 `system_grant`、`system_basic`、`provisionEnable=true`；`CUSTOM_SANDBOX` 自 API18 起，`ALLOW_EXTERNAL_NATIVE_CODE` 自 API23 起且设备类型限定 `2in1`。这说明需要按平台流程配置受限权限和有效 profile，并检查实际授予状态；不等于应把应用 APL 改成 system_basic，也不能仅按最低 API24 推断所有设备形态均支持。

## ad-hoc 自签名与本地签名服务是两条路径

### 官方 binary-sign-tool 的 selfSign

[CodeSigning::GetElfCodeSignBlock()](https://github.com/openharmony/developtools_hapsigner/blob/24ef0c843d94f68d16975cac42e377f31def48c6/binary_sign_tool/codesigning/sign/src/code_signing.cpp)明确执行：

1. self-sign 模式设置签名标志 `1 << 4`，即 `0x10`。
2. 生成 fs-verity 摘要结构。
3. 使用 descriptor digest 作为签名数据，不调用证书私钥签名分支。

[SignElf::WriteSecDataToFile()](https://github.com/openharmony/developtools_hapsigner/blob/24ef0c843d94f68d16975cac42e377f31def48c6/binary_sign_tool/hap/sign/src/sign_elf.cpp)在该模式跳过 profile、permission 节写入。

因此，`-selfSign 1` 并不要求取得真机私钥，也没有通过该模式附带调试 UDID 绑定。电脑可以生成这种格式，设备上也可以用移植的 Native 实现生成；最终能否执行仍由设备策略决定。不能把这种摘要签名解释成发布者身份认证。

### 系统 SignLocalCode 服务

[permission_utils.cpp](https://github.com/openharmony/security_code_signature/blob/f41e32b1beca7913bd2c5d888a6ec74dfb5ffe20/services/local_code_sign/src/permission_utils.cpp)将签名调用者限定为 `compiler_service`，初始化本地证书调用者限定为 `key_enable`，并比较 Native Token，而不是只检查普通 HAP 的权限声明。[IPC stub](https://github.com/openharmony/security_code_signature/blob/f41e32b1beca7913bd2c5d888a6ec74dfb5ffe20/services/local_code_sign/src/local_code_sign_stub.cpp)在签名前执行该检查。

真机库包含相同的调用者字符串、`GetCallingTokenID` 和 `GetNativeTokenId` 导入；SA 3507 的配置也与本地签名服务一致。固件 SELinux 仅为指定系统域提供获取该 SA 的规则。

普通终端不能因为库里导出了 `SignLocalCode` 就将它当作可用的公开 NDK 接口。本方案不依赖调用这个服务。

## 真机如何处理自签名文件

固件 `libsps_binary_security_service.z.so` 的以下行为已通过指令、跳转目标、数据指针和字符串交叉引用核对，而非只根据导出名称推测：

| 步骤 | 固件证据 |
| --- | --- |
| 外部二进制处理链 | `HandleExtFirstCall` 入口 `0xdba78`，实现 `0xa832c`；构造标签检查、签名节解析和签名类型判断等节点 |
| 识别 ad-hoc 签名 | `CheckSigned` 入口 `0xdb9e8`，实现 `0xa00e8`；`0xa0110` 检查签名 flags 的第 4 位 |
| 选择 ad-hoc 分支 | `0xa01b8` 将 certType 设为 2，返回专用状态 `0x3ca7680a`；`ExtFirstCallFallback` 在 `0xb1fc0` 匹配该状态，经 GOT `0xe6cc0` 获取 `g_adhocFallbackTask` 并执行 |
| ad-hoc 处理节点 | 构造处 `0x577c0`、`0x5783c`、`0x578ac` 分别引用 `LoadBinCtrlAndManage`、`SignEnforce`、`SetFileCon` |
| 签名使能 | `SignEnforceCall` 实现 `0xa20d8`，检查文件状态并调用 `CertificateManager::EnforceCodeSign()` |
| 文件类型转换 | `CertTypeToFileContext` 实现 `0xa3294`，表 `0xdfbb0` 包含 normal/debug/adhoc 标签及 dev_ 变体；`SetFileCon(fd, label)` 实现 `0xa32f4` 调用 `fsetfilecon()` |

这条 ad-hoc 分支是处理已经具有自签名块的文件，不是自动给任意无签名编译产物补签名。

文件标签白名单位于 `0xe9ef8`，初始化代码在 `0x56ad4` 起，包含 `appdat`、`normal_hap_data_file`、`debug_hap_data_file`、`hishell_hap_data_file`、`data_user_file` 等。系统 `code_protect` 域也有这些类型的 relabel 权限。因此不能认定应用私有目录天然被这条链排除；但这不证明任意目录、sharefs 视图或文件系统都满足签名使能条件。

固件 CIL 第 118354–118363 行允许 HAP 域执行 `adhoc_bin_file` 并转换为 `adhoc_bin`；第 118987–119005 行另有 custom_sandbox 的对应规则和 dev_ 变体。正式运行中，子程序进入 `adhoc_bin` 可以是正常结果，不能把“所有子进程始终保持 develop_tools_debug_hap”设为验收条件。

以上说明写入 `.codesign`、系统验证与使能、文件标签转换、执行域转换是不同步骤。应用不应自行 `chcon` 或修改系统 SELinux 规则来代替后续步骤。

## Zig 的修复边界

已读取 [Zig 0.17.0 的 src/main.zig](https://codeberg.org/ziglang/zig/src/tag/0.17.0/src/main.zig)：`mainArgs()` 在第 351 行附近将 `build/fetch/init/libc/cache-cat` 交给 `jitCmd()`，指定 `Maker.zig` 和 ReleaseSafe；内部的 `jitCmdInner()` 在编译结束后拼接缓存中 Maker 的路径，于第 5215 行附近直接 `process.replace()`，失败即输出当前看到的 `execve ... AccessDenied`。两者之间没有 HarmonyOS 签名步骤。

`zig run/test` 在同文件第 4640 行附近的执行流程另行构造目标路径并 replace/spawn。因此，只给 `jitCmd()` 加签名能覆盖首次 Maker，却不能代替所有最终 ELF 的产出适配。Maker 里的构建配置程序又是后续独立执行步骤。

仅在 shell 外层包装 `zig` 不能处理编译器内部立即执行 Maker 的过程。修复必须覆盖实际生成和执行这些 ELF 的路径：

- 首次现场编译的 Maker。
- 构建配置程序、测试程序和 `zig run` 的临时程序。
- 用户编译后需要本地执行的最终 ELF；加载共享库时还需要分别验证加载策略。

推荐顺序：

1. 保留现场生成 Maker、手工自签名后重试 `zig init` 的真机成功结果作为基线。这一步不需要预编译 Maker，也不需要系统本地签名服务；结果来源和未采集的信息见下文。
2. 将 ad-hoc 签名接入 Zig OHOS 的 ELF 链接完成阶段，在关闭写入句柄、完成 strip 等最终修改之后、执行之前进行。可以先复用官方 Native 签名器，后续再将必要算法直接集成到 Zig，避免依赖 Java。
3. 由工具链适配仓库维护编译器改动，OCP/ocp-repo 维护构建集成、配方和发布版本。保持用户默认 `zig init`、`zig build test`、`zig build run` 的用法。
4. 签名使能后应按不可再原地修改的文件处理，后续重编译使用新文件或原子替换；签名后继续 strip、覆盖写入或重复签署可能破坏签名或触发完整性限制。

系统扩展程序管控仍按设备现有能力与用户设置执行。`CUSTOM_SANDBOX`、`ALLOW_EXTERNAL_NATIVE_CODE` 和签名各自承担不同职责，不能相互替代；实际必要权限应以目标设备审批和运行结果确认。

### 默认自动签名的接入设计（待实现）

自动化应由 Zig OHOS 工具链负责：将 ad-hoc 签名作为目标 ELF 的产出步骤，OCP 负责分发这份适配版工具链。用户仍执行普通的 `zig init`、`zig build`、`zig test`、`zig run` 和 `zig cc`，无需先运行失败再找缓存文件补签。当前版本尚无已接通该流程的 OCP 配置开关。

先将官方 `binary-sign-tool` 的 Native 自签名实现移植为设备端可运行的签名器，随 Zig 一起安装；签名器自身及其依赖也必须通过正常工具包安装链路提供。Zig 应从固定的工具链相对位置加载签名实现，不依赖用户 PATH 中的同名程序。可以先调用 Native 签名程序，后续将同一算法集成进编译器；设备运行时不需要 Java、开发者私钥或在线签名服务。

逻辑顺序为：

```text
链接并完成 strip 等最终写入
  → 关闭写入句柄和可写映射，保留缓存排他保护
  → 生成 ad-hoc 签名产物并原子替换
  → 提交成功的缓存记录
  → 执行 Maker / 构建配置程序 / 用户程序
```

具体接入点需要覆盖 `Compilation.zig` 的公共产出流程。已读取的 0.17.0 源码中，`Compilation.update()` 在第 3037 行附近区分 `.none/.incremental` 与 `.whole`；whole-cache 分支在第 3118 行附近调用 `flush()`，随后关闭输出文件并调用 `man.finalize()`。签名必须在成功缓存记录对其他进程可见之前完成；签名失败不能提交成功记录。该分支在最终 flush 之前已经移动产物目录，因此不能简单将“签名在前”理解为必须在现有目录 rename 之前签名。

缓存命中在第 2839–2847 行附近直接返回，不能指望增加一次 flush 后处理就自动修复旧缓存。签名策略及格式版本应参与缓存区分；旧的未签名结果应重新生成，避免并发改写已共享的缓存文件。增量编译也必须适配：签名使能后的文件按不可变产物处理，后续修改通过新文件替换完成。

默认签名范围以 OHOS ABI（`ohos/ohoseabi`）的最终可执行 ELF 为起点，覆盖静态程序和动态链接程序；不对 `.o`、`.a` 逐个签名。共享库的签名和加载另行验证。仅在 `jitCmdInner()` 中执行 Maker 前补签可以作为第一阶段验证，但不能代替公共产出流程的接入；仅在 `makeBinFileExecutable()` 或 `zig run/test` 前签名也不能覆盖用户先编译、再通过 `./程序` 执行的场景。

工具链改动在 zig-patch 维护并发布新版本；ocp-repo 的 Zig 配方更新下载地址、校验值和版本，OCP 再组装包含适配版 Zig 的安装包。不能只改当前下载原始编译器的组装脚本，就声称默认自动签名已实现。

### hapsigner-rs 候选实现核对

2026-10-15 核对 [hapsigner-rs 的 fcec937](https://github.com/harmony-contrib/hapsigner-rs/tree/fcec93743146f72fadc05f253bbc6251ffc6bc26)：目前支持 HAP/HSP 和 `sign-app --in-form elf` 的证书签名，但未实现官方 `binary-sign-tool sign -selfSign 1` 对应的 ad-hoc 模式。本次结论来自源码与测试代码检查，未进行该库产物的真机执行验收。

- [CLI](https://github.com/harmony-contrib/hapsigner-rs/blob/fcec93743146f72fadc05f253bbc6251ffc6bc26/src/main.rs#L61) 的 ELF 签名仍需要 keystore、certificate 和 key alias，没有 `selfSign` 入口。
- [ElfCodeSignBuilder](https://github.com/harmony-contrib/hapsigner-rs/blob/fcec93743146f72fadc05f253bbc6251ffc6bc26/src/code_sign.rs#L67) 使用 CMS 签名，descriptor flags 为存储 Merkle tree offset 的 `0x1`，没有 ad-hoc 的 `0x10` 分支。`SigningMaterial::without_profile()` 仍要求签名密钥，不能视为无私钥的 selfSign。
- [ElfSigner](https://github.com/harmony-contrib/hapsigner-rs/blob/fcec93743146f72fadc05f253bbc6251ffc6bc26/src/application.rs#L141) 实现的是 `hap-sign-tool sign-app` 的尾部 `elf sign block` 格式；需要另补 `binary-sign-tool` 的 `.codesign` section、对应 descriptor/digest 和自签名标志等格式支持，不能只添加一个 CLI 参数。

该库可作为 Rust 实现的基础。接入 Zig 前，应先增加无需 SigningMaterial 的 ad-hoc 库接口和 CLI、与官方 selfSign 工具的格式及摘要对照验证，再对真实 Maker 重复真机签名执行测试。

## 真机验收

### 手工自签名：用户反馈通过

2026-10-15，用户确认在真机按前述缓存文件自签名方法操作后，最后的 `zig init` 可以执行成功。该结果是用户反馈，未通过本地 HDC 连接该设备复测，也未采集完整日志、文件摘要、实际执行域或签名前后的文件标签。

Maker 的缓存路径规则为：

```text
$ZIG_GLOBAL_CACHE_DIR/o/<编译缓存哈希>/maker
```

可在终端的应用私有项目目录中，通过 `export ZIG_GLOBAL_CACHE_DIR="$PWD/.zig-global-cache"` 固定缓存根目录；首次默认 `zig init` 生成 Maker 后，以报错中的具体路径为签名对象。将签名结果放回同一缓存路径、赋予执行位，并在相同缓存配置下重试。缓存哈希不能写死，当前 OCP 也尚未内置设备端签名命令。

本次通过说明手工签署缓存 Maker 可解决该设备上这一步的执行问题，不代表已自动覆盖构建配置程序、测试程序和用户生成的全部 ELF，也不代表任意目录均可执行。未修改镜像的模拟器失败与本次真机成功分别保留。

### 自动签名接入后的完整验收

在目标终端的真实 PTY 中记录宿主构建模式、获授能力、`tty` 和实际执行域，使用新项目与空缓存：

1. 默认命令现场生成 Maker，记录签名前的拒绝结果。
2. 签署同一份文件，记录摘要、执行位、标签，以及执行后是否发生系统标签转换。
3. 在相同 PTY 中直接执行该文件，并运行默认 `zig init`。签名后检查文件 hash，避免把重新生成的未签名文件误记为签名测试。
4. 工具链自动签名接入后，另建空缓存，完整验证 `zig init`、`zig build test`、`zig build run` 和修改源码后再次构建运行。

API26 原版模拟器已验证权限加 SDK 自签名仍失败；它没有进入开发工具域，也未完成真机二进制安全后端的运行验证。因此该失败不能否定用户反馈已通过的真机 ad-hoc 路径。当前真机验收已推进到手工签署缓存 Maker 后 `zig init` 成功，自动签名和其余开发命令仍待实现及验收。
