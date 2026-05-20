"""
事件监控阈值定义

每个阈值定义：
  - key: 指标标识符（对应 dashboard_data.json 中的路径）
  - name: 中文名称
  - warn: 警告阈值（触发 A 级事件）
  - crisis: 危机阈值（触发 S 级事件）
  - direction: 触发方向（above/below）
  - data_path: JSON 路径（点号分隔）
"""

from typing import Dict, Any, List

# ─── 阈值规则 ──────────────────────────────────────────────

ThresholdDef = Dict[str, Any]

THRESHOLDS: List[ThresholdDef] = [
    # 🟢 货币锚
    {
        "key": "treasury_10y",
        "name": "10Y 美债收益率",
        "warn": 4.5,
        "crisis": 5.0,
        "direction": "above",
        "unit": "%",
        "data_path": "treasury.10yr",
        "quadrant": "货币锚",
        "bullish_for": "gold",
        "description": "10Y > 4.5% 利率压力 → 压制黄金；> 5.0% 危机级",
    },
    {
        "key": "treasury_30y",
        "name": "30Y 美债收益率",
        "warn": 4.8,
        "crisis": 5.5,
        "direction": "above",
        "unit": "%",
        "data_path": "treasury.30yr",
        "quadrant": "货币锚",
        "bullish_for": "gold",
        "description": "30Y 攀升 → 长端风险溢价上升 → 利多黄金（避险逻辑）",
    },
    {
        "key": "dxy",
        "name": "DXY 美元指数",
        "warn": 105,
        "crisis": 110,
        "direction": "above",
        "unit": "",
        "data_path": "dxy.value",
        "quadrant": "货币锚",
        "bullish_for": None,  # 强美元压制黄金
        "description": "DXY > 105 美元强势 → 压制黄金；> 110 极端强势",
    },
    # 🔵 宏观流动性
    {
        "key": "spread_2y10y",
        "name": "2Y-10Y 利差",
        "warn": 0.0,
        "crisis": -0.2,
        "direction": "below",
        "unit": "%",
        "data_path": "__spread__",  # 特殊标记：需计算
        "quadrant": "宏观流动性",
        "bullish_for": "gold",
        "description": "利差 < 0 倒挂 → 衰退预期 → 利多黄金；< -0.2 深度倒挂",
    },
    # 🟠 风险偏好
    {
        "key": "vix",
        "name": "VIX 恐慌指数",
        "warn": 25,
        "crisis": 35,
        "direction": "above",
        "unit": "",
        "data_path": "vix.value",
        "quadrant": "风险偏好",
        "bullish_for": "gold",
        "description": "VIX > 25 恐慌 → 避险买入黄金；> 35 危机级别",
    },
    {
        "key": "gold_daily_change",
        "name": "黄金日内波动",
        "warn": 3.0,
        "crisis": 5.0,
        "direction": "above",
        "unit": "%",
        "data_path": "__change__",  # 特殊标记：需从历史数据计算
        "quadrant": "风险偏好",
        "bullish_for": "gold",
        "description": "单日波动 > 3% 异常波动",
    },
    # 🔴 供需博弈
    {
        "key": "gs_ratio",
        "name": "金银比",
        "warn": 75,
        "crisis": 85,
        "direction": "above",
        "unit": "",
        "data_path": "gold_silver_ratio.value",
        "quadrant": "供需博弈",
        "bullish_for": "silver",
        "description": "金银比 > 75 白银低估；> 85 极端低估",
    },
    {
        "key": "gs_ratio_low",
        "name": "金银比（偏低）",
        "warn": 65,
        "crisis": 55,
        "direction": "below",
        "unit": "",
        "data_path": "gold_silver_ratio.value",
        "quadrant": "供需博弈",
        "bullish_for": "gold",
        "description": "金银比 < 65 白银相对高估",
    },
]


def get_threshold_by_key(key: str) -> ThresholdDef:
    """按 key 查找阈值定义"""
    for t in THRESHOLDS:
        if t["key"] == key:
            return t
    raise KeyError(f"未找到阈值: {key}")
