# 已验证基线与诊断证据

本文件保存 2026-10-14 至 2026-10-15 的实验结论。它是后续诊断的参照，不是对所有版本的能力承诺。

## 环境

| 项目 | 已验证值 |
| --- | --- |
| 电脑 | macOS / ARM64 |
| DevEco Studio | 26.0.0.821 |
| 模拟器 | ARM64 2in1，HarmonyOS 7.0.0.107 / API 26 |
| 原实例 | Arkit PTY Side，`127.0.0.1:10090` |
| 验证副本 | OCP Zig Switch Lab，`127.0.0.1:10091` |
| 宿主 | OHOSTTY 0.1.0，`com.richerfu.ohostty` |
| 成功构建 | `app.debug=true`，APL `normal`，非系统应用 |
| 权限 | 宿主申请且实际获授 `ohos.permission.CUSTOM_SANDBOX` |
| Zig | 0.17.0，OCP 安装的 HNP |
| 实际运行通道 | OHOSTTY 交互 PTY `/dev/pts/0` |
| 最终执行域 | `u:r:develop_tools_debug_hap:s0` |
| SELinux | enforcing，CIL 和 `sehap_contexts` 未修改 |

端口、实例名、用户号和本地目录是本次环境信息。换环境先发现实际值，不盲目照抄。启动助手为了避免误操作，只支持本表中的副本布局。

## 原始失败

宿主虽然已授予 CUSTOM_SANDBOX，但安装的是 release HAP。PTY 仍在 `u:r:normal_hap:s0`。

默认 `zig init` 已现场生成 Maker：ARM64 静态 ELF，约 3.78 MB，mode `0777`，文件标签 `debug_hap_data_file`。执行时返回 `AccessDenied`，日志明确出现：

```text
comm="zig"
scontext=u:r:normal_hap:s0
tcontext=u:object_r:debug_hap_data_file:s0
execute_no_trans
permissive=0
```

`chmod +x` 没有改变结果。把同一 Maker 的副本用 `binary-sign-tool sign -selfSign 1` 自签名，签名验证通过，但在原应用域执行仍失败。这证明该次 SELinux 拒绝没有被执行位或签名消除；不能推广为“自签名在所有场景无效”。

## 启动链路中的三个条件

1. AppMgr 的 `SetStartMsgCustomSandboxFlag` 受 `persist.sys.abilityms.start_options_with_animation` 门控，已审计 SDK 默认关闭。
2. AppMgr 验证 CUSTOM_SANDBOX 后可传入消息标志 bit 31；已审计 SDK 的 AppSpawn 库缺少把该标志转换为 `SELINUX_HAP_CUSTOM_SANDBOX` 掩码 `0x10`（十进制 16，位索引 4）的条件分支。
3. 只有真正的 debug HAP 才进入本次验证使用的开发执行域。调试 profile、`aa start -D` 和 release HAP 的组合不能替代 debug 构建。

对照来源：

