#!/usr/bin/env python3
"""
因子对齐数据计算器 — 将原始数据按7因子模型组织为结构化 JSON

从 dashboard_data.json 读取当前快照，从 data/history/ 读取历史数据计算趋势和变化，
按设计文档第三章的7因子组织数据，输出为 data/factors/current_factors.json。

用法:
    python tools/compute_factors.py                          # 全量计算
    python tools/compute_factors.py --factor opportunity_cost # 单因子
    python tools/compute_factors.py --pretty                 # 带格式化输出到 stdout

所有时间字段统一为 "YYYY-MM-DD HH:mm:ss"，时区 CST (UTC+8)。
缺失数据填 null 不填 0，每个字段标注 source。
signal 字段初始为 null，不由本脚本判断。
"""

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 项目路径 ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CURRENT = PROJECT_ROOT / "data" / "current"
DATA_HISTORY_DAILY = PROJECT_ROOT / "data" / "history" / "daily"
DATA_HISTORY_MINUTELY = PROJECT_ROOT / "data" / "history" / "minutely"
DATA_EVENTS = PROJECT_ROOT / "data" / "events"
DATA_FACTORS = PROJECT_ROOT / "data" / "factors"

DASHBOARD_FILE = DATA_CURRENT / "dashboard_data.json"
EVENT_FILE = DATA_EVENTS / "event_tracker.json"
OUTPUT_FILE = DATA_FACTORS / "current_factors.json"

CST = timezone(timedelta(hours=8))

# ─── 因子定义（与设计文档一致） ──────────────────────────────────────────

FACTOR_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "opportunity_cost": {"label": "机会成本"},
    "currency": {"label": "货币"},
    "safe_haven": {"label": "避险需求"},
    "inflation": {"label": "通胀预期"},
    "positioning": {"label": "持仓动量"},
    "structural_demand": {"label": "结构性需求"},
    "silver_specific": {"label": "银价专用"},
}


# ====================================================================
#  辅助函数
# ====================================================================


