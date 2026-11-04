# Third-party notices

[English](THIRD_PARTY_NOTICES.md) · [简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

OCP's [MIT license](LICENSE) covers the original code and documentation in this repository. Third-party components and tools retain their own licenses and copyright notices.

The bootstrap runtime uses an adapted Zig Maker, nlohmann/json, and OpenHarmony platform interfaces. Its build scripts copy the corresponding upstream notices into the runtime as `LICENSE-ZIG`, `LICENSE-JSON`, `LICENSE-platform-ipc`, and `LICENSE-platform-c-utils`.

The management app uses Arkit and Rust dependencies declared in [ui/Cargo.toml](ui/Cargo.toml) and pinned in [ui/Cargo.lock](ui/Cargo.lock). Consult each dependency's source distribution for its license and any additional notices. The generated runtime notices are not a complete inventory of the app's dependencies.

Downloadable tool recipes and their upstream license information are maintained separately in [ocp-repo](https://github.com/openharmony-command-package/ocp-repo). Redistributing a tool or an OCP build must preserve the notices required by the components actually included; OCP's MIT license does not relicense those components.
