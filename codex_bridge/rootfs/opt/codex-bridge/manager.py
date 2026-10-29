from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import signal
from collections import deque
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

DATA_DIR = Path(os.environ.get("CODEX_BRIDGE_DATA_DIR", "/data"))
AUTH_FILE = DATA_DIR / "auth.json"
API_TOKEN_FILE = DATA_DIR / "api_token"
OPTIONS_FILE = DATA_DIR / "options.json"
BACKEND_URL = "http://127.0.0.1:8001"
GPTMOCK_EXECUTABLE = os.environ.get("GPTMOCK_EXECUTABLE", "/app/.venv/bin/gptmock")
CODEX_EXECUTABLE = os.environ.get("CODEX_EXECUTABLE", "/usr/local/bin/codex")
DEVICE_URL_PATTERN = re.compile(r"https://auth\.openai\.com/codex/device")
DEVICE_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4,5})+\b")
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")

DEFAULT_OPTIONS: dict[str, Any] = {
    "log_level": "info",
    "reasoning_effort": "medium",
    "reasoning_summary": "auto",
    "reasoning_compat": "standard",
    "expose_reasoning_models": False,
    "enable_web_search": False,
}


def load_options() -> dict[str, Any]:
    options = dict(DEFAULT_OPTIONS)
    try:
        loaded = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return options
    if isinstance(loaded, dict):
        options.update({key: loaded[key] for key in DEFAULT_OPTIONS if key in loaded})
    return options


