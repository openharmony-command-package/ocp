# DevEco 模拟器处理操作手册

本手册覆盖现有副本的日常启动、离线处理方法、真实 PTY 验证及回滚。精确版本、哈希和已确认差异见 [已验证基线](verified-baseline.md)。只加载当前任务需要的小节。

## 现有副本

先发现项目根和技能根。两者可能不同：技能可能已安装在 `~/.codex/skills`，而镜像放在项目 `build/`。

```sh
SKILL_DIR='<本技能目录绝对路径>'
PROJECT_ROOT='<项目绝对路径>'
LAB_ROOT="$PROJECT_ROOT/build/zig-init-investigation/emulator-switch-lab"

python3 "$SKILL_DIR/scripts/emulator_lab.py" status --lab-root "$LAB_ROOT"
python3 "$SKILL_DIR/scripts/emulator_lab.py" start --lab-root "$LAB_ROOT"
```

启动助手读取已有 manifest，验证复制启动器的哈希和磁盘布局，固定管理 `127.0.0.1:10091` 的本次基线副本。它不创建空白磁盘，不适用于另一版本或另一布局的实例。已经 online 时不重复启动。

停止：

```sh
python3 "$SKILL_DIR/scripts/emulator_lab.py" stop --lab-root "$LAB_ROOT"
```

停止后等待模拟器进程退出。离线编辑前再用 `lsof` 确认没有进程持有目标实例的 system、vendor、sys_prod、userdata、cache 覆盖文件。状态查询失败或窗口关闭都不能单独证明磁盘已释放。

如果屏幕锁定，只请用户在目标模拟器窗口解锁。不要索取密码，不改动账户或认证数据。

## 工具与路径

本次工具基线为 macOS ARM64 的 DevEco SDK、Python 3.11+、`qemu-img` 和 Homebrew e2fsprogs。读取真机 EROFS 组件时另用 `dump.erofs`；普通镜像修复不需要重新下载真机固件。

```sh
DEVECO_STUDIO_HOME='<DevEco Studio.app/Contents>'
SDK="$DEVECO_STUDIO_HOME/sdk/default/openharmony"
HDC="$SDK/toolchains/hdc"
DEBUGFS="$(brew --prefix e2fsprogs)/sbin/debugfs"
E2FSCK="$(brew --prefix e2fsprogs)/sbin/e2fsck"
HDC_TARGET=127.0.0.1:10091
```

设备命令形式统一为：

```sh
"$HDC" -s 127.0.0.1:8710 -t "$HDC_TARGET" shell getenforce
```

不要省略 target 后默认操作列表中的第一台设备。`10091` 只是当前副本的端口；一般诊断使用实际发现并明确选定的模拟器端口。

## 离线处理

以下是重新制作副本的方法。已准备好的副本不重复执行。本 Skill 没有一条从空目录自动生成完整模拟器的命令；复制启动器要求磁盘已存在。

### 1. 准备独立实例与恢复点

正常停止源实例，再复制完整实例目录、配置及需要的基础镜像引用。复制过程中记录源目录、实例 UUID、镜像版本、目标端口、文件 hash、备份时间和 backing chain。

设置新的实例名、目录和 HDC 端口。核对 `config.ini` 中的 `name`、`instancePath`、`imageSubPath`、`sdkPath`、`hw.hdc.port` 和 `isHotBoot=false`；`hardware-qemu.ini` 的磁盘路径也应指向副本的基础镜像。签名绑定 UDID 时，明确采用兼容原 UUID 的副本还是为新 UDID 重签名，不静默换设备身份。

原始验证曾使用运行中 userdata 的 APFS clone；它只具备崩溃一致性，因此在临时 raw 副本回放日志后才使用。新的制作优先正常关机后复制。不要把 crash-consistent 备份标为应用一致快照。

保留至少一个全实例恢复点。macOS APFS 可用 `cp -c` 降低复制成本，但仍需要空间容纳写入后的块和临时 raw 文件。userdata 的虚拟大小与主机实际占用分别记录。

### 2. 展开覆盖文件

`EMU_DIR` 必须是已经停止的验证副本目录：

```sh
EMU_DIR='<副本实例目录>'
WORK_DIR="$(mktemp -d /private/tmp/ocp-native-exec.XXXXXX)"

qemu-img info --backing-chain --output=json "$EMU_DIR/system.img.qcow2"
qemu-img info --backing-chain --output=json "$EMU_DIR/userdata.img.qcow2"
qemu-img convert -f qcow2 -O raw "$EMU_DIR/system.img.qcow2" "$WORK_DIR/system.raw"
qemu-img convert -f qcow2 -O raw "$EMU_DIR/userdata.img.qcow2" "$WORK_DIR/userdata.raw"
```

