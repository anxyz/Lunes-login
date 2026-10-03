import contextlib
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from scripts import notify_failure

ROOT = Path(__file__).resolve().parents[1]


class DownloadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/release":
            self.send_response(302)
            self.send_header("Location", "/asset")
            self.end_headers()
        elif self.path == "/asset":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"release-archive-bytes")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class ProxyInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def download(self, path):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder, "installer.sh")
            url = f"http://127.0.0.1:{self.server.server_port}{path}"
            # Match the upstream command, including expansion of COMMAND.
            script.write_text(f'#!/bin/bash\nCOMMAND="curl -so"\n$COMMAND asset "{url}"\n')
            environment = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/setup_proxy.sh"), str(script)],
                cwd=folder,
                env=environment,
                capture_output=True,
                timeout=10,
            )
            asset = Path(folder, "asset")
            return result.returncode, asset.read_bytes() if asset.exists() else b""

    def test_github_style_redirect_downloads_actual_archive(self):
        code, content = self.download("/release")
        self.assertEqual(code, 0)
        self.assertEqual(content, b"release-archive-bytes")

    def test_http_error_is_reported_as_failure(self):
        code, content = self.download("/missing")
        self.assertNotEqual(code, 0)
        self.assertEqual(content, b"")


class FallbackNotificationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "TG_BOT_TOKEN": "test-token",
                    "TG_CHAT_ID": "test-chat",
                    "PROXY_OUTCOME": "failure",
                    "RENEW_OUTCOME": "skipped",
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_RUN_NUMBER": "7",
                    "GITHUB_RUN_ATTEMPT": "2",
                },
                clear=True,
            )
        )
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.build = self.enterContext(patch.object(notify_failure, "build_opener"))
        self.opener = self.build.return_value
        self.opener.open.return_value.__enter__.side_effect = lambda: io.BytesIO(b'{"ok":true}')
        self.sleep = self.enterContext(patch.object(notify_failure.time, "sleep"))

    def test_early_failure_reports_stage_and_run_without_proxy(self):
        self.assertEqual(notify_failure.main(), 0)
        self.opener.open.assert_called_once()
        self.assertEqual(self.build.call_args.args[0].proxies, {})
        data = json.loads(self.opener.open.call_args.args[0].data)
        self.assertEqual(data["chat_id"], "test-chat")
        self.assertIn("代理初始化", data["text"])
        self.assertIn("续期步骤尚未执行", data["text"])
        self.assertIn("运行 #7 · 第 2 次尝试", data["text"])
        self.assertIn("owner/repo/actions/runs/123", data["text"])
        self.assertNotIn("test-token", self.output.getvalue())

    def test_transient_connection_error_retries_without_printing_details(self):
        success = MagicMock()
        success.__enter__.return_value = io.BytesIO(b'{"ok":true}')
        self.opener.open.side_effect = [URLError("private-node test-token"), success]
        self.assertEqual(notify_failure.main(), 0)
        self.assertEqual(self.opener.open.call_count, 2)
        self.assertNotIn("test-token", self.output.getvalue())

    def test_permanent_api_error_is_not_retried(self):
        self.opener.open.side_effect = HTTPError("private-url", 401, "test-token", {}, None)
        self.assertEqual(notify_failure.main(), 1)
        self.opener.open.assert_called_once()
        self.assertNotIn("test-token", self.output.getvalue())

    def test_api_failure_with_http_success_is_failure(self):
        self.opener.open.return_value.__enter__.side_effect = lambda: io.BytesIO(b'{"ok":false}')
        self.assertEqual(notify_failure.main(), 1)

    def test_retry_is_bounded(self):
        self.opener.open.side_effect = URLError("private-url")
        self.assertEqual(notify_failure.main(), 1)
        self.assertEqual(self.opener.open.call_count, 3)

    def test_manual_notifications_can_be_disabled(self):
        with patch.dict(os.environ, {"SEND_TG": "false"}):
            self.assertEqual(notify_failure.main(), 0)
        self.build.assert_not_called()

    def test_no_pip_dependencies_needed(self):
        result = subprocess.run(
            ["python3", "-S", str(ROOT / "scripts/notify_failure.py")],
            env={**os.environ, "SEND_TG": "false"},
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
