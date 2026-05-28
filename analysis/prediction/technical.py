"""短期预测模块 — 技术指标计算与短期价格预测

基于 OHLC 数据计算常用技术指标，生成短期（1-7 天）价格方向判断。
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from config import DATA_DIR

logger = logging.getLogger(__name__)


class ShortTermPredictor:
    """短期预测（1-7 天）：技术指标 + 价格形态"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._daily_file = self.data_dir / "history" / "daily" / "gold_silver_daily.csv"

    # ─── 数据加载 ────────────────────────────────────────

    def _load_daily(self, symbol: str = "gold", days: int = 365) -> pd.DataFrame:
        """加载日线 OHLC 数据"""
        if not self._daily_file.exists():
            logger.warning(f"日线数据不存在: {self._daily_file}")
            return pd.DataFrame(columns=["date", "close", "open", "high", "low"])

        df = pd.read_csv(self._daily_file, parse_dates=["date"])
        prefix = "gold_" if symbol == "gold" else "silver_"
        col_map = {
            f"{prefix}open": "open",
            f"{prefix}high": "high",
            f"{prefix}low": "low",
            f"{prefix}close": "close",
        }
        keep = ["date"] + [c for c in col_map if c in df.columns]
        df = df[keep].copy()
        df.rename(columns=col_map, inplace=True)
        return df.sort_values("date").tail(days).reset_index(drop=True)

    # ─── 趋势指标 ────────────────────────────────────────

    def calculate_ma(self, df: pd.DataFrame, periods: list = None) -> Dict[str, float]:
        """移动均线"""
        if df.empty:
            return {}
        periods = periods or [5, 10, 20, 60]
        close = df["close"].values
        result = {}
        for p in periods:
            if len(close) >= p:
                result[f"ma_{p}"] = round(float(np.mean(close[-p:])), 2)
        return result

    def calculate_macd(self, df: pd.DataFrame) -> Dict[str, float]:
        """MACD 指标"""
        if df.empty or len(df) < 26:
            return {"macd_line": 0, "signal_line": 0, "histogram": 0, "signal": "neutral"}
        close = df["close"].values

        def ema(data, period):
            k = 2 / (period + 1)
            result = np.zeros_like(data)
            result[0] = data[0]
            for i in range(1, len(data)):
                result[i] = data[i] * k + result[i - 1] * (1 - k)
            return result

        ema12 = ema(close, 12)
        ema26 = ema(close, 26)
        macd_line = ema12 - ema26
        signal_line = ema(macd_line, 9)
        histogram = macd_line - signal_line
        latest = (macd_line[-1], signal_line[-1], histogram[-1])
        prev = (macd_line[-2], signal_line[-2], histogram[-2]) if len(macd_line) > 1 else latest

        if latest[2] > 0 and prev[2] <= 0:
            signal = "bullish_crossover"
        elif latest[2] < 0 and prev[2] >= 0:
            signal = "bearish_crossover"
        elif latest[0] > latest[1]:
            signal = "bullish"
        elif latest[0] < latest[1]:
            signal = "bearish"
        else:
            signal = "neutral"

        return {
            "macd_line": round(float(latest[0]), 2),
            "signal_line": round(float(latest[1]), 2),
            "histogram": round(float(latest[2]), 2),
            "signal": signal,
        }

    # ─── 动量指标 ────────────────────────────────────────

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> Dict[str, float]:
        """RSI 指标"""
        if df.empty or len(df) < period + 1:
            return {"rsi": 50, "signal": "neutral"}
        close = df["close"].values
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        rsi = round(float(rsi), 1)
        signal = "neutral"
        if rsi > 70:
            signal = "overbought"
        elif rsi < 30:
            signal = "oversold"
        elif rsi > 60:
            signal = "bullish"
        elif rsi < 40:
            signal = "bearish"
        return {"rsi": rsi, "signal": signal}

    def calculate_cci(self, df: pd.DataFrame, period: int = 20) -> Dict[str, float]:
        """CCI 商品通道指数"""
        if df.empty or len(df) < period:
            return {"cci": 0, "signal": "neutral"}
        tp = (df["high"] + df["low"] + df["close"]) / 3
        mean = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean())
        cci = ((tp - mean) / (0.015 * mad)).iloc[-1]
        cci = round(float(cci) if not pd.isna(cci) else 0, 1)
        signal = "neutral"
        if cci > 100:
            signal = "overbought"
        elif cci < -100:
            signal = "oversold"
        elif cci > 50:
            signal = "bullish"
        elif cci < -50:
            signal = "bearish"
        return {"cci": cci, "signal": signal}

    # ─── 波动率指标 ──────────────────────────────────────

    def calculate_bollinger(self, df: pd.DataFrame, period: int = 20) -> Dict[str, float]:
        """布林带"""
        if df.empty or len(df) < period:
            return {"upper": 0, "middle": 0, "lower": 0, "bandwidth": 0, "position": "unknown"}
        close = df["close"].values[-period:]
        middle = float(np.mean(close))
        std = float(np.std(close, ddof=1))
        upper = middle + 2 * std
        lower = middle - 2 * std
        current = float(df["close"].iloc[-1])
        bandwidth = (upper - lower) / middle if middle != 0 else 0
        if current >= upper:
            position = "above_upper"
        elif current <= lower:
            position = "below_lower"
        elif current > middle:
            position = "upper_half"
        else:
            position = "lower_half"
        return {
            "upper": round(upper, 2),
            "middle": round(middle, 2),
            "lower": round(lower, 2),
            "bandwidth": round(float(bandwidth), 4),
            "position": position,
        }

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> Dict[str, float]:
        """ATR 平均真实波幅"""
        if df.empty or len(df) < period + 1:
            return {"atr": 0, "normalized_atr": 0}
        high, low, close = df["high"].values, df["low"].values, df["close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )
        atr = float(np.mean(tr[-period:]))
        normalized = round(atr / close[-1] * 100, 2) if close[-1] != 0 else 0
        return {"atr": round(atr, 2), "normalized_atr": normalized}

    # ─── 支撑阻力位 ──────────────────────────────────────

    def identify_support_resistance(self, df: pd.DataFrame, lookback: int = 60) -> Dict[str, list]:
        """支撑阻力位（基于局部极值聚类）"""
        if df.empty or len(df) < 20:
            return {"support": [], "resistance": []}
        highs = df["high"].values[-lookback:]
        lows = df["low"].values[-lookback:]

        def find_extrema(arr, mode="high"):
            levels = []
            for i in range(2, len(arr) - 2):
                if mode == "high":
                    if arr[i] > arr[i - 1] and arr[i] > arr[i - 2] and arr[i] >= arr[i + 1] and arr[i] >= arr[i + 2]:
                        levels.append(round(float(arr[i]), 1))
                else:
                    if arr[i] < arr[i - 1] and arr[i] < arr[i - 2] and arr[i] <= arr[i + 1] and arr[i] <= arr[i + 2]:
                        levels.append(round(float(arr[i]), 1))
            return levels

        def cluster(levels, tol=0.01):
            if not levels:
                return []
            levels = sorted(set(levels))
            clusters, cur = [], [levels[0]]
            for l in levels[1:]:
                if abs(l - cur[-1]) / cur[-1] < tol:
                    cur.append(l)
                else:
                    clusters.append(round(float(np.mean(cur)), 1))
                    cur = [l]
            clusters.append(round(float(np.mean(cur)), 1))
            return clusters[:5]

        return {
            "resistance": cluster(find_extrema(highs, "high")),
            "support": cluster(find_extrema(lows, "low")),
        }

    # ─── 综合预测 ────────────────────────────────────────

    def predict(self, symbol: str = "gold", days: int = 365) -> Dict:
        """短期预测主入口"""
        df = self._load_daily(symbol, days)
        if df.empty:
            return {"error": f"{symbol} 数据不足", "predictions": [], "indicators": {}}

        close = df["close"].values
        current_price = float(close[-1])

        # 计算所有技术指标
        ma = self.calculate_ma(df)
        macd = self.calculate_macd(df)
        rsi = self.calculate_rsi(df)
        cci = self.calculate_cci(df)
        bollinger = self.calculate_bollinger(df)
        atr = self.calculate_atr(df)
        sr = self.identify_support_resistance(df)

        # 信号综合评分
        score, signals = 0.0, []

        if "bullish" in macd.get("signal", ""):
            score += 1
            signals.append("MACD 看多")
        elif "bearish" in macd.get("signal", ""):
            score -= 1
            signals.append("MACD 看空")

        rsi_sig = rsi.get("signal", "")
        if rsi_sig == "oversold":
            score += 2
            signals.append("RSI 超卖 → 反弹预期")
        elif rsi_sig == "overbought":
            score -= 2
            signals.append("RSI 超买 → 回调风险")
        elif rsi_sig == "bullish":
            score += 1
            signals.append("RSI 偏多")
        elif rsi_sig == "bearish":
            score -= 1
            signals.append("RSI 偏空")

        bp = bollinger.get("position", "")
        if bp == "below_lower":
            score += 1.5
            signals.append("触及布林下轨 → 支撑")
        elif bp == "above_upper":
            score -= 1.5
            signals.append("触及布林上轨 → 压力")

        if ma.get("ma_5", 0) > ma.get("ma_20", 0):
            score += 1
            signals.append("短均线 > 中均线")
        elif ma.get("ma_5", 0) < ma.get("ma_20", 0):
            score -= 1
            signals.append("短均线 < 中均线")

        # 方向判定
        if score > 1.5:
            direction, label = "bullish", "看多"
        elif score < -1.5:
            direction, label = "bearish", "看空"
        elif score > 0:
            direction, label = "slightly_bullish", "略偏多"
        elif score < 0:
            direction, label = "slightly_bearish", "略偏空"
        else:
            direction, label = "neutral", "震荡"

        # 价格区间预测
        atr_val = atr.get("atr", 0) or current_price * 0.005
        confidence = min(abs(score) / 4, 0.85)
        predictions = []
        for label_h, mult in {"1d": 1, "3d": 1.7, "7d": 2.6}.items():
            ext = atr_val * mult
            pred_price = current_price + (score / max(abs(score), 1)) * ext * 0.3
            predictions.append({
                "horizon": label_h,
                "target_price": round(pred_price, 1),
                "price_range": {
                    "lower": round(current_price - ext, 1),
                    "upper": round(current_price + ext, 1),
                },
                "confidence": round(max(0, confidence * (1 - mult * 0.05)), 2),
            })

        return {
            "target": symbol,
            "current_price": current_price,
            "direction": direction,
            "direction_label": label,
            "score": round(score, 1),
            "confidence": round(confidence, 2),
            "signals": signals,
            "indicators": {
                "ma": ma,
                "macd": macd,
                "rsi": rsi,
                "cci": cci,
                "bollinger": bollinger,
                "atr": atr,
                "support_resistance": sr,
            },
            "predictions": predictions,
            "timestamp": datetime.now().isoformat(),
        }