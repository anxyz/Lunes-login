#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
import re
from urllib.parse import urlsplit

# 从环境变量获取账号密码和 TG 配置
EMAIL        = os.environ.get("LUNES_EMAIL") or ""     # 登录邮箱
PASSWORD     = os.environ.get("LUNES_PASSWORD") or ""  # 登录密码
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID") or ""      # chat id,可选
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""    # bot token,可选

LOGIN_URL = "https://betadash.lunes.host/login?next=/"
EMAIL_SELECTOR = 'input[name="email" i]'
PASSWORD_SELECTOR = 'input[name="password" i]'
SUBMIT_SELECTOR = 'button[type="submit"], input[type="submit"]'

#  Telegram 推送
def send_tg_message(status_icon, status_text, extra_text=""):
    if os.environ.get("SEND_TG", "true").lower() != "true":
        print("ℹ️ 本次运行已关闭 Telegram 推送。")
        return
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过 Telegram 推送。")
        return

    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)
        if len(name) > 4:
            masked_email = f"{name[:2]}****{name[-2:]}@{domain}"
        else:
            masked_email = f"{name}@{domain}"
    else:
        masked_email = EMAIL[:2] + '****'

    text = (
        f"🇺🇸 Lunes 保活通知\n\n"
        f"{status_icon} {status_text}\n"
        f"👤 登录账户: {masked_email}\n"
        f"⏱️ 登录时间: {current_time_str}"
    )
    if extra_text:
        text += f"\n\n{extra_text}"

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text}
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("📩 Telegram 通知发送成功！")
        else:
            print(f"  ⚠️ Telegram 通知发送失败: {r.text}")
    except Exception as e:
        print(f"  ⚠️ Telegram 通知发送异常: {e}")

#  js注入脚本
_EXPAND_JS = """
return (function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
return (function(){
    return document.querySelector(
        'input[name="cf-turnstile-response"], .cf-turnstile, '
        + 'iframe[src*="challenges.cloudflare.com"]'
    ) !== null;
})()
"""

_SOLVED_JS = """
return (function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
})()
"""

_COORDS_JS = """
return (function(){
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenges')) {
            var r = iframes[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
        }
    }
    var inp = document.querySelector('input[name="cf-turnstile-response"]');
    if (inp) {
        var p = inp.parentElement;
        for (var j = 0; j < 5; j++) {
            if (!p) break;
            var r = p.getBoundingClientRect();
            if (r.width > 100 && r.height > 30)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
            p = p.parentElement;
        }
    }
    return null;
})()
"""

