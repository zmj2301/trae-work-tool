"""TRAE 用量监控 — 实时同步服务器

功能：
  1. 定时自动抓取（默认每30分钟调用 trae_usage_api.py）
  2. /api/data   → 返回最新 JSON 数据
  3. /api/refresh → 手动触发一次抓取
  4. /api/history → 返回签到历史
  5. 首页 → 深色科技风仪表盘卡片

运行：
    python serve.py              # 默认端口 8080
    python serve.py --port 9000  # 自定义端口
    python serve.py --interval 15  # 每15分钟刷新一次
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_FILE = BASE / "trae_usage_data.json"
HIST_FILE = BASE / "trae_signin_history.json"
CONFIG_FILE = BASE / "config.json"
API_SCRIPT = BASE / "trae_usage_api.py"
HTML_FILE = BASE / "index.html"
SETUP_FILE = BASE / "setup.html"

_auto_refresh_interval = 30  # minutes
_last_refresh = {"time": 0, "running": False, "last_ok": False}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def has_config():
    """Check if config.json exists and has required fields."""
    if not CONFIG_FILE.exists():
        return False
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return bool(cfg.get("refresh_token"))
    except Exception:
        return False


def run_api_script():
    """Run trae_usage_api.py, return (ok, elapsed_seconds)."""
    if _last_refresh["running"]:
        return False, 0
    _last_refresh["running"] = True
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(API_SCRIPT)],
            capture_output=True, timeout=300,
            cwd=str(BASE),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        elapsed = round(time.time() - t0, 1)
        ok = r.returncode == 0 and "完成" in (
            r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        )
        _last_refresh["last_ok"] = ok
        _last_refresh["time"] = time.time()
        log(f"API 刷新 {'成功' if ok else '失败'} ({elapsed}s)")
        return ok, elapsed
    except subprocess.TimeoutExpired:
        log("API 刷新超时 (300s)")
        _last_refresh["last_ok"] = False
        return False, 300
    except Exception as e:
        log(f"API 刷新异常: {e}")
        _last_refresh["last_ok"] = False
        return False, 0
    finally:
        _last_refresh["running"] = False


def auto_refresh_worker(interval_minutes):
    """Background thread: refresh data periodically."""
    log(f"自动刷新已启动，间隔 {interval_minutes} 分钟")
    while True:
        time.sleep(interval_minutes * 60)
        run_api_script()


def get_data_json():
    """Read and return the latest data JSON, or fallback."""
    try:
        return DATA_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return json.dumps({"error": "数据文件不存在，请先运行 trae_usage_api.py"})


def get_hist_json():
    try:
        return HIST_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return json.dumps({})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(directory or BASE), **kwargs)

    def do_GET(self):
        # --- API 路由 ---
        if self.path == "/api/data":
            self._json_response(get_data_json())
            return
        if self.path == "/api/history":
            self._json_response(get_hist_json())
            return
        if self.path == "/api/status":
            self._json_response(json.dumps({
                "ok": True,
                "has_config": has_config(),
                "auto_refresh_minutes": _auto_refresh_interval,
                "last_refresh": _last_refresh["time"],
                "last_ok": _last_refresh["last_ok"],
                "running": _last_refresh["running"],
                "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }))
            return
        if self.path == "/api/refresh":
            if not has_config():
                self._json_response(json.dumps({"ok": False, "error": "未配置，请先运行 extract_config.py"}))
                return
            self._json_response(json.dumps({"ok": True, "message": "抓取已启动，请等待约60秒后刷新页面"}))
            threading.Thread(target=run_api_script, daemon=True).start()
            return
        # --- 首页 ---
        if self.path in ("/", "/index.html"):
            if not has_config():
                self._serve_file(SETUP_FILE, "setup.html")
            else:
                self._serve_file(HTML_FILE, "index.html")
            return
        if self.path == "/setup":
            self._serve_file(SETUP_FILE, "setup.html")
            return
        return super().do_GET()

    def _serve_file(self, path, fallback_name):
        try:
            html = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            html = f"<h1>{fallback_name} 不存在</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _json_response(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # suppress default logging


def main():
    global _auto_refresh_interval
    parser = argparse.ArgumentParser(description="TRAE 用量监控服务器")
    parser.add_argument("--port", type=int, default=8080, help="端口 (默认 8080)")
    parser.add_argument("--interval", type=int, default=30, help="自动刷新间隔分钟 (默认 30)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--no-auto", action="store_true", help="禁用自动刷新")
    args = parser.parse_args()

    _auto_refresh_interval = args.interval

    # 检查配置
    if not has_config():
        log("未检测到 config.json，将显示配置页面")
        log("请运行 python extract_config.py 提取配置")
    elif not DATA_FILE.exists():
        log("首次运行，抓取数据...")
        run_api_script()
    else:
        log("已存在数据文件，跳过首次抓取")

    # 启动自动刷新线程
    if not args.no_auto:
        t = threading.Thread(target=auto_refresh_worker, args=(args.interval,), daemon=True)
        t.start()

    # 启动 HTTP 服务器
    server = HTTPServer(("0.0.0.0", args.port), lambda *a, **k: Handler(*a, **k))
    url = f"http://127.0.0.1:{args.port}"
    log(f"服务器启动: {url}")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
