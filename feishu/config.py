"""
feishu/config.py — 飞书推送模块自包含配置

环境变量:
    FEISHU_BOT_WEBHOOK_URL: 飞书自定义机器人 Webhook 地址
    FEISHU_BOT_SECRET:       签名密钥（可选，创建机器人时获得）
"""

import os
from pathlib import Path

# 当前模块所在目录（feishu/），用于定位项目根目录
_MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _MODULE_DIR.parent

# Webhook 配置
WEBHOOK_URL = os.getenv("FEISHU_BOT_WEBHOOK_URL", "")
SECRET = os.getenv("FEISHU_BOT_SECRET", "")

# 项目数据路径（仅 push_morning_brief 等需要读数据时用）
DATA_DIR = PROJECT_ROOT / "data"
FACTORS_DIR = DATA_DIR / "factors"
EVENTS_DIR = DATA_DIR / "events"
CURRENT_DIR = DATA_DIR / "current"