这些 raw 文件是临时可写目标。不要把 SDK 的基础 `system.img` 或 `userdata.img` 当输出。

如原实例并非干净关闭，只对临时副本执行日志回放：

```sh
"$E2FSCK" -p -E journal_only "$WORK_DIR/userdata.raw"
```

检查退出码和日志；修复了日志的退出码可能为 1。遇到非日志问题先分析，不对整份镜像盲目运行自动修复。历史 sys_prod 覆盖文件曾带有位图校验问题，不能用自动 fsck 顺便重写它，再把结果归因于执行域修复。

### 3. 预置产品参数

userdata 内部路径为：

```text
/service/el1/public/startup/parameters/private_persist_parameters
/service/el1/startup/parameters/public_persist_parameters
```

先分别 `stat`、`ea_list` 和 `dump`，保存原文件内容、uid/gid、mode 和所有已有 ACL/xattr。根据实际文件内容更新记录，保持键唯一，不截断其他参数：

```text
persist.sys.abilityms.start_options_with_animation=true
```

该键在本基线按 private key 加载。只更新 public 文件会被 init 忽略；本次成功快照的两份文件均保留同值。不要改完公开文件后仅凭文件内容宣称 AppMgr 已读取。

成功快照还保留以下诊断参数：

```text
persist.binary_security_service.binary_source=1
```

其独立必要性未做消融验证。复刻同一基线时记录并保留它；若研究最小改动，逐项撤销并重新验收，不能直接宣称它无影响。

写回参数文件时保留元数据。可以使用已核对的 ext4 文件块映射原位更新；改变文件大小时必须同步 inode。也可在临时 raw 中重建文件，再按保存值恢复 uid/gid、mode 和每个原有扩展属性。不要照抄旧文件块号或固定用户号。

完成后重新 dump 并比较内容和元数据。不要把整个原实例的参数文件拷到另一台设备，覆盖它自己的账户、网络和用户配置。

### 4. 恢复 AppSpawn 条件分支

system raw 中的路径包含 `/system` 前缀：

```sh
GUEST_LIB=/system/lib64/appspawn/common/libappspawn_common.z.so
"$DEBUGFS" -R "stat $GUEST_LIB" "$WORK_DIR/system.raw"
"$DEBUGFS" -R "ea_list $GUEST_LIB" "$WORK_DIR/system.raw"
"$DEBUGFS" -R "dump $GUEST_LIB $WORK_DIR/appspawn.original.so" "$WORK_DIR/system.raw"

python3 "$SKILL_DIR/scripts/emulator_custom_sandbox_flag.py" \
  --input "$WORK_DIR/appspawn.original.so" \
  --output "$WORK_DIR/appspawn.patched.so"
```

脚本要求输入是已审计 SDK 的精确哈希。输出旁的 JSON 记录输入/输出 hash、88 字节修改范围和未改变的权限检查边界。拒绝输入时不要继续写回。

这份 SDK 原文件为普通文件、uid/gid `0:0`、mode `0644`，只有 `security.selinux` 扩展属性；其他版本以实际导出值为准。如 `ea_list` 与此不同，先补齐所有属性的保存和恢复，不直接套用以下写回模板：

```sh
"$DEBUGFS" -R "ea_get -f $WORK_DIR/appspawn.selinux $GUEST_LIB security.selinux" \
  "$WORK_DIR/system.raw"

cat >"$WORK_DIR/appspawn.commands" <<EOF
rm $GUEST_LIB
write $WORK_DIR/appspawn.patched.so $GUEST_LIB
sif $GUEST_LIB mode 0100644
sif $GUEST_LIB uid 0
sif $GUEST_LIB gid 0
ea_set -f $WORK_DIR/appspawn.selinux $GUEST_LIB security.selinux
EOF

"$DEBUGFS" -w -f "$WORK_DIR/appspawn.commands" "$WORK_DIR/system.raw"
"$DEBUGFS" -R "dump $GUEST_LIB $WORK_DIR/appspawn.readback.so" "$WORK_DIR/system.raw"
cmp "$WORK_DIR/appspawn.patched.so" "$WORK_DIR/appspawn.readback.so"
```

逐条检查 debugfs 输出。debugfs 遇到子命令失败时不一定通过进程退出码完整反映错误。最后再次 `stat` 和 `ea_list`，比对原始元数据。`WORK_DIR` 使用上面无空格的临时目录；debugfs 命令文件不自动展开未替换的 shell 变量。

不要加入 CIL allow 规则、改写 `sehap_contexts`，或把 AppSpawn 的包名判断改为强制放行。产品参数和条件转换应保留在同一个权限启动链路中。

