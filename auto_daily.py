"""TRAE 每日自动任务

由定时任务（ECS cron / Windows 计划任务）每天执行：
1. 检查 token 过期时间，30 天内到期则钉钉提醒
2. 自动签到（已签到则跳过），钉钉通知结果
3. 抓取用量 + 积分包到期分析，推送详细版预算报告
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trae_usage_api import (
    load_config, get_valid_token, api_request,
    load_signin_history, save_signin_history, compute_continuous_days,
    collect,
)
from dingtalk import send_text, send_markdown, notify_signin, notify_token_warning
from budget import compute_budget, build_report_section

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
        # 兼容 ISO 字符串和毫秒时间戳（Python 3.6 无 fromisoformat，手动解析）
        if isinstance(exp, str):
            s = exp.replace("Z", "+0000").replace("+00:00", "+0000")
            exp_dt = None
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    exp_dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
            if exp_dt is None:
                return None
        else:
            exp_dt = datetime.utcfromtimestamp(exp / 1000)
        left = (exp_dt - datetime.now(exp_dt.tzinfo)).days
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


def build_full_report(result):
    """组装详细版钉钉报告（预算 + 用量 + 签到）。"""
    daily = result.get("daily") or []
    today_consumed = daily[-1]["consumed"] if daily else 0
    today_sessions = daily[-1]["sessions"] if daily else 0
    usage = result.get("overall_usage") or {}
    checkin = result.get("checkin") or {}

    # 近7天日均（不含今天）
    past = [d["consumed"] for d in daily[:-1][-7:]] if len(daily) > 1 else []
    recent_avg = round(sum(past) / len(past), 1) if past else 0.0

    parts = []

    # 预算分析段
    try:
        packs = result.get("packs") or []
        budget = compute_budget(packs, recent_avg)
        parts.append(build_report_section(budget))
    except Exception as e:
        log(f"预算计算失败: {e}")
        parts.append(f"### ⚠️ 预算计算失败\n\n{e}\n\n")

    # 用量统计段
    parts.append("### 📊 用量统计\n\n")
    parts.append(
        f"- **今日消耗**: {today_consumed:.1f} 积分 ({today_sessions} 会话)\n"
        f"- **近7天日均**: {recent_avg} 积分\n"
        f"- **本月累计**: {result.get('month_total', 0):.1f} 积分\n"
        f"- **总余额**: {usage.get('remaining', 0):.0f} 积分"
        f"（总额 {usage.get('total_limit', 0):.0f}）\n")

    # 签到段
    sign_line = "❌ 未签到"
    if checkin.get("checked_in"):
        sign_line = "✅ 已签到 +{} 积分，连续 {} 天".format(
            checkin.get("credits") or 200, result.get("continuous_days", 0))
    parts.append(f"- **签到**: {sign_line}\n")
    parts.append(f"\n> 数据时间: {result.get('fetched_at', '')}\n")

    return "".join(parts)


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

    # 3. 抓取数据 + 预算报告（积分包解析失败会抛异常并钉钉报错）
    log("抓取每日用量...")
    try:
        result = collect(7)
        report = build_full_report(result)
        ok = send_markdown("TRAE 每日预算报告", report)
        log("详细预算报告已发送" if ok else "报告发送失败")
    except Exception as e:
        log(f"抓取/报告失败: {e}")
        send_text("TRAE 每日任务报错", f"{type(e).__name__}: {str(e)[:300]}")

    print("=" * 55)
    print("完成！")


if __name__ == "__main__":
    main()
