"""开学模式日历：判断每天是 全天可用(full)/半天可用(half)/上学日(off)

数据来源：
- 国务院办公厅《2026年部分节假日安排》(国办发明电〔2025〕7号)
  https://www.gov.cn/zhengce/content/202511/content_7047090.htm
- config.json: school_mode / school_start / friday_weight / winter_break_start

日型规则（school_mode=true 时）：
  full  法定节假日、周六/周日(非调休补班)、开学前、寒假开始后
  half  周五下午回家（权重 friday_weight，默认 0.5）
  off   周一~周四、调休补班的周末
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"

# 官方公布的放假日期（追加新年份时在此补充）
HOLIDAYS = {
    # 2026 中秋节 9/25~9/27（不调休）
    "2026-09-25": "中秋节",
    "2026-09-26": "中秋节",
    "2026-09-27": "中秋节",
    # 2026 国庆节 10/1~10/7
    "2026-10-01": "国庆节",
    "2026-10-02": "国庆节",
    "2026-10-03": "国庆节",
    "2026-10-04": "国庆节",
    "2026-10-05": "国庆节",
    "2026-10-06": "国庆节",
    "2026-10-07": "国庆节",
}

# 官方公布的调休补班日（这些周末要上课）
MAKEUP_WORKDAYS = {
    "2026-09-20",
    "2026-10-10",
}


def load_cfg():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_date(v):
    """兼容 datetime/date/'YYYY-MM-DD' 字符串。"""
    if isinstance(v, datetime):
        return v.date() if hasattr(v, "date") else v
    if hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def day_type(d=None):
    """返回 'full' | 'half' | 'off'。"""
    dt = d or datetime.now()
    if isinstance(dt, datetime):
        d = dt.date()
    else:
        d = dt
    key = d.strftime("%Y-%m-%d")

    cfg = load_cfg()

    # 暑期/非开学模式：全部可用
    if not cfg.get("school_mode"):
        return "full"
    try:
        school_start = _parse_date(cfg.get("school_start") or "1900-01-01")
        if d < school_start:
            return "full"
    except Exception:
        pass

    # 寒假（配置了 winter_break_start 之后全可用）
    wb = cfg.get("winter_break_start")
    if wb:
        try:
            if d >= _parse_date(wb):
                return "full"
        except Exception:
            pass

    # 法定节假日
    if key in HOLIDAYS:
        return "full"

    wd = d.weekday()  # Mon=0 ... Sun=6
    makeup = key in MAKEUP_WORKDAYS

    if wd >= 5:  # 周六日
        return "off" if makeup else "full"
    if wd == 4:  # 周五下午回家
        return "half"
    return "off"


def day_weight(d=None):
    """该日的可用权重：full=1.0, half=friday_weight(默认0.5), off=0。"""
    cfg = load_cfg()
    try:
        fw = float(cfg.get("friday_weight", 0.5))
    except Exception:
        fw = 0.5
    t = day_type(d)
    if t == "full":
        return 1.0
    if t == "half":
        return fw
    return 0.0


def day_label(d=None):
    """中文描述，用于报告标注。"""
    t = day_type(d)
    dt = d or datetime.now()
    key = dt.strftime("%Y-%m-%d") if isinstance(dt, datetime) else str(dt)
    name = HOLIDAYS.get(key, "")
    if t == "full":
        return ("节假日：" + name) if name else "休息日"
    if t == "half":
        return "周五下午回家"
    return "上学日"


if __name__ == "__main__":
    # 自测：覆盖各种日型
    tests = [
        ("2026-08-24", "暑期应full"),
        ("2026-08-31", "开学前应full"),
        ("2026-09-02", "周三应off"),
        ("2026-09-04", "周五应half"),
        ("2026-09-05", "周六应full"),
        ("2026-09-20", "补班周日应off"),
        ("2026-09-25", "中秋周五应full"),
        ("2026-10-03", "国庆周六应full"),
        ("2026-10-10", "补班周六应off"),
    ]
    for ds, expect in tests:
        d = datetime.strptime(ds, "%Y-%m-%d")
        print(f"{ds} [{['一','二','三','四','五','六','日'][d.weekday()]}] "
              f"-> {day_type(d):4s} w={day_weight(d)}  ({expect})")
