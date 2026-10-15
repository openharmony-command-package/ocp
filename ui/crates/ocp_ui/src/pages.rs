use crate::manager::{Controller, Page};
use crate::package_table::PackageTable;
use arkit::prelude::*;
use arkit::shadcn::components::{
    Alert, AlertDescription, AlertDialog, AlertTitle, AlertVariant, Button, ButtonVariant, Card,
    CardContent, CardHeader, Input, Select, Spinner, Table, Text, TextVariant,
};
use arkit::shadcn::theme::{use_theme, Theme, ThemeMode, ThemePreset};
use ocp_client::{Action, ServiceUrl};
use std::time::{Duration, Instant};

#[component]
pub(crate) fn Tools(installed_only: bool) -> Element {
    let controller = use_context::<Controller>();
    let snapshot = (controller.snapshot)();
    let busy = (controller.busy)();
    let needle = (controller.query)().to_lowercase();
    let packages = snapshot
        .packages
        .into_iter()
        .filter(|package| {
            (!installed_only || package.installed.is_some())
                && format!(
                    "{} {} {} {}",
                    package.name,
                    package.provenance.publisher.name,
                    package.upstream_project(),
                    package.commands.join(" ")
                )
                .to_lowercase()
                .contains(&needle)
        })
        .collect::<Vec<_>>();
    rsx! {
        column { width: "100%",
            if packages.is_empty() {
                Card { shadow: Some(false),
                    CardContent { Text { content: if busy {"正在加载仓库…"}else{"没有匹配的工具"}, variant: TextVariant::Large }
                        Text { content: "在仓库页面注册来源，刷新后即可选择工具。", variant: TextVariant::Muted }
                        column { margin_top: 16.0, Button { variant: ButtonVariant::Outline, onclick: move |_|controller.navigate(Page::Repositories), "管理仓库" } }
                    }
                }
            } else {
                PackageTable { packages }
            }
        }
    }
}

#[component]
pub(crate) fn Details() -> Element {
    let mut controller = use_context::<Controller>();
    let name = (controller.selected)();
    let package = (controller.snapshot)()
        .packages
        .into_iter()
        .find(|package| package.name == name);
    let busy = (controller.busy)();
    let version = (controller.version)();
    let confirm = (controller.confirm)();
    let Some(package) = package else {
        return rsx! { Text { content: "该工具不在活动索引中，请刷新仓库。", variant: TextVariant::Muted } };
    };
    let installed = package.installed.clone().unwrap_or_else(|| "未安装".into());
    let title = package.tool_name().to_owned();
    rsx! {
        column { width: "100%",
            Card { shadow: Some(false), CardHeader { title, description: name.clone() }
                CardContent {
                    Table { headers: vec!["仓库".into(),"已安装".into(),"最新版本".into()], rows: vec![vec![package.tap().into(),installed,package.latest.clone()]] }
                    column { width: "100%", margin_top: 16.0,
                        Table { headers: vec!["来源信息".into(),"内容".into()], rows: vec![
                            vec!["包发布者".into(),if package.provenance.publisher.name.is_empty() {"未声明".into()} else {package.provenance.publisher.name.clone()}],
                            vec!["发布者主页".into(),package.provenance.publisher.url.as_str().into()],
                            vec!["仓库索引".into(),package.provenance.repository.as_str().into()],
                            vec!["上游项目".into(),package.provenance.upstream.as_str().into()],
                            vec!["可执行命令".into(),package.commands.join(", ")],
                        ] }
                    }
                    column { width: "100%", margin_top: 24.0, align_items: "start",
                        Text { content: "安装版本", variant: TextVariant::Small }
                        column { width: "100%", margin_top: 8.0,
                            Select { options: package.versions.clone(), selected: Some(version.clone()), default_selected: package.latest.clone(), default_open: false,
                                accessibility_label: "安装版本", disabled: busy, on_select: move |value|controller.version.set(value) }
                        }
                        Text { content: format!("提供命令：{}",package.commands.join(", ")), variant: TextVariant::Muted }
                    }
                }
            }
        }
        AlertDialog { title: format!("卸载 {name}？"), description: "工具导出的命令将从设备中移除。", open: Some(confirm),
            on_close: move |_|controller.confirm.set(false),
            cancel: rsx! { Button { full: true, variant: ButtonVariant::Outline, onclick: move |_|controller.confirm.set(false), "取消" } },
            action: {let name=name.clone(); rsx! { Button { full: true, variant: ButtonVariant::Destructive, onclick: move |_|controller.start(Action::Uninstall{name:name.clone()}), "确认卸载" } }}
        }
    }
}