def _now_cst() -> str:
    """返回当前 CST 时间字符串"""
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: Path) -> dict:
    """安全读取 JSON 文件，失败返回空字典"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _read_history_csv(path: Path, value_col: str = "value",
                      date_col: str = "date") -> List[Dict[str, Any]]:
    """
    读取日频历史 CSV，返回排序后的记录列表（日期升序）。

    处理不同日期格式：YYYY-MM-DD 和 MM/DD/YYYY。
    过滤无效行。
    """
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get(value_col):
                    continue
                try:
                    val = float(row[value_col])
                except (ValueError, TypeError):
                    continue
                raw_date = (row.get(date_col) or "").strip()
                # 统一日期格式
                if "/" in raw_date:
                    parts = raw_date.split("/")
                    if len(parts) == 3:
                        raw_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                if not raw_date:
                    continue
                rows.append({"date": raw_date, "value": val})
    except (OSError, csv.Error):
        return []
    # 按日期排序
    rows.sort(key=lambda r: r["date"])
    return rows


def _get_safe(d: dict, *keys: str, default: Any = None) -> Any:
    """安全地从嵌套字典中取值"""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, {})
    return d if d != {} else default


def _get_value(entry: Any) -> Optional[float]:
    """从 dashboard 字段中提取数值"""
    if entry is None:
        return None
    if isinstance(entry, (int, float)):
        return float(entry)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _compute_change_d(records: List[Dict[str, Any]]) -> Optional[float]:
    """计算日变化（绝对值），最后一条 - 前一条"""
    if len(records) < 2:
        return None
    return round(records[-1]["value"] - records[-2]["value"], 6)


def _compute_trend(records: List[Dict[str, Any]], window: int = 20) -> Optional[str]:
    """
    计算趋势方向。

    用简单线性回归计算斜率，归一化为均值百分比。
    - |斜率%| < 0.1% / 天 → "flat"
    - 斜率% > 0.1% / 天 → "up"
    - 斜率% < -0.1% / 天 → "down"
    """
    slope = _compute_slope(records, window)
    if slope is None:
        return None
    slope_pct = slope["slope_pct"]
    if abs(slope_pct) < 0.1:
        return "flat"
    return "up" if slope_pct > 0 else "down"


def _compute_slope(records: List[Dict[str, Any]], window: int = 20) -> Optional[dict]:
    """
    计算滑动窗口内的线性回归斜率，返回斜率和归一化值。

    Returns:
        {"slope": 绝对斜率, "slope_pct": 百分比斜率, "n": 样本数}
    """
    if len(records) < 3:
        return None
    recent = records[-window:] if len(records) >= window else records
    n = len(recent)
    if n < 3:
        return None
    values = [r["value"] for r in recent]
    mean_val = sum(values) / n
    if mean_val == 0:
        return None
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return None
    slope = numerator / denominator
    slope_pct = (slope / mean_val) * 100
    return {"slope": slope, "slope_pct": slope_pct, "n": n}


def _compute_multi_scale_signals(records: List[Dict[str, Any]]) -> dict:
    """
    计算三周期信号（短期/中期/长期）。

    对任意数值序列，用三个时间窗口的线性回归斜率
    归一化后得到方向+强度。

    Args:
        records: [{"date": "...", "value": float}, ...]，日期升序

    Returns:
        {
            "short": {"direction": "bullish"/"bearish"/"neutral", "strength": 0.8, "window_days": 5},
            "mid": {"direction": "...", "strength": 0.3, ...},
            "long": {"direction": "...", "strength": 0.2, ...}
        }
        数据不足时对应维度返回 None
    """
    # 三个时间窗口（交易日数）
    WINDOWS = {"short": 5, "mid": 20, "long": 60}
    # 中性阈值（归一化斜率% < 此值视为中性）
    NEUTRAL_THRESHOLD = 0.05

    result = {}
    for period, window in WINDOWS.items():
        if len(records) < 3:
            result[period] = None
            continue
        recent = records[-window:] if len(records) >= window else records
        n = len(recent)
        if n < 3:
            result[period] = None
            continue

        values = [r["value"] for r in recent]
        mean_val = sum(values) / n
        if mean_val == 0:
            result[period] = None
            continue

        # 线性回归斜率
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        try:
            numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
        except (TypeError, ZeroDivisionError):
            result[period] = None
            continue
        if denominator == 0:
            result[period] = None
            continue
        slope = numerator / denominator
        slope_pct = (slope / mean_val) * 100

        # 方向判断
        if abs(slope_pct) < NEUTRAL_THRESHOLD:
            direction = "neutral"
            strength = round(abs(slope_pct) / NEUTRAL_THRESHOLD, 2)
        else:
            direction = "bullish" if slope_pct < 0 else "bearish"
            # 强度归一化：斜率% × 10，上限1.0
            strength = min(round(abs(slope_pct) * 10, 2), 1.0)

        result[period] = {
            "direction": direction,
            "strength": strength,
            "window_days": min(window, n),
            "evidence": f"{'上升' if slope_pct > 0 else '下降'} {abs(slope_pct):.2f}%/天 ({n}天)",
        }

    return result


def _compute_ma(records: List[Dict[str, Any]], window: int = 20) -> Optional[float]:
    """计算移动平均"""
    if len(records) < 1:
        return None
    recent = records[-window:] if len(records) >= window else records
    values = [r["value"] for r in recent]
    return round(sum(values) / len(values), 4)


def _compute_percentile(records: List[Dict[str, Any]], window: int = 1250) -> Optional[float]:
    """
    计算当前值在过去 N 个交易日中的分位数（0-100）。
    默认 1250 个交易日≈5年。
    """
    if len(records) < 2:
        return None
    recent = records[-window:] if len(records) >= window else records
    current = recent[-1]["value"]
    values = sorted(r["value"] for r in recent[:-1])  # exclude current
    if not values:
        return None
    count_below = sum(1 for v in values if v <= current)
    return round(count_below / len(values) * 100, 1)


def _dxy_vs_200ma(dxy_records: List[Dict[str, Any]],
                  current_dxy: float) -> Optional[str]:
    """判断 DXY 与 200日均线的关系"""
    ma200 = _compute_ma(dxy_records, window=200)
    if ma200 is None or current_dxy is None:
        return None
    diff = current_dxy - ma200
    threshold = ma200 * 0.002  # 0.2% 容忍区间
    if abs(diff) <= threshold:
        return "at"
    return "above" if diff > 0 else "below"


def _vix_regime(vix_value: Optional[float]) -> Optional[str]:
    """VIX 区间判定"""
    if vix_value is None:
        return None
    if vix_value > 30:
        return "panic"  # crisis 需要额外条件
    if vix_value > 25:
        return "panic"
    if vix_value >= 15:
        return "moderate"
    return "calm"


# ====================================================================
#  每个因子的计算
# ====================================================================


def compute_opportunity_cost(dashboard: dict) -> Dict[str, Any]:
    """
    计算机会成本因子（Factor 1）。

    依赖：
    - dashboard.tips_10y / dashboard.treasury_10y（实时或每日快照）
    - dashboard.treasury （美债收益表）
    - data/history/daily/tips.csv
    - data/history/daily/treasury.csv
    """
    now = _now_cst()
    data: Dict[str, Any] = {}

    # ── TIPS 实际利率 ──
    tips_entry = dashboard.get("tips_10y", {})
    tips_value = _get_value(tips_entry)
    if tips_value is not None:
        data["tips_10y"] = {
            "value": round(tips_value, 2),
            "source": tips_entry.get("source", "fred"),
            "updated": tips_entry.get("as_of_date", now),
        }

    # TIPS 日变化
    tips_records = _read_history_csv(
        DATA_HISTORY_DAILY / "tips.csv", value_col="value"
    )
    tips_change = _compute_change_d(tips_records)
    if tips_change is not None:
        data["tips_10y_change_d"] = round(tips_change * 100, 1)  # 转为 bp

    # TIPS 20日趋势
    tips_trend = _compute_trend(tips_records, window=20)
    if tips_trend is not None:
        data["tips_10y_trend_20d"] = tips_trend

    # ── 名义收益率 (10Y) ──
    # 优先使用实时 treasury_10y，如果没有则用 treasury.10yr
    nominal_10y_entry = dashboard.get("treasury_10y", {}) or {}
    nominal_value = _get_value(nominal_10y_entry)
    if nominal_value is None:
        treasury_entry = dashboard.get("treasury", {})
        nominal_value = treasury_entry.get("10yr")
        nominal_source = "ustreasury"
    else:
        nominal_source = nominal_10y_entry.get("source", "yahoo_finance")

    if nominal_value is not None:
        nominal_change = nominal_10y_entry.get("change") if isinstance(nominal_10y_entry, dict) else None
        data["nominal_10y"] = {
            "value": round(nominal_value, 4),
            "change": round(nominal_change, 4) if nominal_change is not None else None,
            "source": nominal_source,
        }

    # 名义收益率日变化（从 treasury.csv）
    treasury_records = _read_history_csv(
        DATA_HISTORY_DAILY / "treasury.csv", value_col="10yr"
    )
    nominal_change_d = _compute_change_d(treasury_records)
    if nominal_change_d is not None:
        data["nominal_10y_change_d"] = round(nominal_change_d * 100, 1)  # bp

    # ── 点阵图 & FedWatch 概率（暂无可获取数据源则置 null） ──
    # fedwatch_dots: 手动/FOMC 会后数据，当前无采集
    # fedwatch_prob: 将由 collectors/fedwatch.py 填充
    fedwatch_prob = dashboard.get("fedwatch_prob")
    if fedwatch_prob:
        data["fedwatch_prob"] = fedwatch_prob
    else:
        data["fedwatch_prob"] = None

    fedwatch_dots = dashboard.get("fedwatch_dots")
    if fedwatch_dots:
        data["fedwatch_dots"] = fedwatch_dots

    # ── 三周期信号 ──
    # TIPS 是机会成本核心指标，用它计算三周期信号
    data["signals"] = _compute_multi_scale_signals(tips_records)

    return data


def compute_currency(dashboard: dict) -> Dict[str, Any]:
    """
    计算货币因子（Factor 2）。

    依赖：
    - dashboard.dxy
    - data/history/daily/dxy.csv
    """
    data: Dict[str, Any] = {}
    now = _now_cst()

    # DXY
    dxy_entry = dashboard.get("dxy", {})
    dxy_value = _get_value(dxy_entry)
    if dxy_value is not None:
        dxy_change = dxy_entry.get("change") if isinstance(dxy_entry, dict) else None
        data["dxy"] = {
            "value": round(dxy_value, 3),
            "change": round(dxy_change, 3) if dxy_change is not None else None,
            "source": dxy_entry.get("source", "yahoo_finance"),
            "updated_at": dxy_entry.get("updated_at", now),
        }

    # DXY 日变化
    dxy_records = _read_history_csv(DATA_HISTORY_DAILY / "dxy.csv", value_col="value")
    dxy_change = _compute_change_d(dxy_records)
    if dxy_change is not None:
        data["dxy_change_d"] = round(dxy_change, 3)

    # DXY vs 200MA
    if dxy_value is not None:
        vs_ma = _dxy_vs_200ma(dxy_records, dxy_value)
        if vs_ma is not None:
            data["dxy_vs_200ma"] = vs_ma

    # DXY 60日趋势
    dxy_trend = _compute_trend(dxy_records, window=60)
    if dxy_trend is not None:
        data["dxy_trend_60d"] = dxy_trend

    # ── 三周期信号 ──
    data["signals"] = _compute_multi_scale_signals(dxy_records)

    return data


def compute_safe_haven(dashboard: dict) -> Dict[str, Any]:
    """
    计算避险需求因子（Factor 3）。

    依赖：
    - dashboard.vix, dashboard.sp500
    - data/history/daily/vix.csv, data/history/daily/sp500.csv
    """
    data: Dict[str, Any] = {}
    now = _now_cst()

    # ── VIX ──
    vix_entry = dashboard.get("vix", {})
    vix_value = _get_value(vix_entry)
    if vix_value is not None:
        vix_change = vix_entry.get("change") if isinstance(vix_entry, dict) else None
        data["vix"] = {
            "value": round(vix_value, 2),
            "change": round(vix_change, 2) if vix_change is not None else None,
            "source": vix_entry.get("source", "cboe"),
            "updated_at": vix_entry.get("updated_at", now),
        }

    # VIX 日变化
    vix_records = _read_history_csv(DATA_HISTORY_DAILY / "vix.csv", value_col="close")
    vix_change = _compute_change_d(vix_records)
    if vix_change is not None:
        data["vix_change_d"] = round(vix_change, 2)

    # VIX 20日均值
    vix_ma = _compute_ma(vix_records, window=20)
    if vix_ma is not None:
        data["vix_ma20"] = vix_ma

    # VIX 区间
    regime = _vix_regime(vix_value)
    if regime is not None:
        # crisis 判定需要额外条件：credit_spread > 500bp AND ted_spread > 100bp
        credit_spread = dashboard.get("credit_spread")
        ted_spread = dashboard.get("ted_spread")
        if vix_value is not None and vix_value > 30:
            cs_high = (isinstance(credit_spread, dict)
                       and credit_spread.get("value", 0) > 5.0)
            ted_high = (isinstance(ted_spread, (int, float))
                        and ted_spread > 1.0)
            if cs_high and ted_high:
                regime = "crisis"
        data["vix_regime"] = regime

    # ── SP500 ──
    sp500_entry = dashboard.get("sp500", {})
    sp500_value = _get_value(sp500_entry)
    if sp500_value is not None:
        data["sp500"] = {
            "value": round(sp500_value, 1),
            "source": sp500_entry.get("source", "fred"),
            "updated_at": sp500_entry.get("updated_at", now),
        }

    # SP500 日变化
    sp500_records = _read_history_csv(
        DATA_HISTORY_DAILY / "sp500.csv", value_col="value"
    )
    sp500_change = _compute_change_d(sp500_records)
    if sp500_change is not None:
        data["sp500_change_d"] = round(sp500_change, 1)

    # ── 信用利差 / TED 利差（FRED BAMLH0A0HYM2） ──
    credit_spread_data = dashboard.get("credit_spread")
    if credit_spread_data:
        data["credit_spread"] = credit_spread_data

    ted_spread_data = dashboard.get("ted_spread")
    if ted_spread_data:
        data["ted_spread"] = ted_spread_data

    # ── 三周期信号（VIX，nota: VIX上升=避险利多，反转方向）──
    vix_signals = _compute_multi_scale_signals(vix_records)
    if vix_signals:
        for p, sig in vix_signals.items():
            if sig and sig["direction"] != "neutral":
                # VIX 上升 = 恐慌 = 利多金银 → 反转方向
                sig["direction"] = "bullish" if sig["direction"] == "bearish" else "bearish"
    data["signals"] = vix_signals

    return data


def compute_inflation(dashboard: dict) -> Dict[str, Any]:
    """
    计算通胀预期因子（Factor 4）。

    关键字段 breakeven_10y = nominal_10y - tips_10y。
    依赖 dashboard.tips_10y 和 dashboard.treasury_10y / treasury。
    """
    data: Dict[str, Any] = {}
    now = _now_cst()

    # ── 盈亏平衡通胀率 ──
    tips_entry = dashboard.get("tips_10y", {})
    tips_value = _get_value(tips_entry)

    nominal_10y_entry = dashboard.get("treasury_10y", {})
    nominal_value = _get_value(nominal_10y_entry)
    if nominal_value is None:
        treasury_entry = dashboard.get("treasury", {})
        nominal_value = treasury_entry.get("10yr")

    if tips_value is not None and nominal_value is not None:
        breakeven = round(nominal_value - tips_value, 2)
        data["breakeven_10y"] = {
            "value": breakeven,
            "source": "calc (nominal_10y - tips_10y)",
            "updated_at": now,
        }

        # 盈亏平衡日变化
        tips_records = _read_history_csv(
            DATA_HISTORY_DAILY / "tips.csv", value_col="value"
        )
        treasury_records = _read_history_csv(
            DATA_HISTORY_DAILY / "treasury.csv", value_col="10yr"
        )
        if tips_records and treasury_records:
            min_len = min(len(tips_records), len(treasury_records))
            if min_len >= 2:
                prev_be = round(
                    treasury_records[-2]["value"] - tips_records[-2]["value"], 2
                )
                be_change = round(breakeven - prev_be, 2)
                data["breakeven_change_d"] = be_change

    # ── 手动/月度指标 ──
    cpi = dashboard.get("cpi_yoy")
    if cpi:
        data["cpi_yoy"] = cpi

    pce = dashboard.get("pce_core")
    if pce:
        data["pce_core"] = pce

    # ── 原油 WTI + 布伦特 ──
    oil_wti = dashboard.get("oil_wti")
    if oil_wti:
        data["oil_wti"] = oil_wti

    oil_brent = dashboard.get("oil_brent")
    if oil_brent:
        data["oil_brent"] = oil_brent

    copper = dashboard.get("copper")
    if copper:
        data["copper"] = copper

    # ── 三周期信号（盈亏平衡通胀率） ──
    if tips_records and treasury_records:
        # 计算盈亏平衡序列
        min_len = min(len(tips_records), len(treasury_records))
        if min_len >= 5:
            be_records = []
            for i in range(min_len):
                t = tips_records[i]["value"]
                n = treasury_records[i]["value"]
                if t is not None and n is not None:
                    be_records.append({"date": tips_records[i]["date"], "value": n - t})
            if len(be_records) >= 5:
                data["signals"] = _compute_multi_scale_signals(be_records)

    return data


def compute_positioning(dashboard: dict) -> Dict[str, Any]:
    """
    计算持仓动量因子（Factor 5）。

    依赖：
    - dashboard.gold_futures（含 volume=OI）
    - dashboard.silver_futures（含 volume=OI）
    - dashboard.shfe_gold, dashboard.shfe_silver
    """
    data: Dict[str, Any] = {}
    now = _now_cst()

    # ── COMEX 黄金 OI ──
    gold_futures = dashboard.get("gold_futures", {})
    gold_oi = gold_futures.get("volume") if isinstance(gold_futures, dict) else None
    if gold_oi is not None:
        data["gold_oi"] = {
            "value": int(gold_oi),
            "source": "yahoo_finance",
            "updated_at": gold_futures.get("updated_at", now),
        }

    # COMEX 白银 OI
    silver_futures = dashboard.get("silver_futures", {})
    silver_oi = silver_futures.get("volume") if isinstance(silver_futures, dict) else None
    if silver_oi is not None:
        data["silver_oi"] = {
            "value": int(silver_oi),
            "source": "yahoo_finance",
            "updated_at": silver_futures.get("updated_at", now),
        }

    # ── GLD / SLV 持仓（待新增采集器填充） ──
    gld = dashboard.get("gld_holdings")
    if gld:
        data["gld_holdings"] = gld

    slv = dashboard.get("slv_holdings")
    if slv:
        data["slv_holdings"] = slv

    # ── COT 净多头（待新增采集） ──
    cot = dashboard.get("cot_net_long_pct")
    if cot:
        data["cot_net_long_pct"] = cot

    # ── 沪金 OI ──
    shfe_gold = dashboard.get("shfe_gold", {})
    shfe_gold_oi = shfe_gold.get("open_interest") if isinstance(shfe_gold, dict) else None
    if shfe_gold_oi is not None:
        data["shfe_gold_oi"] = {
            "value": int(shfe_gold_oi),
            "source": "akshare",
            "updated_at": shfe_gold.get("updated_at", now),
        }

    # ── 沪银 OI ──
    shfe_silver = dashboard.get("shfe_silver", {})
    shfe_silver_oi = shfe_silver.get("open_interest") if isinstance(shfe_silver, dict) else None
    if shfe_silver_oi is not None:
        data["shfe_silver_oi"] = {
            "value": int(shfe_silver_oi),
            "source": "akshare",
            "updated_at": shfe_silver.get("updated_at", now),
        }

    # ── 三周期信号（沪银 OI 或 COMEX 持仓量） ──
    # 沪银持仓量序列从 china_futures.csv 读
    positioning_path = DATA_HISTORY_DAILY / "china_futures.csv"
    if positioning_path.exists():
        import csv
        try:
            with open(positioning_path, "r", encoding="utf-8") as f:
                pos_rows = [r for r in csv.DictReader(f) if r.get("symbol") == "AG"]
            if len(pos_rows) >= 5:
                oi_records = []
                for r in pos_rows:
                    oi = r.get("open_interest")
                    if oi:
                        try:
                            oi_records.append({"date": r.get("date"), "value": float(oi)})
                        except (ValueError, TypeError):
                            continue
                if len(oi_records) >= 5:
                    data["signals"] = _compute_multi_scale_signals(oi_records)
        except Exception:
            pass

    return data


def compute_structural_demand(dashboard: dict) -> Dict[str, Any]:
    """
    计算结构性需求因子（Factor 6）。

    全部为手动/季度数据，当前无自动采集。
    从 dashboard 中读取已有数据（如有），否则留空。
    """
    data: Dict[str, Any] = {}

    # 央行购金数据（手动录入）
    cbg = dashboard.get("central_bank_gold_t")
    if cbg:
        data["central_bank_gold_t"] = cbg

    cbg_yoy = dashboard.get("central_bank_gold_yoy")
    if cbg_yoy:
        data["central_bank_gold_yoy"] = cbg_yoy

    # IMF COFER 数据（手动录入）
    usd_reserve = dashboard.get("usd_reserve_share")
    if usd_reserve:
        data["usd_reserve_share"] = usd_reserve

    gold_reserve = dashboard.get("gold_reserve_share")
    if gold_reserve:
        data["gold_reserve_share"] = gold_reserve

    # 最近已知趋势描述
    last_note = dashboard.get("last_known_note")
    if last_note:
        data["last_known_note"] = last_note

    return data


def compute_silver_specific(dashboard: dict) -> Dict[str, Any]:
    """
    计算银价专用因子（Factor 7）。

    依赖：
    - 金银比（从 dashboard 或历史数据）
    - data/history/daily/gold_silver_daily.csv（用于分位数计算）
    """
    data: Dict[str, Any] = {}
    now = _now_cst()

    # ── 金银比 ──
    ratio_entry = dashboard.get("gold_silver_ratio", {})
    ratio_value = _get_value(ratio_entry)

    if ratio_value is None:
        # 从现货价格计算
        gold_value = _get_value(dashboard.get("gold_price", {}))
        silver_value = _get_value(dashboard.get("silver_price", {}))
        if gold_value and silver_value and silver_value > 0:
            ratio_value = round(gold_value / silver_value, 2)

    if ratio_value is not None:
        data["gold_silver_ratio"] = {
            "value": ratio_value,
            "source": "calc (gold/silver)",
            "updated_at": now,
        }

    # 金银比 5 年分位数
    gs_records = _read_history_csv(
        DATA_HISTORY_DAILY / "gold_silver_daily.csv", value_col="ratio_close"
    )
    if ratio_value is not None:
        percentile = _compute_percentile(gs_records, window=1250)
        if percentile is not None:
            data["gs_ratio_percentile"] = percentile

    # ── 白银库存（待新增采集） ──
    silver_inv = dashboard.get("silver_inventory")
    if silver_inv:
        data["silver_inventory"] = silver_inv

    # ── 光伏增速（手动/年度） ──
    solar_growth = dashboard.get("solar_pv_growth")
    if solar_growth:
        data["solar_pv_growth"] = solar_growth

    # ── 三周期信号（金银比） ──
    if len(gs_records) >= 5:
        data["signals"] = _compute_multi_scale_signals(gs_records)

    return data


# ====================================================================
#  事件与新闻加载
# ====================================================================


def load_events_for_factors() -> List[Dict[str, Any]]:
    """
    从 event_tracker.json 加载事件数据，按 factor_tags 归类。

    V1 版本：news_rss 已直接标注 factor_tags 字段（七因子），不再需要四象限映射。
    """
    events_data: List[Dict[str, Any]] = []
    tracker = _read_json(EVENT_FILE)
    active_events = tracker.get("active_events", [])

    for evt in active_events[:20]:  # 最多20条
        factor_tags = evt.get("factor_tags", [])
        events_data.append({
            "id": evt.get("title", "")[:40] + "...",
            "title": evt.get("title", ""),
            "summary": evt.get("summary", "")[:200],
            "source": evt.get("source", "news_rss"),
            "detected_at": evt.get("detected_at", ""),
            "factor_tags": factor_tags,
            "impact": None,  # 由后续分析填充
            "expiry": None,
        })

    return events_data


# ====================================================================
#  技术指标计算
# ====================================================================

def _read_records_sorted(path: Path, date_col: str = "date",
                          sort_asc: bool = True) -> List[Dict[str, Any]]:
    """
    读取 CSV 并统一排序返回。
    自动处理 YYYY-MM-DD 和 MM/DD/YYYY 两种日期格式。
    """
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
    except (OSError, csv.Error):
        return []
    # 统一日期格式
    for r in rows:
        raw = (r.get(date_col) or "").strip()
        if "/" in raw:
            parts = raw.split("/")
            if len(parts) == 3:
                r["_date"] = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
        else:
            r["_date"] = raw
    rows.sort(key=lambda r: r.get("_date", ""), reverse=not sort_asc)
    return rows


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default
    return default


def _ema(values: List[float], window: int) -> List[Optional[float]]:
    """计算指数移动平均，返回与输入等长的列表"""
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < window:
        return result
    # 初始 SMA
    sma = sum(values[:window]) / window
    result[window - 1] = sma
    multiplier = 2 / (window + 1)
    for i in range(window, len(values)):
        result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def _compute_rsi(closes: List[float], window: int = 14) -> Optional[float]:
    """计算 RSI(14)，返回最新值"""
    if len(closes) < window + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    # 初始 SMA
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    if avg_loss == 0:
        return 100.0
    # 平滑计算
    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _compute_macd(closes: List[float], fast: int = 12, slow: int = 26,
                   signal: int = 9) -> Optional[Dict[str, float]]:
    """计算 MACD(12,26,9)，返回最新值"""
    if len(closes) < slow + signal:
        return None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line: List[Optional[float]] = []
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line.append(ema_fast[i] - ema_slow[i])
        else:
            macd_line.append(None)
    valid_macd = [v for v in macd_line if v is not None]
    if len(valid_macd) < signal:
        return None
    signal_line_values = _ema(valid_macd, signal)
    macd_val = valid_macd[-1]
    sig_val = signal_line_values[-1]
    if macd_val is None or sig_val is None:
        return None
    return {
        "macd": round(macd_val, 2),
        "signal": round(sig_val, 2),
        "histogram": round(macd_val - sig_val, 2),
    }


def _compute_atr(highs: List[float], lows: List[float],
                 closes: List[float], window: int = 14) -> Optional[float]:
    """计算 ATR(14)，返回最新值"""
    if len(highs) < window + 1 or len(lows) < window + 1 or len(closes) < window + 1:
        return None
    tr_values = []
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_values.append(max(hl, hc, lc))
    if len(tr_values) < window:
        return None
    # 初始 SMA
    atr = sum(tr_values[:window]) / window
    # 平滑
    for i in range(window, len(tr_values)):
        atr = (atr * (window - 1) + tr_values[i]) / window
    return round(atr, 2)


def _compute_adx(highs: List[float], lows: List[float],
                 closes: List[float], window: int = 14) -> Optional[float]:
    """计算 ADX(14)，返回最新值"""
    if len(highs) < window * 2 + 1:
        return None
    # +DM, -DM, TR
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0)
        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0)
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr.append(max(hl, hc, lc))

    if len(tr) < window:
        return None

    # 平滑
    def _smooth(values, w):
        result = [0.0] * len(values)
        result[w - 1] = sum(values[:w]) / w
        for i in range(w, len(values)):
            result[i] = (result[i - 1] * (w - 1) + values[i]) / w
        return result

    smooth_tr = _smooth(tr, window)
    smooth_pdm = _smooth(plus_dm, window)
    smooth_mdm = _smooth(minus_dm, window)

    # +DI, -DI
    di_plus, di_minus = [], []
    for i in range(window, len(smooth_tr)):
        tr_v = smooth_tr[i]
        di_plus.append(100 * smooth_pdm[i] / tr_v if tr_v != 0 else 0)
        di_minus.append(100 * smooth_mdm[i] / tr_v if tr_v != 0 else 0)

    if len(di_plus) < window:
        return None

    # DX
    dx_values = []
    for i in range(len(di_plus)):
        sum_di = di_plus[i] + di_minus[i]
        if sum_di != 0:
            dx_values.append(100 * abs(di_plus[i] - di_minus[i]) / sum_di)
        else:
            dx_values.append(0)

    # ADX = EMA of DX
    adx_values = _smooth(dx_values, window)
    adx = [v for v in adx_values if v > 0]
    return round(adx[-1], 1) if adx else None


def _compute_ma_from(values: List[float], window: int) -> Optional[float]:
    """计算简单移动平均最新值"""
    if len(values) < window:
        return None
    recent = values[-window:]
    return round(sum(recent) / window, 2)


def compute_technicals(dashboard: dict) -> Dict[str, Any]:
    """
    计算金银技术指标。

    数据来源：
    - china_futures.csv — SHFE 金银 (AU/AG)，有完整 OHLC + 成交量数据
    - gold_silver_daily.csv — 现货金银 (USD)，日线数据

    指标：MA20/60/200, RSI(14), MACD(12,26,9), ATR(14), ADX(14)
    """
    result: Dict[str, Any] = {}

    # ── SHFE 数据（china_futures.csv）──
    cf_path = DATA_HISTORY_DAILY / "china_futures.csv"
    cf_rows = _read_records_sorted(cf_path) if cf_path.exists() else []

    for symbol, key in [("AU", "shfe_gold"), ("AG", "shfe_silver")]:
        sym_rows = [r for r in cf_rows if r.get("symbol") == symbol]
        if len(sym_rows) < 20:
            result[key] = {"error": f"数据不足 (共{len(sym_rows)}行)"}
            continue

        closes = [_safe_float(r.get("close")) for r in sym_rows if r.get("close")]
        highs = [_safe_float(r.get("high")) for r in sym_rows if r.get("high")]
        lows = [_safe_float(r.get("low")) for r in sym_rows if r.get("low")]
        volumes = [_safe_float(r.get("volume")) for r in sym_rows if r.get("volume")]
        oi = [_safe_float(r.get("open_interest")) for r in sym_rows if r.get("open_interest")]

        tech: Dict[str, Any] = {
            "price": closes[-1] if closes else None,
            "volume": volumes[-1] if volumes else None,
            "open_interest": oi[-1] if oi else None,
            "ma20": _compute_ma_from(closes, 20),
            "ma60": _compute_ma_from(closes, 60),
            "ma200": _compute_ma_from(closes, 200),
            "rsi_14": _compute_rsi(closes, 14),
            "macd": _compute_macd(closes, 12, 26, 9),
            "atr_14": _compute_atr(highs, lows, closes, 14),
            "adx_14": _compute_adx(highs, lows, closes, 14),
            "data_range": f"{sym_rows[0].get('_date', '')} ~ {sym_rows[-1].get('_date', '')}",
            "data_rows": len(sym_rows),
        }
        result[key] = tech

    # ── 现货数据（gold_silver_daily.csv）──
    gs_path = DATA_HISTORY_DAILY / "gold_silver_daily.csv"
    gs_rows = _read_records_sorted(gs_path) if gs_path.exists() else []

    for prefix, close_col, high_col, low_col in [
        ("gold", "gold_close", "gold_high", "gold_low"),
        ("silver", "silver_close", "silver_high", "silver_low"),
    ]:
        closes = [_safe_float(r.get(close_col)) for r in gs_rows if r.get(close_col)]
        highs = [_safe_float(r.get(high_col)) for r in gs_rows if r.get(high_col)]
        lows = [_safe_float(r.get(low_col)) for r in gs_rows if r.get(low_col)]
        if len(closes) < 14:
            result[f"spot_{prefix}"] = {"error": f"数据不足 (共{len(closes)}行)"}
            continue

        tech: Dict[str, Any] = {
            "price": closes[-1] if closes else None,
            "ma20": _compute_ma_from(closes, 20),
            "ma60": _compute_ma_from(closes, 60),
            "ma200": _compute_ma_from(closes, 200),
            "rsi_14": _compute_rsi(closes, 14),
            "macd": _compute_macd(closes, 12, 26, 9),
            "atr_14": _compute_atr(highs, lows, closes, 14),
            "adx_14": _compute_adx(highs, lows, closes, 14),
            "data_range": f"{gs_rows[0].get('_date', '')} ~ {gs_rows[-1].get('_date', '')}",
            "data_rows": len(gs_rows),
        }
        result[f"spot_{prefix}"] = tech

    return result


def compute_all() -> dict:
    """
    全量计算所有因子的数据。

    流程:
    1. 读取 dashboard_data.json 快照
    2. 读取历史 CSV 计算趋势和变化
    3. 读取 event_tracker.json 获取事件
    4. 按7因子组织数据
    5. 写回 data/factors/current_factors.json
    """
    dashboard = _read_json(DASHBOARD_FILE)

    # 计算每个因子
    factor_computers = {
        "opportunity_cost": compute_opportunity_cost,
        "currency": compute_currency,
        "safe_haven": compute_safe_haven,
        "inflation": compute_inflation,
        "positioning": compute_positioning,
        "structural_demand": compute_structural_demand,
        "silver_specific": compute_silver_specific,
    }

    factors: Dict[str, Any] = {}
    for factor_id, computer in factor_computers.items():
        label = FACTOR_DEFINITIONS[factor_id]["label"]
        factor_data = computer(dashboard)
        factors[factor_id] = {
            "label": label,
            "signal": None,
            "data": factor_data if factor_data else {},
        }

    # 加载事件
    events = load_events_for_factors()

    # 计算技术指标
    technicals = compute_technicals(dashboard)

    # 组装顶层结构
    result: dict = {
        "updated_at": _now_cst(),
        "data_source": "V1 采集 + compute_factors.py",
        "factors": factors,
        "events": events,
        "technicals": technicals,
        "summary": {},
    }

    return result


def compute_single_factor(factor_id: str) -> Optional[dict]:
    """
    计算单个因子数据。

    Args:
        factor_id: 因子 ID（opportunity_cost / currency / ...）

    Returns:
        包含该因子的完整顶层结构，因子不存在时返回 None
    """
    if factor_id not in FACTOR_DEFINITIONS:
        return None

    dashboard = _read_json(DASHBOARD_FILE)

    computer_map = {
        "opportunity_cost": compute_opportunity_cost,
        "currency": compute_currency,
        "safe_haven": compute_safe_haven,
        "inflation": compute_inflation,
        "positioning": compute_positioning,
        "structural_demand": compute_structural_demand,
        "silver_specific": compute_silver_specific,
    }

    label = FACTOR_DEFINITIONS[factor_id]["label"]
    computer = computer_map[factor_id]
    factor_data = computer(dashboard)

    result: dict = {
        "updated_at": _now_cst(),
        "data_source": "V1 采集 + compute_factors.py",
        "factors": {
            factor_id: {
                "label": label,
                "signal": None,
                "data": factor_data if factor_data else {},
            }
        },
        "events": [],
        "summary": {},
    }

    return result


# ====================================================================
#  CLI
# ====================================================================


def main():
    parser = argparse.ArgumentParser(
        description="因子对齐数据计算器 — 将原始数据按7因子模型结构化"
    )
    parser.add_argument(
        "--factor", type=str, default=None,
        choices=list(FACTOR_DEFINITIONS.keys()),
        help="计算指定因子（默认全量计算）"
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="同时输出格式化 JSON 到 stdout"
    )
    args = parser.parse_args()

    if args.factor:
        result = compute_single_factor(args.factor)
        if result is None:
            print(f"错误: 未知因子 '{args.factor}'，可选: {list(FACTOR_DEFINITIONS.keys())}")
            sys.exit(1)
    else:
        result = compute_all()

    # 写入文件
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ 因子数据已写入: {OUTPUT_FILE}")
    except OSError as e:
        print(f"❌ 写入失败: {e}", file=sys.stderr)
        sys.exit(1)

    # stderr 概要
    factor_count = len(result["factors"])
    event_count = len(result["events"])
    print(f"   因子数: {factor_count}, 事件数: {event_count}", file=sys.stderr)
    if args.factor:
        fd = result["factors"].get(args.factor, {})
        field_count = len(fd.get("data", {}))
        print(f"   因子 '{args.factor}' 字段数: {field_count}", file=sys.stderr)

    # stdout 格式化输出
    if args.pretty:
        print("---")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
