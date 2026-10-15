use arkit::shadcn::theme::{Theme, ThemeMode, ThemePreset, ThemeProvider};
use arkit::{entry, prelude::*};
use napi_derive_ohos::napi;
use std::{path::PathBuf, sync::OnceLock};

mod manager;
mod package_table;
mod pages;
use manager::Manager;

static FILES: OnceLock<PathBuf> = OnceLock::new();

pub(crate) fn brand_source() -> arkit::ArkImageSource {
    arkit::ArkImageSource::svg(
        "ocp-grok-icon",
        include_str!("../../../assets/ocp.svg"),
        256,
        256,
    )
}

struct AbilityConfiguration;
impl AbilityConfiguration {
    fn configure(path: PathBuf) -> napi_ohos::Result<()> {
        if !path.is_absolute() {
            return Err(napi_ohos::Error::from_reason(
                "Expected AbilityContext.filesDir",
            ));
        }
        if let Some(existing) = FILES.get() {
            if existing != &path {
                return Err(napi_ohos::Error::from_reason(
                    "Ability files directory changed",
                ));
            }
        } else {
            FILES
                .set(path)
                .map_err(|_| napi_ohos::Error::from_reason("Ability configuration conflict"))?;
        }
        Ok(())
    }
}

#[napi]
pub fn configure(files_dir: String) -> napi_ohos::Result<()> {
    AbilityConfiguration::configure(PathBuf::from(files_dir))
}

#[entry]
fn app() -> Element {
    let theme = use_signal(|| Theme::preset(ThemePreset::Zinc, ThemeMode::Light));
    use_context_provider(|| theme);
    rsx! { ThemeProvider { theme: theme(), AdaptiveProvider { config: AdaptiveConfig::default(), Manager {} } } }
}
