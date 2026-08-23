"""钉钉通知模块

支持两种通知：
1. 签到成功/失败通知
2. 每日用量异常提醒

配置: 在 config.json 中添加 "dingtalk_webhook": "你的webhook地址"
"""
import json
import requests
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"


def get_webhook():
    """读取钉钉 webhook 地址。"""
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("dingtalk_webhook", "")
    except Exception:
        return ""


def send_text(title, content):
    """发送文本消息到钉钉。

    Args:
        title: 消息标题（显示在通知栏）
        content: 消息内容
    """
    webhook = get_webhook()
    if not webhook:
        return False

    body = {
        "msgtype": "text",
        "text": {"content": f"[{title}] {content}"}
    }
    try:
        r = requests.post(webhook, json=body, timeout=10)
        return r.json().get("errcode") == 0
    except Exception:
        return False


def send_markdown(title, text):
    """发送 Markdown 格式消息到钉钉。

    Args:
        title: 消息标题
        text: Markdown 格式内容
    """
    webhook = get_webhook()
    if not webhook:
        return False

    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text}
    }
    try:
        r = requests.post(webhook, json=body, timeout=10)
        return r.json().get("errcode") == 0
    except Exception:
        return False


def notify_signin(success, credits=0, message=""):
    """签到通知。"""
    if success:
        send_text("TRAE 签到成功", f"成功领取 {credits} Work 积分！{message}")
    else:
        send_text("TRAE 签到失败", f"签到失败: {message}")


def notify_daily_usage(consumed, threshold=200):
    """每日用量异常提醒。"""
    if consumed > threshold:
        send_text(
            "TRAE 用量提醒",
            f"今日消耗 {consumed:.1f} 积分，超过阈值 {threshold}。请注意控制用量。"
        )


def notify_token_warning(days_left):
    """Token 即将过期提醒。"""
    if days_left <= 30:
        send_text(
            "TRAE Token 提醒",
            f"你的 refresh_token 将在 {days_left} 天后过期，请及时续期。"
        )


if __name__ == "__main__":
    # 测试
    ok = send_text("TRAE Work", "通知功能测试成功！")
    print("发送结果:", "成功" if ok else "失败")
