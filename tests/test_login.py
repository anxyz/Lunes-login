import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import app


class Clock:
    def __init__(self):
        self.now = 0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


class Browser:
    """模拟表单、验证码和提交后异步跳转，不访问真实账号。"""

    def __init__(self, clock, redirect_after=5, turnstile_at=None,
                 cloudflare=False):
        self.clock = clock
        self.redirect_after = redirect_after
        self.turnstile_at = turnstile_at
        self.cloudflare = cloudflare
        self.solved = False
        self.submitted_at = None
        self.captcha_clicks = 0
        self.values = {}
        self.screenshots = []
        self.driver = types.SimpleNamespace(
            is_cdp_mode_active=lambda: False, is_connected=lambda: True)

    def authenticated(self):
        return (self.submitted_at is not None
                and self.redirect_after is not None
                and self.clock.now - self.submitted_at >= self.redirect_after)

    def uc_open_with_reconnect(self, url, reconnect_time):
        pass

    def get_current_url(self):
        if self.authenticated():
            return "https://betadash.lunes.host/"
        return app.LOGIN_URL

    def get_title(self):
        if self.cloudflare:
            return "Just a moment..."
        if self.authenticated():
            return "Lunes Host | Account page"
        return "Lunes Host | Login"

    def is_element_visible(self, selector):
        if selector in (app.EMAIL_SELECTOR, app.PASSWORD_SELECTOR):
            return not self.cloudflare and not self.authenticated()
        if selector == "a.server-card":
            return self.authenticated()
        return False

    def is_element_present(self, selector):
        return self.cloudflare

    def find_elements(self, selector):
        return []

    def execute_script(self, script, *args):
        if args:
            selector, value = args
            self.values[selector] = value
            return True
        if script == app._EXISTS_JS:
            return (self.turnstile_at is not None
                    and self.clock.now >= self.turnstile_at)
        if script == app._SOLVED_JS:
            return self.solved
        return None

    def uc_gui_click_captcha(self):
        self.captcha_clicks += 1
        self.cloudflare = False
        self.solved = True

    def uc_click(self, selector, reconnect_time):
        if self.turnstile_at is not None and not self.solved:
            raise AssertionError("提交时验证码尚未通过")
        self.submitted_at = self.clock.now

    def get_text(self, selector):
        return f"Invalid credentials for {app.EMAIL}; password: {app.PASSWORD}"

    def save_screenshot(self, filename):
        self.screenshots.append(filename)


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.output = io.StringIO()
        for patcher in (
            patch.object(app.time, "sleep", self.clock.sleep),
            patch.object(app.time, "monotonic", self.clock.monotonic),
            patch.object(app, "EMAIL", "test@example.invalid"),
            patch.object(app, "PASSWORD", "password-for-tests"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_waits_for_delayed_account_redirect(self):
        browser = Browser(self.clock, redirect_after=5)
        self.assertTrue(app.login(browser, timeout=10))
        self.assertGreaterEqual(self.clock.now - browser.submitted_at, 5)
        self.assertEqual(browser.screenshots, [])

    def test_login_url_does_not_end_wait_early(self):
        browser = Browser(self.clock, redirect_after=None)
        self.assertFalse(app.login(browser, timeout=7))
        self.assertGreaterEqual(self.clock.now - browser.submitted_at, 7)
        self.assertIn("Invalid credentials", self.output.getvalue())
        self.assertNotIn(app.EMAIL, self.output.getvalue())
        self.assertNotIn(app.PASSWORD, self.output.getvalue())
        self.assertEqual(browser.screenshots, ["login_failed.png"])

    def test_waits_for_delayed_turnstile_before_submitting(self):
        browser = Browser(self.clock, turnstile_at=5)
        with patch.object(app, "_click_turnstile") as fallback:
            self.assertTrue(app.login(browser, timeout=10))
        self.assertGreaterEqual(browser.submitted_at, 5)
        self.assertGreater(browser.captcha_clicks, 0)
        self.assertTrue(browser.solved)
        fallback.assert_not_called()

    def test_handles_cloudflare_before_login_form(self):
        browser = Browser(self.clock, cloudflare=True)
        self.assertTrue(app.login(browser, timeout=10))
        self.assertGreater(browser.captcha_clicks, 0)

    def test_does_not_submit_unsolved_turnstile(self):
        browser = Browser(self.clock, turnstile_at=0)
        with patch.object(app, "handle_turnstile", return_value=False):
            self.assertFalse(app.login(browser))
        self.assertIsNone(browser.submitted_at)

    def test_missing_form_fails_without_submitting(self):
        browser = Browser(self.clock, cloudflare=True)
        with patch.object(app, "click_browser_captcha"):
            self.assertFalse(app.login(browser))
        self.assertIsNone(browser.submitted_at)


class AuthenticationTests(unittest.TestCase):
    def browser(self, url, title, visible=False):
        browser = MagicMock()
        browser.get_current_url.return_value = url
        browser.get_title.return_value = title
        browser.is_element_visible.return_value = visible
        return browser

    def test_login_route_is_not_success_even_with_stale_account_title(self):
        browser = self.browser(app.LOGIN_URL, "Lunes Host | Account page")
        self.assertFalse(app.is_authenticated(browser))

    def test_similar_domain_is_not_success(self):
        browser = self.browser("https://betadash.lunes.host.example/", "Account")
        self.assertFalse(app.is_authenticated(browser))

    def test_dashboard_title_is_case_insensitive(self):
        browser = self.browser("https://betadash.lunes.host/", "Lunes | DASHBOARD")
        self.assertTrue(app.is_authenticated(browser))

    def test_visible_login_form_prevents_success(self):
        browser = self.browser("https://betadash.lunes.host/", "Account", True)
        self.assertFalse(app.is_authenticated(browser))

    def test_password_is_passed_as_an_argument(self):
        browser = MagicMock()
        browser.execute_script.return_value = True
        password = 'quotes"\\\n`${not_javascript}`'
        app.js_fill_input(browser, app.PASSWORD_SELECTOR, password)
        script, selector, value = browser.execute_script.call_args.args
        self.assertNotIn(password, script)
        self.assertEqual(selector, app.PASSWORD_SELECTOR)
        self.assertEqual(value, password)

    def test_missing_field_is_an_error(self):
        browser = MagicMock()
        browser.execute_script.return_value = False
        with self.assertRaisesRegex(RuntimeError, "无法填写登录字段"):
            app.js_fill_input(browser, app.EMAIL_SELECTOR, "test@example.invalid")


@unittest.skipUnless(shutil.which("node"), "JavaScript 回归检查需要 Node.js")
class BrowserScriptTests(unittest.TestCase):
    def execute(self, script, input_value=None, cdp=False, args=()):
        # 使用 JavaScript 引擎分别复现 WebDriver 的函数体和 CDP 的表达式执行。
        harness = """
            const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
            const input = data.value === null ? null : {value: data.value};
            global.document = {
                querySelector: () => input,
                querySelectorAll: () => [{
                    src: 'https://challenges.cloudflare.com/turnstile',
                    getBoundingClientRect: () => ({x: 10, y: 20, width: 300, height: 60})
                }]
            };
            global.window = {screenX: 1, screenY: 2, outerHeight: 800, innerHeight: 700};
            const result = data.cdp ? eval(data.script) : new Function(data.script)(...data.args);
            process.stdout.write(JSON.stringify(result === undefined ? null : result));
        """

        def run_script(script, *script_args):
            result = subprocess.run(
                [shutil.which("node"), "-e", harness],
                input=json.dumps({"script": script, "value": input_value,
                                  "cdp": cdp, "args": script_args}),
                capture_output=True, text=True, check=True,
            )
            return json.loads(result.stdout)

        browser = types.SimpleNamespace(
            driver=types.SimpleNamespace(is_cdp_mode_active=lambda: cdp,
                                         is_connected=lambda: not cdp),
            execute_script=run_script,
        )
        return app.execute_js(browser, script, *args)

    def test_turnstile_detection_returns_boolean(self):
        for cdp in (False, True):
            with self.subTest(cdp=cdp):
                self.assertIs(self.execute(app._EXISTS_JS, "", cdp), True)
                self.assertIs(self.execute(app._EXISTS_JS, cdp=cdp), False)

    def test_turnstile_solution_returns_boolean(self):
        for cdp in (False, True):
            with self.subTest(cdp=cdp):
                self.assertIs(self.execute(app._SOLVED_JS, "a" * 30, cdp), True)
                self.assertIs(self.execute(app._SOLVED_JS, "", cdp), False)

    def test_turnstile_coordinates_reach_python(self):
        for cdp in (False, True):
            with self.subTest(cdp=cdp):
                self.assertEqual(self.execute(app._COORDS_JS, cdp=cdp), {"cx": 40, "cy": 50})

    def test_window_geometry_reaches_python(self):
        for cdp in (False, True):
            with self.subTest(cdp=cdp):
                self.assertEqual(self.execute(app._WININFO_JS, cdp=cdp),
                                 {"sx": 1, "sy": 2, "oh": 800, "ih": 700})

    def test_special_character_arguments_survive_both_browser_modes(self):
        password = 'quotes"\\\n`${not_javascript}`\u2028'
        for cdp in (False, True):
            with self.subTest(cdp=cdp):
                self.assertEqual(self.execute("return arguments[0]", cdp=cdp,
                                              args=(password,)), password)


class ResultTests(unittest.TestCase):
    def run_main(self, logged_in, visited, browser_error=None):
        browser = MagicMock()
        factory = MagicMock()
        factory.return_value.__enter__.return_value = browser
        factory.return_value.__exit__.return_value = bool(browser_error)
        module = types.SimpleNamespace(SB=factory)
        info = {"server_name": "Test", "server_id": "123", "error": "No server"}
        with (patch.dict(sys.modules, {"seleniumbase": module}),
              patch.object(app, "EMAIL", "test@example.invalid"),
              patch.object(app, "PASSWORD", "test-password"),
              patch.object(app, "login", return_value=logged_in,
                           side_effect=browser_error),
              patch.object(app, "visit_server", return_value=(visited, info)),
              patch.object(app, "send_tg_message") as notify,
              contextlib.redirect_stdout(io.StringIO())):
            result = app.main()
            notify.assert_called_once()
            self.assertIs(notify.call_args.kwargs["sb"], browser)
            self.notification = notify.call_args
            return result

    def test_login_failure_exits_with_failure(self):
        self.assertEqual(self.run_main(False, False), 1)

    def test_server_failure_exits_with_failure(self):
        self.assertEqual(self.run_main(True, False), 1)

    def test_success_exits_with_success(self):
        self.assertEqual(self.run_main(True, True), 0)

    def test_suppressed_browser_error_still_exits_with_failure(self):
        self.assertEqual(self.run_main(False, False, RuntimeError("Browser closed")), 1)
        self.assertEqual(self.notification.args[1], "续期异常")

    def test_missing_credentials_fail_before_starting_browser(self):
        with (patch.object(app, "EMAIL", ""),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(app.main(), 1)

    def test_notifications_can_be_disabled_for_verification(self):
        with (patch.dict(os.environ, {"SEND_TG": "false"}),
              patch.object(app.requests, "post") as post,
              contextlib.redirect_stdout(io.StringIO())):
            app.send_tg_message("✅", "续期成功")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
