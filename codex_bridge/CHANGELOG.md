# Changelog

## 2026.7.13.1

- Preserve streaming Ollama tool calls so Home Assistant can request device
  states and execute Assist tools.
- Decode complete tool arguments into native Ollama objects for both streaming
  and non-streaming replies. Reject malformed or incomplete tool calls.
- Retain the pinned GPTMock release and existing request-option behaviour.

Validation: adapter regression tests cover fragmented parallel calls, tool-only
replies, normal text, invalid arguments, truncated streams, and upstream errors.
An app rebuild is required. Live Home Assistant tool execution remains a
post-deployment check.

## 2026.7.13

- Add the initial experimental Home Assistant add-on scaffold.
- Pin the unmodified upstream GPTMock 2026.7.13 source commit and archive checksum.
- Build GPTMock locally from that verified GitHub source instead of using its
  potentially outdated upstream Docker image.
- Add an ingress-only device authorization flow using the official Codex CLI.
- Print the device authorization URL and one-time code once to the add-on log
  as an ingress fallback.
- Add persistent credential storage and a bearer-token API proxy.