#[component]
pub(crate) fn Repositories() -> Element {
    let controller = use_context::<Controller>();
    let snapshot = (controller.snapshot)();
    let busy = (controller.busy)();
    let mut name = use_signal(String::new);
    let mut url = use_signal(String::new);
    rsx! {
        for tap in snapshot.taps {
            column { key: "{tap.name}", width: "100%", margin_top: 16.0,
                Card { shadow: Some(false), CardHeader { title: tap.name.clone(), description: tap.url.as_str().to_owned() }
                    CardContent { Button { variant: ButtonVariant::Outline, disabled: Some(busy), accessibility_label: format!("移除仓库 {}",tap.name), onclick: move |_|controller.start(Action::TapRemove{name:tap.name.clone()}), "移除仓库" } }
                }
            }
        }
        column { width: "100%", margin_top: 24.0,
            Card { shadow: Some(false), CardHeader { title: "添加仓库", description: "使用维护者提供的仓库名称与索引地址。" }
                CardContent {
                    Text { content: "仓库名称", variant: TextVariant::Small }
                    column { width: "100%", margin_top: 8.0, Input { value: name(), placeholder: "community", accessibility_label: "仓库名称", disabled: busy, on_change: move |value|name.set(value) } }
                    column { width: "100%", margin_top: 16.0, align_items: "start", Text { content: "索引地址", variant: TextVariant::Small } }
                    column { width: "100%", margin_top: 8.0, Input { value: url(), placeholder: "https://…/index.tar.gz", accessibility_label: "仓库索引地址", disabled: busy, on_change: move |value|url.set(value) } }
                    column { margin_top: 16.0, Button { disabled: Some(busy || name().is_empty() || url().is_empty()), onclick: move |_|{
                        match ServiceUrl::try_from(url().trim().to_owned()) {
                            Ok(url) => controller.start(Action::TapAdd{name:name().trim().into(),url}),
                            Err(reason) => controller.fail("注册仓库失败".into(), reason.to_string()),
                        }
                    }, "添加并更新" } }
                }
            }
        }
    }
}

#[component]
pub(crate) fn Preferences() -> Element {
    let mut theme = use_context::<Signal<Theme>>();
    rsx! {
        column { width: "100%", margin_top: 24.0, Card { shadow: Some(false), CardHeader { title: "外观", description: "使用统一的 Zinc 主题与 shadcn 组件。" }
            CardContent { Button { variant: ButtonVariant::Outline, onclick: move |_|{
                let mode=if theme.peek().mode==ThemeMode::Dark {ThemeMode::Light}else{ThemeMode::Dark};
                theme.set(Theme::preset(ThemePreset::Zinc,mode));
            }, "切换明暗主题" } }
        } }
    }
}

#[derive(Default)]
struct DebugGate {
    count: u8,
    last: Option<Instant>,
}
impl DebugGate {
    fn tap(&mut self, now: Instant) -> bool {
        if self
            .last
            .is_none_or(|last| now.duration_since(last) > Duration::from_secs(2))
        {
            self.count = 0;
        }
        self.last = Some(now);
        self.count += 1;
        if self.count == 7 {
            *self = Self::default();
            true
        } else {
            false
        }
    }
}

#[component]
pub(crate) fn About() -> Element {
    let controller = use_context::<Controller>();
    let mut gate = use_signal(DebugGate::default);
    let logo = use_hook(crate::brand_source);
    rsx! {
        column { width: "100%", margin_top: 24.0, Card { shadow: Some(false), CardHeader { title: "OCP", description: "OpenHarmony Command Package" }
            CardContent {
                image { src: dioxus_core::AttributeValue::any_value(logo), width: 64.0, height: 64.0, accessibility_text: "OCP 图标" }
                Text { content: "安装、更新与管理 OpenHarmony 命令工具。", variant: TextVariant::P }
                column { margin_top: 16.0, Button { variant: ButtonVariant::Ghost, accessibility_label: "版本号", onclick: move |_|{if gate.write().tap(Instant::now()){controller.navigate(Page::Debug);}}, "版本 {env!(\"CARGO_PKG_VERSION\")}" } }
                Text { content: "Arkit · shadcn · com.richerfu.ocp", variant: TextVariant::Muted }
            }
        } }
    }
}

