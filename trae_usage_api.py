"""TRAE 每日用量爬取（API 版）

复用 coing/trae_checkin.py 的 refresh_token 认证机制，直接调用 TRAE API
抓取最近7天的每日积分消耗数据，输出 JSON + CSV，供仪表盘卡片使用。

运行:
    python trae_usage_api.py
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # Python < 3.7
        import io
        try:
            _wrapped = io.TextIOWrapper(
                _stream.buffer, encoding="utf-8", errors="replace",
                line_buffering=_stream.line_buffering,
            )
            if _stream is sys.stdout:
                sys.stdout = _wrapped
            else:
                sys.stderr = _wrapped
        except Exception:
            pass

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"
SIGNIN_HISTORY = BASE / "trae_signin_history.json"
DAYS = 7  # 遍历最近7天


def load_config(path=None):
    path = Path(path) if path else CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {path}\n"
            "请复制 config.example.json 为 config.json 并填入你的信息\n"
            "或运行: python setup_wizard.py"
        )
    cfg = json.load(open(path, encoding="utf-8"))
    cfg.setdefault("host", "https://api.trae.cn")
    return cfg


def save_config(cfg, path=None):
    path = Path(path) if path else CONFIG_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def device_info(cfg):
    return {
        "DeviceID": cfg.get("device_id", ""),
        "MachineID": cfg.get("machine_id", ""),
        "PlatformCode": cfg.get("platform_code", "SOLO_PC"),
        "DeviceType": cfg.get("device_type", "PC"),
        "DeviceName": cfg.get("device_name", ""),
        "DeviceModel": cfg.get("device_model", ""),
        "ClientVersion": cfg.get("app_version", ""),
        "DevicePublicKey": cfg.get("public_key_pem", ""),
        "DeviceBrand": cfg.get("device_brand", ""),
        "DeviceCPU": cfg.get("device_cpu", ""),
        "OSInfo": cfg.get("os_info", ""),
        "OSVersion": cfg.get("os_version", ""),
    }


def sign_data(private_pem, payload):
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    sig = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()


def exchange_token(cfg, old_token=""):
    """用 refresh_token 换取新的 access_token。"""
    if not HAVE_CRYPTO:
        raise SystemExit("cryptography 库未安装，无法续期 token")
    host = cfg["host"].rstrip("/")
    client_id = cfg["client_id"]
    refresh_token = cfg["refresh_token"]
    path = "/trae/api/v3/oauth/ExchangeToken"
    url = host + path

    timestamp = int(time.time())
    nonce = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    to_sign = f"POST\n{path}\n{client_id}\n{refresh_token}\n{timestamp}\n{nonce}"
    signature = sign_data(cfg["private_key_pem"], to_sign.encode())

    body = {
        "ClientID": client_id,
        "ClientSecret": "",
        "RefreshToken": refresh_token,
        "DeviceInfo": device_info(cfg),
        "DeviceProof": {"Signature": signature, "Timestamp": timestamp, "Nonce": nonce},
        "IDEVersion": cfg.get("app_version", ""),
    }
    headers = {
        "Content-Type": "application/json",
        "x-cloudide-token": old_token,
    }
    r = requests.post(url, json=body, headers=headers, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:500]}
    return r.status_code, data


def api_request(cfg, path, token, body=None):
    url = cfg["host"].rstrip("/") + path
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Cloud-IDE-JWT {token}",
        "x-device-id": cfg.get("device_id", ""),
    }
    return requests.post(url, json=body or {}, headers=headers, timeout=30)


def get_valid_token(cfg):
    """返回有效 token，必要时自动续期。"""
    tok = cfg.get("access_token", "")
    if tok:
        try:
            r = api_request(cfg, "/trae/api/v2/ug/checkin_credits/status", tok)
            if r.json().get("code") == 0:
                return tok
        except Exception:
            pass
    log("access_token 失效，正在续期...")
    code, data = exchange_token(cfg, cfg.get("access_token", ""))
    result = (data or {}).get("Result") or {}
    if code != 200 or not result.get("Token"):
        log(f"token 续期失败: HTTP {code} -> {json.dumps(data, ensure_ascii=False)[:300]}")
        raise SystemExit("无法续期 token")
    cfg["access_token"] = result["Token"]
    if result.get("RefreshToken"):
        cfg["refresh_token"] = result["RefreshToken"]
    save_config(cfg)
    log("token 续期成功")
    return cfg["access_token"]


def _day_bounds(days_ago=0):
    """返回某一天(本地时区)的 [开始, 结束] 时间戳。"""
    d = datetime.now() - timedelta(days=days_ago)
    start = datetime(d.year, d.month, d.day, 0, 0, 0)
    end = datetime(d.year, d.month, d.day, 23, 59, 59)
    return int(start.timestamp()), int(end.timestamp())


def fetch_daily_session_usage(cfg, token, days_ago=0):
    """获取某一天的每会话积分消耗。返回 (总消耗, 会话数, 明细列表)。"""
    start_ts, end_ts = _day_bounds(days_ago)
    try:
        page = 1
        total = 0.0
        sessions = []
        while True:
            body = {
                "start_time": start_ts,
                "end_time": end_ts,
                "page_size": 20,
                "page_num": page,
                "usage_type": [7],
            }
            r = api_request(cfg, "/trae/api/v1/pay/query_user_usage_group_by_session",
                            token, body=body)
            d = r.json()
            page_sess = d.get("user_usage_group_by_sessions") or []
            sessions.extend(page_sess)
            for s in page_sess:
                try:
                    total += float(s.get("credits_float") or 0)
                except (TypeError, ValueError):
                    pass
            count = d.get("total") or 0
            if page * 20 >= count or not page_sess or page > 10:
                break
            page += 1
        lines = []
        for s in sessions:
            try:
                c = float(s.get("credits_float") or 0)
                model = s.get("model_name") or "?"
                t = s.get("usage_time") or 0
                tm = datetime.fromtimestamp(t).strftime("%H:%M") if t else ""
                lines.append({"time": tm, "model": model, "credits": c})
            except Exception:
                continue
        return round(total, 2), len(sessions), lines
    except Exception as e:
        log(f"获取 {days_ago} 天前用量失败: {e}")
        return 0.0, 0, []


def fetch_month_grouped(cfg, token):
    """一次调用拿整月(当月1号~今天)全部会话，按日期分组。

    返回 dict: {"2026-08-13": {"consumed": float, "sessions": int}, ...}
    """
    now = datetime.now()
    start = datetime(now.year, now.month, 1, 0, 0, 0)
    end = datetime(now.year, now.month, now.day, 23, 59, 59)
    grouped = {}
    try:
        page = 1
        while True:
            body = {
                "start_time": int(start.timestamp()),
                "end_time": int(end.timestamp()),
                "page_size": 20,
                "page_num": page,
                "usage_type": [7],
            }
            r = api_request(cfg, "/trae/api/v1/pay/query_user_usage_group_by_session",
                            token, body=body)
            d = r.json()
            page_sess = d.get("user_usage_group_by_sessions") or []
            if not page_sess:
                break
            for s in page_sess:
                t = s.get("usage_time") or 0
                if not t:
                    continue
                day = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
                g = grouped.setdefault(day, {"consumed": 0.0, "sessions": 0})
                try:
                    g["consumed"] += float(s.get("credits_float") or 0)
                except (TypeError, ValueError):
                    pass
                g["sessions"] += 1
            total = d.get("total") or 0
            if page * 20 >= total or page > 10:
                break
            page += 1
        for g in grouped.values():
            g["consumed"] = round(g["consumed"], 2)
        return grouped
    except Exception as e:
        log(f"获取整月用量失败: {e}")
        return {}


def load_signin_history():
    if SIGNIN_HISTORY.exists():
        try:
            return json.loads(SIGNIN_HISTORY.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_signin_history(hist):
    SIGNIN_HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def compute_continuous_days(hist, today_str):
    """从历史记录里计算截止今天(含今天)的连续签到天数。"""
    days = 0
    dt = datetime.strptime(today_str, "%Y-%m-%d")
    for i in range(365):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if hist.get(d) is True:
            days += 1
        elif i == 0:
            continue  # 今天还没记录时不断裂，从昨天开始往前数
        else:
            break
    return days


def fetch_credit_usage(cfg, token):
    """获取总积分 / 已消耗 / 剩余。"""
    try:
        r = api_request(cfg, "/trae/api/v2/pay/ide_user_ent_usage", token,
                        body={"require_usage": True, "req_source": 2})
        d = r.json()
        if d.get("code") not in (None, 0):
            return None
        packs = d.get("user_entitlement_pack_list") or []
        total_limit = 0.0
        total_used = 0.0
        lines = []
        for p in packs:
            bi = p.get("entitlement_base_info") or {}
            q = bi.get("quota") or {}
            us = p.get("usage") or {}
            try:
                limit = float(q.get("credits_limit") or 0)
            except (TypeError, ValueError):
                limit = 0.0
            try:
                used = float(us.get("credits_amount") or 0)
            except (TypeError, ValueError):
                used = 0.0
            total_limit += limit
            total_used += used
            if used > 0:
                lines.append({
                    "name": p.get("display_desc") or p.get("group_name") or "权益",
                    "limit": limit,
                    "used": used,
                    "remaining": limit - used,
                })
        return {
            "total_limit": total_limit,
            "total_used": total_used,
            "remaining": max(total_limit - total_used, 0),
            "packs": lines,
        }
    except Exception as e:
        log(f"获取总量失败: {e}")
        return None


def fetch_checkin_status(cfg, token):
    """获取签到状态。"""
    try:
        r = api_request(cfg, "/trae/api/v2/ug/checkin_credits/status", token)
        d = r.json()
        if d.get("code") != 0:
            return None
        return {
            "checked_in": d.get("checked_in"),
            "credits": d.get("credits"),
            "raw": {k: v for k, v in d.items()
                    if k in ("checked_in", "credits", "continuous_days",
                             "consecutive_days", "sign_days", "total_days",
                             "week_list", "sign_list", "has_signed", "next_credits")},
        }
    except Exception as e:
        log(f"获取签到状态失败: {e}")
        return None


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def main():
    parser = argparse.ArgumentParser(description="TRAE 每日用量爬取(API版)")
    parser.add_argument("--days", type=int, default=DAYS, help="抓取天数(默认7)")
    args = parser.parse_args()

    print("=" * 55)
    print("TRAE 每日用量爬取 (API版)")
    print("=" * 55)

    cfg = load_config()
    token = get_valid_token(cfg)
    log("token 有效，开始抓取...")

    # 1. 总量信息
    usage = fetch_credit_usage(cfg, token)
    if usage:
        log(f"总量: 总额{usage['total_limit']:.0f} / 已耗{usage['total_used']:.0f} / 剩余{usage['remaining']:.0f}")

    # 2. 签到状态 + 连续签到天数
    checkin = fetch_checkin_status(cfg, token)
    hist = load_signin_history()
    today_str = datetime.now().strftime("%Y-%m-%d")
    checked_in = bool(checkin and checkin["checked_in"])
    hist[today_str] = checked_in
    save_signin_history(hist)
    continuous_days = compute_continuous_days(hist, today_str)
    if checkin:
        checkin["continuous_days"] = continuous_days
        log(f"签到: checked_in={checkin['checked_in']}, 积分={checkin['credits']}, 连续签到={continuous_days}天")

    # 3. 整月数据(一次API调用，按天分组)
    month_grouped = fetch_month_grouped(cfg, token)
    month_total = round(sum(g["consumed"] for g in month_grouped.values()), 2)

    # 4. 遍历最近 N 天
    daily = []
    for days_ago in range(args.days - 1, -1, -1):
        date_str = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        mg = month_grouped.get(date_str, {"consumed": 0.0, "sessions": 0})
        total, count, lines = fetch_daily_session_usage(cfg, token, days_ago)
        daily.append({
            "date": date_str,
            "days_ago": days_ago,
            "consumed": round(total, 2) or mg["consumed"],
            "sessions": count or mg["sessions"],
            "details": lines,
        })
        log(f"{date_str}: 消耗 {total:.2f} 积分 ({count} 会话)")

    # 5. 输出 JSON
    result = {
        "user": {"user_id": "719548110874768", "username": "用户94336119047", "product": "solo"},
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall_usage": usage,
        "checkin": checkin,
        "month_total": month_total,
        "continuous_days": continuous_days,
        "daily": daily,
    }
    json_file = BASE / "trae_usage_data.json"
    json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✓ 数据已保存: {json_file}")

    # 6. 输出 CSV
    csv_file = BASE / "trae_usage_daily.csv"
    import csv
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["日期", "消耗积分", "会话数"])
        for d in daily:
            writer.writerow([d["date"], d["consumed"], d["sessions"]])
    log(f"✓ CSV已保存: {csv_file}")
    log(f"本月累计消耗: {month_total} 积分")

    # 7. 钉钉通知
    try:
        from dingtalk import send_text, send_markdown, notify_daily_usage
        today_consumed = daily[-1]["consumed"] if daily else 0
        today_sessions = daily[-1]["sessions"] if daily else 0
        remaining = usage["remaining"] if usage else 0

        # 每日用量报告
        send_markdown(
            "TRAE 每日报告",
            f"### TRAE 用量报告\n\n"
            f"- **今日消耗**: {today_consumed:.1f} 积分 ({today_sessions} 会话)\n"
            f"- **本月累计**: {month_total:.1f} 积分\n"
            f"- **剩余积分**: {remaining:.0f}\n"
            f"- **签到状态**: {'已签到 +200' if checked_in else '未签到'}\n"
            f"- **连续签到**: {continuous_days} 天\n"
        )

        # 用量异常提醒
        threshold = 200
        try:
            cfg_check = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            threshold = cfg_check.get("daily_consumption_alert_threshold", 200)
        except Exception:
            pass
        notify_daily_usage(today_consumed, threshold)

    except ImportError:
        pass  # dingtalk.py 不存在，跳过通知
    except Exception as e:
        log(f"钉钉通知失败: {e}")

    print("=" * 55)
    print("完成！")


if __name__ == "__main__":
    main()
