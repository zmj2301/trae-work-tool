"""TRAE Work 配置提取工具

在你的 Windows 电脑上运行（需要已安装并登录 TRAE Work），自动提取：
- refresh_token（用于 API 认证，有效期约6个月）
- 设备密钥对（用于签名）
- 设备信息

运行后会生成 config.json，然后就可以启动监控面板了。

用法:
    python extract_config.py
"""
import json
import sys
from pathlib import Path

try:
    from trae_token import load_auth_info, find_storage_json
except ImportError:
    print("错误: 缺少 trae_token.py")
    print("请确保 trae_token.py 在同一目录下")
    sys.exit(1)

OUT = Path(__file__).parent / "config.json"


def get_machine_id():
    store = json.load(open(find_storage_json(), encoding="utf-8"))
    return store.get("telemetry.machineId", "")


def main():
    print("=" * 50)
    print("TRAE Work 配置提取工具")
    print("=" * 50)
    print()

    try:
        info = load_auth_info()
    except FileNotFoundError as e:
        print(f"错误: {e}")
        print("请确保 TRAE Work 已安装并登录")
        sys.exit(1)

    # 解析认证信息
    auth = None
    for k, v in info.items():
        if k.endswith("icube.cloudide"):
            try:
                auth = json.loads(v.strip("\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
            except Exception:
                pass
            break

    if not auth:
        print("错误: 未找到认证信息")
        print("请确保 TRAE Work 已登录")
        sys.exit(1)

    # 解析设备信息
    device = None
    for k, v in info.items():
        if "icube-dc:" in k:
            try:
                device = json.loads(v.strip("\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
            except Exception:
                pass
            break

    # 获取 device_id
    device_id = None
    for k in info:
        if "icube-dc:" in k:
            device_id = k.rsplit(":", 1)[-1]
            break

    # 读取旧配置（如果有）
    old_cfg = {}
    if OUT.exists():
        try:
            old_cfg = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 构建配置
    cfg = {
        "host": auth.get("host", "https://api.trae.cn"),
        "device_id": device_id or "",
        "machine_id": get_machine_id(),
        "client_id": old_cfg.get("client_id") or "en1oxy7wnw8j9n",
        "app_version": old_cfg.get("app_version") or "0.1.48",
        "platform_code": "SOLO_PC",
        "device_type": "PC",
        "device_name": old_cfg.get("device_name") or "",
        "device_model": old_cfg.get("device_model") or "",
        "device_brand": old_cfg.get("device_brand") or "",
        "device_cpu": old_cfg.get("device_cpu") or "",
        "os_info": old_cfg.get("os_info") or "windows",
        "os_version": old_cfg.get("os_version") or "",
        "refresh_token": auth.get("refreshToken", ""),
        "access_token": auth.get("token", ""),
        "token_expired_at": auth.get("expiredAt", 0),
        "private_key_pem": (device or {}).get("privateKeyPEM", ""),
        "public_key_pem": (device or {}).get("publicKeyPEM", ""),
    }

    # 写入配置文件
    OUT.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("配置提取成功！")
    print()
    print(f"  用户ID: {auth.get('userId', '未知')}")
    print(f"  设备ID: {device_id or '未知'}")
    print(f"  机器ID: {cfg['machine_id'][:16]}...")
    print(f"  Token过期: {auth.get('expiredAt', '未知')}")
    print(f"  Refresh过期: {auth.get('refreshExpiredAt', '未知')}")
    print()
    print(f"配置已保存到: {OUT}")
    print()
    print("下一步:")
    print("  1. 编辑 config.json，填入你的 user_id 和 username")
    print("     (从 TRAE 仪表盘 URL 中获取)")
    print("  2. 运行 python serve.py 启动监控面板")


if __name__ == "__main__":
    main()