#[component]
pub(crate) fn Debug() -> Element {
    let controller = use_context::<Controller>();
    let busy = (controller.busy)();
    let theme = use_theme();
    let logs = (controller.logs)();
    let mut commands = (controller.snapshot)()
        .packages
        .into_iter()
        .filter(|package| package.installed.is_some())
        .flat_map(|package| package.commands)
        .collect::<Vec<_>>();
    commands.sort();
    commands.dedup();
    let mut selected = use_signal(|| commands.first().cloned().unwrap_or_default());
    rsx! {
        column { width: "100%",
            Card { shadow: Some(false), CardHeader { title: "已安装命令", description: "选择已安装工具提供的命令，执行 --version。" }
                CardContent {
                    Select { options: commands.clone(), selected: Some(selected()), default_selected: selected(), default_open: false, accessibility_label: "测试命令", disabled: busy, on_select: move |value|selected.set(value) }
                    column { margin_top: 16.0, Button { variant: ButtonVariant::Outline, disabled: Some(busy||!commands.contains(&selected())), onclick: move |_|controller.start(Action::RunVersion{command:selected()}), "运行命令测试" } }
                }
            }
        }
        column { width: "100%", margin_top: 24.0, Card { shadow: Some(false), CardHeader { title: "测试输出", description: "编译产物在本应用保存，当前镜像需用 HDC 调试目录执行新生成的 ELF。" }
            CardContent { text { width: "100%", font_size: 13.0, font_color: theme.colors.foreground, "{logs}" } }
        } }
    }
}

#[component]
pub(crate) fn Toolbar() -> Element {
    let mut controller = use_context::<Controller>();
    let page = (controller.page)();
    let busy = (controller.busy)();
    let version = (controller.version)();
    let selected = (controller.selected)();
    let package = if page == Page::Details {
        controller
            .snapshot
            .read()
            .packages
            .iter()
            .find(|package| package.name == selected)
            .cloned()
    } else {
        None
    };
    rsx! {
        row { width: "100%", align_items: "center", accessibility_description: "页面操作栏",
            match page {
                Page::Tools | Page::Installed => rsx! {
                    column { layout_weight: 1.0,
                        Input { value: (controller.query)(), placeholder: "搜索工具、仓库或发布者…", accessibility_label: "搜索工具", on_change: move |value|controller.query.set(value) }
                    }
                    column { margin_left: 12.0, Button { variant: ButtonVariant::Outline, disabled: Some(busy), onclick: move |_|controller.start(Action::Refresh), "刷新" } }
                },
                Page::Details => rsx! {
                    Button { variant: ButtonVariant::Ghost, onclick: move |_|controller.back(), "{controller.back_label()}" }
                    column { layout_weight: 1.0 }
                    if let Some(package) = package {
                        Button { disabled: Some(busy||version.is_empty()), accessibility_label: "安装所选版本", onclick: {let name=selected.clone();let version=version.clone();move |_|controller.start(Action::Install{name:name.clone(),version:version.clone()})}, "安装所选版本" }
                        if package.installed.is_some() && !package.latest.is_empty() && package.installed.as_ref()!=Some(&package.latest) {
                            column { margin_left: 8.0, Button { variant: ButtonVariant::Outline, disabled: Some(busy), onclick: {let name=selected.clone();move |_|controller.start(Action::Upgrade{name:name.clone()})}, "更新到最新版本" } }
                        }
                        if package.installed.is_some() { column { margin_left: 8.0, Button { variant: ButtonVariant::Destructive, disabled: Some(busy), onclick: move |_|controller.confirm.set(true), "卸载" } } }
                    }
                },
                Page::Debug => rsx! {
                    Button { variant: ButtonVariant::Ghost, onclick: move |_|controller.back(), "← 关于" }
                    column { layout_weight: 1.0 }
                    Button { variant: ButtonVariant::Outline, disabled: Some(busy), onclick: move |_|controller.start(Action::Doctor), "环境诊断" }
                    column { margin_left: 8.0, Button { variant: ButtonVariant::Outline, disabled: Some(busy), onclick: move |_|controller.start(Action::TestZig), "Zig 命令测试" } }
                    column { margin_left: 8.0, Button { disabled: Some(busy), onclick: move |_|controller.start(Action::TestCompile), "Zig 编译测试" } }
                },
                _ => rsx! {},
            }
        }
    }
}

#[component]
pub(crate) fn Feedback() -> Element {
    let controller = use_context::<Controller>();
    let status = (controller.status)();
    let busy = (controller.busy)();
    let failed = (controller.failed)();
    if status == "准备就绪" && !busy && !failed {
        return rsx! {};
    }
    let output = (controller.logs)();
    rsx! {
        column { width: "100%", margin_bottom: 16.0,
            if failed {
                Alert { icon: "circle-alert", variant: AlertVariant::Destructive, AlertTitle { content: status } AlertDescription { content: output } }
            } else {
                row { align_items: "center",
                    if busy { Spinner { accessibility_label: "操作进行中" } }
                    column { margin_left: if busy {8.0}else{0.0}, Text { content: status, variant: TextVariant::Muted } }
                }
            }
        }
    }
}
