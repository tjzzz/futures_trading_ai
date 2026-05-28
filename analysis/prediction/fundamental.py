"""长期预测模块 — 基本面分析与结构性趋势研判

基于供需平衡、宏观周期定位和结构性因素的趋势展望。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from config import DATA_DIR

logger = logging.getLogger(__name__)


class LongTermPredictor:
    """长期预测（1-12 个月）：基本面 + 周期定位"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._daily_dir = self.data_dir / "history" / "daily"

    # ─── 数据加载 ────────────────────────────────────────

    def _load_factor(self, name: str, days: int = 365) -> pd.DataFrame:
        """加载宏观因子历史"""
        f = self._daily_dir / f"{name}.csv"
        if not f.exists():
            return pd.DataFrame()
        df = pd.read_csv(f, parse_dates=["date"])
        for target in ["value", "close", "10yr"]:
            if target in df.columns:
                df.rename(columns={target: "val"}, inplace=True)
                break
        return df.sort_values("date").tail(days).reset_index(drop=True)

    # ─── 宏观周期定位 ────────────────────────────────────

    def assess_economic_cycle(self) -> Dict:
        """判断经济周期阶段"""
        snapshot = self._get_snapshot()
        treasury = self._load_factor("treasury", 365)
        sp500 = self._load_factor("sp500", 365)
        vix = self._load_factor("vix", 365)

        indicators = {}

        # 收益率曲线斜率
        if not treasury.empty and "10yr" in treasury.columns and "2yr" in treasury.columns:
            latest_spread = float(treasury["10yr"].iloc[-1] - treasury["2yr"].iloc[-1])
            avg_spread_3m = float(
                (treasury["10yr"] - treasury["2yr"]).tail(60).mean()
            ) if len(treasury) >= 60 else latest_spread
            indicators["yield_spread"] = latest_spread
            indicators["yield_spread_3m_avg"] = avg_spread_3m
        else:
            latest_spread = avg_spread_3m = 0
            indicators["yield_spread"] = 0
            indicators["yield_spread_3m_avg"] = 0

        # SP500 趋势
        if not sp500.empty and len(sp500) > 20:
            vals = sp500["val"].values
            sp500_3m_chg = float((vals[-1] - vals[-60]) / vals[-60] * 100) if len(vals) >= 60 else 0
            indicators["sp500_3m_chg"] = round(sp500_3m_chg, 1)
        else:
            sp500_3m_chg = 0
            indicators["sp500_3m_chg"] = 0

        # VIX 均值
        if not vix.empty:
            indicators["vix_3m_avg"] = round(float(vix["val"].tail(60).mean()), 1) if len(vix) >= 60 else 15
        else:
            indicators["vix_3m_avg"] = 15

        # 实际利率趋势
        tips = self._load_factor("tips", 365)
        if not tips.empty and len(tips) > 20:
            tips_3m_chg = float((tips["val"].iloc[-1] - tips["val"].iloc[-60]) * 100) if len(tips) >= 60 else 0
            indicators["tips_3m_chg"] = round(tips_3m_chg, 2)
        else:
            tips_3m_chg = 0
            indicators["tips_3m_chg"] = 0

        # 周期判断（简化版）
        if latest_spread < 0 and sp500_3m_chg < -5:
            cycle, desc = "early_recession", "衰退初期"
        elif latest_spread < 0 and tips_3m_chg < 0:
            cycle, desc = "late_recession", "衰退后期"
        elif sp500_3m_chg > 5 and latest_spread > 0:
            cycle, desc = "recovery", "复苏期"
        elif tips_3m_chg > 0.5:
            cycle, desc = "overheat", "过热期"
        else:
            cycle, desc = "normalization", "正常化"

        return {
            "cycle": cycle,
            "cycle_label": desc,
            "indicators": indicators,
        }

    # ─── 基本面分析 ──────────────────────────────────────

    def analyze_gold_fundamentals(self) -> Dict[str, str]:
        """黄金基本面分析"""
        snapshot = self._get_snapshot()

        assessment = {}

        # 宏观环境
        if snapshot:
            treasury_10y = snapshot.get("treasury_10y")
            tips = snapshot.get("tips_10y")
            dxy = snapshot.get("dxy")
            # snapshot 中的值可能是嵌套 dict（含 value 字段）
            t10 = float(treasury_10y["value"]) if isinstance(treasury_10y, dict) and "value" in treasury_10y else (
                float(treasury_10y) if treasury_10y else None
            )
            t10_tips = float(tips["value"]) if isinstance(tips, dict) and "value" in tips else (
                float(tips) if tips else None
            )
            dxy_val = float(dxy["value"]) if isinstance(dxy, dict) and "value" in dxy else (
                float(dxy) if dxy else None
            )
            if t10 is not None and t10_tips is not None:
                real_rate = t10 - t10_tips
                assessment["real_rate_environment"] = (
                    "宽松" if real_rate < 1.5 else "中性" if real_rate < 2.5 else "紧缩"
                )
            if dxy_val is not None:
                assessment["dollar_environment"] = (
                    "弱势" if dxy_val < 100 else "中性" if dxy_val < 105 else "强势"
                )
            gold = snapshot.get("gold_price")
            gold_val = float(gold["value"]) if isinstance(gold, dict) and "value" in gold else (
                float(gold) if gold else None
            )
            if gold_val:
                assessment["gold_price_level"] = f"${gold_val:.0f}"

        assessment["supply_demand_note"] = (
            "央行购金持续 + 矿产量增速放缓 + 投资需求韧性 → 供需紧平衡"
        )
        assessment["key_driver"] = "美联储政策路径+实际利率方向+地缘风险溢价"

        return assessment

    def structural_trends(self) -> Dict[str, str]:
        """结构性趋势识别"""
        return {
            "dollar_cycle": "美元处于长期高位区间，去美元化趋势为黄金提供结构性支撑",
            "real_rate_regime": "实际利率从高位回落，降息周期预期利好黄金",
            "geopolitical_risk": "地缘政治不确定性持续，避险需求结构性提升",
            "central_bank_demand": "全球央行购金创历史新高，官方储备多元化趋势",
            "debt_sustainability": "主要经济体债务率攀升，黄金作为储备资产吸引力增强",
        }

    # ─── 综合预测 ────────────────────────────────────────

    def predict(self, horizon: str = "12m") -> Dict:
        """长期预测主入口"""
        cycle = self.assess_economic_cycle()
        fundamentals = self.analyze_gold_fundamentals()
        trends = self.structural_trends()

        current_price = self._get_current_price()

        # 基于周期阶段的方向判断
        cycle_signals = {
            "early_recession": ("bullish", "衰退预期升温，避险需求推动"),
            "late_recession": ("bullish", "宽松政策预期，实际利率下行"),
            "recovery": ("neutral", "经济改善但通胀预期支撑"),
            "overheat": ("mixed", "高通胀利多但政策收紧利空"),
            "normalization": ("neutral", "宏观环境趋于正常，震荡为主"),
        }
        direction, rationale = cycle_signals.get(cycle["cycle"], ("neutral", ""))

        if direction == "bullish":
            label = "看多"
            base_return = 0.08
        elif direction == "bearish":
            label = "看空"
            base_return = -0.08
        elif direction == "mixed":
            label = "多空交织"
            base_return = 0.02
        else:
            label = "中性"
            base_return = 0.03

        target_price = round(current_price * (1 + base_return), 0) if current_price else None
        scenarios = self._generate_scenarios(current_price)

        return {
            "direction": direction,
            "direction_label": label,
            "rationale": rationale,
            "confidence": 0.55,  # 长期预测置信度天然较低
            "current_price": current_price,
            "target_price": target_price,
            "economic_cycle": cycle,
            "fundamentals": fundamentals,
            "structural_trends": trends,
            "scenarios": scenarios,
            "predictions": [{
                "horizon": horizon,
                "target_price": target_price,
                "price_range": None if not current_price else {
                    "lower": round(current_price * 0.9, 0),
                    "upper": round(current_price * 1.15, 0),
                },
                "confidence": 0.55,
            }],
            "timestamp": datetime.now().isoformat(),
        }

    def _generate_scenarios(self, current_price: float) -> List[Dict]:
        """多情景分析"""
        if not current_price:
            return []
        return [
            {
                "name": "基准情景",
                "probability": 0.55,
                "target_price": round(current_price * 1.08, 0),
                "range": [round(current_price * 0.95, 0), round(current_price * 1.15, 0)],
                "drivers": ["降息周期", "央行购金", "地缘风险"],
            },
            {
                "name": "乐观情景",
                "probability": 0.25,
                "target_price": round(current_price * 1.18, 0),
                "range": [round(current_price * 1.05, 0), round(current_price * 1.30, 0)],
                "drivers": ["深度衰退 + QE", "美元大幅走弱", "危机模式"],
            },
            {
                "name": "悲观情景",
                "probability": 0.20,
                "target_price": round(current_price * 0.92, 0),
                "range": [round(current_price * 0.82, 0), round(current_price * 1.02, 0)],
                "drivers": ["经济软着陆", "美元反弹", "风险偏好回升"],
            },
        ]

    def _get_snapshot(self) -> Dict:
        """获取当前快照"""
        f = self.data_dir / "current" / "dashboard_data.json"
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text())
        except Exception:
            return {}

    def _get_current_price(self) -> Optional[float]:
        snap = self._get_snapshot()
        if "gold_price" in snap:
            gp = snap["gold_price"]
            if isinstance(gp, dict):
                gp = gp.get("value")
            if gp:
                return float(gp)
        return None