_WININFO_JS = """
return (function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""

def js_fill_input(sb, selector: str, text: str):
    filled = sb.execute_script("""
        var el = document.querySelector(arguments[0]);
        if (!el) return false;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {
            nativeInputValueSetter.call(el, arguments[1]);
        } else {
            el.value = arguments[1];
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return el.value === arguments[1];
    """, selector, text)
    if not filled:
        raise RuntimeError(f"无法填写登录字段: {selector}")


def redact(text):
    text = str(text)
    for secret in (EMAIL, PASSWORD, TG_BOT_TOKEN, TG_CHAT_ID):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)


def login_failed(sb, reason, screenshot="login_failed.png"):
    print(f"❌ {reason}")
    try:
        current = urlsplit(sb.get_current_url())
        print(f"  当前 URL: {current.scheme}://{current.netloc}{current.path}")
        print(f"  当前标题: {redact(sb.get_title() or '')}")
        # 只读取可见文本，不输出含有密码、验证码令牌或 Cookie 的页面源码。
        body = redact(sb.get_text("body") or "")
        print(f"  页面提示: {body[:2000]}")
        sb.save_screenshot(screenshot)
    except Exception as error:
        print(f"  ⚠️ 获取登录诊断信息失败: {redact(error)}")
    return False


def login_form_visible(sb):
    return (sb.is_element_visible(EMAIL_SELECTOR)
            and sb.is_element_visible(PASSWORD_SELECTOR))


def is_authenticated(sb):
    current = urlsplit(sb.get_current_url())
    if (current.scheme != "https"
            or current.netloc.lower() != "betadash.lunes.host"
            or current.path.rstrip("/").lower() == "/login"
            or login_form_visible(sb)):
        return False
    title = (sb.get_title() or "").lower()
    return (sb.is_element_visible("a.server-card")
            or "account" in title or "dashboard" in title)


def is_cloudflare_page(sb):
    title = (sb.get_title() or "").lower()
    return ("just a moment" in title or "cloudflare" in title
            or sb.is_element_present("#challenge-running, #challenge-form"))


def click_browser_captcha(sb):
    try:
        sb.uc_gui_click_captcha()
    except Exception as error:
        print(f"  ⚠️ 浏览器验证码点击未完成: {redact(error)}")


def wait_for_login_form(sb, timeout=60):
    deadline = time.monotonic() + timeout
    next_click = time.monotonic()
    while time.monotonic() < deadline:
        if login_form_visible(sb):
            return True
        if time.monotonic() >= next_click and is_cloudflare_page(sb):
            print("⏳ 正在处理登录页面的 Cloudflare 验证...")
            click_browser_captcha(sb)
            next_click = time.monotonic() + 10
        time.sleep(1)
    return False

def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls], capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]], timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"], timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _xdotool_click(x: int, y: int):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")

def _click_turnstile(sb):
    try:
        coords = sb.execute_script(_COORDS_JS)
    except Exception as e:
        print(f"⚠️ 获取 Turnstile 坐标失败: {e}")
        return
    if not coords:
        print("⚠️ 无法定位 Turnstile 坐标")
        return
    try:
        wi = sb.execute_script(_WININFO_JS)
    except Exception:
        wi = {"sx": 0, "sy": 0, "oh": 800, "ih": 768}
        
    bar = wi["oh"] - wi["ih"]
    ax  = coords["cx"] + wi["sx"]
    ay  = coords["cy"] + wi["sy"] + bar
    print(f"🖱️ 尝试点击 Turnstile ({ax}, {ay})")
    _xdotool_click(ax, ay)

def handle_turnstile(sb) -> bool:
    print("🔍 处理 Cloudflare Turnstile 验证...")
    time.sleep(2)
    
    if sb.execute_script(_SOLVED_JS):
        print("✅ 已静默通过")
        return True

    for _ in range(3):
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.5)

    for attempt in range(6):
        if sb.execute_script(_SOLVED_JS):
            print(f"✅ Turnstile 通过（第 {attempt + 1} 次尝试）")
            return True
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.3)

        # SeleniumBase 可定位普通页面脚本无法直接读取的验证码控件。
        click_browser_captcha(sb)
        if not sb.execute_script(_SOLVED_JS):
            _click_turnstile(sb)
        
        for _ in range(8):
            time.sleep(0.5)
            if sb.execute_script(_SOLVED_JS):
                print(f"✅ Turnstile 通过（第 {attempt + 1} 次尝试）")
                return True
        print(f"  ⚠️ 第 {attempt + 1} 次未通过，重试...")

    print("  ❌ Turnstile 6 次均失败")
    return False

def login(sb, timeout=45) -> bool:
    print(f"🌐 打开登录页面: {LOGIN_URL}")
    sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=5)

    print("⏳ 等待登录表单及 Cloudflare 验证...")
    if not wait_for_login_form(sb):
        return login_failed(sb, "页面未加载出登录表单", "login_load_fail.png")

    print("🍪 关闭可能的 Cookie 弹窗...")
    try:
        for btn in sb.find_elements("button"):
            if "Accept" in (btn.text or ""):
                btn.click()
                time.sleep(0.5)
                break
    except Exception:
        pass

    print(f"📧 填写邮箱...")
    js_fill_input(sb, EMAIL_SELECTOR, EMAIL)
    time.sleep(0.3)
    
    print("🔑 填写密码...")
    js_fill_input(sb, PASSWORD_SELECTOR, PASSWORD)
    time.sleep(1)

    # 验证组件异步加载，不能只在填写密码后检查一次。
    for _ in range(8):
        if sb.execute_script(_EXISTS_JS):
            if not handle_turnstile(sb):
                return login_failed(sb, "登录界面的 Turnstile 验证失败",
                                    "login_turnstile_fail.png")
            break
        time.sleep(1)
    else:
        print("ℹ️ 未检测到 Turnstile")

    print("🖱️ 点击登录按钮提交登录...")
    sb.uc_click(SUBMIT_SELECTOR, reconnect_time=3)

    print("⏳ 等待登录跳转...")
    deadline = time.monotonic() + timeout
    next_click = time.monotonic()
    while time.monotonic() < deadline:
        if is_authenticated(sb):
            print("✅ 登录成功，已进入账户页面！")
            return True
        if time.monotonic() >= next_click and is_cloudflare_page(sb):
            click_browser_captcha(sb)
            next_click = time.monotonic() + 10
        time.sleep(1)

    return login_failed(sb, "登录失败，等待后仍未进入账户页面")

# 访问服务器页面
def visit_server(sb) -> (bool, dict):
    print("🔍 正在查找服务器卡片...")
    try:
        sb.wait_for_element('a.server-card', timeout=15)
    except Exception:
        print("❌ 未找到服务器卡片（可能没有服务器）")
        return False, {"error": "未找到服务器卡片，可能账户无服务器"}

    cards = sb.find_elements('a.server-card')
    if not cards:
        return False, {"error": "未找到服务器卡片"}

    card = cards[0]
    href = card.get_attribute('href')
    if not href:
        return False, {"error": "卡片缺少 href 属性"}

    match = re.search(r'/servers/(\d+)', href)
    if not match:
        return False, {"error": f"无法从 href 解析服务器 ID: {href}"}
    server_id = match.group(1)

    print(f"🖱️ 点击服务器卡片 (ID: {server_id})")
    card.click()
    time.sleep(3)

    expected_url_prefix = f"https://betadash.lunes.host/servers/{server_id}"
    for _ in range(10):
        cur_url = sb.get_current_url().split('?')[0]
        if cur_url == expected_url_prefix:
            break
        time.sleep(1)
    else:
        return False, {"server_id": server_id, "error": f"跳转后 URL 不匹配，当前: {sb.get_current_url()}"}

    page_title = sb.get_title() or ""
    server_name = ""
    if "Server " in page_title:
        server_name = page_title.split("Server ", 1)[-1].strip()
    else:
        server_name = f"ID {server_id}"

    print(f"✅ 成功访问服务器: {server_name} (ID: {server_id})")
    return True, {"server_id": server_id, "server_name": server_name}

def main():
    print("#" * 25)
    print("   Lunes 自动登录续期")
    print("#" * 25)

    if not EMAIL.strip() or not PASSWORD:
        print("❌ 请配置 LUNES_EMAIL 和 LUNES_PASSWORD。")
        return 1

    from seleniumbase import SB
    
    is_proxy = os.environ.get("IS_PROXY", "false").lower() == "true"
    sb_kwargs = {"uc": True, "headless": False}
    
    if is_proxy:
        proxy_str = os.environ.get("PROXY_SERVER") or "http://127.0.0.1:1081"
        print("🔗 使用 sing-box 代理")
        sb_kwargs["proxy"] = proxy_str
    else:
        print("🌐 未使用代理，直连访问")
    
    with SB(**sb_kwargs) as sb:
        print("✅ 浏览器已启动")
        try:
            sb.open("https://api.ip.sb/ip")
            print(f"🌐 当前出口真实 IP: {sb.get_text('body')}")
        except Exception:
            pass

        if login(sb):
            success, info = visit_server(sb)
            if success:
                extra = f"服务器: {info['server_name']}\nID: {info['server_id']}"
                send_tg_message("✅", "续期成功", extra)
                return 0
            else:
                error_msg = info.get('error', '未知错误')
                print(f"❌ 访问服务器失败: {error_msg}")
                extra = f"错误: {error_msg}"
                if 'server_id' in info:
                    extra += f"\n服务器ID: {info['server_id']}"
                send_tg_message("❌", "续期失败", extra)
                return 1
        else:
            print("\n❌ 登录失败，终止后续续期操作。")
            send_tg_message("❌", "登录失败", "")
            return 1

    # 即使浏览器上下文接管了异常，也不能把未完成的续期标记为成功。
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
