use crate::manager::Controller;
use arkit::prelude::*;
use arkit::shadcn::components::{
    Badge, BadgeVariant, Button, ButtonSize, ButtonVariant, Text, TextVariant,
};
use arkit::shadcn::theme::use_theme;
use ocp_client::Package;

/// Rich cells for the package table; Arkit's text-only Table remains used for details.
#[component]
pub(crate) fn PackageTable(packages: Vec<Package>) -> Element {
    let controller = use_context::<Controller>();
    let theme = use_theme();
    let busy = (controller.busy)();
    let count = packages.len();
    let headers = [
        ("工具", 18),
        ("已安装", 10),
        ("最新版本", 10),
        ("来源仓库", 12),
        ("包发布者", 16),
        ("上游项目", 24),
        ("操作", 10),
    ];
    rsx! {
        scroll { width: "100%", scroll_direction: "horizontal", alignment: "top-start",
            column { width: "100%", min_width: 920.0, accessibility_role: "grid", accessibility_text: "工具表格",
                border_width: 1.0, border_color: theme.colors.border, border_radius: theme.radii.sm,
                background_color: theme.colors.card, clip: true,
                row { width: "100%", height: 40.0, border_width: "0,0,1,0", border_color: theme.colors.border,
                    for (label,width) in headers {
                        column { layout_weight: f64::from(width), height: "100%", padding_x: 12.0, align_items: "start", justify_content: "center",
                            Text { content: label, variant: TextVariant::Muted }
                        }
                    }
                }
                for (index,package) in packages.into_iter().enumerate() {
                    {
                        let name = package.name.clone();
                        let tool = package.tool_name().to_owned();
                        let tap = package.tap().to_owned();
                        let installed = package.installed.clone().unwrap_or_else(|| "未安装".into());
                        let publisher = if package.provenance.publisher.name.is_empty() { "未声明".into() } else { package.provenance.publisher.name.clone() };
                        let upstream = package.upstream_project();
                        let upstream = if upstream.is_empty() { "未声明".into() } else { upstream };
                        rsx! {
                            row { key: "{name}", width: "100%", min_height: 68.0, align_items: "center",
                                accessibility_role: "list_item", accessibility_description: name.clone(),
                                border_width: if index+1 == count {"0,0,0,0"} else {"0,0,1,0"}, border_color: theme.colors.border,
                                column { layout_weight: 18.0, padding: 12.0, align_items: "start", Text { content: tool, variant: TextVariant::Small } Text { content: name.clone(), variant: TextVariant::Muted } }
                                column { layout_weight: 10.0, padding: 12.0, align_items: "start", Text { content: installed, variant: TextVariant::Small } }
                                column { layout_weight: 10.0, padding: 12.0, align_items: "start", Text { content: package.latest.clone(), variant: TextVariant::Small } }
                                column { layout_weight: 12.0, padding: 12.0, align_items: "start", Badge { content: tap, variant: BadgeVariant::Outline } }
                                column { layout_weight: 16.0, padding: 12.0, align_items: "start", Text { content: publisher, variant: TextVariant::Small } }
                                column { layout_weight: 24.0, padding: 12.0, align_items: "start", Text { content: upstream, variant: TextVariant::Muted } }
                                column { layout_weight: 10.0, padding: 12.0, align_items: "start",
                                    Button { variant: ButtonVariant::Outline, size: ButtonSize::Sm, disabled: Some(busy), accessibility_label: format!("管理 {name}"), onclick: move |_|controller.open(&package), "管理" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
