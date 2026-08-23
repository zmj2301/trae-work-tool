"""TRAE 每日自动任务

由 Windows 计划任务每天定时执行：
1. 检查 token 过期时间，30 天内到期则钉钉提醒
2. 自动签到（已签到则跳过），钉钉通知结果
3. 调用 trae_usage_api.py 抓取数据并发送每日用量报告
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trae_usage_api import (
    load_config, get_valid_token, api_request,
    load_signin_history, save_signin_history, compute_continuous_days,
    CONFIG_FILE,
)
from dingtalk import send_text, notify_signin, notify_token_warning

BASE = Path(__file__).parent
HISTORY_FILE = BASE / "trae_signin_history.json"

TOKEN_WARN_DAYS = 30


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def check_token_expiry(cfg):
    """检查 refresh_token 过期时间，返回剩余天数（未知返回 None）。

    注意：只看 refresh_expired_at（长期凭证）。
    access_token 只有约 14 天且会自动续期，不作为提醒依据。
    """
    exp = cfg.get("refresh_expired_at")
    if not exp:
        return None
    try:
        # 兼容 ISO 字符串和毫秒时间戳
        if isinstance(exp, str):
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        else:
            exp_dt = datetime.fromtimestamp(exp / 1000, tz=timezone.utc)
        left = (exp_dt - datetime.now(timezone.utc)).days
        return left
    except Exception as e:
        log(f"解析过期时间失败: {e}")
        return None


def do_checkin(cfg, token):
    """签到，返回 (success, credits, message)。"""
    today_str = datetime.now().strftime("%Y-%m-%d")

    r = api_request(cfg, "/trae/api/v2/ug/checkin_credits/status", token)
    st = r.json()
    checked_in = bool(st.get("checked_in"))

    hist = load_signin_history()
    hist[today_str] = checked_in
    save_signin_history(hist)

    if checked_in:
        credits = st.get("credits", 200)
        days = compute_continuous_days(hist, today_str)
        return True, credits, f"今日已签到，连续 {days} 天"

    r2 = api_request(cfg, "/trae/api/v2/ug/checkin_credits/claim", token)
    cl = r2.json()
    if cl.get("code") == 0:
        credits = cl.get("credits", 200)
        hist[today_str] = True
        save_signin_history(hist)
        days = compute_continuous_days(hist, today_str)
        return True, credits, f"签到成功 +{credits}，连续 {days} 天"
    return False, 0, cl.get("message", str(cl))


def main():
    print("=" * 55)
    print("TRAE 每日自动任务")
    print("=" * 55)

    cfg = load_config()
    token = get_valid_token(cfg)

    # 1. token 过期检查
    days_left = check_token_expiry(cfg)
    if days_left is not None:
        log(f"refresh_token 剩余 {days_left} 天")
        notify_token_warning(days_left)

    # 2. 自动签到
    try:
        ok, credits, msg = do_checkin(cfg, token)
        log(f"签到: {msg}")
        notify_signin(ok, credits, msg)
    except Exception as e:
        log(f"签到失败: {e}")
        send_text("TRAE 签到失败", f"异常: {e}")

    # 3. 抓取用量 + 每日报告（trae_usage_api 内部会发钉钉）
    log("抓取每日用量...")
    r = subprocess.run(
        [sys.executable, str(BASE / "trae_usage_api.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(r.stdout[-2000:] if r.stdout else "")
    if r.returncode != 0:
        send_text("TRAE 用量抓取失败", f"exit={r.returncode}: {r.stderr[-300:]}")
        log(f"用量抓取失败 exit={r.returncode}")
    else:
        log("用量报告已发送")

    print("=" * 55)
    print("完成！")


if __name__ == "__main__":
    main()
