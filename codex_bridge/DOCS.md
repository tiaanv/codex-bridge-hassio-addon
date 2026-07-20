# Codex Bridge (Hassio Add-on)

Codex Bridge (Hassio Add-on) installs an unmodified, checksum-verified GPTMock repository
commit into its Home Assistant container. A small external manager provides
the Home Assistant-specific setup and security boundary.

## First-time setup

1. Install and start the add-on.
   Home Assistant builds it locally from the pinned GPTMock GitHub source, so
   the first installation can take several minutes.
2. Open **Web UI** from the add-on page.
3. Select **Generate device code**.
4. Open the displayed OpenAI device authorization link.
5. Sign in, enter the one-time code shown in the add-on, and confirm access.
6. Return to the add-on and wait until the Web UI reports that GPTMock is
   running. No localhost callback or copied URL is required.

Device code authorization must be enabled for the OpenAI account. The code
expires after 15 minutes and must not be shared.

The authorization URL and one-time code are also written once to the add-on
log as a fallback when the ingress page cannot be opened. Home Assistant
administrators can view them on the add-on's **Log** tab.

The GPTMock credentials are stored in `/data/auth.json` and are included in
normal add-on backups. They are not stored in Home Assistant add-on options.

## Connect Home Assistant

1. Add the official **Ollama** integration in Home Assistant.
2. Use `http://2f0fd6f2-codex-bridge:8000` as its server URL.
3. Copy the API key displayed in the add-on's Web UI into the integration's
   API key field.
4. Select one of the models returned by GPTMock.

Home Assistant generates the internal DNS name from the repository identifier
and add-on slug. For this repository, `{REPO}_{SLUG}` becomes
`2f0fd6f2_codex_bridge`; underscores are replaced with hyphens when used as a
hostname. A local add-on checkout instead uses
`http://local-codex-bridge:8000`.

Port 8000 is available only on Home Assistant's internal add-on network and is
not published on the Home Assistant host. All endpoints except `/health`
require the generated bearer token.

## Current limitations

- This is an experimental, unofficial bridge. It is not supported by OpenAI,
  Home Assistant, or the GPTMock project.
- The add-on is built locally rather than pulled as a pre-built image. This is
  intentional because the upstream GPTMock Docker image can lag behind its
  maintained GitHub source.
- ChatGPT subscriptions and OpenAI API usage are separate products. Review the
  applicable OpenAI terms before use.
- Plain conversation is the first compatibility target. Home Assistant device
  control requires correct streaming Ollama tool calls. GPTMock 2026.7.13 does
  not currently forward these through its Ollama streaming adapter, so device
  control is not yet declared supported by this add-on.
- Reauthentication and API-token rotation do not yet have UI controls.

## Security

- The OAuth credential file and generated bridge API key are stored with mode
  `0600` under `/data`.
- Device authorization is performed by the pinned official OpenAI Codex CLI;
  GPTMock itself remains unchanged.
- GPTMock listens only on the container loopback interface. Network clients
  reach it through the bearer-token proxy.
- The bearer-token proxy is reachable from Home Assistant's internal add-on
  network, but its port is not published to the host or LAN.
- The setup UI is available only through Home Assistant ingress and is limited
  to Home Assistant administrators.
- The short-lived device code appears in the add-on log. Treat exported logs
  as sensitive while a login is active.
- Verbose GPTMock request/response logging is disabled by default.
