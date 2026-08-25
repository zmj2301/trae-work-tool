"""模型推荐：根据当日预算额度与 Lite 会员限制，推荐合适的模型档位。

适用版本：TRAE 国内版（api.trae.cn / solo）。
模型倍率为用户模型选择器截图中的真实值（2026-08-25 确认），
其中 Kimi-K3 带 🔒 图标，为 Lite 会员不可用模型。

设计（用户确认）：
- 「Lite 不能用的模型」名单 = API 探测 + 内置清单（两者结合）
- 推荐结果 = 具体模型名（含真实消耗倍率）
- 触发依据 = 今日剩余预算（来自 budget.py 的 suggested）

数据源：
1. MODEL_TABLE：模型清单（真实倍率 / Lite可用性 / 标签），来自选择器截图
2. config.json 的 model_overrides：用户手动纠正（倍率 / Lite可用性 / 档位）
3. config.json 的 model_list_endpoint（可选）：TRAE 模型列表接口，运行时探测
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent

# 倍率 = 模型选择器显示的真实值（会员2.5折/专属补贴已体现在显示倍率中）
# tier: eco=经济, std=标准, high=高配, flagship=旗舰
# lite: Lite 会员是否可用（Kimi-K3 截图带锁，确认不可用）
MODEL_TABLE = [
    # —— 经济档（≤0.10x，最省）——
    {"name": "Seed-Code",               "tier": "eco",      "multiplier": 0.03, "lite": True,  "tag": "会员2.5折", "caps": "编程"},
    {"name": "DeepSeek-V4-Flash",       "tier": "eco",      "multiplier": 0.08, "lite": True,  "tag": "", "caps": "编程"},
    {"name": "DeepSeek-V4-Flash 正式版", "tier": "eco",      "multiplier": 0.08, "lite": True,  "tag": "", "caps": "编程"},
    {"name": "Seed-2.1-Turbo",          "tier": "eco",      "multiplier": 0.10, "lite": True,  "tag": "会员2.5折", "caps": "推理"},

    # —— 标准档（0.25–0.40x，均衡）——
    {"name": "Qwen3.7-Plus",            "tier": "std",      "multiplier": 0.25, "lite": True,  "tag": "", "caps": "推理"},
    {"name": "MiniMax-M3",              "tier": "std",      "multiplier": 0.26, "lite": True,  "tag": "", "caps": "推理"},
    {"name": "GLM-5.3",                 "tier": "std",      "multiplier": 0.40, "lite": True,  "tag": "专属补贴", "caps": "编程,推理"},
    {"name": "GLM-5.2",                 "tier": "std",      "multiplier": 0.40, "lite": True,  "tag": "专属补贴", "caps": "编程,推理"},

    # —— 高配档（0.6–0.8x，强力）——
    {"name": "Kimi-K2.7-Code",          "tier": "high",     "multiplier": 0.62, "lite": True,  "tag": "", "caps": "编程"},
    {"name": "Kimi-K2.6",               "tier": "high",     "multiplier": 0.69, "lite": True,  "tag": "", "caps": "推理"},
    {"name": "DeepSeek-V4-Pro",         "tier": "high",     "multiplier": 0.72, "lite": True,  "tag": "", "caps": "编程,推理"},
    {"name": "DeepSeek-V4-Pro 正式版",  "tier": "high",      "multiplier": 0.72, "lite": True,  "tag": "", "caps": "编程,推理"},
    {"name": "Seed-2.1-Pro",            "tier": "high",     "multiplier": 0.77, "lite": True,  "tag": "", "caps": "推理"},

    # —— 旗舰档（≥1.5x，最强最贵）——
    {"name": "Qwen3.8-Max",             "tier": "flagship", "multiplier": 1.50, "lite": True,  "tag": "", "caps": "推理"},
    {"name": "Kimi-K3",                 "tier": "flagship", "multiplier": 1.65, "lite": False, "tag": "", "caps": "推理"},  # 🔒 Lite 不可用
]

TIER_ORDER = ("eco", "std", "high", "flagship")
TIER_LABEL = {
    "eco": "🟢 经济档", "std": "🔵 标准档",
    "high": "🟠 高配档", "flagship": "🟣 旗舰档",
}
TIER_HINT = {
    "eco": "日常/简单任务，最省（Seed 系列 Lite 2.5折）",
    "std": "均衡之选（GLM/MiniMax 有专属补贴）",
    "high": "强力模型（Kimi / DeepSeek-Pro / Seed-Pro）",
    "flagship": "最强但最贵",
}

# 预算包络（今日 suggested）-> 允许档位
ECO_CEIL = 150      # >150  → +标准档
HIGH_CEIL = 300     # >300  → +高配档
FLAG_CEIL = 500     # >500  → +旗舰档


def _fmt(x):
    """倍率显示：去掉多余的 0（0.03→0.03, 0.40→0.4, 1.50→1.5）。"""
    s = f"{float(x):.2f}".rstrip("0").rstrip(".")
    return s or "0"


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

    仅当 config.json 配置了 model_list_endpoint 才尝试；失败/未配置返回 None。
    只读 GET/POST，不修改任何数据。
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
    """根据预算与会员限制，给出模型推荐结构。"""
    table = get_model_table(cfg)
    today_type = budget.get("today_type", "full")
    envelope = float(budget.get("suggested", 0) or 0)
    infeasible = bool(budget.get("infeasible"))
    weight = float(budget.get("today_weight", 1) or 0)

    if today_type == "off" or weight <= 0:
        allowed = ["eco"]
    elif infeasible or envelope > FLAG_CEIL:
        allowed = list(TIER_ORDER)
    elif envelope > HIGH_CEIL:
        allowed = ["eco", "std", "high"]
    elif envelope > ECO_CEIL:
        allowed = ["eco", "std"]
    else:
        allowed = ["eco"]

    tiers = {t: [] for t in TIER_ORDER}
    lite_blocked = []
    for m in table:
        em = dict(m)
        em["lite_ok"] = effective_lite(m, availability)
        if not em["lite_ok"]:
            lite_blocked.append(em)
            continue
        if m["tier"] in allowed:
            tiers[m["tier"]].append(em)

    if infeasible:
        note = "🔴 有积分在其到期前无可用日、注定浪费，建议今天就上高配/旗舰加速消耗。"
    elif today_type == "off" or weight <= 0:
        note = "📚 上学日：白天不主动用；若晚上可用，用经济档省着花。"
    elif envelope <= ECO_CEIL:
        note = f"今日预算包络仅 {envelope:.0f} 积分，用经济档（×0.1 级别）足够。"
    elif envelope <= HIGH_CEIL:
        note = f"今日预算包络 {envelope:.0f} 积分，经济/标准档都行。"
    elif envelope <= FLAG_CEIL:
        note = f"今日预算包络 {envelope:.0f} 积分，可上高配档，旗舰留给硬骨头。"
    else:
        note = (f"今日预算充裕（{envelope:.0f} 积分），全档开放；"
                f"Kimi-K3 为 Lite 锁定不可用。")

    return {
        "today_type": today_type,
        "envelope": envelope,
        "infeasible": infeasible,
        "allowed_tiers": allowed,
        "tiers": tiers,
        "lite_blocked": lite_blocked,
        "note": note,
    }


def _model_label(m):
    """模型显示名：Seed-Code(×0.03, 会员2.5折)。"""
    s = f"{m['name']}(×{_fmt(m['multiplier'])}"
    if m.get("tag"):
        s += f", {m['tag']}"
    return s + ")"


def build_model_section(budget, cfg, availability=None):
    """渲染「🤖 模型推荐」markdown 片段。"""
    rec = recommend_models(budget, cfg, availability)
    lines = [f"### 🤖 模型推荐（今日预算包络 ≈ {rec['envelope']:.0f} 积分）\n"]

    any_model = False
    for tier in TIER_ORDER:
        models = rec["tiers"].get(tier) or []
        if not models:
            continue
        any_model = True
        names = "、".join(_model_label(m) for m in models)
        lines.append(f"- {TIER_LABEL[tier]}（{TIER_HINT[tier]}）\n  {names}\n")

    if not any_model:
        lines.append("- （当前预算/日型下无推荐模型）\n")

    blocked = rec["lite_blocked"]
    if blocked:
        names = "、".join(_model_label(m) for m in blocked)
        lines.append(f"- ⛔ **Lite 会员不可用**（请勿选择）：{names}\n")

    lines.append(f"- {rec['note']}\n")
    return "".join(lines)


if __name__ == "__main__":
    # 自测：用 budget.py 的模拟数据验证四种日型/预算场景
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
