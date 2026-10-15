# OCP

[English](README.md) · [简体中文](README.zh-CN.md)

**OpenHarmony Command Package** — install, update, and manage command-line tools on OpenHarmony through a native app or a CLI.

## Features

- Install, upgrade, and uninstall tools from registered repositories.
- Manage tools in an Arkit app with a shadcn-style interface.
- See installed versions, package publishers, and upstream projects.
- Add community repositories without changing OCP itself.
- Use installed commands from a compatible terminal. Tool packages contain no UI and do not add desktop icons.

## Using OCP

Open the OCP app, add a repository in **Repositories**, then manage packages in **Tools** or **Installed**. The OCP desktop icon opens the management app.

For terminal use, register an index URL provided by a repository maintainer, then run:

```sh
ocp tap add core <repository-index-url>
ocp update
ocp install core/zig
zig version
ocp upgrade core/zig
ocp uninstall core/zig
```

[OCP Repository](https://github.com/harmony-contrib/ocp-repo) maintains the supported tool recipes, starting with Zig. A Git repository URL is different from the downloadable package index URL.

OCP is currently a development preview. Device validation uses the DevEco ARM64 2in1 emulator; setup and platform requirements are documented in the guides below.

## Documentation and contribution

- [Build and test OCP](example/README.md)
- [App interface and interaction](docs/ui.md)
- [Repository registration and storage](docs/repositories.md)
- [Contribute tool packages](https://github.com/harmony-contrib/ocp-repo/blob/main/CONTRIBUTING.md)
- [Create a community repository](docs/contributing-taps.md)
- [Device installation requirements](docs/device-backend.md)
- [HarmonyOS emulator native execution skill](skills/harmonyos-emulator-native-exec/SKILL.md)

Tool recipes and releases belong in [ocp-repo](https://github.com/harmony-contrib/ocp-repo). Changes to the app, CLI, packaging toolkit, and repository protocol belong here.

## License

OCP is licensed under [MIT](LICENSE). Third-party components and tools retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
