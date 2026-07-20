# Changelog

## 2026.7.13

- Add the initial experimental Home Assistant add-on scaffold.
- Pin the unmodified upstream GPTMock 2026.7.13 source commit and archive checksum.
- Build GPTMock locally from that verified GitHub source instead of using its
  potentially outdated upstream Docker image.
- Add an ingress-only device authorization flow using the official Codex CLI.
- Print the device authorization URL and one-time code once to the add-on log
  as an ingress fallback.
- Add persistent credential storage and a bearer-token API proxy.
