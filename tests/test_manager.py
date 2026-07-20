from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient


MANAGER_PATH = (
    Path(__file__).parents[1]
    / "codex_bridge"
    / "rootfs"
    / "opt"
    / "codex-bridge"
    / "manager.py"
)
SPEC = importlib.util.spec_from_file_location("codex_bridge_manager", MANAGER_PATH)
assert SPEC is not None and SPEC.loader is not None
manager_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager_module)


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        data_directory = Path(self.temporary_directory.name)
        manager_module.DATA_DIR = data_directory
        manager_module.AUTH_FILE = data_directory / "auth.json"
        manager_module.API_TOKEN_FILE = data_directory / "api_token"
        manager_module.OPTIONS_FILE = data_directory / "options.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_api_token_is_persistent_and_private(self) -> None:
        first_token = manager_module.load_or_create_api_token()
        second_token = manager_module.load_or_create_api_token()

        self.assertEqual(first_token, second_token)
        self.assertGreaterEqual(len(first_token), 40)
        self.assertEqual(os.stat(manager_module.API_TOKEN_FILE).st_mode & 0o777, 0o600)

    def test_options_are_filtered_and_merged_with_defaults(self) -> None:
        manager_module.OPTIONS_FILE.write_text(
            json.dumps({"reasoning_effort": "high", "unexpected": "ignored"}),
            encoding="utf-8",
        )

        options = manager_module.load_options()

        self.assertEqual(options["reasoning_effort"], "high")
        self.assertEqual(options["reasoning_summary"], "auto")
        self.assertNotIn("unexpected", options)

    def test_codex_uses_the_addon_data_directory(self) -> None:
        bridge_manager = manager_module.BridgeManager()

        environment = bridge_manager._codex_environment()

        self.assertEqual(environment["CODEX_HOME"], str(manager_module.DATA_DIR))

    def test_device_login_output_is_parsed_without_terminal_codes(self) -> None:
        class Output:
            def __init__(self) -> None:
                self.lines = iter(
                    [
                        b"\x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n",
                        b"\x1b[94mABCD-EFG12\x1b[0m\n",
                    ]
                )

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.lines)
                except StopIteration as error:
                    raise StopAsyncIteration from error

        class Process:
            stdout = Output()

            async def wait(self) -> int:
                return 1

        bridge_manager = manager_module.BridgeManager()

        captured_output = StringIO()
        with redirect_stdout(captured_output):
            asyncio.run(bridge_manager._capture_login_output(Process()))

        self.assertEqual(
            bridge_manager.device_url, "https://auth.openai.com/codex/device"
        )
        self.assertEqual(bridge_manager.device_code, "ABCD-EFG12")
        self.assertNotIn("\x1b", "\n".join(bridge_manager.login_messages))
        self.assertIn(
            "[manager] URL: https://auth.openai.com/codex/device",
            captured_output.getvalue(),
        )
        self.assertIn("[manager] Code: ABCD-EFG12", captured_output.getvalue())
        self.assertEqual(captured_output.getvalue().count("Device authorization started"), 1)


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        manager_module.manager.api_token = "test-secret"
        manager_module.manager.backend_process = None

    def test_setup_health_is_available(self) -> None:
        with TestClient(manager_module.admin_app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_setup_page_uses_internal_addon_hostname(self) -> None:
        with TestClient(manager_module.admin_app) as client:
            response = client.get("/")

        self.assertIn("http://2f0fd6f2-codex-bridge:8000", response.text)
        self.assertNotIn("HOME_ASSISTANT_IP", response.text)

    def test_proxy_rejects_missing_api_token(self) -> None:
        with TestClient(manager_module.proxy_app) as client:
            response = client.get("/api/tags")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_proxy_reports_backend_not_ready_after_authentication(self) -> None:
        with TestClient(manager_module.proxy_app) as client:
            response = client.get(
                "/api/tags",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 503)

    def test_proxy_forwards_authorized_requests(self) -> None:
        class UpstreamStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"models":[{"model":"gpt-test"}]}'

        def upstream(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/tags")
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=UpstreamStream(),
            )

        manager_module.manager.backend_process = SimpleNamespace(returncode=None)
        manager_module.manager.proxy_client = httpx.AsyncClient(
            transport=httpx.MockTransport(upstream)
        )
        try:
            with TestClient(manager_module.proxy_app) as client:
                response = client.get(
                    "/api/tags",
                    headers={"Authorization": "Bearer test-secret"},
                )
        finally:
            asyncio.run(manager_module.manager.proxy_client.aclose())
            manager_module.manager.proxy_client = None

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"models": [{"model": "gpt-test"}]})


if __name__ == "__main__":
    unittest.main()
