"""
中期预测模块 — 宏观因子模型与方向预测

基于宏观因子（DXY、美债收益率、VIX、实际利率等）的加权预测模型。
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from config import DATA_DIR

logger = logging.getLogger(__name__)


class MidTermPredictor:
    """中期预测（1-4 周）：宏观因子模型"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._daily_dir = self.data_dir / "history" / "daily"

    def _load_csv(self, name: str, col: str = "value", days: int = 90) -> pd.DataFrame:
        """加载日频数据"""
        f = self._daily_dir / f"{name}.csv"
        if not f.exists():
            logger.warning(f"数据文件不存在: {f}")
            return pd.DataFrame()
        df = pd.read_csv(f, parse_dates=["date"])
        if col in df.columns and col != "value":
            pass
        elif "value" in df.columns:
            df.rename(columns={"value": "val"}, inplace=True)
        elif "close" in df.columns:
            df.rename(columns={"close": "val"}, inplace=True)
        elif "10yr" in df.columns:
            df.rename(columns={"10yr": "val"}, inplace=True)
        return df.sort_values("date").tail(days).reset_index(drop=True)

    def _load_treasury(self, days: int = 90) -> pd.DataFrame:
        """加载收益率曲线数据"""
        f = self._daily_dir / "treasury.csv"
        if not f.exists():
            return pd.DataFrame()
        return pd.read_csv(f, parse_dates=["date"]).tail(days).reset_index(drop=True)

    # ─── 因子计算 ────────────────────────────────────────

    def collect_factors(self, days: int = 90) -> Dict[str, float]:
        """收集并计算各宏观因子当前值"""
        dxy = self._load_csv("dxy", days=days)
        vix = self._load_csv("vix", days=days)
        sp500 = self._load_csv("sp500", days=days)
        tips = self._load_csv("tips", days=days)
        treasury = self._load_treasury(days=days)

        factors = {}

        # 美元指数变化率
        if not dxy.empty and len(dxy) > 1:
            vals = dxy["val"].values
            factors["dxy_current"] = round(float(vals[-1]), 2)
            factors["dxy_change_1w"] = round(float((vals[-1] - vals[-5]) / vals[-5] * 100) if len(vals) >= 5 else 0, 2)
            factors["dxy_change_1m"] = round(float((vals[-1] - vals[-20]) / vals[-20] * 100) if len(vals) >= 20 else 0, 2)

        # VIX 市场情绪
        if not vix.empty and len(vix) > 1:
            vals = vix["val"].values
            factors["vix_current"] = round(float(vals[-1]), 2)
            factors["vix_change_1w"] = round(float(vals[-1] - vals[-5]) if len(vals) >= 5 else 0, 2)

        # 实际利率 (TIPS)
        if not tips.empty:
            factors["tips_current"] = round(float(tips["val"].iloc[-1]), 2)

        # 收益率曲线
        if not treasury.empty:
            cols = treasury.columns
            if "10yr" in cols:
                factors["treasury_10y"] = round(float(treasury["10yr"].iloc[-1]), 2)
            if "2yr" in cols:
                factors["treasury_2y"] = round(float(treasury["2yr"].iloc[-1]), 2)
            if "10yr" in cols and "2yr" in cols:
                factors["yield_spread"] = round(float(treasury["10yr"].iloc[-1] - treasury["2yr"].iloc[-1]), 2)
            if "30yr" in cols and "10yr" in cols:
                factors["yield_spread_30_10"] = round(float(treasury["30yr"].iloc[-1] - treasury["10yr"].iloc[-1]), 2)

        # SP500 风险偏好
        if not sp500.empty and len(sp500) > 1:
            vals = sp500["val"].values
            factors["sp500_current"] = round(float(vals[-1]), 1)
            factors["sp500_change_1m"] = round(float((vals[-1] - vals[-20]) / vals[-20] * 100) if len(vals) >= 20 else 0, 2)

        return factors

    def _score_direction(self, factors: Dict[str, float]) -> Tuple[float, List[str]]:
        """因子评分 → 方向信号"""
        score, signals = 0.0, []

        # DXY：美元弱 → 黄金多
        dxy_chg = factors.get("dxy_change_1w", 0)
        if dxy_chg < -0.5:
            score += 1.5
            signals.append(f"美元走弱 ({dxy_chg:+.2f}%) → 利多黄金")
        elif dxy_chg > 0.5:
            score -= 1.5
            signals.append(f"美元走强 ({dxy_chg:+.2f}%) → 利空黄金")

        # VIX：恐慌 ↑ → 避险 ↑ → 黄金多
        vix_val = factors.get("vix_current", 15)
        if vix_val > 25:
            score += 2
            signals.append(f"VIX 高企 ({vix_val}) → 避险情绪 → 利多黄金")
        elif vix_val > 20:
            score += 1
            signals.append(f"VIX 偏高 ({vix_val}) → 温和避险")
        elif vix_val < 12:
            score -= 1
            signals.append(f"VIX 低位 ({vix_val}) → 风险偏好 → 利空黄金")

        # 实际利率：TIPS ↓ → 黄金 ↑
        tips_val = factors.get("tips_current", 2)
        if tips_val < 1.5:
            score += 1.5
            signals.append(f"实际利率低位 ({tips_val}%) → 利多黄金")
        elif tips_val > 2.5:
            score -= 1.5
            signals.append(f"实际利率高位 ({tips_val}%) → 利空黄金")

        # 收益率曲线斜率
        spread = factors.get("yield_spread", 0)
        if spread < 0:
            score += 1
            signals.append(f"收益率曲线倒挂 ({spread}bp) → 衰退预期 → 利多黄金")
        elif spread > 0.5:
            score -= 0.5
            signals.append(f"收益率曲线陡峭化 → 经济预期改善 → 略利空黄金")

        return score, signals

    # ─── 综合预测 ────────────────────────────────────────

    def predict(self, horizon: str = "1m") -> Dict:
        """中期预测主入口"""
        factors = self.collect_factors(days=90)
        if not factors:
            return {"error": "宏观数据不足", "factors": {}, "predictions": []}

        score, signals = self._score_direction(factors)

        if score > 1.5:
            direction, label = "bullish", "看多"
        elif score < -1.5:
            direction, label = "bearish", "看空"
        elif score > 0.5:
            direction, label = "slightly_bullish", "略偏多"
        elif score < -0.5:
            direction, label = "slightly_bearish", "略偏空"
        else:
            direction, label = "neutral", "中性"

        confidence = min((abs(score) / 5) * 0.7 + 0.15, 0.8)

        # 从快照获取当前价格
        current_price = self._get_current_price()

        return {
            "direction": direction,
            "direction_label": label,
            "score": round(score, 1),
            "confidence": round(confidence, 2),
            "signals": signals,
            "factors": factors,
            "predictions": [{
                "horizon": horizon,
                "target_price": None if not current_price else round(current_price * (1 + score * 0.005), 1),
                "confidence": round(confidence, 2),
            }],
            "timestamp": datetime.now().isoformat(),
        }

    def _get_current_price(self) -> Optional[float]:
        """从快照获取当前价格"""
        snapshot = self.data_dir / "current" / "dashboard_data.json"
        if not snapshot.exists():
            return None
        try:
            import json
            data = json.loads(snapshot.read_text())
            gp = data.get("gold_price", 0)
            if isinstance(gp, dict):
                gp = gp.get("value", 0)
            return float(gp) if gp else None
        except Exception:
            return None

    def get_factor_history(self, factor: str, days: int = 60) -> List[Dict]:
        """获取因子历史序列"""
        name_map = {
            "dxy": "dxy", "vix": "vix", "sp500": "sp500",
            "tips": "tips", "treasury_10y": "treasury",
            "yield_spread": "treasury",
        }
        fn = name_map.get(factor, "")
        if not fn:
            return []
        df = self._load_csv(fn, days=days) if fn != "treasury" else self._load_treasury(days=days)
        if df.empty:
            return []
        if factor == "yield_spread" and "10yr" in df.columns and "2yr" in df.columns:
            vals = df["10yr"] - df["2yr"]
            return [{"date": str(d.date()), "value": round(float(v), 2)} for d, v in zip(df["date"], vals)]
        col = "val" if "val" in df.columns else ("10yr" if "10yr" in df.columns else None)
        if not col:
            return []
        return [{"date": str(d.date()), "value": round(float(v), 2)} for d, v in zip(df["date"], df[col])]