### 5. 可选的系统开关展示诊断

只有任务要求检查系统页面时才处理。成功副本使用 system 早期参数目录 `/system/etc/param/ohos_const/` 中的独立 `.para` 文件：

```text
const.product.model=ocp-lab1
const.appsecurityprivacy.binarysecurity.control_ext_binary=1
```

新文件的 mode、uid/gid 和 SELinux 标签参照同目录正常参数文件恢复。const 参数加载次序会影响覆盖关系，冷启动后必须读回实际 model 并打开原 Settings 页面检查。成功副本还保留 vendor/sys_prod 的 model 诊断修改，见修改账本；没有做过只保留上述两行的新实例消融证明。

开关显示后若仍报 `BinarySourceScope of undefined`，停止此 UI 写入路径并记录缺失模块；不要靠反复认证或修改显示值假装后端可用。它不阻塞已验证的 debug 开发域测试。

### 6. 转回 QCOW2 并替换副本覆盖文件

`BASE_SYSTEM` 和 `BASE_USERDATA` 从第 2 步的 backing chain 读取绝对路径，并核对其实际格式。本基线基础文件为 raw：

```sh
qemu-img convert -f raw -O qcow2 -B "$BASE_SYSTEM" -F raw \
  "$WORK_DIR/system.raw" "$WORK_DIR/system.patched.qcow2"
qemu-img convert -f raw -O qcow2 -B "$BASE_USERDATA" -F raw \
  "$WORK_DIR/userdata.raw" "$WORK_DIR/userdata.patched.qcow2"

qemu-img check "$WORK_DIR/system.patched.qcow2"
qemu-img check "$WORK_DIR/userdata.patched.qcow2"
qemu-img compare -f raw -F qcow2 "$WORK_DIR/system.raw" "$WORK_DIR/system.patched.qcow2"
qemu-img compare -f raw -F qcow2 "$WORK_DIR/userdata.raw" "$WORK_DIR/userdata.patched.qcow2"
```

check 成功且 compare 返回相同时，再替换**已停止副本**的对应覆盖文件；替换前保留原文件和配置。所有磁盘转换与写回任务完成后才启动模拟器，不让异步命令在后台继续改写已启动实例。

### 7. 保留系统覆盖文件的启动器

原 SDK 启动流程会重建 system/vendor/sys_prod 的 QCOW2 覆盖文件，使修复在重启后消失。直接修改基础 system.img 又会遭镜像完整性校验拒绝。

生成一个新的主机启动器副本：

```sh
python3 "$SKILL_DIR/scripts/emulator_overlay_runtime.py" \
  --deveco-contents "$DEVECO_STUDIO_HOME" \
  --output "$LAB_ROOT/overlay-runtime"
```

输出目录必须不存在。脚本保留原启动器，复制资源引用，对复制的 ARM64 Mach-O 修改两处覆盖文件重建入口，再以原 entitlements ad-hoc 签名；原始 SDK 和镜像签名校验不变。所有磁盘需提前准备，包括 cache 覆盖文件。

通过现有 manifest 启动，或核对参数后直接使用该复制启动器：

```sh
"$LAB_ROOT/overlay-runtime/Emulator" \
  -start 'OCP Zig Switch Lab' \
  -instancePath "$LAB_ROOT/deployed" \
  -imageRoot "$LAB_ROOT/images" \
  -hdcPort 10091 -bootMode coldboot
```

`imageRoot` 指向包含 `system-image/...` 的上级目录，`instancePath` 指向实例集合目录，不是单个实例目录。不要改完覆盖文件后改用原 SDK 的默认启动按钮，再误判为 guest 配置没有持久化。

现有助手需要 manifest 中至少具备 `name`、`target`、`instance_path`、`image_root`，并要求实例在 `<lab-root>/deployed/`、镜像在 `<lab-root>/images/`。制作新副本时另外记录版本、哈希、备份、参数和诊断残留。

## 宿主构建与真实 PTY 验证

安装有效签名、匹配目标 UDID 的 debug HAP。宿主必须声明并实际获授 CUSTOM_SANDBOX。重签名者不一致时，不自动卸载原应用；优先选择新的隔离副本，或在已有授权范围内先备份应用数据再迁移。

构建后检查 HAP 的 `app.debug=true`，不能仅依据 profile 类型判断。保留原终端 Native payload 的哈希；同项目的性能演示构建可能只展示 benchmark、根本没有 PTY，不可用作验收宿主。

运行宿主后，在应用终端中执行：

```sh
export PATH=/data/service/hnp/bin:/data/app/bin:/system/bin
tty
cat /proc/self/attr/current
```

