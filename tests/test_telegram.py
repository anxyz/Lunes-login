import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import app


PNG = b"\x89PNG\r\n\x1a\nscreenshot-test-data"


def response(ok=True, status=200, description=""):
    value = MagicMock(status_code=status)
    value.json.return_value = {"ok": ok, "description": description}
    return value


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(patch.dict(os.environ, {"SEND_TG": "true"}))
        self.enterContext(patch.multiple(
            app, TG_BOT_TOKEN="12345:test-token", TG_CHAT_ID="67890",
            EMAIL="tester@example.invalid", PASSWORD="test-password"))
        self.post = self.enterContext(patch.object(app.requests, "post"))
        self.post.return_value = response()
        self.capture = self.enterContext(patch.object(
            app, "capture_notification_screenshot", return_value=PNG))
        self.browser = object()

    def test_success_sends_photo_with_result_caption(self):
        self.assertTrue(app.send_tg_message("✅", "续期成功", "服务器: Test", sb=self.browser))
        self.capture.assert_called_once_with(self.browser)
        self.post.assert_called_once()
        call = self.post.call_args
        self.assertTrue(call.args[0].endswith("/sendPhoto"))
        self.assertEqual(call.kwargs["files"]["photo"], ("lunes-status.png", PNG, "image/png"))
        self.assertEqual(call.kwargs["data"]["chat_id"], app.TG_CHAT_ID)
        self.assertIn("续期成功", call.kwargs["data"]["caption"])
        self.assertIn("服务器: Test", call.kwargs["data"]["caption"])
        self.assertNotIn(app.EMAIL, call.kwargs["data"]["caption"])

    def test_failure_sends_photo_with_failure_caption(self):
        self.assertTrue(app.send_tg_message("❌", "登录失败", "验证码未通过", sb=self.browser))
        caption = self.post.call_args.kwargs["data"]["caption"]
        self.assertIn("登录失败", caption)
        self.assertIn("验证码未通过", caption)

    def test_rejected_photo_falls_back_to_text(self):
        self.post.side_effect = [response(False, 400, "Invalid photo"), response()]
        self.assertTrue(app.send_tg_message("✅", "续期成功", sb=self.browser))
        self.assertEqual(self.post.call_count, 2)
        self.assertTrue(self.post.call_args_list[0].args[0].endswith("/sendPhoto"))
        self.assertTrue(self.post.call_args_list[1].args[0].endswith("/sendMessage"))
        self.assertIn("续期成功", self.post.call_args.kwargs["json"]["text"])

    def test_capture_failure_still_sends_text(self):
        self.capture.return_value = None
        self.assertTrue(app.send_tg_message("❌", "登录失败", sb=self.browser))
        self.post.assert_called_once()
        self.assertTrue(self.post.call_args.args[0].endswith("/sendMessage"))

    def test_without_browser_sends_text_only(self):
        self.assertTrue(app.send_tg_message("❌", "启动失败"))
        self.capture.assert_not_called()
        self.assertTrue(self.post.call_args.args[0].endswith("/sendMessage"))

    def test_disabled_notifications_do_not_capture_or_send(self):
        with patch.dict(os.environ, {"SEND_TG": "false"}):
            self.assertFalse(app.send_tg_message("✅", "续期成功", sb=self.browser))
        self.capture.assert_not_called()
        self.post.assert_not_called()

    def test_missing_config_does_not_capture_or_send(self):
        with patch.object(app, "TG_BOT_TOKEN", ""):
            self.assertFalse(app.send_tg_message("✅", "续期成功", sb=self.browser))
        self.capture.assert_not_called()
        self.post.assert_not_called()

    def test_network_error_falls_back_without_logging_bot_token(self):
        self.post.side_effect = [
            requests.ConnectionError(f"Failed https://api.telegram.org/bot{app.TG_BOT_TOKEN}/sendPhoto"),
            response(),
        ]
        self.assertTrue(app.send_tg_message("✅", "续期成功", sb=self.browser))
        self.assertEqual(self.post.call_count, 2)
        self.assertNotIn(app.TG_BOT_TOKEN, self.output.getvalue())

    def test_non_json_api_failure_is_reported(self):
        self.post.return_value = response(status=502)
        self.post.return_value.json.side_effect = ValueError("not JSON")
        self.assertFalse(app.send_tg_message("❌", "登录失败"))
        self.assertIn("HTTP 502", self.output.getvalue())

    def test_http_success_with_api_failure_is_not_treated_as_sent(self):
        self.post.return_value = response(False, 200, "Rejected")
        self.assertFalse(app.send_tg_message("❌", "登录失败"))

    def test_long_caption_and_text_fit_telegram_limits(self):
        extra = "🖼️" * 3000
        self.assertTrue(app.send_tg_message("✅", "续期成功", extra, sb=self.browser))
        caption = self.post.call_args.kwargs["data"]["caption"]
        self.assertLessEqual(len(caption.encode("utf-16-le")), 1024 * 2)
        self.assertTrue(caption.endswith("…"))
        self.assertTrue(app.send_tg_message("✅", "续期成功", extra))
        text = self.post.call_args.kwargs["json"]["text"]
        self.assertLessEqual(len(text.encode("utf-16-le")), 4096 * 2)


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.execute_js = self.enterContext(patch.object(app, "execute_js", return_value=True))
        self.browser = MagicMock()

    def test_capture_returns_bytes_and_removes_temporary_file(self):
        paths = []

        def save(name, folder):
            path = Path(folder, name)
            paths.append(path)
            path.write_bytes(PNG)

        self.browser.save_screenshot.side_effect = save
        self.assertEqual(app.capture_notification_screenshot(self.browser), PNG)
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].parent.exists())
        self.assertEqual(self.execute_js.call_count, 2)

    def test_mask_failure_does_not_capture_unmasked_fields(self):
        self.execute_js.return_value = False
        self.assertIsNone(app.capture_notification_screenshot(self.browser))
        self.browser.save_screenshot.assert_not_called()

    def test_capture_error_still_restores_page(self):
        self.browser.save_screenshot.side_effect = RuntimeError("Browser closed")
        self.assertIsNone(app.capture_notification_screenshot(self.browser))
        self.assertEqual(self.execute_js.call_count, 2)


if __name__ == "__main__":
    unittest.main()
