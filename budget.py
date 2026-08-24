"""每日用量预算计算

基于积分包的到期时间做逐日模拟（FIFO：先到期先消耗），
给出"今天用多少"的建议，目标是积分零浪费。

核心概念:
  - must_use   防浪费底线: 要让所有包都不作废, 每天至少要消耗的量
               = max(每个到期事件前需烧掉的累计量 / 剩余天数)
  - suggested  今日建议 = max(must_use, 近7天日均), 不超过硬上限
  - hard_cap   硬上限 = 当前存量 × (1 - buffer)，防止建议一次性清空
  - waste      按近7天日均节奏推算未来31天将过期的量
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
HORIZON_DAYS = 31


def get_buffer_ratio():
    """缓冲比例，可在 config.json 用 budget_buffer_ratio 配置，默认 0.10。"""
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return float(cfg.get("budget_buffer_ratio", 0.10))
    except Exception:
        return 0.10


def compute_budget(packs, recent_avg, today=None):
    """计算今日用量预算。

    Args:
        packs: fetch_entitlement_packs() 的输出列表
        recent_avg: 近7天日均消耗
        today: 计算基准日（默认当前时间）

    Returns:
        dict: total_alive / must_use / suggested / hard_cap /
              waste_forecast / next_expiries / critical_event
    """
    now = today or datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    alive = [dict(p) for p in packs if p.get("alive") and p.get("remaining", 0) > 0]
    total_alive = round(sum(p["remaining"] for p in alive), 2)

    # --- 最近到期 TOP3（必须在模拟消耗前快照，否则会被清零）---
    next_expiries = [
        {"name": p["name"], "amount": p["remaining"], "expire_str": p["expire_str"]}
        for p in sorted(alive, key=lambda x: x["expire_time"])[:3]
    ]

    # --- 到期事件按天分组 ---
    events = {}
    for p in alive:
        d = datetime.fromtimestamp(p["expire_time"]).replace(
            hour=0, minute=0, second=0, microsecond=0)
        events[d] = events.get(d, 0.0) + p["remaining"]
    sorted_events = sorted(events.items())

    # --- 防浪费底线 ---
    # FIFO 假设下, 到第 k 个事件日(含)之前累计消耗必须 >= 前 k 个事件的量
    must_use = 0.0
    critical_event = None
    cum = 0.0
    for d, amt in sorted_events:
        cum += amt
        days_left = max((d - start).days + 1, 1)  # 含今天
        need = cum / days_left
        if need > must_use:
            must_use = need
            critical_event = {
                "date": d.strftime("%m-%d"),
                "amount": round(amt, 1),
                "days_left": (d - start).days,
            }
    must_use = round(must_use, 1)

    # --- 未来31天浪费预测（按 recent_avg 节奏 FIFO 消耗）---
    pace = max(recent_avg, 0.0)
    pool = sorted(alive, key=lambda p: p["expire_time"])
    waste = 0.0
    for day in range(HORIZON_DAYS):
        day_end = (start + timedelta(days=day + 1)).timestamp()
        # 先处理当天到期的包
        for p in pool:
            if 0 < p["expire_time"] < day_end and p["remaining"] > 0:
                waste += p["remaining"]
                p["remaining"] = 0.0
        # 再按节奏消耗（先吃快过期的）
        burn = min(pace, sum(p["remaining"] for p in pool))
        for p in pool:
            if burn <= 0:
                break
            take = min(p["remaining"], burn)
            p["remaining"] -= take
            burn -= take
    waste = round(waste, 1)

    # --- 今日建议 ---
    buffer_ratio = get_buffer_ratio()
    hard_cap = round(total_alive * (1 - buffer_ratio), 1)
    suggested = max(must_use, min(pace, hard_cap))
    suggested = round(min(suggested, hard_cap), 1)

    return {
        "total_alive": total_alive,
        "must_use": must_use,
        "suggested": suggested,
        "hard_cap": hard_cap,
        "buffer_ratio": buffer_ratio,
        "waste_forecast": waste,
        "critical_event": critical_event,
        "next_expiries": next_expiries,
        "recent_avg": round(pace, 1),
        "pack_count": len(alive),
    }


def build_report_section(budget):
    """把预算结果渲染成钉钉 markdown 片段。"""
    ce = budget.get("critical_event")
    lines = []
    lines.append(f"### 🎯 今日额度建议\n")
    lines.append(
        f"- **今日建议消耗**: {budget['suggested']} 积分\n"
        f"- **防浪费底线**: {budget['must_use']}/天")
    if ce:
        lines.append(
            f"  （因 {ce['amount']} 积分将在 {ce['date']} 到期，剩 {max(ce['days_left'],0)} 天）\n")
    else:
        lines.append("（近期无到期压力）\n")
    lines.append(
        f"- **近7天日均**: {budget['recent_avg']} | **硬上限**: {budget['hard_cap']}"
        f"（含{int(budget['buffer_ratio']*100)}%缓冲）\n")

    if budget["waste_forecast"] > 1:
        lines.append(
            f"- ⚠️ **按近期节奏，未来31天将浪费约 {budget['waste_forecast']} 积分**\n")
    else:
        lines.append("- ✅ 按近期节奏可基本零浪费\n")

    tops = budget.get("next_expiries") or []
    if tops:
        lines.append("**⏰ 最近到期 TOP3:**\n")
        for i, t in enumerate(tops, 1):
            lines.append(f"{i}. {t['name']} {t['amount']:.0f} 积分 → {t['expire_str']}\n")

    return "".join(lines)


if __name__ == "__main__":
    # 自测：构造假数据
    from datetime import datetime as dt
    base = dt.now()
    mock_packs = [
        {"name": "福利A", "remaining": 785, "expire_time": (base + timedelta(days=7)).timestamp(),
         "expire_str": "08-31 19:05", "alive": True},
        {"name": "签到包", "remaining": 200, "expire_time": (base + timedelta(days=20)).timestamp(),
         "expire_str": "09-13 07:00", "alive": True},
        {"name": "会员月度", "remaining": 2000, "expire_time": (base + timedelta(days=30)).timestamp(),
         "expire_str": "09-23 11:00", "alive": True},
    ]
    b = compute_budget(mock_packs, recent_avg=190)
    print(json.dumps(b, ensure_ascii=False, indent=2))
    print()
    print(build_report_section(b))
