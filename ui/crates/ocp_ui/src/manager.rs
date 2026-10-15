use crate::pages::{About, Debug, Details, Feedback, Preferences, Repositories, Toolbar, Tools};
use arkit::prelude::*;
use arkit::shadcn::components::{Button, ButtonVariant, Text, TextVariant};
use arkit::shadcn::{icon::icon_placeholder, theme::use_theme};
use ocp_client::{Action, Package, PackageClient, Snapshot};
use std::sync::Arc;

#[derive(Clone, Copy, PartialEq)]
pub(crate) enum Page {
    Tools,
    Installed,
    Repositories,
    Details,
    Settings,
    About,
    Debug,
}

#[derive(Clone, Copy)]
pub(crate) struct Controller {
    pub(crate) page: Signal<Page>,
    navigation: Signal<Page>,
    generation: Signal<u64>,
    pub(crate) client: Signal<Option<Arc<PackageClient>>>,
    pub(crate) snapshot: Signal<Snapshot>,
    pub(crate) selected: Signal<String>,
    pub(crate) version: Signal<String>,
    pub(crate) busy: Signal<bool>,
    pub(crate) status: Signal<String>,
    pub(crate) failed: Signal<bool>,
    pub(crate) logs: Signal<String>,
    pub(crate) worker: Signal<tokio::runtime::Handle>,
    pub(crate) confirm: Signal<bool>,
    pub(crate) query: Signal<String>,
}
impl Controller {
    pub(crate) fn start(mut self, action: Action) {
        if *self.busy.peek() {
            return;
        }
        let Some(client) = self.client.peek().clone() else {
            return;
        };
        self.busy.set(true);
        self.confirm.set(false);
        self.failed.set(false);
        let label = action.label();
        self.status.set(format!("正在{label}…"));
        self.logs.set(String::new());
        let worker = self.worker.peek().clone();
        let generation = *self.generation.peek();
        dioxus_core::spawn(async move {
            match worker.spawn_blocking(move || client.execute(action)).await {
                Ok(outcome) => {
                    self.snapshot.set(outcome.snapshot);
                    if generation == *self.generation.peek() {
                        self.failed.set(!outcome.success);
                        self.status.set(format!(
                            "{}：{}",
                            label,
                            if outcome.success { "成功" } else { "失败" }
                        ));
                        self.logs.set(outcome.output);
                    } else {
                        self.status.set("准备就绪".into());
                    }
                }
                Err(error) => {
                    if generation == *self.generation.peek() {
                        self.fail(format!("{label}失败"), error.to_string());
                    } else {
                        self.status.set("准备就绪".into());
                    }
                }
            }
            self.busy.set(false);
        });
    }
    pub(crate) fn fail(mut self, status: String, output: String) {
        self.failed.set(true);
        self.status.set(status);
        self.logs.set(output);
    }
    pub(crate) fn navigate(mut self, page: Page) {
        let generation = *self.generation.peek() + 1;
        self.generation.set(generation);
        self.failed.set(false);
        self.logs.set(String::new());
        if !*self.busy.peek() {
            self.status.set("准备就绪".into());
        }
        self.page.set(page);
        if !matches!(page, Page::Details | Page::Debug) {
            self.navigation.set(page);
        }
        self.confirm.set(false);
    }
    pub(crate) fn open(mut self, package: &Package) {
        self.selected.set(package.name.clone());
        self.version.set(if package.latest.is_empty() {
            package.versions.last().cloned().unwrap_or_default()
        } else {
            package.latest.clone()
        });
        self.navigate(Page::Details);
    }
    pub(crate) fn back(self) {
        let page = *self.page.peek();
        self.navigate(if matches!(page, Page::Details | Page::Debug) {
            *self.navigation.peek()
        } else {
            Page::Tools
        });
    }
    pub(crate) fn back_label(self) -> &'static str {
        if *self.navigation.peek() == Page::Installed {
            "← 已安装"
        } else {
            "← 工具"
        }
    }
}

