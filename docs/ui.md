# Arkit 管理应用的界面与交互

管理应用使用 Arkit 的真实 shadcn 组件与 Zinc 主题。布局和操作属于 UI，工具选择、下载校验、注册与安装状态属于共用的 OCP CLI。管理 HAP 内嵌同一份无 UI HNP，bundle 为 `com.richerfu.ocp`；CLI 安装包和管理 HAP 是同一 bundle 的两种交付形式。

## 信息结构

桌面布局使用侧栏和内容区域；窄窗口使用紧凑导航。导航包含工具、已安装、仓库、设置和关于。内容区域直接展示当前 Tab 的控件，没有全局 OCP 通栏或重复的页面标题。工具页以搜索和刷新控件开头，随后展示表格：工具、已安装、最新版本、来源仓库、包发布者、上游项目和操作；工具详情使用 Select 选择发布版本，提供安装、更新与卸载操作。详情返回到来源 Tab，Debug 提供返回关于的操作栏。所有顶部操作栏在滚动区之外固定显示，Loading 和 Alert 位于操作栏下方的页内内容区。

仓库页显示已注册来源与 URL，通过有标签的 Input 添加 tap。设置页管理应用外观；安装操作直接调用设备 BMS。关于页显示产品名称与版本。

工具表格以 Arkit 原生 grid 语义和 shadcn 主题组成富单元格，管理列使用真实 Button；纯文本详情使用组件库 Table。窄窗口提供横向滚动。表格最后一行不绘制内部分隔边框，仅保留容器边框。发布者字段和来源匹配规则见 [仓库协议](repositories.md#协议-2)。

当前导航项使用 Secondary 按钮和加粗文字，侧栏背景与选中背景保持可见差异。进入工具详情保留来源导航项，进入 Debug 保留“关于”的选中态。键盘焦点由 Button 的焦点环表示。

## 组件和主题

| 用途 | Arkit shadcn 组件 |
| --- | --- |
| 主操作、次操作、导航、卸载 | Button 的 Default、Outline、Secondary、Ghost、Destructive |
| 工具和仓库容器 | Card、CardHeader、CardContent、Separator |
| 状态与来源 | Badge |
| 搜索、仓库地址 | Input |
| 版本选择与详情 | Select、Table |
| 卸载确认 | 受控 AlertDialog |
| 错误与执行中状态 | Alert、Spinner |
| 字体、颜色、圆角 | Text 与 Zinc ThemeProvider |

布局只设置尺寸、留白和位置；颜色使用 background、foreground、muted、border、destructive 等语义 token。图标可使用产品色，管理控件遵循统一主题。浅色与深色由同一套 token 切换。

## 操作状态

一次只执行一个管理任务；执行中禁用会改变工具或仓库的按钮，显示任务名称与 Spinner。失败保留原安装收据，错误只在当前页面顶部的一个 Destructive Alert 中显示。表单校验与命令错误共用该位置。切换页面清除错误；切换后才完成的旧任务仍同步安装状态，但不把错误带到新页面或重新进入的旧页面。Debug 显示当前测试的命令输出。卸载先打开 AlertDialog，取消、返回或关闭弹窗都不执行卸载；确认后才调用 CLI。

表单同时提供可见标签与无障碍名称。按钮、Input、Select 和 Dialog 使用组件库的焦点、键盘、悬停与模态行为。控件不能用不同颜色与自制弹层另造一套交互。

## Debug 入口

关于页连续点击版本号七次进入 Debug。两次点击间隔超过两秒时重新计数，离开关于页后计数不保留。正常导航不提供 Debug 入口。

Debug 提供环境诊断、Zig 版本查询和 C 编译测试，并显示真实命令输出。当前模拟器允许调用预装 HNP 命令；应用中新生成 ELF 的运行仍通过同一模拟器的 HDC 调试目录验证。

设计依据：[shadcn 主题机制](https://ui.shadcn.com/docs/theming)、[Alert Dialog](https://ui.shadcn.com/docs/components/alert-dialog)。原生实现以当前 Arkit 组件的行为为准。

## 桌面入口

管理 HAP 使用 `EntryAbility` 作为唯一的 home 入口，采用 singleton 启动模式。OCP 图标打开管理 UI；重复启动复用同一 Ability。应用不调用系统任务管理器。

工具安装 HAP 不声明 home Ability，HNP 也不包含界面。工具安装后只导出终端命令，不新增桌面图标。仅写 `app.hideDesktopIcon` 不会获得隐藏能力：工具包的签名 profile 必须包含 `app-privilege-capabilities: ["AllowAppDesktopIconHide"]`。模拟器调试签名器自动为纯 HNP 宿主配置该能力，为管理 UI 保留可见入口。

没有 home Ability 的普通 HAP 可能由系统补充应用详情入口，表现为额外的原生进程管理图标。OCP 管理 HAP 必须保持 `mainElement=EntryAbility` 和唯一的 home skill，安装后核对 `needAppDetail=false`。自动化检查桌面双击后的实际窗口与 Ability，不能只检查系统任务管理器进程是否存在。

正式分发须使用平台批准的 profile 能力；手动修改 profile 仅适用于调试，不能推断正式发行也可自行添加该能力。依据：[OpenHarmony 应用特权配置指南](https://github.com/openharmony/docs/blob/master/zh-cn/device-dev/subsystems/subsys-app-privilege-config-guide.md)。

## 产品图标

`ui/assets/ocp.svg` 由 Grok 调整为 1024×1024 满幅不透明背景，应用圆角交给系统蒙版处理。图标不再自行缩进底板或留透明外圈，包体与工具模块同步放大。桌面图标与管理界面的品牌图使用同一资源。