预期为真实 `/dev/pts/*` 和 `u:r:develop_tools_debug_hap:s0`。再用宿主自己的文件传输入口放入测试脚本，例如 debug bundle 文件服务：

```sh
"$HDC" -s 127.0.0.1:8710 -t "$HDC_TARGET" file send \
  -b com.richerfu.ohostty "$SKILL_DIR/scripts/zig_default_workflow.sh" \
  data/storage/el2/base/haps/entry/files/terminal/zig_default_workflow.sh
```

远端相对路径应按实际 bundle 文件服务要求核对，目标目录需已存在。不要把全局 `/data/app/...` 路径当作所有应用内部的同一路径。`/data/local/tmp` 对应用可能不可读，本次尝试也确实被拒绝；优先写入宿主自己的目录。

然后由应用 PTY 进入脚本所在目录执行：

```sh
/system/bin/sh ./zig_default_workflow.sh new-project
```

测试目录必须新建。脚本仅调整 PATH 和缓存位置，直接执行默认三条 Zig 命令；首次 Maker 编译可能需要数分钟。用进程和日志确认进度，不因暂时没有输出就换预编译产物。生成程序运行输出和三个 `EXIT=0` 均需要保存。

HDC UI 自动化可以向终端输入命令；这仍是应用 PTY 执行。避免复杂 shell 字符在 HDC 参数中被提前展开：上传脚本，再只输入简单的脚本调用。root/HDC 调试目录运行生成产物，不能算应用原地执行成功。

## 可选：加载真机 app_custom 过滤规则

仅在已进入开发执行域时使用。需要从有来源和哈希记录的真机 system 提取 `libseccomp.z.so` 和其匹配的过滤 DSO，放入**隔离副本覆盖文件**的原系统路径，并恢复相应文件标签。不可直接把整套真机 AppSpawn 替换回来。

编译附带探针：

```sh
"$SDK/native/llvm/bin/clang" --target=aarch64-linux-ohos \
  --sysroot="$SDK/native/sysroot" -O2 -Wall -Wextra -Werror \
  "$SKILL_DIR/scripts/custom_policy_shell.c" -ldl \
  -o "$WORK_DIR/custom-policy-shell"
```

通过宿主文件服务传入自己的目录，在应用 PTY 中运行：

```sh
chmod 700 ./custom-policy-shell
./custom-policy-shell /system/bin/sh -i
/system/bin/sh ./zig_default_workflow.sh another-new-project
```

探针检查现有开发域，再调用原始 `SetSeccompPolicyWithName(APP, "app_custom")`，读回 `Seccomp=2` 后启动 shell。规则继承给其后代，只增加限制，不修改调用方身份。当前探针不能自动让每次新建终端都启用它；报告应写“手动过滤的测试 PTY”。

未提取过滤库、库加载失败、规则启用失败或域不匹配时，不能把普通开发域的成功写成“已在真机 app_custom 下验证”。

## 回滚与排错

回滚前正常停止验证实例并等待镜像释放。恢复同一时间点的完整配置和被修改的覆盖文件；恢复整个 userdata 会回退应用、数据和系统设置，不能当作无损操作。若只是放弃验证副本，保留原实例即可，不把副本磁盘覆盖回原实例。

| 现象 | 下一步 |
| --- | --- |
| chmod、自签名后仍 AccessDenied | 核对真正的域和 AVC，不重复增加执行位 |
| 权限已授予，域仍为 normal_hap | 查产品参数、AppMgr 消息 bit 31、AppSpawn 的 SELinux 标志掩码 0x10 转换和 debug 构建属性 |
| 配置文件有 true，但重启仍不生效 | 查 private/public 分类、进程缓存及实际启动器是否重建覆盖文件 |
| `BinarySourceScope of undefined` | 记录 HMS Native 模块缺失和 setter 前失败，停止重复认证 |
| 启动镜像完整性错误 | 恢复原基础镜像；确认只修改实例覆盖文件 |
| 整套真机启动库移植后重启循环 | 停机回滚该组变更，保存 seccomp 和 critical-process 日志 |
| 探针提示 factory library 无法加载 | 查路径、namespace、依赖和标签，不跳过激活检查 |
| PTY 中 cp/chmod 找不到 | 核对 PATH，使用 `/system/bin` 或已安装工具 |
| zig init 首次长时间无输出 | 查实际 zig 进程和 CPU/日志；全新 Maker 编译可能需数分钟 |

收尾只清理可再生成的临时 raw、下载片段和中间产物；清理前保存选定组件 hash、验证报告和恢复点。不要删除用户签名材料、当前工作磁盘或唯一可用备份。
