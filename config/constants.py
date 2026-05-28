"""项目常量配置

集中管理所有硬编码值，避免魔法数字和分散配置。
"""

# ============ API 配置 ============

# Dashboard API 默认配置
API_DEFAULT_PORT = 8082
API_MAX_DATA_POINTS = 200  # 历史数据最大返回点数

# Yahoo Finance 符号映射
YAHOO_SYMBOLS = {
    "dxy": "DX-Y.NYB",
    "treasury": "^TNX",  # 10Y
    "vix": "^VIX",
    "gold": "GC=F",
    "silver": "SI=F",
}

# 数据采集间隔（秒）
COLLECTOR_INTERVALS = {
    "gold_silver": 5 * 60,      # 5 分钟
    "yahoo_finance": 5 * 60,    # 5 分钟
    "daily": 86400,             # 每日
    "rss_news": 30 * 60,        # 30 分钟
}

# ============ 文件路径配置 ============

# 数据目录结构
DATA_PATHS = {
    "snapshot": "data/current/dashboard_data.json",
    "history_daily": "data/history/daily",
    "history_minutely": "data/history/minutely",
    "events": "data/events",
    "sources": "data/sources/source_registry.json",
}

# 日志目录
LOG_DIR = "logs"

# ============ 预测模块配置 ============

# 预测周期配置
PREDICTION_HORIZONS = {
    "short_term": {"days": 7, "label": "1周内"},
    "mid_term": {"days": 28, "label": "1-4周"},
    "long_term": {"days": 365, "label": "1-12月"},
}

# 预测波动率参数
PREDICTION_VOLATILITY = {
    "short": 0.02,   # 短期波动率 2%
    "mid": 0.03,     # 中期波动率 3%
    "long": 0.15,    # 长期波动率 15%
}

# 方向标签映射
DIRECTION_LABELS = {
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "中性",
    "mixed": "多空交织",
    "slightly_bullish": "略偏多",
    "slightly_bearish": "略偏空",
}

DIRECTION_ARROWS = {
    "bullish": "↑",
    "bearish": "↓",
    "neutral": "-",
    "mixed": "-",
    "slightly_bullish": "↑",
    "slightly_bearish": "↓",
}

# ============ 事件监控配置 ============

# 默认阈值配置
DEFAULT_THRESHOLDS = {
    "treasury_10y": {"warning": 4.5, "critical": 5.0},
    "vix": {"warning": 20, "critical": 25},
    "gold_silver_ratio": {"warning": 80, "critical": 85},
}

# 预警防重复时间（秒）
ALERT_COOLDOWN = 24 * 3600  # 24小时

# ============ RSS 新闻配置 ============

# 象限关键词映射
QUADRANT_KEYWORDS = {
    "currency": ["美元", "DXY", "美联储", "利率", "Treasury", "TIPS"],
    "liquidity": ["流动性", "利差", "曲线", "spread", "curve"],
    "risk": ["VIX", "恐慌", "避险", "风险", "地缘", "战争", "冲突"],
    "supply_demand": ["央行购金", "ETF", "矿产量", "供需", "金银比"],
}

# RSS 源配置
RSS_SOURCES = [
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "MarketWatch", "url": "https://www.marketwatch.com/rss/topstories"},
]

# ============ 飞书命令配置 ============

V2_COMMANDS = {
    "宏观": "四象限综合分析",
    "归因": "指标区间归因分析",
    "趋势": "指标历史趋势",
    "事件": "活跃事件列表",
    "监控": "当前阈值状态",
    "预测": "多周期融合预测",
}

# ============ CSV 数值列候选 ============

CSV_VALUE_CANDIDATES = [
    "value", "close", "Close", "CLOSE",
    "gold_usd", "silver_usd", "ratio", "ratio_close",
    "10yr", "2yr", "30yr",
    "10 Yr", "2 Yr", "30 Yr",
    "price", "Price", "PRICE",
]

# 日期列候选
CSV_DATE_CANDIDATES = [
    "date", "timestamp", "Date", "Timestamp", "DATE", "TIMESTAMP"
]

# ============ 缓存配置 ============

# 宏观分析缓存时间（秒）
MACRO_CACHE_TTL = 300  # 5分钟
