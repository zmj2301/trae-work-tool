"""晚间检查任务（ECS cron 每天 20:30）

1. 周五/周末/法定节假日: 推送今日消耗进度 vs 防浪费底线 + 今晚到期提醒
2. 守护检查（每天）: 今早 7 点任务没成功运行则告警（兼每日心跳）

上学日（off）不推进度，只做守护检查（异常才发声，不骚扰）。

注意：守护检查与本任务同在 ECS 上，整机宕机时两边都不会跑——
那时你收不到任何推送本身就是信号。如需整机级监控，后续可接
免费外部监控（如 UptimeRobot）。

用法:
    python evening_check.py            # 正常运行（会推送）
    python evening_check.py --dry-run  # 只打印不推送
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trae_usage_api import (
    load_config, get_valid_token, fetch_entitlement_packs,
    fetch_month_grouped, log,
)
from budget import compute_budget
from dingtalk import send_markdown, send_text
import school_calendar

BASE = Path(__file__).parent
MARKER = BASE / "last_run_ok"
EXPIRE_WINDOW_H = 14  # 20:30 起 14 小时内到期的算「今晚到期」


def morning_ok():
    """今早任务是否成功跑过（成功标记时间 >= 今天 0 点）。"""
    if not MARKER.exists():
        return False
    try:
        ts = float(MARKER.read_text(encoding="utf-8").strip() or 0)
    except (ValueError, OSError):
        return False
    today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime.fromtimestamp(ts) >= today0


def _bar(pct, width=10):
    filled = int(round(max(0.0, min(pct, 1.0)) * width))
    return "▓" * filled + "░" * (width - filled)


def build_progress(cfg, token):
    """组装今日进度消息。返回 (markdown, floor)；底线为 0 时返回 (None, 0)。"""
    now = datetime.now()
    packs = fetch_entitlement_packs(cfg, token)

    grouped = fetch_month_grouped(cfg, token)
    today_str = now.strftime("%Y-%m-%d")
    today_consumed = (grouped.get(today_str) or {}).get("consumed", 0.0)

    # 近7天日均（不含今天）
    past = []
    for i in range(1, 8):
        ds = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        if ds in grouped:
            past.append(grouped[ds]["consumed"])
    avg = round(sum(past) / len(past), 1) if past else 0.0

    b = compute_budget(packs, avg)
    floor = float(b.get("suggested", 0) or 0)
    if floor <= 0:
        return None, 0.0

    pct = today_consumed / floor if floor else 0
    lines = [f"### 📉 今日进度（{school_calendar.day_label(now)}）\n"]
    lines.append(
        f"- 已消耗 **{today_consumed:.0f}** / 底线 **{floor:.0f}** 积分\n"
        f"- {_bar(pct)} {int(pct * 100)}%\n")

    if today_consumed >= floor:
        lines.append("- ✅ 已达标，今晚放心休息（多用不亏）\n")
    else:
        gap = floor - today_consumed
        lines.append(f"- 还差 **{gap:.0f} 积分**：多用不亏、早用早安全\n")

    # 今晚到期提醒
    horizon = now.timestamp() + EXPIRE_WINDOW_H * 3600
    expiring = [(p["name"], p["remaining"], p["expire_str"])
                for p in packs
                if p.get("alive") and p.get("remaining", 0) > 0
                and 0 < p["expire_time"] < horizon]
    if expiring:
        total = sum(x[1] for x in expiring)
        comp = "、".join(f"{n}{r:.0f}" for n, r, _ in expiring)
        lines.append(
            f"- ⏰ **今晚到期 {total:.0f} 积分**（{comp}），没烧就亏了！\n")

    # 超标提示（消耗远超底线也告知，属正常但别烧穿余额）
    if pct > 1.5:
        lines.append(f"- 💬 今天已烧 {today_consumed:.0f}，远超底线，注意留点余额给后面\n")

    return "".join(lines), floor


def main():
    dry = "--dry-run" in sys.argv
    print("=" * 55)
    print("TRAE 晚间检查" + ("（dry-run）" if dry else ""))
    print("=" * 55)

    # 1. 守护检查（每天，异常才发声）
    if not morning_ok():
        msg = "⚠️ 今早 7 点任务未成功运行（无成功标记），请检查 ECS cron 与日志"
        log(msg)
        if not dry:
            send_text("TRAE 任务异常", msg)
    else:
        log("今早任务正常")

    # 2. 进度推送（仅周五/周末/法定节假日）
    t = school_calendar.day_type()
    if t == "off":
        log("上学日，不推进度")
        return

    cfg = load_config()
    token = get_valid_token(cfg)
    md, floor = build_progress(cfg, token)
    if not md:
        log("底线为 0，跳过推送")
        return
    if dry:
        print(md)
        return
    ok = send_markdown("TRAE 今日进度", md)
    log("进度已推送" if ok else "推送失败")


if __name__ == "__main__":
    main()
