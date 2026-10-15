//! Application adapter for the installed OCP CLI. Package policy stays in OCP.
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fmt, fs,
    io::{self, Read},
    path::{Path, PathBuf},
    process::Command,
};

#[derive(Debug)]
pub struct ClientError(String);
impl fmt::Display for ClientError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ClientError {}
impl From<io::Error> for ClientError {
    fn from(error: io::Error) -> Self {
        Self(error.to_string())
    }
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq)]
#[serde(try_from = "String", into = "String")]
pub struct ServiceUrl(Box<str>);
impl ServiceUrl {
    pub fn as_str(&self) -> &str {
        &self.0
    }
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}
impl TryFrom<String> for ServiceUrl {
    type Error = ClientError;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        if !value.is_empty() && !(value.starts_with("https://") || value.starts_with("http://")) {
            return Err(ClientError("服务地址必须使用 HTTP 或 HTTPS".into()));
        }
        if value.chars().any(char::is_control) {
            return Err(ClientError("服务地址包含控制字符".into()));
        }
        Ok(Self(value.into_boxed_str()))
    }
}
impl From<ServiceUrl> for String {
    fn from(value: ServiceUrl) -> Self {
        value.0.into()
    }
}

#[derive(Clone, Default, Deserialize, Serialize, PartialEq)]
struct Settings {
    repository: ServiceUrl,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Package {
    pub name: String,
    pub latest: String,
    pub versions: Vec<String>,
    pub installed: Option<String>,
    pub commands: Vec<String>,
    pub provenance: Provenance,
}
#[derive(Clone, Debug, Default, Deserialize, PartialEq)]
pub struct Publisher {
    pub name: String,
    #[serde(default)]
    pub url: ServiceUrl,
}
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Provenance {
    pub publisher: Publisher,
    pub upstream: ServiceUrl,
    pub repository: ServiceUrl,
}
impl Package {
    pub fn tool_name(&self) -> &str {
        self.name
            .split_once('/')
            .map_or(self.name.as_str(), |(_, name)| name)
    }
    pub fn tap(&self) -> &str {
        self.name.split_once('/').map_or("core", |(tap, _)| tap)
    }
    pub fn upstream_project(&self) -> String {
        self.provenance
            .upstream
            .as_str()
            .strip_prefix("https://github.com/")
            .map(|path| path.split('/').take(2).collect::<Vec<_>>().join("/"))
            .unwrap_or_else(|| self.provenance.upstream.as_str().to_owned())
    }
}
#[derive(Clone, Default, PartialEq)]
pub struct Tap {
    pub name: String,
    pub url: ServiceUrl,
}
#[derive(Clone, Default)]
pub struct Snapshot {
    pub packages: Vec<Package>,
    pub taps: Vec<Tap>,
}

#[derive(Clone, Debug)]
pub enum Action {
    Refresh,
    Install { name: String, version: String },
    Upgrade { name: String },
    Uninstall { name: String },
    Doctor,
    TestZig,
    TestCompile,
    RunVersion { command: String },
    TapAdd { name: String, url: ServiceUrl },
    TapRemove { name: String },
}
impl Action {
    pub fn label(&self) -> String {
        match self {
            Self::Refresh => "刷新工具与安装状态".into(),
            Self::Install { name, version } => format!("安装 {name} {version}"),
            Self::Upgrade { name } => format!("更新 {name}"),
            Self::Uninstall { name } => format!("卸载 {name}"),
            Self::Doctor => "环境诊断".into(),
            Self::TestZig => "Zig 命令测试".into(),
            Self::TestCompile => "Zig 编译测试".into(),
            Self::RunVersion { command } => format!("命令测试 {command}"),
            Self::TapAdd { name, .. } => format!("注册仓库 {name}"),
            Self::TapRemove { name } => format!("移除仓库 {name}"),
        }
    }
}

pub struct Outcome {
    pub success: bool,
    pub output: String,
    pub snapshot: Snapshot,
}

pub struct PackageClient {
    state: PathBuf,
    cli: PathBuf,
    settings: Settings,
}
impl PackageClient {
    pub fn open(files: &Path) -> Result<Self, ClientError> {
        let state = files.join("ocp");
        fs::create_dir_all(&state)?;
        let settings: Settings = match fs::read(state.join("settings.json")) {
            Ok(bytes) => {
                serde_json::from_slice(&bytes).map_err(|error| ClientError(error.to_string()))?
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => Settings::default(),
            Err(error) => return Err(error.into()),
        };
        let mut client = Self {
            state,
            cli: PathBuf::from("/data/service/hnp/bin/ocp"),
            settings,
        };
        // Migrate the original single repository to a registered core tap once.
        if !client.settings.repository.is_empty() {
            fs::create_dir_all(client.state.join("taps"))?;
            let core = client.state.join("taps/core");
            if !core.is_file() {
                fs::write(core, client.settings.repository.as_str())?;
            }
            let settings = Settings {
                repository: ServiceUrl::default(),
            };
            client = client.save_settings(settings)?;
        }
        Ok(client)
    }
    fn save_settings(&self, settings: Settings) -> Result<Self, ClientError> {
        let temporary = self.state.join("settings.json.new");
        let bytes =
            serde_json::to_vec_pretty(&settings).map_err(|error| ClientError(error.to_string()))?;
        fs::write(&temporary, bytes)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))?;
        }
        fs::rename(temporary, self.state.join("settings.json"))?;
        Ok(Self {
            state: self.state.clone(),
            cli: self.cli.clone(),
            settings,
        })
    }
    fn command(&self, executable: &Path) -> Command {
        let mut command = Command::new(executable);
        command
            .current_dir(&self.state)
            .env("PATH", "/data/service/hnp/bin:/system/bin:/vendor/bin")
            .env("TMPDIR", &self.state)
            .env("OCP_STATE_DIR", &self.state)
            .env_remove("OCP_REPOSITORY");
        command
    }
    fn capture(&self, executable: &Path, args: &[&str]) -> Result<String, ClientError> {
        let result = self.command(executable).args(args).output()?;
        let mut output = String::from_utf8_lossy(&result.stdout).into_owned();
        output.push_str(&String::from_utf8_lossy(&result.stderr));
        if result.status.success() {
            Ok(output)
        } else {
            Err(ClientError(format!("命令退出 {}\n{output}", result.status)))
        }
    }
    fn cli(&self, args: &[&str]) -> Result<String, ClientError> {
        self.capture(&self.cli, args)
    }
    pub fn snapshot(&self) -> Result<Snapshot, ClientError> {
        let mut taps = Vec::new();
        match fs::read_dir(self.state.join("taps")) {
            Ok(entries) => {
                for entry in entries {
                    let entry = entry?;
                    if !entry.file_type()?.is_file() {
                        continue;
                    }
                    let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
                        continue;
                    };
                    if !name.ends_with(".new") {
                        taps.push(Tap {
                            name,
                            url: fs::read_to_string(entry.path())?
                                .trim()
                                .to_owned()
                                .try_into()?,
                        });
                    }
                }
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        taps.sort_by(|a, b| a.name.cmp(&b.name));
        let index_path = match fs::read_to_string(self.state.join("catalogs/current")) {
            Ok(generation) => {
                Catalog::identifier(generation.trim())?;
                self.state
                    .join("catalogs/generations")
                    .join(generation.trim())
                    .join("index.tsv")
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => self.state.join("index.tsv"),
            Err(error) => return Err(error.into()),
        };
        let index = match fs::read_to_string(&index_path) {
            Ok(index) => index,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Ok(Snapshot {
                    taps,
                    packages: Vec::new(),
                })
            }
            Err(error) => return Err(error.into()),
        };
        let abi = match std::env::consts::ARCH {
            "aarch64" => "arm64-v8a",
            "x86_64" => "x86_64",
            "arm" => "armeabi-v7a",
            _ => "unsupported",
        };
        let mut packages = Catalog::parse(&index, abi)?;
        for package in &mut packages {
            let key = format!("{}@{}", package.tap(), package.tool_name());
            match fs::read_to_string(self.state.join("installed").join(key)) {
                Ok(receipt) => package.installed = receipt.split('\t').next().map(str::to_owned),
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
        packages.retain(|package| {
            package.installed.is_some() || taps.iter().any(|tap| tap.name == package.tap())
        });
        Catalog::provenance(&self.state, &index_path, &index, abi, &mut packages)?;
        Ok(Snapshot { packages, taps })
    }
    pub fn execute(&self, action: Action) -> Outcome {
        let result = self.apply(&action);
        let success = result.is_ok();
        let mut output = result.unwrap_or_else(|error| error.to_string());
        let snapshot = match self.snapshot() {
            Ok(snapshot) => snapshot,
            Err(error) => {
                output.push_str(&format!("\n读取工具状态失败：{error}"));
                return Outcome {
                    success: false,
                    output,
                    snapshot: Snapshot::default(),
                };
            }
        };
        Outcome {
            success,
            output,
            snapshot,
        }
    }
    fn apply(&self, action: &Action) -> Result<String, ClientError> {
        match action {
            Action::Refresh => {
                let mut output = self.cli(&["update"])?;
                output.push_str(&self.cli(&["sync"])?);
                Ok(output)
            }
            Action::Install { name, version } => {
                Catalog::package_identity(name)?;
                Catalog::identifier(version)?;
                self.cli(&["install", name, "--version", version])
            }
            Action::Upgrade { name } => {
                Catalog::package_identity(name)?;
                self.cli(&["upgrade", name])
            }
            Action::Uninstall { name } => {
                Catalog::package_identity(name)?;
                self.cli(&["uninstall", name])
            }
            Action::Doctor => {
                let mut output = self.capture(Path::new("/system/bin/uname"), &["-a"])?;
                output.push_str(&self.cli(&["--help"])?);
                output.push_str(&self.cli(&["tap", "list"])?);
                output.push_str("安装后端：设备 BMS（使用宿主的 BM 授权）\n");
                output.push_str(&self.cli(&["doctor"])?);
                Ok(output)
            }
            Action::TestZig => self.capture(Path::new("/data/service/hnp/bin/zig"), &["version"]),
            Action::RunVersion { command } => {
                if command.is_empty()
                    || matches!(command.as_str(), "." | "..")
                    || !command
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_.+-".contains(&c))
                {
                    return Err(ClientError("无效的命令名称".into()));
                }
                self.capture(
                    &Path::new("/data/service/hnp/bin").join(command),
                    &["--version"],
                )
            }
            Action::TestCompile => {
                let source = self.state.join("ocp-debug.c");
                fs::write(&source, b"#include <stdio.h>\nint main(void) { puts(\"OCP_UI_COMPILE_OK\"); return 0; }\n")?;
                let result = self
                    .command(Path::new("/data/service/hnp/bin/zig"))
                    .args([
                        "cc",
                        "ocp-debug.c",
                        "-target",
                        "aarch64-linux-ohos",
                        "-O2",
                        "-o",
                        "ocp-debug",
                    ])
                    .env("ZIG_GLOBAL_CACHE_DIR", self.state.join("zig-cache"))
                    .output()?;
                if !result.status.success() {
                    return Err(ClientError(
                        String::from_utf8_lossy(&result.stderr).into_owned(),
                    ));
                }
                Ok("C 编译通过：ocp/ocp-debug\n当前模拟器请在 HDC 调试目录运行产物。".into())
            }
            Action::TapAdd { name, url } => {
                Catalog::identifier(name)?;
                let mut output = self.cli(&["tap", "add", name, url.as_str()])?;
                output.push_str(&self.cli(&["update"])?);
                Ok(output)
            }
            Action::TapRemove { name } => {
                Catalog::identifier(name)?;
                self.cli(&["tap", "remove", name])
            }
        }
    }
}

struct Catalog;
#[derive(Deserialize)]
struct PublishedCatalog {
    schema_version: u32,
    tap: String,
    packages: Vec<PublishedPackage>,
}
#[derive(Deserialize)]
struct PublishedPackage {
    name: String,
    version: String,
    abi: String,
    bundle: String,
    hap_sha256: String,
    #[serde(default)]
    publisher: Publisher,
    #[serde(default)]
    upstream: ServiceUrl,
}
impl Catalog {
    fn provenance(
        state: &Path,
        index_path: &Path,
        index: &str,
        abi: &str,
        packages: &mut [Package],
    ) -> Result<(), ClientError> {
        let sources = match fs::read_to_string(index_path.with_file_name("sources.tsv")) {
            Ok(sources) => sources,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(error.into()),
        };
        let releases = index
            .lines()
            .filter_map(|line| {
                let row = line.split('\t').collect::<Vec<_>>();
                (row.len() >= 7 && row[2] == abi)
                    .then(|| ((row[0].to_owned(), row[1].to_owned()), (row[3], row[4])))
            })
            .collect::<BTreeMap<_, _>>();
        for source in sources.lines() {
            let fields = source.split('\t').collect::<Vec<_>>();
            if fields.len() != 3 {
                return Err(ClientError("来源记录字段不完整".into()));
            }
            Self::identifier(fields[0])?;
            Self::identifier(fields[2])?;
            let origin: ServiceUrl = fields[1].to_owned().try_into()?;
            for package in packages
                .iter_mut()
                .filter(|package| package.tap() == fields[0])
            {
                package.provenance.repository = origin.clone();
            }
            let path = state.join("cache/p").join(fields[2]).join("registry.json");
            let file = match fs::File::open(path) {
                Ok(file) => file,
                Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
                Err(error) => return Err(error.into()),
            };
            let mut bytes = Vec::new();
            file.take(2 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
            if bytes.len() > 2 * 1024 * 1024 {
                continue;
            }
            let Ok(catalog) = serde_json::from_slice::<PublishedCatalog>(&bytes) else {
                continue;
            };
            if catalog.schema_version != 2 || catalog.tap != fields[0] {
                continue;
            }
            let metadata = catalog
                .packages
                .iter()
                .filter(|entry| entry.abi == abi)
                .map(|entry| ((entry.name.clone(), entry.version.clone()), entry))
                .collect::<BTreeMap<_, _>>();
            for package in packages
                .iter_mut()
                .filter(|package| package.tap() == fields[0])
            {
                let version = package.installed.as_ref().unwrap_or(&package.latest);
                let entry = metadata.get(&(package.tool_name().to_owned(), version.clone()));
                let Some(entry) = entry else { continue };
                let matches_index = releases
                    .get(&(package.name.clone(), entry.version.clone()))
                    .is_some_and(|(bundle, sha)| {
                        *bundle == entry.bundle && *sha == entry.hap_sha256
                    });
                if !matches_index
                    || entry.publisher.name.chars().count() > 128
                    || entry.publisher.name.chars().any(char::is_control)
                {
                    continue;
                }
                package.provenance.publisher = entry.publisher.clone();
                package.provenance.upstream = entry.upstream.clone();
            }
        }
        Ok(())
    }
    fn package_identity(value: &str) -> Result<(), ClientError> {
        if let Some((tap, tool)) = value.split_once('/') {
            Self::identifier(tap)?;
            Self::identifier(tool)
        } else {
            Self::identifier(value)
        }
    }
    fn identifier(value: &str) -> Result<(), ClientError> {
        if value.is_empty()
            || matches!(value, "." | "..")
            || !value
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
        {
            return Err(ClientError("无效的工具名称或版本".into()));
        }
        Ok(())
    }
    fn parse(index: &str, abi: &str) -> Result<Vec<Package>, ClientError> {
        let mut packages = BTreeMap::<String, Package>::new();
        for row in index.lines().filter(|row| !row.is_empty()) {
            let fields = row.split('\t').collect::<Vec<_>>();
            if !(7..=8).contains(&fields.len()) {
                return Err(ClientError("仓库索引字段不完整".into()));
            }
            if fields[2] != abi {
                continue;
            }
            Self::package_identity(fields[0])?;
            Self::identifier(fields[1])?;
            let package = packages.entry(fields[0].into()).or_insert_with(|| Package {
                name: fields[0].into(),
                latest: String::new(),
                versions: Vec::new(),
                installed: None,
                provenance: Provenance::default(),
                commands: fields.get(7).map_or(Vec::new(), |value| {
                    value.split(',').map(str::to_owned).collect()
                }),
            });
            if !package.versions.iter().any(|version| version == fields[1]) {
                package.versions.push(fields[1].into());
            }
            if fields[6] == "1" {
                if !package.latest.is_empty() {
                    return Err(ClientError("仓库声明了多个最新版本".into()));
                }
                package.latest = fields[1].into();
            }
        }
        Ok(packages.into_values().collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct ProvenanceFixture {
        state: PathBuf,
    }
    impl ProvenanceFixture {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let id = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let state =
                std::env::temp_dir().join(format!("ocp-provenance-{}-{id}", std::process::id()));
            fs::create_dir_all(state.join("cache/p/hash")).unwrap();
            fs::write(
                state.join("sources.tsv"),
                "core\thttps://packages.example/core/index.tar.gz\thash\n",
            )
            .unwrap();
            Self { state }
        }
        fn write(&self, metadata: serde_json::Value) {
            fs::write(
                self.state.join("cache/p/hash/registry.json"),
                serde_json::to_vec(&metadata).unwrap(),
            )
            .unwrap();
        }
        fn enrich(&self, index: &str, packages: &mut [Package]) {
            Catalog::provenance(
                &self.state,
                &self.state.join("index.tsv"),
                index,
                "arm64-v8a",
                packages,
            )
            .unwrap();
        }
    }
    impl Drop for ProvenanceFixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.state);
        }
    }
    #[test]
    fn provenance_uses_installed_version_and_active_source() {
        let fixture = ProvenanceFixture::new();
        fixture.write(serde_json::json!({"schema_version":2,"tap":"core","packages":[
            {"name":"zig","version":"0.16.0","abi":"arm64-v8a","bundle":"b","hap_sha256":"old","publisher":{"name":"Previous Publisher"},"upstream":"https://github.com/old/project/releases/tag/0.16.0"},
            {"name":"zig","version":"0.17.0","abi":"arm64-v8a","bundle":"b","hap_sha256":"new","publisher":{"name":"RicherFu"},"upstream":"https://github.com/openharmony-zig/zig-patch/releases/tag/0.17.0"}
        ]}));
        let index="core/zig\t0.16.0\tarm64-v8a\tb\told\tu\t0\tzig\ncore/zig\t0.17.0\tarm64-v8a\tb\tnew\tu\t1\tzig";
        let mut packages = Catalog::parse(index, "arm64-v8a").unwrap();
        packages[0].installed = Some("0.16.0".into());
        fixture.enrich(index, &mut packages);
        assert_eq!(packages[0].provenance.publisher.name, "Previous Publisher");
        assert_eq!(
            packages[0].provenance.repository.as_str(),
            "https://packages.example/core/index.tar.gz"
        );
        packages[0].installed = None;
        fixture.enrich(index, &mut packages);
        assert_eq!(packages[0].provenance.publisher.name, "RicherFu");
        assert_eq!(packages[0].upstream_project(), "openharmony-zig/zig-patch");
    }
    #[test]
    fn provenance_does_not_accept_other_namespace_or_payload() {
        let fixture = ProvenanceFixture::new();
        let index = "core/zig\t0.17.0\tarm64-v8a\tb\texpected\tu\t1\tzig";
        for (tap, sha, publisher) in [
            ("other", "expected", "Impersonator"),
            ("core", "wrong", "Impersonator"),
            ("core", "expected", "Spoof\nPublisher"),
        ] {
            fixture.write(serde_json::json!({"schema_version":2,"tap":tap,"packages":[{"name":"zig","version":"0.17.0","abi":"arm64-v8a","bundle":"b","hap_sha256":sha,"publisher":{"name":publisher}}]}));
            let mut packages = Catalog::parse(index, "arm64-v8a").unwrap();
            fixture.enrich(index, &mut packages);
            assert!(packages[0].provenance.publisher.name.is_empty());
        }
        fs::remove_file(fixture.state.join("cache/p/hash/registry.json")).unwrap();
        let mut packages = Catalog::parse(index, "arm64-v8a").unwrap();
        fixture.enrich(index, &mut packages);
        assert!(packages[0].provenance.publisher.name.is_empty());
    }
    #[test]
    fn catalog_selects_architecture_and_preserves_latest() {
        let packages = Catalog::parse("zig\t0.16.0\tarm64-v8a\tb\ts\tu\t0\nzig\t0.17.0\tarm64-v8a\tb\ts\tu\t1\nzig\t0.15.0\tx86_64\tb\ts\tu\t1", "arm64-v8a").unwrap();
        assert_eq!(packages[0].latest, "0.17.0");
        assert_eq!(packages[0].versions, ["0.16.0", "0.17.0"]);
    }
    #[test]
    fn rejects_paths_and_ambiguous_catalogs() {
        for name in ["../zig", "..", "zig\n", "zig;id"] {
            assert!(Catalog::identifier(name).is_err());
        }
        assert!(Catalog::parse(
            "zig\t1\tarm64-v8a\tb\ts\tu\t1\nzig\t2\tarm64-v8a\tb\ts\tu\t1",
            "arm64-v8a"
        )
        .is_err());
        assert!(Catalog::parse("broken", "arm64-v8a").is_err());
    }
    #[test]
    fn accepts_network_urls_and_rejects_control_characters() {
        assert!(ServiceUrl::try_from("https://example.org/index.tar.gz".to_owned()).is_ok());
        assert!(ServiceUrl::try_from("file:///tmp/index".to_owned()).is_err());
        assert!(ServiceUrl::try_from("https://example.org/\nindex".to_owned()).is_err());
    }

    #[test]
    fn protocol_two_keeps_same_named_tools_in_separate_taps() {
        let packages=Catalog::parse("core/zig\t0.17.0\tarm64-v8a\tb\ts\tu\t1\tzig\ncommunity/zig\t1.0.0\tarm64-v8a\tb\ts\tu\t1\tzig-custom,clang++", "arm64-v8a").unwrap();
        assert_eq!(packages.len(), 2);
        assert_eq!(packages[0].name, "community/zig");
        assert_eq!(packages[0].commands, ["zig-custom", "clang++"]);
        assert_eq!(packages[1].tap(), "core");
        assert!(Catalog::package_identity("core/../../zig").is_err());
    }

    #[test]
    fn service_urls_round_trip_through_persisted_settings() {
        let settings = Settings {
            repository: "https://example.org/core/index.tar.gz"
                .to_owned()
                .try_into()
                .unwrap(),
        };
        let restored: Settings =
            serde_json::from_slice(&serde_json::to_vec(&settings).unwrap()).unwrap();
        assert_eq!(restored.repository, settings.repository);
        assert!(serde_json::from_str::<Settings>(r#"{"repository":"file:///tmp/x"}"#).is_err());
    }
}
