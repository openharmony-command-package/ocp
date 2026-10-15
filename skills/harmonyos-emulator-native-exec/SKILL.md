---
name: harmonyos-emulator-native-exec
description: 排查和适配 DevEco HarmonyOS 模拟器中的本地编译执行问题，包括已授予 CUSTOM_SANDBOX 但 PTY 仍无法执行新生成 ELF、zig init AccessDenied、系统扩展程序开关缺失或回滚。使用隔离镜像副本修复已确认的启动链路差异，并在应用真实 PTY 验证。普通 OCP 包安装、通用构建失败和真机权限申请不属于本技能的主要范围。
---

# HarmonyOS 模拟器本地编译与执行

让终端或 IDE 在 DevEco 模拟器的应用 PTY 内现场编译并执行程序。成功标准是默认开发命令真正完成，而非编译完成、权限显示已授予或 HDC shell 能执行。

## 选择工作路径

- 诊断执行失败：先收集实际目标、HAP 构建属性、权限、PTY 执行域及拒绝日志，再读 [已验证基线](references/verified-baseline.md)。不要先修改镜像。
- 使用已经准备的副本：读 [操作手册](references/emulator-workflow.md) 的“现有副本”，核对 manifest 和运行状态后复用。不要重新执行离线修复。
- 制作或修复副本：读操作手册的“离线处理”，先按实际 SDK 哈希判断现有脚本是否适用。
- 用户只要求分析、整理资料或制作 Skill：完成相应产物；不因此重启模拟器或重做镜像。

## 先确认失败发生在哪一层

1. 固定显式 HDC target。区分原实例、验证副本和同时连接的真机；后续设备命令始终使用该 target。
2. 查询宿主的 `app.debug`、`isSystemApp`、APL、`CUSTOM_SANDBOX` 申请和授权状态。debug 签名 profile 不等于 debug HAP。
3. 在**该应用 PTY**读取 `tty`、`/proc/self/attr/current` 和工作目录，执行原本失败的命令。HDC 只用于观察、传输测试资源或通过 UI 输入。
4. 对照拒绝来源：SELinux `execute_no_trans`、DAC/目录权限、挂载限制、加载器、seccomp、签名服务分别处理。不要从一个 `Permission denied` 推断出全部原因。
5. 当前已审计 SDK 的特征是：权限已授予但启动域仍为 `normal_hap`；AppMgr 产品配置关闭，且 AppSpawn 缺少条件标志转换。它不是所有 HarmonyOS 镜像的通用结论。

## 镜像与权限边界

- 在用户授权的本地验证范围内操作独立实例和其 QCOW2 覆盖文件。保留可恢复的原实例、SDK 基础镜像和备份。
- 所有离线写入必须等待目标模拟器进程退出并释放镜像。停止命令返回不代表磁盘已经关闭。
- `qemu-img` 是这里的离线磁盘工具；运行验证仍使用 DevEco 模拟器，不启动独立 QEMU 来代替用户环境。
- 保留 AppMgr 的权限检查、原 SELinux CIL/`sehap_contexts` 和 enforcing 状态。若用户另行选择策略放宽实验，将其单独记录，不能据此声称与真机行为一致。
- 已验证补丁只恢复权限标志的条件转换，不按包名强制执行域、不重写 Zig 逻辑、不替换预编译 Maker。
- `scripts/emulator_custom_sandbox_flag.py` 和 `scripts/emulator_overlay_runtime.py` 有精确 SHA-256 门控。版本不匹配时停止该补丁路径，继续只读分析；不要猜偏移或移除门控。
- 当前 SDK 对整套真机 AppSpawn/seccomp 的移植曾发生系统应用重启循环。相同失败不重复尝试；停止并恢复修改前覆盖文件。需要扩展移植时先提出新的兼容性证据和恢复方案。

## 执行与验收

复用现有副本时，先从项目目录发现 `manifest.json`，不要假定技能安装目录就是项目目录：

```sh
python3 <skill-dir>/scripts/emulator_lab.py status --lab-root <lab-root>
python3 <skill-dir>/scripts/emulator_lab.py start --lab-root <lab-root>
```

此启动助手仅适用于已准备的 OCP 基线副本；没有创建磁盘、申请权限或修复开关的功能。其他实例配置按操作手册核对实际启动参数。

在 debug 宿主已获授权并实际进入 `develop_tools_debug_hap` 后，把 `scripts/zig_default_workflow.sh` 放入该宿主自己的可写目录，由应用 PTY 启动：

```sh
/system/bin/sh ./zig_default_workflow.sh new-project
```

脚本要求目录尚不存在，使用项目内空缓存，并直接执行默认 `zig init`、`zig build test`、`zig build run`。不要删除用户原有项目或缓存来强行满足前置条件。

验收记录至少包含：

- 明确的实例/target、SDK 版本、宿主 bundle、实际构建模式和权限状态。
- 实际 PTY 名称、执行域、工作目录及 enforcing 状态。
- 新项目、全新缓存下三个命令的退出码和生成程序输出。
- 原始 PTY 日志和 UI 截图；读取日志时保留原文件，SELinux 上下文中的 NUL 只在可读副本中去除。
- 改动账本、保留的诊断项、恢复点及本次尚未验证的范围。

如需要核对真机 `app_custom` 规则，再按操作手册编译 `scripts/custom_policy_shell.c` 并使用已提取、校验过的真机过滤库。它只给当前 shell 增加限制，不能替代权限或整个二进制安全后端。

## 区分结论

系统开关可见、参数值为 `1`、管理员认证通过、Native setter 成功、应用进入开发域、debug ELF 可执行、release 签名 ELF 可执行，分别记录。

已知 SDK 的开关在访问缺失的 `@hms:security.binarySecurityManager` 模块时回滚，发生在 setter IPC 之前。debug Zig 全流程通过不能写成“系统开关已修好”或“完整真机行为已复现”。

报告先回答用户关心的命令是否可用，再给出适用实例、必要改动、验证证据和实际限制。把已验证事实与待验证候选方案分开。
