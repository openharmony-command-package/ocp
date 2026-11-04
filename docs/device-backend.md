# 设备端安装后端与权限

OCP 0.5.0 默认在设备调用 BMS。CLI 和 Arkit UI 使用同一条安装路径，工具 HNP 保持无 UI。电脑上的服务只需托管静态索引和 Bottle；安装、更新与卸载不经过 HDC 安装服务。

## 权限和适用范围

宿主声明 `ohos.permission.ALLOW_USE_BM`、`ohos.permission.ALLOW_EXTERNAL_NATIVE_CODE` 和网络权限。BM 权限负责系统包管理授权，外部 Native Code 权限负责对应的原生代码能力；二者不互相替代。权限属于宿主应用，PTY 中启动的 OCP 和原生适配器继承该宿主身份。仅安装 OCP HNP 不能让其他终端应用自动获得权限。

当前完整验证对象是 DevEco 的 ARM64 2in1 模拟器，HarmonyOS 7.0.0.107 / API 26。普通应用 `com.richerfu.ocp` 和 `com.richerfu.ocp.example` 使用 `hos_normal_app`、APL `normal` 的本地 SDK debug profile，ACL 包含上述两个受限权限。设备返回两个权限均已授权；应用的 `isSystemApp` 为 false。没有修改系统权限检查或 SELinux 策略。

