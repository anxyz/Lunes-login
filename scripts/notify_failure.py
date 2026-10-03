#!/usr/bin/env python3
"""Send a workflow failure alert without browser, pip packages or node access."""

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def failure_message():
    stages = (
        ("CHECKOUT_OUTCOME", "代码检出"),
        ("PYTHON_OUTCOME", "Python 初始化"),
        ("INSTALL_OUTCOME", "依赖安装"),
        ("TEST_OUTCOME", "回归测试"),
        ("PROXY_OUTCOME", "代理初始化"),
        ("RENEW_OUTCOME", "续期检查或通知"),
    )
    stage = next(
        (label for name, label in stages if os.getenv(name) == "failure"),
        "任务异常退出或超时",
    )
    detail = (
        "续期步骤尚未执行。"
        if os.getenv("RENEW_OUTCOME") == "skipped"
        else "未收到通知发送成功记录，请查看运行结果确认续期状态。"
    )
    repository = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return (
        f"❌ Lunes 登录保活任务失败\n\n失败阶段：{stage}\n{detail}\n"
        "此告警独立直连发送，不依赖续期代理或浏览器。\n"
        f"运行 #{os.getenv('GITHUB_RUN_NUMBER', '')} · 第 {attempt} 次尝试\n"
        f"https://github.com/{repository}/actions/runs/{run_id}"
    )


def main():
    if os.getenv("SEND_TG", "true").lower() != "true":
        print("ℹ️ 本次不发送 Telegram 通知", flush=True)
        return 0
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    chat = os.getenv("TG_CHAT_ID", "").strip()
    if not token or not chat:
        print("ℹ️ Telegram 未配置，跳过通知", flush=True)
        return 0
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": failure_message()}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Ignore all proxy environment variables, including a broken renewal node.
    opener = build_opener(ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(request, timeout=25) as response:
                result = json.load(response)
                if isinstance(result, dict) and result.get("ok") is True:
                    print("📩 Telegram 文字通知发送成功", flush=True)
                    return 0
            break
        except HTTPError as error:
            print(f"⚠️ Telegram sendMessage 失败（HTTP {error.code}）", flush=True)
            if error.code != 429 and error.code < 500:
                break
        except (URLError, OSError, ValueError):
            print("⚠️ Telegram 请求异常", flush=True)
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    print("❌ Telegram 通知发送失败", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
