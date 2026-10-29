# 2026.7.13.1

- Preserve streaming Ollama tool calls so Home Assistant can request device
  states and execute Assist tools.
- Decode complete tool arguments into native Ollama objects for both streaming
  and non-streaming replies. Reject malformed or incomplete tool calls.
- Retain the pinned GPTMock release and existing request-option behaviour.

Validation: adapter regression tests cover fragmented parallel calls, tool-only
replies, normal text, invalid arguments, truncated streams, and upstream errors.
An app rebuild is required. Live Home Assistant tool execution remains a
post-deployment check.