#[component]
pub(crate) fn Manager() -> Element {
    let initial = use_hook(|| {
        crate::FILES
            .get()
            .ok_or_else(|| "Ability 尚未初始化".into())
            .and_then(|path| {
                PackageClient::open(path)
                    .map(Arc::new)
                    .map_err(|error| error.to_string())
            })
    });
    let worker = arkit::use_runtime_handle().tokio();
    let controller = Controller {
        page: use_signal(|| Page::Tools),
        navigation: use_signal(|| Page::Tools),
        generation: use_signal(|| 0),
        client: use_signal(|| initial.clone().ok()),
        snapshot: use_signal(|| {
            initial
                .as_ref()
                .ok()
                .and_then(|client| client.snapshot().ok())
                .unwrap_or_default()
        }),
        selected: use_signal(String::new),
        version: use_signal(String::new),
        busy: use_signal(|| false),
        status: use_signal(|| {
            initial
                .as_ref()
                .err()
                .cloned()
                .unwrap_or_else(|| "准备就绪".into())
        }),
        failed: use_signal(|| initial.is_err()),
        logs: use_signal(String::new),
        worker: use_signal(|| worker),
        confirm: use_signal(|| false),
        query: use_signal(String::new),
    };
    use_context_provider(|| controller);
    let handle = arkit::use_runtime_handle();
    let _back = use_hook(move || {
        std::rc::Rc::new(handle.register_back_handler(std::rc::Rc::new(move || {
            if *controller.confirm.peek() {
                let mut controller = controller;
                controller.confirm.set(false);
                return true;
            }
            let page = *controller.page.peek();
            if page == Page::Tools {
                return false;
            }
            controller.back();
            true
        })))
    });
    use_hook(move || {
        if !controller.snapshot.peek().taps.is_empty() {
            controller.start(Action::Refresh);
        }
    });
    let theme = use_theme();
    let logo = use_hook(crate::brand_source);
    let adaptive = use_adaptive_layout();
    let wide = adaptive.width_vp >= 760.0;
    let page = (controller.page)();
    rsx! {
        row { width: "100%", height: "100%", background_color: theme.colors.background,
            if wide {
                column { width: 196.0, height: "100%", align_items: "start", padding: 16.0, background_color: theme.colors.background, border_width: "0,1,0,0", border_color: theme.colors.sidebar_border,
                    row { height: 52.0, align_items: "center", image { src: dioxus_core::AttributeValue::any_value(logo), width: 32.0, height: 32.0, accessibility_mode: "disabled" } column { margin_left: 10.0, align_items: "start", Text { content: "OCP", variant: TextVariant::Large } Text { content: "Command Package", variant: TextVariant::Muted } } }
                    column { width: "100%", margin_top: 24.0, Navigation {} }
                    column { layout_weight: 1.0 }
                    Text { content: "OpenHarmony", variant: TextVariant::Muted }
                }
            }
            column { layout_weight: 1.0, height: "100%", align_items: "start",
                if !wide { row { width: "100%", padding: 8.0, Navigation { compact: true } } }
                if matches!(page,Page::Tools|Page::Installed|Page::Details|Page::Debug) {
                    column { width: "100%", align_items: "center", padding_x: if wide {32.0}else{16.0}, padding_top: if wide {24.0}else{16.0}, padding_bottom: 16.0,
                        column { width: "100%", max_width: 1120.0, Toolbar {} }
                    }
                }
                scroll { width: "100%", layout_weight: 1.0, alignment: "top-start",
                    column { width: "100%", align_items: "center", padding_x: if wide {32.0}else{16.0}, padding_bottom: if wide {32.0}else{16.0}, padding_top: if matches!(page,Page::Tools|Page::Installed|Page::Details|Page::Debug) {0.0}else if wide {32.0}else{16.0},
                        column { width: "100%", max_width: 1120.0, align_items: "start",
                            Feedback {}
                            match page {
                                Page::Tools => rsx! { Tools { installed_only: false } },
                                Page::Installed => rsx! { Tools { installed_only: true } },
                                Page::Repositories => rsx! { Repositories {} },
                                Page::Details => rsx! { Details {} },
                                Page::Settings => rsx! { Preferences {} },
                                Page::About => rsx! { About {} },
                                Page::Debug => rsx! { Debug {} },
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn Navigation(#[props(default)] compact: bool) -> Element {
    let controller = use_context::<Controller>();
    let current = (controller.navigation)();
    let items = [
        (Page::Tools, "工具", "package"),
        (Page::Installed, "已安装", "check"),
        (Page::Repositories, "仓库", "database"),
        (Page::Settings, "设置", "settings"),
        (Page::About, "关于", "info"),
    ];
    let theme = use_theme();
    rsx! {
        for (page,label,icon) in items {
            column { width: if compact { "20%" } else { "100%" }, margin_bottom: if compact {0.0}else{4.0},
                Button { full: true, variant: if page==current {ButtonVariant::Secondary}else{ButtonVariant::Ghost}, accessibility_label: label, accessibility_selected: Some(page==current), onclick: move |_|controller.navigate(page),
                    row { width: "100%", align_items: "center", justify_content: if compact {"center"}else{"start"},
                        if !compact { {icon_placeholder(icon,16.0,theme.colors.foreground)} }
                        column { margin_left: if compact {0.0}else{8.0}, text { font_size: 14.0, font_weight: if page==current {600}else{400}, font_color: theme.colors.foreground, "{label}" } }
                    }
                }
            }
        }
    }
}