- [AppMgr 固定提交](https://github.com/openharmony/ability_ability_runtime/blob/a0047a48162ef9b18dd403c14925058d506c3d0f/services/appmgr/src/app_mgr_service_inner.cpp)：搜索 `SetStartMsgCustomSandboxFlag`。
- 同提交的 `services/common/src/app_utils.cpp`：产品参数默认 false，结果缓存；修改参数后需冷启动。
- [AppSpawn 固定提交](https://github.com/openharmony/startup_appspawn/blob/751538e417925348ef212077030f464355da71a4/modules/common/appspawn_adapter.cpp)：搜索 `CUSTOM_SANDBOX`、`SetHapDomainInfo` 和 `app_custom`。

结论已和当前 SDK 的实际反汇编核对，不是仅凭开源分支猜测。

## 修改账本

| 对象 | 成功基线中的状态 | 如何解释 |
| --- | --- | --- |
| 原 SDK `Emulator` | 未修改 | 另建副本保留实例覆盖文件 |
| SDK 基础 `system.img` 等 | 未修改 | 签名检查没有被打补丁 |
| 副本 system 覆盖文件 | AppSpawn 条件转换，88 字节补丁 | 恢复权限门控的启动转换，不按 bundle 强制选域 |
| 副本 userdata | 私有持久化文件设 `persist.sys.abilityms.start_options_with_animation=true` | AppMgr 的产品条件 |
| 持久化文件的公开副本 | 同步保留同值 | private key 的公开副本会被 init 忽略，不能只改公开文件 |
| 宿主 HAP | 有效签名的 debug 构建，CUSTOM_SANDBOX 已授权 | 普通应用身份，未改成系统应用 |
| CIL、`sehap_contexts` | 原样 | 使用原本存在的开发域执行规则 |
| system 早期参数 | `const.product.model=ocp-lab1`、开关显示参数 `1` | 系统开关展示诊断，与执行成功分别记录 |
| vendor / sys_prod 覆盖文件 | 曾保留 model 展示诊断修改 | 没有单独证明这些残留是开发执行的必要条件 |
| `persist.binary_security_service.binary_source=1` | 成功快照仍保留，getter 读回 `1` | 未单独消融；不证明 setter 或后端可用，也不能声称已证明它完全不影响执行 |
| 真机 seccomp 库和策略 | 保留在副本；手动仅对测试 PTY 加载 `app_custom` | 不对 SDK 系统应用全局激活 |
| 真机整套 AppSpawn | 试验失败后撤销 | 系统应用 seccomp 审计和 SceneBoard 重启循环 |
| Zig / Maker | 默认逻辑，现场编译 | 未替换预编译文件、未改配方 |

隔离副本复用了原实例 UUID，以兼容已有 profile 的设备绑定。两份实例仍使用不同目录和 HDC 端口；此做法不是所有环境都必须采用的要求。

## 精确版本门控

| 文件 | SHA-256 |
| --- | --- |
| SDK 主机 `tools/emulator/Emulator` | `d48732884d6b2e9b81caff88e88de5533f900a154ba8f0ae0ccd5b8c92d3fdfd` |
| SDK guest `libappspawn_common.z.so` | `d69ad3b508dac94941587e2bc1459ee95795d7dc83067424b221083b2fee63a3` |
| 条件转换补丁输出 | `838f558c61ae4623dfb6867cbfeb65f0e55dc5feaea464bf5d625ca0e71e47e8` |
| 真机 system 组件 | `8a4ec0bfd42ece76087e90d2a2cd43d5870b08d2712f525766bc3097b1d8ba38` |
| 真机 `libapp_custom_filter.z.so` | `8d502fd83a32f5990da120aeb6e7f110f1ca93b8c75226a96787afcf33ddd922` |

SDK guest 库大小为 148032 字节，完整路径为 `/system/lib64/appspawn/common/libappspawn_common.z.so`。不要误用 `/system/lib64/libappspawn_common.z.so`。

主机补丁在复制的 ARM64 Mach-O 中跳过 `DeleteQcow` 与 `create_qcow2` 的覆盖文件重建，仅供所有磁盘均已准备好的副本使用；签名校验函数保持原样。重新 ad-hoc 签名后的主机副本 hash 应以每次生成的 JSON 为准。

## 系统开关为何回滚

Settings 在 `const.product.model == "emulator"` 时隐藏隐私安全入口，页面内还检查 `const.appsecurityprivacy.binarysecurity.control_ext_binary`。仅写后一个参数不足以证明页面会显示。const 参数必须在早期加载，普通 HDC shell 的运行时写入并不能替代它。

原系统开关显示后，用户管理员认证成功，但设置应用报：

```text
Cannot read property BinarySourceScope of undefined
set state failed, roll back switch!
```

缺失的导入是 `@hms:security.binarySecurityManager`。错误发生在访问枚举、调用 setter IPC 之前。当前 SDK 的 HMS security 模块目录缺少对应 Native 模块。因此不得继续要求用户重复认证，也不要把参数 getter 读回 `1` 当作写入后端已经修复。

## 真机组件对比

镜像来源是用户提供的 [MateBook 更新清单](https://update.dbankcdn.com/download/data/pub_13/HWHOTA_hota_900_9/43/v3/7iUm9qRlQgm4LTz5ut812A/full/filelist.xml)。本次只提取并校验所需 system 组件，未保存整个 11.8 GB 更新 ZIP。

真机包含 SDK 缺失的二进制安全模块、配套服务、seccomp 库和过滤 DSO。真机与 SDK 的 `sehap_contexts` 字节一致；以下允许规则也一致：

```text
(allow develop_tools_debug_hap debug_hap_data_file (file (execute execute_no_trans map open read)))
```

这支持当前 debug 执行路径的规则对照，不证明整份策略、签名服务、内核或 TEE 行为等价。完整二进制安全服务尚未移植验证。

直接换成真机 AppSpawn 和全局过滤策略时，SDK 系统应用出现 syscall 425（ARM64 `io_uring_setup`）的 seccomp 审计，SceneBoard 连续退出并触发重启。恢复 SDK 启动库兼容分支后系统可用。此失败不是“所有真机组件都不能移植”的证据，而是这次整套启动组件替换不兼容。

提取 EROFS/ext4 内容时，先辨别符号链接。某些工具对 symlink 的 `dump` 输出为零字节，不能据此宣称原系统提供了空 stub。

## 最终验证结果

未额外加载过滤策略和手动加载原始 `app_custom` 的两组真实 PTY 验证，默认命令均成功。后者读回 `NoNewPrivs=1`、`Seccomp=2`、`Seccomp_filters=1`，使用新目录和项目内全新 Zig 全局缓存：

```text
PTY: /dev/pts/0
Domain: u:r:develop_tools_debug_hap:s0
ZIG_INIT_EXIT=0
ZIG_TEST_EXIT=0
All your codebase are belong to us.
ZIG_RUN_EXIT=0
```

无 CUSTOM_SANDBOX 请求的 OCP debug 应用仍在 `debug_hap`，未因补丁普遍进入弱沙箱域。

原项目的本地证据位于 `build/zig-init-investigation/`：

- `development-workflow-report.json`：完整范围和结果。
- `factory-policy-final-workflow.log`：最终原始日志。
- `factory-policy-workflow-complete.png`：真实应用窗口截图。
- `factory-transplant-failure.log`：整套真机 AppSpawn 移植失败证据。
- `emulator-switch-lab/manifest.json`：当前副本状态与改动账本。

这些大文件、镜像和厂商二进制不随 Skill 分发。即使本地证据目录被清理，后续也应按操作手册重新验收，而不是仅引用历史退出码。
