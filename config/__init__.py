"""
期货交易系统 V2 — 全局配置
"""

import os
from pathlib import Path

# ─── 项目路径 ──────────────────────────────────────────────
# __file__ 现在在 config/ 目录下，需要向上回溯一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# ─── 分析模式 ──────────────────────────────────────────────
# "rules" — 规则引擎模式（默认）
# "llm"   — LLM 模式（需配置 LLM API）
ANALYSIS_MODE = os.getenv("ANALYSIS_MODE", "rules")

# ─── LLM 配置（仅 LLM 模式时需要） ─────────────────────────
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# ─── 数据路径 ──────────────────────────────────────────────
DATA_CURRENT = DATA_DIR / "current" / "dashboard_data.json"
DATA_HISTORY_DAILY = DATA_DIR / "history" / "daily"
DATA_HISTORY_MINUTELY = DATA_DIR / "history" / "minutely"
DATA_EVENTS = DATA_DIR / "events" / "latest_feed.json"

# ─── 采集器配置 ────────────────────────────────────────────
COLLECTOR_INTERVALS = {
    "gold_silver": 5 * 60,      # 5 分钟
    "daily": 86400,             # 每日
    "rss_news": 30 * 60,        # 30 分钟
}

# ─── 飞书配置 ──────────────────────────────────────────────
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_WEBHOOK_PORT = int(os.getenv("FEISHU_WEBHOOK_PORT", "8080"))

# ─── V2 命令前缀 ──────────────────────────────────────────
V2_COMMANDS = ["归因", "趋势", "宏观", "事件", "监控", "预测"]


def validate_config() -> list:
    """
    启动时验证关键配置，返回缺失/错误的配置项列表。
    调用方根据返回值决定是否继续启动。
    """
    issues = []

    if ANALYSIS_MODE not in ("rules", "llm"):
        issues.append(f"ANALYSIS_MODE 无效: '{ANALYSIS_MODE}'，应为 'rules' 或 'llm'")

    if ANALYSIS_MODE == "llm":
        if not LLM_API_KEY:
            issues.append("LLM 模式需要配置 LLM_API_KEY（环境变量）")
        if not LLM_API_URL:
            issues.append("LLM 模式需要配置 LLM_API_URL")

    if FEISHU_APP_ID and not FEISHU_APP_SECRET:
        issues.append("已配置 FEISHU_APP_ID 但未配置 FEISHU_APP_SECRET")

    if FEISHU_APP_SECRET and not FEISHU_APP_ID:
        issues.append("已配置 FEISHU_APP_SECRET 但未配置 FEISHU_APP_ID")

    return issues
