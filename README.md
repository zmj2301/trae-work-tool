# TRAE Work 工具

实时监控你的 TRAE Work 积分消耗，深色科技风仪表盘。

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![TRAE](https://img.shields.io/badge/TRAE-Work-brightgreen)

## 功能

- 实时积分消耗监控
- 每日/每月用量统计
- 签到状态追踪
- 7天消耗趋势图
- CSV 导出

## 快速开始

### 1. 安装依赖

```bash
pip install requests cryptography
```

### 2. 提取配置

在你的 Windows 电脑上运行（需要已登录 TRAE Work）：

```bash
python extract_config.py
```

这会自动从 TRAE 桌面端提取认证信息，生成 `config.json`。

### 3. 填写用户信息

编辑 `config.json`，填入你的 `user_id` 和 `username`。

从 TRAE 仪表盘 URL 获取：
```
https://www.trae.cn/dashboard?user_id=你的ID&username=你的用户名&product=solo#usage
```

### 4. 抓取数据

```bash
python trae_usage_api.py
```

### 5. 查看结果（二选一）

#### 方式 A：静态页面（推荐，简单）

```bash
python gen_index.py
```

双击生成的 `trae_usage_card.html` 即可查看，无需服务器。

#### 方式 B：实时服务器（可选，支持自动刷新）

```bash
python serve.py
```

浏览器自动打开 `http://127.0.0.1:8080`，支持：
- 每30分钟自动抓取
- 点击「立即抓取」手动刷新
- 每60秒自动检测更新

## 命令行参数

### serve.py（可选）

```bash
python serve.py --port 9000      # 自定义端口
python serve.py --interval 15    # 每15分钟刷新
python serve.py --no-browser     # 不自动打开浏览器
python serve.py --no-auto        # 禁用自动刷新
```

### trae_usage_api.py

```bash
python trae_usage_api.py              # 抓取最近7天
python trae_usage_api.py --days 30    # 抓取最近30天
```

### gen_index.py

```bash
python gen_index.py           # 生成静态页面（可直接打开）
python gen_index.py --server  # 生成服务器版页面（配合 serve.py）
```

## 两种模式对比

| | 静态模式 | 服务器模式 |
|--|---------|-----------|
| 命令 | `python gen_index.py` | `python serve.py` |
| 打开方式 | 双击 HTML 文件 | 浏览器访问 localhost |
| 自动刷新 | 需手动重新运行 | 自动定时刷新 |
| 点击抓取 | 不支持 | 支持 |
| 依赖 | 仅 Python | 仅 Python |
| 适合场景 | 偶尔查看 | 持续监控 |

## 文件说明

| 文件 | 说明 | 必需 |
|------|------|------|
| `extract_config.py` | 从 TRAE 桌面端提取配置 | 首次使用 |
| `config.json` | 你的认证信息（不上传） | 是 |
| `config.example.json` | 配置模板 | 否 |
| `trae_usage_api.py` | API 抓取脚本 | 是 |
| `gen_index.py` | 生成 HTML 页面 | 是 |
| `trae_usage_card.html` | 生成的静态页面 | 否（自动生成） |
| `serve.py` | 实时服务器 | 可选 |
| `trae_token.py` | TRAE 解密逻辑 | 是 |

## 注意事项

- `config.json` 包含你的 `refresh_token` 和私钥，请勿公开分享
- `refresh_token` 有效期约6个月，过期后需重新运行 `extract_config.py`
- 数据存储在本地，不会上传到任何服务器
- 建议将 `config.json` 加入 `.gitignore`

## 技术栈

- Python + requests
- TRAE 官方 API
- refresh_token 自动续期
- 纯 HTML/CSS/JS 前端

## License

MIT
