"""模型推荐：根据当日预算额度与 Lite 会员限制，推荐合适的模型档位。

设计（用户确认）：
- 「Lite 不能用的模型」名单 = API 探测 + 内置清单（两者结合）
- 推荐结果 = 具体模型名（含消耗倍率）
- 触发依据 = 今日剩余预算（来自 budget.py 的 suggested / must_use_per_day）

数据源：
1. MODEL_TABLE：内置模型清单（档位 / 倍率 / Lite是否可用 / 能力），来自官方文档整理
2. config.json 的 model_overrides：用户手动纠正（倍率 / Lite可用性）
3. config.json 的 model_list_endpoint（可选）：TRAE 模型列表接口，运行时探测账号实际可用模型
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent

# 倍率以 Seed-2.1-Turbo / Seed-Code ≈ 1.0 为基准，
# 依据官方公开的每百万 token 价格（输出价为主）归一化估算。
# tier: eco=经济, std=标准, flagship=旗舰
# lite: Lite 会员默认可用性（保守默认，可用 model_overrides 纠正）
MODEL_TABLE = [
    # —— 经济档（倍率 ≤ 1.2，省积分）——
    {"name": "Seed-Code",            "tier": "eco",       "multiplier": 1.0, "lite": True,  "caps": "编程,中文"},
    {"name": "Seed-2.1-Turbo",       "tier": "eco",       "multiplier": 1.0, "lite": True,  "caps": "推理,中文"},
    {"name": "Doubao-Seed-2.0-Code", "tier": "eco",       "multiplier": 1.0, "lite": True,  "caps": "编程,中文"},
    {"name": "DeepSeek-V4-Flash",    "tier": "eco",       "multiplier": 0.9, "lite": True,  "caps": "编程"},
    {"name": "DeepSeek-V4-Flash 正式版", "tier": "eco",   "multiplier": 0.9, "lite": True,  "caps": "编程"},
    {"name": "MiniMax-M2.7",         "tier": "eco",       "multiplier": 0.6, "lite": True,  "caps": "推理"},
    {"name": "MiniMax-M3",           "tier": "eco",       "multiplier": 1.0, "lite": True,  "caps": "图片,推理"},
    {"name": "GLM-5-Turbo",          "tier": "eco",       "multiplier": 0.8, "lite": True,  "caps": "推理"},

    # —— 标准档（倍率 1.2–3）——
    {"name": "DeepSeek-V4-Pro",      "tier": "std",       "multiplier": 1.6, "lite": True,  "caps": "编程,推理"},
    {"name": "DeepSeek-V4-Pro 正式版", "tier": "std",     "multiplier": 1.6, "lite": True,  "caps": "编程,推理"},
    {"name": "Kimi-K2.5",            "tier": "std",       "multiplier": 1.2, "lite": True,  "caps": "推理"},
    {"name": "Kimi-K2.7-Code",      "tier": "std",       "multiplier": 1.2, "lite": True,  "caps": "编程,推理"},
    {"name": "GLM-5.2",             "tier": "std",       "multiplier": 1.3, "lite": True,  "caps": "编程,推理,图片"},
    {"name": "GLM-5",               "tier": "std",       "multiplier": 1.5, "lite": True,  "caps": "推理"},
    {"name": "Gemini-3-Flash-Preview", "tier": "std",    "multiplier": 1.2, "lite": True,  "caps": "图片,推理,长上下文"},
    {"name": "Doubao-Seed-2.1-Pro", "tier": "std",       "multiplier": 2.0, "lite": True,  "caps": "推理,图片"},
    {"name": "Doubao-Seed-Evolving", "tier": "std",      "multiplier": 2.0, "lite": True,  "caps": "推理,图片"},

    # —— 旗舰档（倍率 > 3，贵；Lite 默认不可用）——
    {"name": "GPT-5.2",             "tier": "flagship",  "multiplier": 5.6, "lite": False, "caps": "图片,推理"},
    {"name": "GPT-5.4",             "tier": "flagship",  "multiplier": 8.0, "lite": False, "caps": "图片,推理,长上下文"},
    {"name": "Gemini-3.1-Pro-Preview", "tier": "flagship", "multiplier": 6.5, "lite": False, "caps": "图片,推理,记忆,长上下文"},
]

TIER_LABEL = {"eco": "🟢 经济档", "std": "🔵 标准档", "flagship": "🟣 旗舰档"}
TIER_HINT = {
    "eco": "日常/简单任务：Flash、Turbo 类，倍率低、省钱",
    "std": "复杂编程/推理：Pro、Kimi、GLM-5.2 类，性价比均衡",
    "flagship": "疑难/长上下文：GPT-5、Gemini-Pro 类，能力强但贵",
}

# 预算包络（今日 suggested）-> 允许档位
# off 日单独处理；非 off 日按包络大小放开档位
ECO_CEIL = 150      # 包络 ≤ 150 → 仅经济
STD_CEIL = 500      # 150 < 包络 ≤ 500 → 经济+标准；> 500 → 全开放


def get_model_table(cfg):
    """返回合并 model_overrides 后的模型表。"""
    table = [dict(m) for m in MODEL_TABLE]
    overrides = (cfg or {}).get("model_overrides") or {}
    for m in table:
        ov = overrides.get(m["name"])
        if isinstance(ov, dict):
            if "multiplier" in ov:
                try:
                    m["multiplier"] = float(ov["multiplier"])
                except (TypeError, ValueError):
                    pass
            if "lite" in ov:
                m["lite"] = bool(ov["lite"])
            if "tier" in ov and ov["tier"] in TIER_LABEL:
                m["tier"] = ov["tier"]
    return table


def fetch_model_availability(cfg, token):
    """（可选）探测 TRAE 模型列表接口，返回 {模型名: 是否可用} 或 None。

    仅当 config.json 配置了 model_list_endpoint 才尝试；失败/未配置返回 None，
    上层将回退到内置清单。这是一个只读 GET/POST，不修改任何数据。
    """
    import requests
    endpoint = (cfg or {}).get("model_list_endpoint")
    if not endpoint:
        return None
    host = (cfg or {}).get("host", "https://api.trae.cn").rstrip("/")
    url = host + endpoint if endpoint.startswith("/") else endpoint
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Cloud-IDE-JWT {token}",
        "x-device-id": (cfg or {}).get("device_id", ""),
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code >= 400:
            r = requests.post(url, json={}, headers=headers, timeout=15)
        data = r.json()
    except Exception:
        return None

    # 启发式解析：兼容 list / {models:[]} / {data:[]} 等结构
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in ("models", "data", "list", "result", "Result"):
            v = data.get(k)
            if isinstance(v, list):
                items = v
                break
    if not items:
        return None

    out = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or it.get("model_name") or it.get("model")
                or it.get("label") or "").strip()
        if not name:
            continue
        avail = True
        for ak in ("available", "enabled", "is_available", "usable", "is_usable"):
            if ak in it:
                avail = bool(it[ak])
                break
        out[name] = avail
    return out or None


def effective_lite(m, availability):
    """结合 API 探测结果与内置清单，得到该模型 Lite 是否可用。"""
    if availability and m["name"] in availability:
        return bool(availability[m["name"]])
    return bool(m["lite"])


def recommend_models(budget, cfg, availability=None):
    """根据预算与会员限制，给出模型推荐结构。

    返回 dict:
    {
      "today_type": ..., "envelope": float, "infeasible": bool,
      "allowed_tiers": [tier...],
      "tiers": {tier: [模型dict...]},
      "lite_blocked": [模型dict...],   # Lite 不可用但可能被误选的
      "note": str,
    }
    """
    table = get_model_table(cfg)
    today_type = budget.get("today_type", "full")
    envelope = float(budget.get("suggested", 0) or 0)
    infeasible = bool(budget.get("infeasible"))
    weight = float(budget.get("today_weight", 1) or 0)

    # 允许的档位
    if today_type == "off" or weight <= 0:
        allowed = ["eco"]
    elif envelope > STD_CEIL:
        allowed = ["eco", "std", "flagship"]
    elif envelope > ECO_CEIL:
        allowed = ["eco", "std"]
    else:
        allowed = ["eco"]
    if infeasible:
        # 有积分注定浪费 → 鼓励今天尽量用旗舰烧积分
        allowed = ["eco", "std", "flagship"]

    tiers = {t: [] for t in ("eco", "std", "flagship")}
    lite_blocked = []
    for m in table:
        em = dict(m)
        em["lite_ok"] = effective_lite(m, availability)
        if not em["lite_ok"]:
            lite_blocked.append(em)
            continue
        if m["tier"] in allowed:
            tiers[m["tier"]].append(em)

    # 备注
    if infeasible:
        note = "🔴 有积分在其到期前无可用日、注定浪费，建议今天就上旗舰档加速消耗。"
    elif today_type == "off" or weight <= 0:
        note = "📚 上学日：白天不主动用；若晚上可用，用经济档省着花。"
    elif envelope <= ECO_CEIL:
        note = f"今日预算包络仅 {envelope:.0f} 积分，先用经济档，别浪费在贵模型上。"
    elif envelope <= STD_CEIL:
        note = f"今日预算包络 {envelope:.0f} 积分，经济/标准档都行，旗舰先留给硬骨头。"
    else:
        note = (f"今日预算充裕（{envelope:.0f} 积分），经济/标准档可放开用；"
                f"旗舰档受 Lite 限制，详见下方 ⛔ 提示。")

    return {
        "today_type": today_type,
        "envelope": envelope,
        "infeasible": infeasible,
        "allowed_tiers": allowed,
        "tiers": tiers,
        "lite_blocked": lite_blocked,
        "note": note,
    }


def build_model_section(budget, cfg, availability=None):
    """渲染「🤖 模型推荐」markdown 片段。"""
    rec = recommend_models(budget, cfg, availability)
    lines = [f"### 🤖 模型推荐（今日预算包络 ≈ {rec['envelope']:.0f} 积分）\n"]

    any_model = False
    for tier in ("eco", "std", "flagship"):
        models = rec["tiers"].get(tier) or []
        if not models:
            continue
        any_model = True
        names = "、".join(
            f"{m['name']}(×{m['multiplier']:.1f})" for m in models)
        lines.append(f"- {TIER_LABEL[tier]}（{TIER_HINT[tier]}）\n  {names}\n")

    if not any_model:
        lines.append("- （当前预算/日型下无推荐模型）\n")

    # Lite 不可用提示
    blocked = rec["lite_blocked"]
    if blocked:
        names = "、".join(
            f"{m['name']}(×{m['multiplier']:.1f})" for m in blocked)
        lines.append(f"- ⛔ **Lite 会员不可用**（请勿选择）：{names}\n")

    lines.append(f"- {rec['note']}\n")
    return "".join(lines)


if __name__ == "__main__":
    # 自测：用 budget.py 的模拟数据验证三种日型
    import sys
    sys.path.insert(0, str(BASE))
    from datetime import datetime, timedelta
    from budget import compute_budget

    cfg = {}
    for ds, desc in [("2026-09-02", "周三(off)"), ("2026-09-04", "周五(half)"),
                     ("2026-09-05", "周六(full)")]:
        ft = datetime.strptime(ds, "%Y-%m-%d")
        mock_packs = [
            {"name": "老用户福利", "remaining": 785,
             "expire_time": (ft + timedelta(days=6)).timestamp(),
             "expire_str": "", "alive": True},
            {"name": "会员Lite月度", "remaining": 2000,
             "expire_time": (ft + timedelta(days=7)).timestamp(),
             "expire_str": "", "alive": True},
        ]
        b = compute_budget(mock_packs, 190, today=ft)
        print(f"===== {ds} {desc} type={b['today_type']} suggested={b['suggested']} =====")
        print(build_model_section(b, cfg))
