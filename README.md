# TRAE Work 工具

实时监控你的 TRAE Work 积分消耗，深色科技风仪表盘。

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![TRAE](https://img.shields.io/badge/TRAE-Work-brightgreen)

## 功能

- 实时积分消耗监控
- 每日/每月用量统计
- 签到状态追踪
- 7天消耗趋势图
- 自动定时刷新
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

### 4. 启动服务

```bash
python serve.py
```

浏览器会自动打开监控面板。

## 命令行参数

```bash
python serve.py --port 9000      # 自定义端口
python serve.py --interval 15    # 每15分钟刷新
python serve.py --no-browser     # 不自动打开浏览器
python serve.py --no-auto        # 禁用自动刷新
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `extract_config.py` | 从 TRAE 桌面端提取配置 |
| `config.example.json` | 配置模板 |
| `trae_usage_api.py` | API 抓取脚本 |
| `serve.py` | 实时同步服务器 |
| `gen_index.py` | 生成 index.html |
| `setup.html` | 配置引导页面 |
| `trae_token.py` | TRAE 解密逻辑 |

## 注意事项

- `config.json` 包含你的认证信息，请勿公开分享
- `refresh_token` 有效期约6个月，过期后需重新运行 `extract_config.py`
- 数据存储在本地，不会上传到任何服务器

## 技术栈

- Python + requests
- TRAE 官方 API
- refresh_token 自动续期
- 纯 HTML/CSS/JS 前端

## License

MIT