def load_or_create_api_token() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        token = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            API_TOKEN_FILE.chmod(0o600)
            return token
    except FileNotFoundError:
        pass

    token = secrets.token_urlsafe(36)
    descriptor = os.open(API_TOKEN_FILE, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
        token_file.write(token)
        token_file.write("\n")
    API_TOKEN_FILE.chmod(0o600)
    return token


class BridgeManager:
    def __init__(self) -> None:
        self.api_token = ""
        self.device_url: str | None = None
        self.device_code: str | None = None
        self.device_login_logged = False
        self.login_process: asyncio.subprocess.Process | None = None
        self.backend_process: asyncio.subprocess.Process | None = None
        self.login_messages: deque[str] = deque(maxlen=20)
        self.login_error: str | None = None
        self.lock = asyncio.Lock()
        self.proxy_client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self.api_token = load_or_create_api_token()
        self.proxy_client = httpx.AsyncClient(timeout=None)
        if AUTH_FILE.is_file():
            await self.start_backend()

    async def shutdown(self) -> None:
        for process in (self.login_process, self.backend_process):
            if process is not None and process.returncode is None:
                process.terminate()
        for process in (self.login_process, self.backend_process):
            if process is None or process.returncode is not None:
                continue
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self.proxy_client is not None:
            await self.proxy_client.aclose()

    def _gptmock_environment(self) -> dict[str, str]:
        options = load_options()
        environment = dict(os.environ)
        environment.update(
            {
                "GPTMOCK_HOME": str(DATA_DIR),
                "GPTMOCK_HOST": "127.0.0.1",
                "GPTMOCK_PORT": "8001",
                "GPTMOCK_LOGIN_BIND": "127.0.0.1",
                "GPTMOCK_REASONING_EFFORT": str(options["reasoning_effort"]),
                "GPTMOCK_REASONING_SUMMARY": str(options["reasoning_summary"]),
                "GPTMOCK_REASONING_COMPAT": str(options["reasoning_compat"]),
                "GPTMOCK_EXPOSE_REASONING_MODELS": str(
                    bool(options["expose_reasoning_models"])
                ).lower(),
                "GPTMOCK_DEFAULT_WEB_SEARCH": str(bool(options["enable_web_search"])).lower(),
                # Browser clients are not part of the supported API path. Home
                # Assistant connects server-to-server and does not need CORS.
                "GPTMOCK_CORS_ORIGINS": "",
            }
        )
        return environment

    def _codex_environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["CODEX_HOME"] = str(DATA_DIR)
        return environment

    async def start_backend(self) -> None:
        async with self.lock:
            if self.backend_process is not None and self.backend_process.returncode is None:
                return
            if not AUTH_FILE.is_file():
                return
            self.backend_process = await asyncio.create_subprocess_exec(
                GPTMOCK_EXECUTABLE,
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
                env=self._gptmock_environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            asyncio.create_task(self._copy_backend_output(self.backend_process))

    async def _copy_backend_output(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode(errors="replace").rstrip()
            if line:
                print(f"[gptmock] {line}", flush=True)
        return_code = await process.wait()
        print(f"[manager] GPTMock exited with status {return_code}", flush=True)

    async def start_login(self) -> None:
        if AUTH_FILE.is_file():
            await self.start_backend()
            return
        async with self.lock:
            if self.login_process is not None and self.login_process.returncode is None:
                return

            self.device_url = None
            self.device_code = None
            self.device_login_logged = False
            self.login_error = None
            self.login_messages.clear()
            self.login_process = await asyncio.create_subprocess_exec(
                CODEX_EXECUTABLE,
                "login",
                "--device-auth",
                "--config",
                'cli_auth_credentials_store="file"',
                env=self._codex_environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            asyncio.create_task(self._capture_login_output(self.login_process))

    def _log_device_authorization(self) -> None:
        if self.device_login_logged or not self.device_url or not self.device_code:
            return
        print("[manager] Device authorization started.", flush=True)
        print(f"[manager] URL: {self.device_url}", flush=True)
        print(f"[manager] Code: {self.device_code}", flush=True)
        print(
            "[manager] The code is valid for 15 minutes. Do not share it.",
            flush=True,
        )
        self.device_login_logged = True

    async def _capture_login_output(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = ANSI_PATTERN.sub("", raw_line.decode(errors="replace")).rstrip()
            url_match = DEVICE_URL_PATTERN.search(line)
            if url_match:
                self.device_url = url_match.group(0)
            code_match = DEVICE_CODE_PATTERN.search(line)
            if code_match:
                self.device_code = code_match.group(0)
            self._log_device_authorization()
            if line:
                self.login_messages.append(line)

        return_code = await process.wait()
        if return_code == 0 and AUTH_FILE.is_file():
            self.login_messages.append("Sign-in successful.")
            self.device_url = None
            self.device_code = None
            await self.start_backend()
        else:
            self.login_error = f"Codex sign-in exited with status {return_code}."

    def status(self) -> dict[str, Any]:
        login_running = self.login_process is not None and self.login_process.returncode is None
        backend_running = self.backend_process is not None and self.backend_process.returncode is None
        return {
            "authenticated": AUTH_FILE.is_file(),
            "backend_running": backend_running,
            "login_running": login_running,
            "device_url": self.device_url,
            "device_code": self.device_code,
            "api_token": self.api_token,
            "messages": list(self.login_messages),
            "error": self.login_error,
        }


manager = BridgeManager()
admin_app = FastAPI(title="Codex Bridge (Hassio Add-on)", docs_url=None, redoc_url=None)
proxy_app = FastAPI(title="Codex Bridge (Hassio Add-on)", docs_url=None, redoc_url=None)


@admin_app.get("/", response_class=HTMLResponse)
async def admin_index() -> str:
    return ADMIN_HTML


@admin_app.get("/health")
async def admin_health() -> dict[str, str]:
    return {"status": "ok"}


@admin_app.get("/api/status")
async def admin_status() -> dict[str, Any]:
    return manager.status()


@admin_app.post("/api/login/start")
async def admin_login_start() -> JSONResponse:
    await manager.start_login()
    return JSONResponse(manager.status())


def _is_authorized(request: Request) -> bool:
    authorization = request.headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    return separator == " " and scheme.lower() == "bearer" and secrets.compare_digest(
        credential, manager.api_token
    )


@proxy_app.get("/health")
async def public_health() -> JSONResponse:
    status_code = 200 if manager.status()["backend_running"] else 503
    return JSONResponse(
        {"status": "ok" if status_code == 200 else "starting"},
        status_code=status_code,
    )


@proxy_app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_request(path: str, request: Request):
    if not _is_authorized(request):
        return JSONResponse(
            {"error": "Missing or invalid API token"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if manager.backend_process is None or manager.backend_process.returncode is not None:
        return JSONResponse({"error": "GPTMock is not ready"}, status_code=503)
    if manager.proxy_client is None:
        return JSONResponse({"error": "Proxy is not ready"}, status_code=503)

    excluded_request_headers = {"host", "content-length", "connection", "transfer-encoding"}
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_request_headers
    }
    body = await request.body()
    upstream_request = manager.proxy_client.build_request(
        request.method,
        f"{BACKEND_URL}/{path}",
        params=request.query_params,
        headers=headers,
        content=body,
    )
    try:
        upstream_response = await manager.proxy_client.send(upstream_request, stream=True)
    except httpx.RequestError as error:
        return JSONResponse({"error": f"GPTMock is unavailable: {error}"}, status_code=502)

    excluded_response_headers = {"content-length", "connection", "transfer-encoding"}
    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in excluded_response_headers
    }
    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream_response.aclose),
    )


async def serve() -> None:
    await manager.initialize()
    options = load_options()
    log_level = str(options["log_level"])
    admin_server = uvicorn.Server(
        uvicorn.Config(admin_app, host="0.0.0.0", port=8099, log_level=log_level)
    )
    proxy_server = uvicorn.Server(
        uvicorn.Config(proxy_app, host="0.0.0.0", port=8000, log_level=log_level)
    )
    admin_server.install_signal_handlers = lambda: None
    proxy_server.install_signal_handlers = lambda: None

    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        admin_server.should_exit = True
        proxy_server.should_exit = True

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, request_shutdown)

    try:
        await asyncio.gather(admin_server.serve(), proxy_server.serve())
    finally:
        await manager.shutdown()


ADMIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Codex Bridge (Hassio Add-on)</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --background: #212121;
      --surface: #292929;
      --surface-strong: #171717;
      --border: #383838;
      --text: #f2f2f2;
      --text-secondary: #b4b4b4;
      --accent: #2e73da;
      --accent-hover: #2868c7;
    }
    body { margin: 0; background: var(--background); color: var(--text); }
    main { max-width: 760px; margin: 0 auto; padding: 32px 20px; }
    h1, h2 { color: var(--text); }
    main > p, section > p { color: var(--text-secondary); }
    section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 16px 0; }
    button { box-sizing: border-box; border-radius: 7px; padding: 10px 12px; font: inherit; }
    button { border: 0; background: var(--accent); color: #fff; font-weight: 650; cursor: pointer; }
    button:hover:not(:disabled) { background: var(--accent-hover); }
    button:focus-visible, a:focus-visible { outline: 2px solid #8ab4f8; outline-offset: 3px; }
    button:disabled { opacity: .5; cursor: wait; }
    a { color: #70a7f7; }
    code { color: var(--text); overflow-wrap: anywhere; }
    .device-code { display: inline-block; padding: 10px 14px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-strong); font-size: 1.35rem; letter-spacing: .12em; user-select: all; }
    .ok { color: #6fd6a8; } .warn { color: var(--text-secondary); } .error { color: #ff8585; }
  </style>
</head>
<body><main>
  <h1>Codex Bridge (Hassio Add-on)</h1>
  <p>GPTMock runs behind this Home Assistant adapter with an Ollama tool-call compatibility backport.</p>
  <section>
    <h2>1. Sign in with ChatGPT</h2>
    <p id="auth-state">Loading status …</p>
    <button id="start-login" onclick="startLogin()">Generate device code</button>
    <div id="device-box" hidden>
      <p>Open the following link, sign in, and enter this one-time code:</p>
      <p><a id="device-link" target="_blank" rel="noopener"></a></p>
      <p><code id="device-code" class="device-code"></code></p>
      <p class="warn">The code expires after 15 minutes. Do not share it.</p>
    </div>
    <p id="error" class="error"></p>
  </section>
  <section>
    <h2>2. Connect Home Assistant</h2>
    <p>Ollama URL: <code>http://2f0fd6f2-codex-bridge:8000</code></p>
    <p>API key: <code id="api-token">loading …</code></p>
    <p>Enter the API key as the bearer token in the official Ollama integration.</p>
  </section>
</main>
<script>
async function call(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Unknown error');
  return data;
}
async function refresh() {
  try {
    const status = await call('api/status');
    document.getElementById('api-token').textContent = status.api_token;
    document.getElementById('auth-state').innerHTML = status.authenticated
      ? '<span class="ok">Signed in; GPTMock is ' + (status.backend_running ? 'running.' : 'starting …') + '</span>'
      : '<span class="warn">Not signed in yet.</span>';
    document.getElementById('start-login').disabled = status.authenticated || status.login_running;
    if (status.device_url && status.device_code && !status.authenticated) {
      const link = document.getElementById('device-link');
      link.href = status.device_url;
      link.textContent = status.device_url;
      document.getElementById('device-code').textContent = status.device_code;
      document.getElementById('device-box').hidden = false;
    } else {
      document.getElementById('device-box').hidden = true;
    }
    document.getElementById('error').textContent = status.error || '';
  } catch (error) {
    document.getElementById('error').textContent = error.message;
  }
}
async function startLogin() {
  document.getElementById('error').textContent = '';
  try { await call('api/login/start', {method: 'POST'}); await refresh(); }
  catch (error) { document.getElementById('error').textContent = error.message; }
}
refresh(); setInterval(refresh, 3000);
</script></body></html>"""


if __name__ == "__main__":
    asyncio.run(serve())
