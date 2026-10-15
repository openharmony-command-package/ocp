# DevEco 模拟器验证

本目录包含独立 PTY 验证应用、只读静态仓库、第三方 tap 示例与 Arkit UI 自动化。验证资源不会进入 CLI HNP。默认流程使用设备 BMS；目标是 DevEco ARM64 2in1 模拟器，不使用独立 QEMU。

工具与验证宿主的调试 profile 使用 `AllowAppDesktopIconHide`，安装后不添加桌面图标。OCP 管理 UI 保留唯一的正常桌面入口。每次重签名会改变 HAP hash；应生成新的本地测试仓库目录，不覆盖第三方已发布的同版本文件。

## 构建与签名

先设置目标模拟器的 UDID。它与 HDC target `127.0.0.1:10090` 是不同标识。SDK 公共调试密钥只用于该模拟器。

```sh
OCP_EMULATOR_UDID='替换为模拟器UDID'
OCP_FORMULAS='/path/to/ocp-repo'
python3 scripts/ocp.py bottle zig --config "$OCP_FORMULAS/installer/zig/component.json" --version 0.16.0 --debug-udid "$OCP_EMULATOR_UDID"
python3 scripts/ocp.py bottle zig --config "$OCP_FORMULAS/installer/zig/component.json" --version 0.17.0 --debug-udid "$OCP_EMULATOR_UDID"
python3 scripts/ocp.py bottle hello --tap community --version 0.1.0 \
  --config example/tap/installer/hello/component.json --debug-udid "$OCP_EMULATOR_UDID"
python3 ui/build.py build --debug-udid "$OCP_EMULATOR_UDID"
python3 example/build.py install --target 127.0.0.1:10090 --debug-udid "$OCP_EMULATOR_UDID"
hdc -s 127.0.0.1:8710 -t 127.0.0.1:10090 install -r dist/arm64-v8a/ocp-manager-debug.hap
```

旧 unsigned 管理应用迁移到新签名时，系统可能要求先卸载旧应用。先备份其私有注册与设置，避免丢失个人来源。两个宿主均声明 BM、外部 Native Code 和网络权限，使用普通应用 profile；权限适用范围见 [设备后端文档](../docs/device-backend.md)。

## 静态下载服务

```sh
python3 scripts/ocp.py publish --tap core --base-url http://127.0.0.1:18090/core \
  --output example/build/native-repository/core
python3 scripts/ocp.py publish --tap community --base-url http://127.0.0.1:18090/taps/community \
  --output example/build/native-repository/taps/community
python3 example/static_repository.py --directory example/build/native-repository
```

服务只返回文件，没有安装、卸载、状态查询或 HDC 调用。HTTP/1.1、Content-Length 与正确的 ZIP Content-Type 用于可靠传输大 Bottle。loopback 测试通过 HDC reverse 转发访问；换成设备可直接访问的 HTTPS 静态地址后，下载也无需电脑连接。

## CLI 与 UI 全流程

```sh
python3 ui/build.py configure --target 127.0.0.1:10090 \
  --repository http://127.0.0.1:18090/core/index.tar.gz
python3 example/native_lifecycle.py --target 127.0.0.1:10090
python3 example/ui_verify.py --target 127.0.0.1:10090
python3 example/native_payload_test.py
```

CLI 测试在真实应用 forkpty 中执行安装 0.16.0、升级 0.17.0、卸载、断网模式下从缓存重装、跨宿主状态同步、第三方工具安装与命令执行，另外检查索引原子更新和非工具 bundle 卸载保护。测试结束恢复 Zig 0.17.0，并卸载测试用 community/hello，供 UI 流程重新安装。

UI 自动化使用设备 uitest 操作实际 Arkit shadcn 控件，覆盖卸载取消、卸载、安装、更新、仓库注册、第三方命令、关于页七次点击进入 Debug 和编译测试。设备工具操作通过 BMS 完成，测试脚本仅用 HDC 准备与观察。输入步骤验证输入框内容，处理模拟器输入法的 ASCII 模式，并恢复临时设置。

报告分别保存到 `dist/arm64-v8a/native-lifecycle.json`、`ui-verification.json` 和 example/build 对应运行目录；UI 截图在 `example/build/ui/<run>/`。原生 payload 校验测试覆盖身份、版本、UI、权限、ABI、保留命令、路径穿越、重复 ZIP/JSON 字段与截断数据。

## 编译与执行限制

```sh
python3 example/build.py verify --target 127.0.0.1:10090
```

C、Zig 与 C++ 在 OCP/example 的普通应用 PTY 编译。两个受限权限已授予，但该执行域仍拒绝直接执行应用数据目录中新生成的 ELF；测试原样取出产物，在同一模拟器的 HDC 调试目录执行。该验证与设备 BMS 安装验证分开记录，结果位于 `dist/arm64-v8a/verification.json`。

## OHOSTTY 弱沙箱开发验证

这套模拟器处理流程已沉淀为 [harmonyos-emulator-native-exec Skill](../skills/harmonyos-emulator-native-exec/SKILL.md)，可复用其中的独立脚本、离线操作手册和验收标准。

隔离副本 `OCP Zig Switch Lab` 使用 HDC `127.0.0.1:10091`。它补齐当前 SDK 缺失的权限启动转换，并安装具有 `CUSTOM_SANDBOX` 的 debug OHOSTTY；实际 PTY 域为 `develop_tools_debug_hap`。默认 `zig init`、`zig build test`、`zig build run` 均已在应用 PTY 通过。原模拟器、SDK 基础镜像和 SELinux 策略保持原样。适用条件及真机组件对比见 [设备后端文档](../docs/device-backend.md#模拟器弱沙箱启动链路)。

已准备的本地副本使用以下入口启动，避免 SDK 默认启动器重建系统分区覆盖文件：

```sh
python3 example/emulator_lab.py status
python3 example/emulator_lab.py start
python3 example/emulator_lab.py stop
```

入口只管理已有的隔离副本，不自动创建镜像。停止请求返回后，需等待模拟器进程完全退出，再进行离线磁盘编辑。`emulator_overlay_runtime.py` 和 `emulator_custom_sandbox_flag.py` 只接受已审计版本的 SHA-256；SDK 升级后需要重新分析。

`custom_policy_shell.c` 可在上述执行域额外加载从真机提取的 `app_custom` 过滤规则。编译后将它和 `zig_default_workflow.sh` 放入调试宿主自己的可写目录，在应用 PTY 执行：

```sh
chmod 700 ./custom-policy-shell
./custom-policy-shell /system/bin/sh -i
/system/bin/sh ./zig_default_workflow.sh new-project
```

脚本要求项目目录尚不存在，并使用该项目内的全新 Zig 缓存；默认命令现场编译 Maker 和项目，不使用预编译替代。`workflow.log` 记录 PTY、过滤状态和各步骤退出码。真机厂商组件只保留在本地分析目录，不纳入源码仓库或工具包；完整系统开关与正式应用签名执行仍有待验证。
