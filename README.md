# Codex Bridge (Hassio Add-on)

<p align="center">
  <img src="codex_bridge/logo.png" alt="Codex Bridge logo" width="250">
</p>

This repository packages [GPTMock](https://github.com/rapidrabbit76/GPTMock)
as an installable Home Assistant add-on. The build installs a checksum-verified upstream repository commit
and adds a small management layer for Home Assistant ingress, OAuth setup,
persistent credentials, and API authentication.

Version `2026.7.13.1` applies a narrow Ollama response-adapter backport to
that pinned source. It preserves streamed tool calls for Home Assistant and
normalises tool arguments to Ollama objects; other upstream behaviour is unchanged.

The OAuth setup uses the official Codex CLI's device authorization flow. The
user opens one URL and enters a short-lived code; no localhost callback needs
to be copied into Home Assistant.

> [!WARNING]
> This project is experimental and is not affiliated with or supported by
> OpenAI or Home Assistant. ChatGPT subscriptions and the OpenAI API are
> separate products. Review the applicable OpenAI terms before using this
> project.

## Installation

The add-on is still under development. Once these changes are published, add
this repository URL to the Home Assistant add-on store and install **Codex
Bridge (Hassio Add-on)**. Home Assistant builds the add-on from its Dockerfile.

See [the add-on documentation](codex_bridge/DOCS.md) for the planned setup
flow and current limitations.

## Build strategy

The add-on is intentionally built locally by Home Assistant Supervisor. Its
configuration does not contain an `image` entry. During the build, the
Dockerfile downloads a pinned GPTMock commit from GitHub, verifies the archive
checksum, and installs its locked dependencies. The upstream GPTMock Docker
Hub image is not used because it can lag behind the maintained source
repository.

This approach makes the first installation slower than pulling a pre-built
image, but ensures that the add-on uses the explicitly reviewed source commit.

## Versioning

The add-on's base version matches the embedded GPTMock release. The current
upstream version is [2026.7.13](https://github.com/rapidrabbit76/GPTMock/releases/tag/2026.7.13).
If the Home Assistant wrapper needs a release without a new GPTMock version,
it will use a fourth numeric component such as `2026.7.13.1` so Home Assistant
recognizes it as a newer version.

## Development

The upstream GPTMock commit and archive checksum are pinned in
[`codex_bridge/Dockerfile`](codex_bridge/Dockerfile). Update it deliberately
and validate OAuth, OpenAI-compatible endpoints, Ollama chat streaming, and
tool calls before releasing a new add-on version.

## License

The add-on wrapper is licensed under the MIT License. GPTMock is an independent
MIT-licensed project; its license notice is included in
[`codex_bridge/THIRD_PARTY_NOTICES.md`](codex_bridge/THIRD_PARTY_NOTICES.md).
