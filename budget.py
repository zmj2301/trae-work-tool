"""每日用量预算计算（开学模式版）

基于积分包的到期时间 + 学校日历做逐日模拟（FIFO：先到期先消耗），
给出"今天用多少"的建议，目标是积分零浪费。

日型权重（school_calendar.day_weight）:
  full=1.0(周末/节假日/假期)  half=0.5(周五下午回家)  off=0(上学日)

核心概念:
  - R(per_full_day) 防浪费底线: 要让所有包不作废, 每个全天可用日
    至少要消耗的量 = max(各到期事件的累计量 ÷ 该事件前的加权可用容量)
  - suggested 今日建议 = R 与近期节奏取大后 × 今日权重（off 日为 0）
  - hard_cap 硬上限 = 当前存量 × (1 - buffer)，防止建议一次性清空
  - waste 按可用日节奏推算未来31天将过期的量
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import school_calendar

CONFIG_FILE = Path(__file__).parent / "config.json"
HORIZON_DAYS = 31
CHECKIN_CREDITS = 200

# 用户只能在晚上用电脑；中午前到期的积分包 = 前一天晚上就用不了了
_USER_AVAIL_HOUR = 12  # 中午12点为界：之前到期 → 算作前一天


def _cfg():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_buffer_ratio():
    """缓冲比例，可在 config.json 用 budget_buffer_ratio 配置，默认 0.10。"""
    try:
        return float(_cfg().get("budget_buffer_ratio", 0.10))
    except Exception:
        return 0.10


def project_checkins_enabled():
    """是否把未来的自动签到包计入预测（默认开启）。"""
    return bool(_cfg().get("project_future_checkins", True))


def _last_usable_ts(pack):
    """pack 的最后可用时刻（用户只能晚上用电脑，中午前到期 = 前一天晚上）。

    返回 Unix 时间戳，用于替代原始 expire_time 参与可用日计算。
    """
    expire_dt = datetime.fromtimestamp(pack["expire_time"])
    if expire_dt.hour < _USER_AVAIL_HOUR:
        # 中午前到期 → 最后可用 = 前一天 23:00
        last = expire_dt - timedelta(days=1)
        last = last.replace(hour=23, minute=0, second=0, microsecond=0)
    else:
        last = expire_dt
    return last.timestamp()


def compute_budget(packs, recent_avg, today=None):
    """计算今日用量预算。

    Args:
        packs: fetch_entitlement_packs() 的输出列表
        recent_avg: 近7天日均消耗（按历史全可用日口径）
        today: 计算基准 datetime（默认当前时间）

    Returns:
        dict，含 total_alive / must_use(R) / suggested / hard_cap /
        waste_forecast / expiry_events / critical_event / today_type 等
    """
    now = today or datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = start.timestamp()

    # 只保留基准日之后才过期的包（防御：过期数据/深夜运行时不污染计算）
    alive = [dict(p) for p in packs
             if p.get("remaining", 0) > 0 and p.get("expire_time", 0) > start_ts]
    total_alive = round(sum(p["remaining"] for p in alive), 2)

    # --- 未来签到投影：每天自动签到 +200，31天后过期 ---
    pool_packs = [dict(p) for p in alive]
    if project_checkins_enabled():
        for i in range(HORIZON_DAYS):
            sign_day = start + timedelta(days=i)
            proj = {
                "name": "签到(预)",
                "remaining": float(CHECKIN_CREDITS),
                "expire_time": (sign_day + timedelta(days=31)).timestamp(),
                "expire_str": "",
                "alive": True,
            }
            pool_packs.append(proj)

    # --- 到期事件按天分组（含包组成明细）---
    # 中午前到期的包 → 算作前一天到期（用户中午前用不了电脑）
    events = {}
    for p in pool_packs:
        usable_ts = _last_usable_ts(p)
        d = datetime.fromtimestamp(usable_ts).replace(
            hour=0, minute=0, second=0, microsecond=0)
        ev = events.setdefault(d, {"amount": 0.0, "items": {}})
        ev["amount"] += p["remaining"]
        ev["items"][p["name"]] = ev["items"].get(p["name"], 0.0) + p["remaining"]
    sorted_events = sorted(events.items())

    # 即将到期明细（最多展示前4个事件日）
    expiry_events = [
        {
            "date": d.strftime("%m-%d"),
            "amount": round(v["amount"], 1),
            "items": [{"name": n, "amount": round(a, 1)}
                      for n, a in sorted(v["items"].items(), key=lambda kv: -kv[1])],
        }
        for d, v in sorted_events[:4]
    ]

    # --- 加权可用容量 ---
    def capacity_until(end_date):
        """[start, end_date] 区间的加权可用天数（含两端）。"""
        w, d = 0.0, start
        while d <= end_date:
            w += school_calendar.day_weight(d)
            d += timedelta(days=1)
        return w

    # --- 防浪费底线 R（每全天可用日的最低消耗）---
    # FIFO 假设下, 到第 k 个到期日前必须累计烧掉前 k 个事件的量
    buffer_ratio = get_buffer_ratio()
    hard_cap = round(total_alive * (1 - buffer_ratio), 1)

    must_use = 0.0
    critical_event = None
    infeasible = False  # 存在"到期前完全无可用日"的积分 → 只能尽力而为
    cum = 0.0
    for d, ev in sorted_events:
        amt = ev["amount"]
        cum += amt
        cap = capacity_until(d)
        if cap <= 0:
            # 截止日前完全无可用日 → 无法挽救，单独标记
            infeasible = True
            critical_event = {
                "date": d.strftime("%m-%d"),
                "amount": round(amt, 1),
                "days_left": (d - start).days,
                "usable_capacity": 0.0,
            }
            continue
        need = cum / cap
        if need > must_use:
            must_use = need
            critical_event = {
                "date": d.strftime("%m-%d"),
                "amount": round(amt, 1),
                "days_left": (d - start).days,
                "usable_capacity": round(cap, 1),
            }
    if infeasible:
        # 有积分注定浪费：建议按硬上限全力消耗，报告会给出紧急提示
        must_use = hard_cap
    must_use = round(must_use, 1)

    # --- 未来31天浪费预测（只在实际可用的日子按节奏消耗）---
    pace = max(recent_avg, 0.0)
    pool = sorted(pool_packs, key=lambda p: p["expire_time"])
    waste = 0.0
    for day_i in range(HORIZON_DAYS):
        day = start + timedelta(days=day_i)
        w = school_calendar.day_weight(day)
        day_end_ts = (day + timedelta(days=1)).timestamp()
        # 先处理当天到期的包（用调整后的时间：中午前到期 → 算作前一天）
        for p in pool:
            usable_ts = _last_usable_ts(p)
            if 0 < usable_ts < day_end_ts and p["remaining"] > 0:
                waste += p["remaining"]
                p["remaining"] = 0.0
        # 可用日才消耗（先吃快过期的）
        burn = min(pace * w, sum(p["remaining"] for p in pool))
        for p in pool:
            if burn <= 0:
                break
            take = min(p["remaining"], burn)
            p["remaining"] -= take
            burn -= take
    waste = round(waste, 1)

    # --- 今日建议 ---
    today_w = school_calendar.day_weight(now)
    today_t = school_calendar.day_type(now)
    if today_w <= 0:
        suggested = 0.0
    else:
        target = max(must_use, min(pace, hard_cap))
        suggested = round(min(target * today_w, hard_cap), 1)

    return {
        "total_alive": total_alive,
        "must_use_per_day": must_use,
        "suggested": suggested,
        "hard_cap": hard_cap,
        "buffer_ratio": buffer_ratio,
        "waste_forecast": waste,
        "critical_event": critical_event,
        "infeasible": infeasible,
        "expiry_events": expiry_events,
        "recent_avg": round(pace, 1),
        "pack_count": len(alive),
        "today_type": today_t,
        "today_weight": today_w,
        "today_label": school_calendar.day_label(now),
    }


def build_report_section(budget):
    """把预算结果渲染成钉钉 markdown 片段（full/half 日用）。"""
    ce = budget.get("critical_event")
    lines = []
    lines.append(f"### 🎯 今日额度建议\n")
    lines.append(
        f"- **今日最低消耗**: {budget['suggested']} 积分"
        f"（防浪费底线，多用不亏；{budget['today_label']}，"
        f"权重{budget['today_weight']}）\n"
        f"- **防浪费底线**: {budget['must_use_per_day']}/全天可用日\n")
    if budget.get("infeasible"):
        lines.append(
            "- 🔴 **紧急: 部分积分在其到期日之前没有任何可用日，注定浪费！"
            "建议今天就全力消耗。**\n")
    elif ce:
        lines.append(
            f"  （因 {ce['amount']} 积分将在 {ce['date']} 到期，"
            f"此前仅剩 {ce['usable_capacity']} 个加权可用日）\n")
    else:
        lines.append("（近期无到期压力）\n")

    lines.append(
        f"- **近7天日均**: {budget['recent_avg']} | **硬上限**: {budget['hard_cap']}"
        f"（含{int(budget['buffer_ratio']*100)}%缓冲）\n")

    if budget["waste_forecast"] > 1:
        lines.append(
            f"- ⚠️ **按当前节奏，未来31天将浪费约 {budget['waste_forecast']} 积分**\n")
    else:
        lines.append("- ✅ 按当前节奏可基本零浪费\n")

    events = budget.get("expiry_events") or []
    if events:
        lines.append("**⏰ 即将到期明细:**\n\n")
        for ev in events:
            comp = " + ".join(
                f"{it['name']}{it['amount']:.0f}" for it in ev["items"])
            lines.append(f"- **{ev['date']} 到期 {ev['amount']:.0f} 积分**（{comp}）\n")

    return "".join(lines)


def build_offday_section(budget):
    """上学日的简化片段。"""
    ce = budget.get("critical_event") or {}
    txt = "📚 今日上学，额度由周末/假期消化。\n"
    if ce:
        txt += (
            f"⚠️ 提醒: {ce['amount']} 积分将在 {ce['date']} 前到期，"
            f"剩余加权可用日仅 {ce['usable_capacity']} 个。\n")
    return txt


if __name__ == "__main__":
    # 自测：构造假数据，分别模拟 上学日/周五/周六 三种日型
    # 积分包过期时间相对模拟日期（+6天/+7天），保证场景一致
    results = []
    for ds, desc in [("2026-09-02", "周三"), ("2026-09-04", "周五"),
                     ("2026-09-05", "周六")]:
        ft = datetime.strptime(ds, "%Y-%m-%d")
        mock_packs = [
            {"name": "老用户福利", "remaining": 785,
             "expire_time": (ft + timedelta(days=6)).timestamp(),
             "expire_str": "", "alive": True},
            {"name": "会员Lite月度", "remaining": 2000,
             "expire_time": (ft + timedelta(days=7)).timestamp(),
             "expire_str": "", "alive": True},
        ]
        b = compute_budget(mock_packs, recent_avg=190, today=ft)
        ce = b["critical_event"] or {}
        print(f"--- {ds}({desc}) type={b['today_type']} "
              f"suggested={b['suggested']} R={b['must_use_per_day']}/全天 "
              f"事件{ce.get('date')}前可用容量={ce.get('usable_capacity')} ---")
    print(json.dumps(compute_budget(mock_packs, 190), ensure_ascii=False, indent=2)[:400])