本地 debug profile 的结果不代表正式发布证书已获批。发行时需要通过平台申请相应权限和签名材料；适用设备、APL 和签名条件以审批结果为准。权限说明见 [OpenHarmony 受限开放权限](https://github.com/openharmony/docs/blob/master/zh-cn/application-dev/security/AccessToken/restricted-permissions.md)。

`ALLOW_USE_BM` 的普通应用授权分支要求设备处于开发者模式，操作前台用户，并且安装对象具有 debug provision 类型。工具包也需要有效签名和适配当前设备的 debug profile。它不是任意 release HAP 的通用安装授权。当前自动签名脚本只使用 SDK 公开测试密钥，生成绑定指定模拟器 UDID、有效期 30 天的调试产物，不能作为商用发行签名。

## 安装过程

1. CLI 从注册的静态仓库选择版本，下载 Bottle，校验 HAP SHA-256。
2. `ocp-bm` 读取 ZIP 元数据，核对实际 bundle/version、单一 public HNP、无 Ability/扩展/权限、命令列表和 ELF ABI；拒绝路径穿越、重复条目和重复 JSON 字段。
3. 使用调用方自己的 access token 获取 BMS installer。宿主没有 BM 授权时立即失败。
4. 创建 BMS stream installer，把本地 HAP 写入系统返回的文件描述符。这样不需要把应用沙箱路径解释成系统路径，也不需要让应用直接写入安装目录。
5. BMS 执行系统权限、签名、版本和 HNP 安装检查。只有成功回调后，OCP 才提交安装收据；卸载失败保留原收据。

更新使用同一 bundle 的更高 versionCode；系统拒绝降级时原版本继续保留。卸载仅允许 `com.richerfu.ocp.pkg.*` 工具 bundle。命令冲突同时检查本地收据和系统 HNP 命令链接，避免其他已安装工具占用同名命令。

`ocp sync` 根据已注册活动索引，核对 `/data/service/hnp/bin` 中真实可执行链接是否落在预期 HNP/版本目录，重建该宿主的工具收据。它不枚举所有系统应用，也不声称重新测得已安装 HAP 的 SHA；收据中的 hash 来自匹配的不可变目录项。未注册或未在索引中保留的版本不参与同步，因此仓库应保留历史版本。

`OCP_OFFLINE=1 ocp install TAP/TOOL` 只使用本地缓存的已下载 HAP，仍重新检查 SHA 和实际包元数据。首次安装和 `ocp update` 需要访问仓库。

## 原生适配器的兼容性

系统 `/system/bin/bm` 在当前普通应用域中不能执行。适配器因此使用官方 IPC parcel、proxy、stub 和线程接口，并通过少量平台 ABI 获取 IPC context 和构造 MessageOption。BMS 使用事务码 0 创建文件流，而公开 IPC C wrapper 的用户事务码从 1 开始，所以此处使用真实平台 proxy 的虚方法。

这是经过当前镜像验证的平台适配层，不是稳定的公开 BMS NDK API。平台头文件按提交锁定在 `installer/ocp/prepare-native.py`，InstallParam 使用当前 API 26 镜像已验证的布局。运行时缺少符号立即报错；升级系统镜像必须重新验证，不能静默回退到特权身份或关闭校验。

## 原生代码执行

真机的宿主授权、ad-hoc 签名、系统验证及执行域转换已按源码和所提供 MateBook 固件整理为 [真机本地编译与执行方案](native-execution.md)。该方案与下面的模拟器 debug 验证分别记录；普通应用不能直接使用系统 `SignLocalCode` 服务。

2026-10-15，用户确认此前讨论的 API24 真机在对现场生成的缓存 Maker 手工自签名后，重试 `zig init` 可以成功。该结果来自用户反馈，尚未采集该设备的完整执行日志；Zig 工具链尚未接入自动签名，空缓存下无需手工干预的 `init/build/test/run` 流程仍需完成适配和验收。

已安装工具的 PTY 执行与实时编译 ELF 的执行条件不同。OCP/example 的普通应用域验证在 PTY 编译 C、Zig 和 C++，再通过模拟器 HDC 调试目录运行产物。下述 OHOSTTY 隔离开发实例则已验证在应用 PTY 原地编译并运行；两组结果适用的宿主和执行域不同。

Zig 0.17.0 的 `init` 等命令还会现场编译并执行缓存中的 Maker，见 [Zig 官方构建系统说明](https://ziglang.org/devlog/2026/#all-package-management-functionality-moved-from-compiler-to-build-system)。因此，`zig version` 或 `zig cc` 编译成功不能证明 `zig init`、完整 `zig build` 已可用。

2026-10-14 在上述模拟器的 OHOSTTY 0.1.0（`com.richerfu.ohostty`）真实 PTY 中，`zig init` 已生成 ARM64 静态 Maker，但执行 `.cache/zig/o/<hash>/maker` 返回 `AccessDenied`。文件权限为 `777`，重新 `chmod +x` 后仍失败。安装信息显示 OHOSTTY 的 `CUSTOM_SANDBOX` 已授予，PTY shell 的执行上下文仍为 `u:r:normal_hap:s0`，缓存文件标记为 `debug_hap_data_file`。模拟器内核日志确认该次调用被 SELinux 拒绝：`comm="zig"`，权限 `execute_no_trans`，`permissive=0`。对同一现场 Maker 的副本进行 `binary-sign-tool sign -selfSign 1`，并在同类应用目录执行该副本，仍被拒绝。因此，当前运行域的执行策略是已确认的阻碍；增加执行位或自签名不能单独解决它。

### 模拟器弱沙箱启动链路

可复用的诊断、镜像处理、PTY 验收和回滚流程已整理为 [harmonyos-emulator-native-exec Skill](../skills/harmonyos-emulator-native-exec/SKILL.md)。该技能附带独立辅助脚本，并按需加载操作手册和已验证基线。

隔离验证实例为 `OCP Zig Switch Lab`（HDC `127.0.0.1:10091`）。原来的 `Arkit PTY Side`（`127.0.0.1:10090`）和 SDK 基础镜像保持原样。

这里存在三个独立问题：

1. SDK 的 `persist.sys.abilityms.start_options_with_animation` 默认关闭。AppMgr 在检查 `CUSTOM_SANDBOX` 前先检查该产品配置；关闭时不会传入弱沙箱启动标志。
2. SDK 的 AppSpawn 库没有编入 `CUSTOM_SANDBOX` 条件分支。即使 AppMgr 已检查权限并传入 `APP_FLAGS_CUSTOM_SANDBOX`，该库也没有转换为 `SELINUX_HAP_CUSTOM_SANDBOX`，进程仍落入 `normal_hap`。
3. 已安装的终端 HAP 是 release 构建。开发构建和正式构建使用不同的执行域及数据文件执行规则；debug profile 不等于 HAP 的 `app.debug=true`。

第一个条件见 [AppMgr 启动标志实现](https://github.com/openharmony/ability_ability_runtime/blob/a0047a48162ef9b18dd403c14925058d506c3d0f/services/appmgr/src/app_mgr_service_inner.cpp)，第二个条件见 [AppSpawn 的宏内转换分支](https://github.com/openharmony/startup_appspawn/blob/751538e417925348ef212077030f464355da71a4/modules/common/appspawn_adapter.cpp)。这些判断同时与当前 SDK 库的反汇编核对，未仅依据开源主分支推测。

验证副本预置第一个参数，补齐第二个条件分支，并安装有有效调试签名、`app.debug=true` 和已授予 `CUSTOM_SANDBOX` 的 OHOSTTY。应用仍为 APL `normal`、非系统应用。PTY 的实际执行域变为 `u:r:develop_tools_debug_hap:s0`；全局 SELinux 保持 enforcing，原始 CIL 策略和 `sehap_contexts` 未改变，没有按包名直接指定执行域。未申请该权限的应用不会因这段条件转换自动获得弱沙箱标志。

在真实应用 PTY `/dev/pts/0` 中，默认 `zig init` 首次现场编译 Maker，随后成功生成项目；`zig build test` 和 `zig build run` 也均返回 `0`，生成的程序输出默认模板消息。验证没有替换预编译 Maker、修改 Zig 配方或重编译终端的 Rust 实现。截图及原始 PTY 日志位于 `build/zig-init-investigation/default-workflow-complete.png` 和 `default-workflow-pty.log`。

兼容分支的生成脚本为 [emulator_custom_sandbox_flag.py](../example/emulator_custom_sandbox_flag.py)，只接受已核对 SHA-256 的那一份 SDK 库。SDK 启动器会重建实例的系统分区覆盖文件，因此副本还使用 [emulator_overlay_runtime.py](../example/emulator_overlay_runtime.py) 生成的启动器保留覆盖文件。原始启动器及基础镜像签名校验保持原样。此结果适用于当前验证副本的开发构建，完整真机行为仍需核对；没有完成正式构建的运行时签名与二进制安全服务验证。

### 系统扩展程序开关

开关的展示与实际后端是两件事。设置应用在 `const.product.model == "emulator"` 时隐藏 `privacy_settings`；页面内开关还受 `const.appsecurityprivacy.binarysecurity.control_ext_binary` 控制。隔离副本通过早期参数展示了原来的系统开关，状态读取返回预置的 `persist.binary_security_service.binary_source=1`。

用户完成管理员验证后，设置应用报 `Cannot read property BinarySourceScope of undefined` 并回滚。错误发生在访问 `@hms:security.binarySecurityManager` 的枚举时，尚未调用 `setBinarySourceScope()`；对应 Native 模块不在当前镜像的 HMS security 模块目录中。因此，显示开关、修改持久化状态或增加执行位，都不能补上这个后端。上述开发构建的成功验证不等于系统开关已经修复，也不证明正式构建可以直接执行未签名 ELF。

IDE 弱沙箱方案可以申请 `ohos.permission.CUSTOM_SANDBOX`，还需要有效签名 profile、实际授权和支持该能力的产品配置；OCP 管理应用和 example 目前没有请求该权限，也没有完成授权后原地执行验证。官方条件见 [IDE 插件二进制的权限与签名要求](https://developer.huawei.com/consumer/cn/doc/doccenter-dev-faq/faqs-access-control-23)。

### 真机镜像对比与移植边界

从用户提供的 MateBook 更新地址按组件提取 `/system`，校验其 SHA-256 为 `8a4ec0bfd42ece76087e90d2a2cd43d5870b08d2712f525766bc3097b1d8ba38`。分析组件留在本地 `build/zig-init-investigation/matebook-components/`，不随 OCP 分发。确认的差异包括弱沙箱启动转换、`libseccomp`/过滤策略，以及二进制安全管理 Native 模块和配套服务。

真机和 SDK 的 `sehap_contexts` 内容完全一致，允许 `develop_tools_debug_hap` 执行 `debug_hap_data_file` 的 CIL 规则也一致。这支持补齐启动条件后进入既有开发执行域；无需增加 ELF 执行的 SELinux 放行规则。但这不代表两个系统的全部安全行为完全一致。

直接把真机 AppSpawn 库、seccomp 库和过滤策略一起放入副本，会使 SDK 的系统应用触发 seccomp 审计（ARM64 syscall 425，即 `io_uring_setup`），并出现 SceneBoard 重启循环。已恢复 SDK 启动库的兼容分支，未将整套真机启动组件替换保留为解决方案。

[custom_policy_shell.c](../example/custom_policy_shell.c) 用于单独验证真机的 `app_custom` 规则：仅接受已经处于 `develop_tools_debug_hap` 的进程，通过原始真机 `libseccomp` 加载原始过滤策略，并检查 `NoNewPrivs=1`、`Seccomp=2`。它只给当前测试 shell 和后代增加限制，不给应用授予权限，也不改变 SDK 系统应用的过滤规则。该入口是开发验证资源，未集成到正式终端启动链路。

2026-10-15 在该过滤规则生效的 OHOSTTY PTY 中，使用新项目目录和空的项目内全局缓存，再次运行默认 `zig init`、`zig build test`、`zig build run`，退出码全部为 `0`。因此，此次测试未发现真机 `app_custom` 过滤规则对该默认开发流程的额外阻碍。验证脚本为 [zig_default_workflow.sh](../example/zig_default_workflow.sh)。最终报告、日志和截图分别位于 `build/zig-init-investigation/development-workflow-report.json`、`factory-policy-final-workflow.log` 和 `factory-policy-workflow-complete.png`。

完整二进制安全服务的移植、系统开关写入及 release 宿主执行仍未验证。当前已验证范围是具有弱沙箱权限的 debug IDE 在对应开发执行域中进行编译与执行；不能据此承诺正式宿主的签名执行行为。

## 实现和验证入口

- `installer/ocp/native/ocp_bm.cpp`：BM IPC、回调、流安装、卸载与命令状态。
- `installer/ocp/native/payload.h`：设备端包身份校验。
- `scripts/sign_debug.py`：模拟器调试 profile 与代码签名。
- `example/static_repository.py`：没有安装端点的静态服务。
- `example/native_lifecycle.py`：真实应用 PTY 中的安装、更新、卸载、离线重装、跨宿主同步和第三方工具验证。
- `example/native_payload_test.py`：归档、命名空间、UI、ABI 和保留命令拒绝测试。

安装后端统一使用设备 BMS。关于页连续点击版本号七次进入 Debug，可执行环境、命令和编译诊断。
