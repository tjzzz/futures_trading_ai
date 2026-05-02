"""
技术指标计算工具
整合 system 和 skills 的技术指标计算
"""
from typing import Tuple, List, Optional, Dict, Any
import pandas as pd
import numpy as np


def calculate_ma(data: pd.Series, period: int) -> pd.Series:
    """计算简单移动平均"""
    return data.rolling(window=period).mean()


def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """计算指数移动平均"""
    return data.ewm(span=period, adjust=False).mean()


def calculate_macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    """
    计算MACD
    返回: (macd, signal_line, histogram)
    """
    ema_fast = data.ewm(span=fast, adjust=False).mean()
    ema_slow = data.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return macd.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]


def calculate_rsi(data: pd.Series, period: int = 14) -> float:
    """计算RSI"""
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50


def calculate_bollinger(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
    """
    计算布林带
    返回: (upper, middle, lower)
    """
    middle = data.rolling(window=period).mean()
    std = data.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper.iloc[-1], middle.iloc[-1], lower.iloc[-1]


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """计算ATR"""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0


def calculate_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> Tuple[float, float, float]:
    """
    计算KDJ指标
    返回: (k, d, j)
    """
    rsv = (close - low.rolling(window=n).min()) / (high.rolling(window=n).max() - low.rolling(window=n).min()) * 100
    k = rsv.ewm(com=m1-1, adjust=False).mean()
    d = k.ewm(com=m2-1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k.iloc[-1], d.iloc[-1], j.iloc[-1]


def calculate_volume_ma(volume: pd.Series, period: int = 20) -> float:
    """计算成交量均线"""
    return volume.rolling(window=period).mean().iloc[-1]


def calculate_all_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算所有技术指标
    输入DataFrame需要包含: open, high, low, close, volume
    """
    if len(df) < 60:
        raise ValueError("数据量不足，至少需要60条数据")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df.get("volume", pd.Series([0] * len(df)))

    indicators = {}

    # 移动平均线
    for period in [5, 10, 20, 60]:
        indicators[f"ma_{period}"] = calculate_ma(close, period).iloc[-1]

    # 指数移动平均
    for period in [12, 26]:
        indicators[f"ema_{period}"] = calculate_ema(close, period).iloc[-1]

    # MACD
    macd, signal, hist = calculate_macd(close)
    indicators["macd"] = macd
    indicators["macd_signal"] = signal
    indicators["macd_hist"] = hist

    # RSI
    indicators["rsi"] = calculate_rsi(close)

    # 布林带
    upper, middle, lower = calculate_bollinger(close)
    indicators["bollinger_upper"] = upper
    indicators["bollinger_middle"] = middle
    indicators["bollinger_lower"] = lower

    # ATR
    indicators["atr"] = calculate_atr(high, low, close)

    # 成交量指标
    indicators["volume_ma_20"] = calculate_volume_ma(volume, 20)

    # KDJ
    k, d, j = calculate_kdj(high, low, close)
    indicators["kdj_k"] = k
    indicators["kdj_d"] = d
    indicators["kdj_j"] = j

    return indicators


def generate_signals(indicators: Dict[str, float], price: float) -> List[Dict[str, Any]]:
    """
    基于技术指标生成交易信号
    """
    signals = []

    # MA信号
    ma_5 = indicators.get("ma_5", price)
    ma_20 = indicators.get("ma_20", price)
    ma_60 = indicators.get("ma_60", price)

    if ma_5 > ma_20 > ma_60 and price > ma_5:
        signals.append({
            "type": "ma_bullish_alignment",
            "direction": "long",
            "strength": 20,
            "description": "均线多头排列"
        })
    elif ma_5 < ma_20 < ma_60 and price < ma_5:
        signals.append({
            "type": "ma_bearish_alignment",
            "direction": "short",
            "strength": 20,
            "description": "均线空头排列"
        })

    # MACD信号
    macd = indicators.get("macd", 0)
    macd_signal = indicators.get("macd_signal", 0)
    macd_hist = indicators.get("macd_hist", 0)

    if macd_hist > 0 and macd > macd_signal:
        signals.append({
            "type": "macd_golden_cross",
            "direction": "long",
            "strength": min(15, abs(macd_hist) * 5),
            "description": "MACD金叉"
        })
    elif macd_hist < 0 and macd < macd_signal:
        signals.append({
            "type": "macd_dead_cross",
            "direction": "short",
            "strength": min(15, abs(macd_hist) * 5),
            "description": "MACD死叉"
        })

    # RSI信号
    rsi = indicators.get("rsi", 50)
    if rsi < 30:
        signals.append({
            "type": "rsi_oversold",
            "direction": "long",
            "strength": 30 - rsi,
            "description": f"RSI超卖({rsi:.1f})"
        })
    elif rsi > 70:
        signals.append({
            "type": "rsi_overbought",
            "direction": "short",
            "strength": rsi - 70,
            "description": f"RSI超买({rsi:.1f})"
        })

    # 布林带信号
    bollinger_upper = indicators.get("bollinger_upper", price * 1.05)
    bollinger_lower = indicators.get("bollinger_lower", price * 0.95)

    if price < bollinger_lower:
        signals.append({
            "type": "bollinger_lower_break",
            "direction": "long",
            "strength": 15,
            "description": "价格跌破布林下轨"
        })
    elif price > bollinger_upper:
        signals.append({
            "type": "bollinger_upper_break",
            "direction": "short",
            "strength": 15,
            "description": "价格突破布林上轨"
        })

    return signals


def analyze_trend(indicators: Dict[str, float], price: float) -> Dict[str, Any]:
    """
    分析趋势
    """
    score = 50  # 中性起点

    # MA趋势
    ma_5 = indicators.get("ma_5", price)
    ma_20 = indicators.get("ma_20", price)

    if ma_5 > ma_20:
        score += 10
    elif ma_5 < ma_20:
        score -= 10

    # MACD趋势
    macd_hist = indicators.get("macd_hist", 0)
    if macd_hist > 0:
        score += 10
    elif macd_hist < 0:
        score -= 10

    # RSI趋势
    rsi = indicators.get("rsi", 50)
    if rsi > 60:
        score += 5
    elif rsi < 40:
        score -= 5

    score = max(0, min(100, score))

    if score >= 70:
        direction = "strong_bullish"
    elif score >= 55:
        direction = "bullish"
    elif score <= 30:
        direction = "strong_bearish"
    elif score <= 45:
        direction = "bearish"
    else:
        direction = "neutral"

    # 风险等级
    atr = indicators.get("atr", 0)
    volatility = atr / price if price > 0 else 0
    if volatility > 0.03:
        risk_level = "high"
    elif volatility > 0.015:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "direction": direction,
        "strength": score,
        "risk_level": risk_level,
        "volatility": volatility
    }
