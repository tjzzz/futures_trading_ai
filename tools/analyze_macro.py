#!/usr/bin/env python3
"""
宏观综合研判脚本 — 金银价格七因子信号合成

定位：
  对七个因子做信号合成，输出结构化分析结果。
  可作为 AI Agent 的工具调用，也可独立运行输出可读文本。

用法:
  python tools/analyze_macro.py                           # 默认：输出可读文本
  python tools/analyze_macro.py --json                    # JSON 输出到 stdout
  python tools/analyze_macro.py --output analysis.json    # JSON 输出到文件
  python tools/analyze_macro.py --input factors.json      # 指定输入文件

信号合成规则 (加权投票制):
  bullish_score = Σ(strength_i) for factor_i.signal == bullish
  bearish_score = Σ(strength_i) for factor_i.signal == bearish
  if bullish_score > bearish_score * 1.5 → bullish
  if bearish_score > bullish_score * 1.5 → bearish
  else → neutral/mixed

  主导因子 = max(strength) 的非中性因子

框架文档:
  Projects/交易Agent系统/1_宏观三维七因子归因框架.md
"""

import argparse
import csv
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("analyze_macro")

# =============================================================================
# 路径配置
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"
DATA_CURRENT = PROJECT_ROOT / "data" / "current"
DATA_FACTORS = PROJECT_ROOT / "data" / "factors"
DATA_HISTORY = PROJECT_ROOT / "data" / "history" / "daily"

DASHBOARD_FILE = DATA_CURRENT / "dashboard_data.json"
FACTORS_FILE = DATA_FACTORS / "current_factors.json"
PREDICTION_LOG_FILE = DATA_FACTORS / "prediction_log.json"
COMPUTE_FACTORS_SCRIPT = TOOLS_DIR / "compute_factors.py"

VAULT_ROOT = Path(
    "/Users/zhenzhenzheng/Library/Mobile Documents/"
    "com~apple~CloudDocs/Obsidian/blog_zhenzhen"
)
WIKI_TRADE = VAULT_ROOT / "wiki_trade"
MACRO_MEMO_FILE = WIKI_TRADE / "memory" / "macro_memo.md"

# =============================================================================
# 因子定义
# =============================================================================

# 因子权重配置 — 反映各因子对金价的解释力
FACTOR_DEFINITIONS: Dict[str, dict] = {
    "opportunity_cost": {
        "label": "机会成本",
        "weight": 1.0,       # 常态主导因子，解释力 50-60%
        "order": 1,
    },
    "currency": {
        "label": "货币",
        "weight": 0.6,       # 与机会成本有重叠，需正交化
        "order": 2,
    },
    "safe_haven": {
        "label": "避险需求",
        "weight": 0.8,
        "order": 3,
    },
    "inflation": {
        "label": "通胀预期",
        "weight": 0.6,
        "order": 4,
    },
    "positioning": {
        "label": "持仓动量",
        "weight": 0.5,       # 放大器角色，非独立驱动
        "order": 5,
    },
    "structural_demand": {
        "label": "结构性需求",
        "weight": 0.4,       # 长期因素，短期变化小
        "order": 6,
    },
    "silver_specific": {
        "label": "银价专用",
        "weight": 0.3,
        "order": 7,
    },
}

# =============================================================================
# 工具函数
# =============================================================================


def _safe_float(v, default: float = 0.0) -> float:
    """将各种可能的值安全转为 float

    Args:
        v: 输入值（可以是数字、字符串、或 {'value': X} 形式）
        default: 转换失败时的默认值

    Returns:
        浮点数
    """
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return _safe_float(v.get("value"), default)
    if isinstance(v, str):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default
    return default


def _get_nested(d: dict, *keys, default=None):
    """安全获取嵌套字典值

    Args:
        d: 字典
        *keys: 键路径
        default: 缺失时的默认值

    Returns:
        找到的值或默认值
    """
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, {})
        else:
            return default
    return current if current != {} else default


def _read_json(path: Path) -> dict:
    """读取 JSON 文件，失败返回空字典"""
    if not path.exists():
        logger.debug(f"文件不存在: {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return {}


def _read_csv_tail(path: Path, n: int = 30) -> List[dict]:
    """读取 CSV 文件最后 n 行

    Args:
        path: CSV 文件路径
        n: 返回行数

    Returns:
        dict 列表，最近的在最后
    """
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows[-n:]
    except Exception as e:
        logger.warning("读取 CSV %s 失败: %s", path, e)
        return []


def _detect_trend(values: List[float], threshold_pct: float = 1.0) -> str:
    """从数值序列检测趋势方向

    比较序列前 1/3 和后 1/3 的均值，判断趋势。

    Args:
        values: 数值序列（时间升序）
        threshold_pct: 判定趋势的最小变化百分比

    Returns:
        "up" / "down" / "flat"
    """
    if len(values) < 6:
        return "unknown"

    mid = len(values) // 3
    first_avg = sum(values[:mid]) / mid
    last_avg = sum(values[-mid:]) / mid

    if first_avg == 0:
        return "flat"

    change_pct = (last_avg - first_avg) / abs(first_avg) * 100
    if change_pct > threshold_pct:
        return "up"
    elif change_pct < -threshold_pct:
        return "down"
    return "flat"


def _parse_front_matter(text: str) -> dict:
    """解析 Markdown YAML front matter

    Args:
        text: 完整的 Markdown 文本

    Returns:
        解析出的front matter字段字典
    """
    match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    result = {}
    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


# =============================================================================
# 历史数据读取
# =============================================================================


def _get_tips_data() -> Tuple[float, str]:
    """从历史 CSV 读取 TIPS 趋势

    Returns:
        (最新值, 20日趋势)
    """
    path = DATA_HISTORY / "tips.csv"
    rows = _read_csv_tail(path, 25)
    if not rows:
        return 0.0, "unknown"

    values = []
    for r in rows:
        try:
            values.append(float(r.get("value", 0)))
        except (ValueError, TypeError):
            continue

    if not values:
        return 0.0, "unknown"

    latest = values[-1]
    trend = _detect_trend(values, threshold_pct=1.0)
    return latest, trend


def _get_dxy_data() -> Tuple[float, str]:
    """从历史 CSV 读取 DXY 趋势

    Returns:
        (最新值, 60日趋势)
    """
    path = DATA_HISTORY / "dxy.csv"
    rows = _read_csv_tail(path, 65)
    if not rows:
        return 0.0, "unknown"

    values = []
    for r in rows:
        try:
            values.append(float(r.get("value", 0)))
        except (ValueError, TypeError):
            continue

    if not values:
        return 0.0, "unknown"

    latest = values[-1]
    trend = _detect_trend(values, threshold_pct=0.5)
    return latest, trend


# =============================================================================
# 数据加载
# =============================================================================


def load_factor_data() -> dict:
    """加载因子数据

    优先级：
    1. 尝试读取 data/factors/current_factors.json（compute_factors.py 输出）
    2. 尝试调用 compute_factors.py 生成
    3. 从 dashboard_data.json 自行构建

    Returns:
        因子数据字典（与 compute_factors.py 输出格式一致）
    """
    # 优先级 1：直接读取
    factors_data = _read_json(FACTORS_FILE)
    if factors_data:
        logger.info("已从 %s 读取因子数据", FACTORS_FILE)
        return factors_data

    # 优先级 2：调用 compute_factors.py
    if COMPUTE_FACTORS_SCRIPT.exists():
        logger.info("调用 compute_factors.py 生成因子数据...")
        try:
            result = subprocess.run(
                [sys.executable, str(COMPUTE_FACTORS_SCRIPT), "--pretty"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                factors_data = json.loads(result.stdout)
                logger.info("compute_factors.py 调用成功")
                return factors_data
            else:
                logger.warning("compute_factors.py 失败: %s", result.stderr[:200])
        except Exception as e:
            logger.warning("compute_factors.py 异常: %s", e)

    # 优先级 3：从 dashboard 自行构建
    logger.info("从 dashboard_data.json 自行构建因子数据...")
    factors_data = _build_factors_from_dashboard()
    return factors_data


def _build_factors_from_dashboard() -> dict:
    """从 dashboard_data.json 构建因子数据结构

    由于 compute_factors.py 尚未实现时的降级方案。
    直接解析已有快照数据，组织为标准因子格式。

    Returns:
        因子数据字典
    """
    dashboard = _read_json(DASHBOARD_FILE)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ===== 提取原始数据 =====
    # 机会成本
    tips_raw = _safe_float(_get_nested(dashboard, "tips_10y", "value"))
    tips_hist, tips_trend = _get_tips_data()
    tips_value = tips_raw if tips_raw else tips_hist

    nominal_raw = _safe_float(_get_nested(dashboard, "treasury_10y", "value"))
    nominal_change = _get_nested(dashboard, "treasury_10y", "change")

    # 货币
    dxy_raw = _safe_float(_get_nested(dashboard, "dxy", "value"))
    dxy_hist, dxy_trend = _get_dxy_data()
    dxy_value = dxy_raw if dxy_raw else dxy_hist
    dxy_change = _safe_float(_get_nested(dashboard, "dxy", "change"))

    # 避险
    vix_raw = _safe_float(_get_nested(dashboard, "vix", "value"))
    vix_change = _safe_float(_get_nested(dashboard, "vix", "change"))
    sp500_raw = _safe_float(_get_nested(dashboard, "sp500", "value"))

    # 价格
    gold_futures = _safe_float(_get_nested(dashboard, "gold_futures", "value"))
    gold_spot = _safe_float(_get_nested(dashboard, "gold_price", "value"))
    gold_price = gold_futures if gold_futures else gold_spot

    silver_futures = _safe_float(_get_nested(dashboard, "silver_futures", "value"))
    silver_spot = _safe_float(_get_nested(dashboard, "silver_price", "value"))
    silver_price = silver_futures if silver_futures else silver_spot

    gs_ratio_val = _safe_float(_get_nested(dashboard, "gold_silver_ratio", "value"))

    # SHFE
    shfe_gold_close = _safe_float(_get_nested(dashboard, "shfe_gold", "close"))
    shfe_gold_oi = _safe_float(_get_nested(dashboard, "shfe_gold", "open_interest"))
    shfe_silver_close = _safe_float(_get_nested(dashboard, "shfe_silver", "close"))
    shfe_silver_oi = _safe_float(_get_nested(dashboard, "shfe_silver", "open_interest"))

    # 盈亏平衡通胀率
    breakeven = nominal_raw - tips_value if nominal_raw and tips_value else 0.0

    # ===== VIX regime =====
    if vix_raw < 15:
        vix_regime = "calm"
    elif vix_raw < 20:
        vix_regime = "moderate"
    elif vix_raw < 25:
        vix_regime = "elevated"
    elif vix_raw < 30:
        vix_regime = "panic"
    else:
        vix_regime = "crisis"

    # ===== 活跃事件摘要 =====
    active_events = []
    for evt_key in ("active_a", "active_s"):
        evts = _get_nested(dashboard, "events", evt_key, default=[])
        if isinstance(evts, list):
            active_events.extend(evts[:3])

    # ===== 组装 =====
    factors = {
        "updated_at": now,
        "data_source": "dashboard_data.json（analyze_macro.py 自行构建）",
        "factors": {
            "opportunity_cost": {
                "label": "机会成本",
                "signal": None,
                "data": {
                    "tips_10y": {
                        "value": round(tips_value, 2),
                        "source": "fred",
                        "updated": _get_nested(
                            dashboard, "tips_10y", "updated_at", default=now
                        ),
                    },
                    "tips_10y_change_d": 0.0,
                    "tips_10y_trend_20d": tips_trend,
                    "nominal_10y": {
                        "value": round(nominal_raw, 2),
                        "source": _get_nested(
                            dashboard, "treasury_10y", "source", default="yahoo"
                        ),
                        "updated": _get_nested(
                            dashboard, "treasury_10y", "updated_at", default=now
                        ),
                    },
                    "nominal_10y_change_d": _safe_float(nominal_change),
                },
            },
            "currency": {
                "label": "货币",
                "signal": None,
                "data": {
                    "dxy": {
                        "value": round(dxy_value, 3),
                        "source": "yahoo",
                        "updated": _get_nested(
                            dashboard, "dxy", "updated_at", default=now
                        ),
                    },
                    "dxy_change_d": round(dxy_change, 3),
                    "dxy_trend_60d": dxy_trend,
                    "dxy_vs_200ma": "unknown",
                },
            },
            "safe_haven": {
                "label": "避险需求",
                "signal": None,
                "data": {
                    "vix": {
                        "value": round(vix_raw, 2),
                        "source": "yahoo",
                        "updated": _get_nested(
                            dashboard, "vix", "updated_at", default=now
                        ),
                    },
                    "vix_change_d": round(vix_change, 2),
                    "vix_ma20": 0.0,
                    "vix_regime": vix_regime,
                    "sp500": {
                        "value": round(sp500_raw, 1),
                    },
                },
            },
            "inflation": {
                "label": "通胀预期",
                "signal": None,
                "data": {
                    "breakeven_10y": {
                        "value": round(breakeven, 2),
                        "source": "计算（10Y - TIPS）",
                    },
                    "nominal_10y": round(nominal_raw, 2),
                    "tips_10y": round(tips_value, 2),
                },
            },
            "positioning": {
                "label": "持仓动量",
                "signal": None,
                "data": {
                    "shfe_gold_oi": shfe_gold_oi,
                    "shfe_gold_price": round(shfe_gold_close, 2),
                    "shfe_silver_oi": shfe_silver_oi,
                    "note": "COT数据待接入，目前仅参考SHFE持仓量",
                },
            },
            "structural_demand": {
                "label": "结构性需求",
                "signal": None,
                "data": {
                    "note": "央行购金数据为季度频次，暂无最新数据",
                    "events_context": active_events[:3],
                },
            },
            "silver_specific": {
                "label": "银价专用",
                "signal": None,
                "data": {
                    "gold_silver_ratio": {
                        "value": round(gs_ratio_val, 2),
                        "percentile_5y": None,
                    },
                    "shfe_silver_close": round(shfe_silver_close, 2),
                },
            },
        },
        "events": [],
        "summary": {},
    }

    return factors


# =============================================================================
# 因子信号判定
# =============================================================================


def _analyze_opportunity_cost(fdata: dict) -> Tuple[str, float, str, dict]:
    """判定机会成本因子信号

    逻辑：
      - TIPS < 1.5% → 强烈看多（strength 0.9）
      - TIPS 1.5~2.0% → 明显看多（strength 0.7）
      - TIPS 2.0~2.3% → 偏多（strength 0.5）
      - TIPS 2.3~2.7% → 中性
      - TIPS 2.7~3.0% → 偏空（strength 0.4）
      - TIPS > 3.0% → 看空（strength 0.7）
      - 趋势增强：同向趋势 +0.15，逆向 -0.15

    Returns:
        (signal, strength, evidence, key_metrics)
    """
    data = fdata.get("data", {})

    tips_raw = data.get("tips_10y", {})
    tips = (
        tips_raw.get("value", 0)
        if isinstance(tips_raw, dict)
        else _safe_float(tips_raw)
    )
    tips_trend = data.get("tips_10y_trend_20d", "unknown")
    nominal_raw = data.get("nominal_10y", {})
    nominal = (
        nominal_raw.get("value", 0)
        if isinstance(nominal_raw, dict)
        else _safe_float(nominal_raw)
    )
    nominal_change = data.get("nominal_10y_change_d", 0)

    # ---- 基础信号 ----
    signal, strength = "neutral", 0.0
    if tips <= 0:
        signal, strength = "neutral", 0.0
    elif tips < 1.5:
        signal, strength = "bullish", 0.9
    elif tips < 2.0:
        signal, strength = "bullish", 0.7
    elif tips < 2.3:
        signal, strength = "bullish", 0.5
    elif tips < 2.7:
        signal, strength = "neutral", 0.0
    elif tips < 3.0:
        signal, strength = "bearish", 0.4
    else:
        signal, strength = "bearish", 0.7

    # ---- 趋势调整 ----
    if signal == "bullish" and tips_trend == "down":
        strength = min(strength + 0.15, 1.0)
    elif signal == "bullish" and tips_trend == "up":
        strength = max(strength - 0.15, 0.1)
    elif signal == "bearish" and tips_trend == "up":
        strength = min(strength + 0.15, 1.0)
    elif signal == "bearish" and tips_trend == "down":
        strength = max(strength - 0.15, 0.1)

    # ---- NFP 预期差修正 ----
    nfp_surprise = data.get("nfp_surprise_pct", {})
    nfp_signal_direction_matched = False
    if isinstance(nfp_surprise, dict):
        nfp_val = nfp_surprise.get("value")
        if nfp_val is not None:
            if nfp_val > 10:  # 超预期 > 10% → 经济过热 → 利空金银
                strength = min(strength + 0.2, 1.0)
                nfp_signal_direction_matched = True
            elif nfp_val > 5:  # 超预期 > 5%
                strength = min(strength + 0.1, 1.0)
            elif nfp_val < -10:  # 低于预期 > 10% → 经济走弱 → 利多金银
                strength = min(strength + 0.2, 1.0)
                nfp_signal_direction_matched = True

    # ---- evidence ----
    trend_cn = {
        "down": "下行",
        "up": "上行",
        "flat": "平稳",
        "unknown": "未知",
    }.get(tips_trend, tips_trend)

    parts = [f"TIPS 当前 {tips:.1f}%"]
    if isinstance(nominal_change, (int, float)) and nominal_change:
        parts.append(f"10Y 日变动 {nominal_change:+.0f}bp")
    parts.append(f"20日趋势 {trend_cn}")

    if signal == "bullish":
        if tips_trend == "up":
            parts.append("TIPS 虽处低位区间但趋势向上，看多力度受限。")
        else:
            parts.append("持有黄金的机会成本持续下降，为金价提供支撑。")
    elif signal == "bearish":
        parts.append("实际利率上升，对金价形成压力。")
    else:
        parts.append("实际利率处于中性区间。")

    evidence = "，".join(parts)

    # 添加 NFP 描述
    if isinstance(nfp_surprise, dict):
        nfp_val = nfp_surprise.get("value")
        nfp_event = nfp_surprise.get("event", "")
        if nfp_val is not None and abs(nfp_val) > 5:
            nfp_desc = f"非农{'超预期' if nfp_val > 0 else '低于预期'}{abs(nfp_val):.1f}%"
            if nfp_event:
                nfp_desc += f" ({nfp_event})"
            evidence += "，" + nfp_desc

    key_metrics = {
        "tips_10y": round(tips, 2),
        "tips_trend_20d": tips_trend,
        "nominal_10y": round(nominal, 2),
    }

    # 添加 NFP key metrics
    if isinstance(nfp_surprise, dict):
        nfp_val = nfp_surprise.get("value")
        if nfp_val is not None:
            key_metrics["nfp_surprise_pct"] = round(nfp_val, 2)

    return signal, round(strength, 2), evidence, key_metrics


def _analyze_currency(
    fdata: dict, opp_signal: str = "neutral"
) -> Tuple[str, float, str, dict]:
    """判定货币因子信号

    逻辑：
      - DXY < 98 → 看多（strength 0.7）
      - DXY 98~99 → 看多（strength 0.6）
      - DXY 99~100 → 偏多（strength 0.4）
      - DXY 100~101 → 略偏多（strength 0.2）
      - DXY 101~103 → 中性
      - DXY 103~105 → 略偏空（strength 0.3）
      - DXY > 105 → 看空（strength 0.5+）

    正交化：当 DXY 变动与 TIPS 同步时，货币因子贡献已被机会成本捕获。
    此时 strength 折减 40%。

    Args:
        fdata: 货币因子数据
        opp_signal: 机会成本因子信号（用于正交化）

    Returns:
        (signal, strength, evidence, key_metrics)
    """
    data = fdata.get("data", {})

    dxy_raw = data.get("dxy", {})
    dxy = (
        dxy_raw.get("value", 0)
        if isinstance(dxy_raw, dict)
        else _safe_float(dxy_raw)
    )
    dxy_change = _safe_float(data.get("dxy_change_d"))
    dxy_trend = data.get("dxy_trend_60d", "unknown")

    # ---- 基础信号 ----
    if dxy < 98:
        signal, strength = "bullish", 0.7
    elif dxy < 99:
        signal, strength = "bullish", 0.6
    elif dxy < 100:
        signal, strength = "bullish", 0.4
    elif dxy < 101:
        signal, strength = "slightly_bullish", 0.2
    elif dxy < 103:
        signal, strength = "neutral", 0.0
    elif dxy < 105:
        signal, strength = "slightly_bearish", 0.3
    elif dxy < 108:
        signal, strength = "bearish", 0.5
    else:
        signal, strength = "bearish", 0.7

    # 投票用信号（仅 bullish/bearish/neutral）
    vote_signal = signal
    if signal in ("slightly_bullish",):
        vote_signal, strength = "bullish", 0.1
    elif signal in ("slightly_bearish",):
        vote_signal, strength = "bearish", 0.1

    # ---- 正交化 ----
    if opp_signal != "neutral" and strength > 0:
        strength *= 0.6
        if strength < 0.1:
            vote_signal = "neutral"
            strength = 0.0

    # ---- evidence ----
    parts = [f"DXY {dxy:.1f}"]
    if dxy_change:
        parts.append(f"日{'涨' if dxy_change > 0 else '跌'}{abs(dxy_change):.2f}")

    if vote_signal == "bullish" and dxy < 100:
        parts.append("美元偏弱，对金价形成支撑。")
        if opp_signal != "neutral":
            parts.append("但 DXY 变动可能与 TIPS 同步，独立贡献有限。")
    elif vote_signal == "bearish":
        parts.append("美元偏强，对金价形成压力。")
    else:
        parts.append("美元处于中性区间。")

    evidence = "，".join(parts)

    key_metrics = {
        "dxy": round(dxy, 3),
        "dxy_change_d": round(dxy_change, 3),
        "dxy_trend_60d": dxy_trend,
    }

    return vote_signal, round(strength, 2), evidence, key_metrics


def _analyze_safe_haven(fdata: dict) -> Tuple[str, float, str, dict]:
    """判定避险需求因子信号

    逻辑（非单调因子）：
      - VIX < 15 → calm，中性
      - VIX 15~20 → moderate，偏多（strength 0.3）
      - VIX 20~25 → elevated，看多（strength 0.5）
      - VIX 25~30 → panic，强烈看多（strength 0.7）
      - VIX > 30 → 需检查流动性危机标志

    Returns:
        (signal, strength, evidence, key_metrics)
    """
    data = fdata.get("data", {})

    vix_raw = data.get("vix", {})
    vix = (
        vix_raw.get("value", 0)
        if isinstance(vix_raw, dict)
        else _safe_float(vix_raw)
    )
    vix_change = _safe_float(data.get("vix_change_d"))
    vix_regime = data.get("vix_regime", "unknown")

    # ---- 基础信号 ----
    if vix < 15:
        signal, strength = "neutral", 0.0
    elif vix < 20:
        signal, strength = "bullish", 0.3
    elif vix < 25:
        signal, strength = "bullish", 0.5
    elif vix < 30:
        signal, strength = "bullish", 0.7
    else:
        # VIX > 30 — 默认不触发流动性危机（需 credit spread 确认）
        signal, strength = "bullish", 0.8

    # ---- evidence ----
    regime_cn = {
        "calm": "低",
        "moderate": "中",
        "elevated": "偏高",
        "panic": "高",
        "crisis": "极高",
        "unknown": "未知",
    }.get(vix_regime, vix_regime)

    parts = [f"VIX {vix:.1f}", f"恐慌水平{regime_cn}"]
    if vix_change:
        parts.append(f"日{'涨' if vix_change > 0 else '跌'}{abs(vix_change):.2f}")

    if signal == "bullish" and vix < 25:
        parts.append("市场存在一定避险需求，对金价有温和支撑。")
    elif signal == "bullish" and vix >= 25:
        parts.append("市场恐慌情绪较高，避险资金流入黄金。")
    else:
        parts.append("市场情绪平稳，避险需求不显著。")

    evidence = "，".join(parts)

    key_metrics = {
        "vix": round(vix, 2),
        "vix_change_d": round(vix_change, 2),
        "vix_regime": vix_regime,
    }

    return signal, round(strength, 2), evidence, key_metrics


def _analyze_inflation(fdata: dict) -> Tuple[str, float, str, dict]:
    """判定通胀预期因子信号

    盈亏平衡通胀率 = 10Y 名义利率 - TIPS 10Y
      - breakeven > 3.0% → 通胀预期高，看多
      - breakeven 2.5~3.0% → 偏多
      - breakeven 2.0~2.5% → 中性
      - breakeven < 2.0% → 通胀预期低，偏空
      - breakeven < 1.5% → 看空

    Returns:
        (signal, strength, evidence, key_metrics)
    """
    data = fdata.get("data", {})

    be_raw = data.get("breakeven_10y", {})
    breakeven = (
        be_raw.get("value", 0)
        if isinstance(be_raw, dict)
        else _safe_float(be_raw)
    )
    nominal = _safe_float(data.get("nominal_10y", {}).get("value"))
    tips = _safe_float(data.get("tips_10y", {}).get("value"))

    if breakeven <= 0:
        signal, strength = "neutral", 0.0
    elif breakeven < 1.5:
        signal, strength = "bearish", 0.3
    elif breakeven < 2.0:
        signal, strength = "slightly_bearish", 0.2
    elif breakeven < 2.5:
        signal, strength = "neutral", 0.0
    elif breakeven < 3.0:
        signal, strength = "slightly_bullish", 0.3
    else:
        signal, strength = "bullish", 0.5

    vote_signal = signal
    if signal in ("slightly_bullish",):
        vote_signal, strength = "bullish", 0.2
    elif signal in ("slightly_bearish",):
        vote_signal, strength = "bearish", 0.15

    parts = [f"盈亏平衡通胀率 {breakeven:.2f}%"]
    if vote_signal == "bullish":
        parts.append("通胀预期偏高，黄金作为通胀对冲工具吸引力上升。")
    elif vote_signal == "bearish":
        parts.append("通胀预期偏低，通胀因子对金价无明显支撑。")
    else:
        parts.append("通胀预期处于正常区间，非当前主导因素。")

    evidence = "，".join(parts)

    key_metrics = {
        "breakeven_10y": round(breakeven, 2),
        "nominal_10y": round(nominal, 2),
        "tips_10y": round(tips, 2),
    }

    return vote_signal, round(strength, 2), evidence, key_metrics


def _analyze_positioning(fdata: dict) -> Tuple[str, float, str, dict]:
    """判定持仓动量因子信号

    基于持仓量(OI)与价格关系判断：
      价格↑ + OI↑ = 新多头入场，趋势确认（看多）
      价格↑ + OI↓ = 空头平仓，趋势衰竭（警告）
      价格↓ + OI↑ = 新空头入场，下跌确认（看空）
      价格↓ + OI↓ = 多头平仓，下跌衰竭（警告）

    注：缺少 COT 数据和历史 OI 序列时，信号可靠性受限。
    """
    data = fdata.get("data", {})

    shfe_gold_oi = _safe_float(data.get("shfe_gold_oi"))
    shfe_gold_price = _safe_float(data.get("shfe_gold_price"))
    note = data.get("note", "")

    evidence_parts = []
    if shfe_gold_oi:
        evidence_parts.append(f"沪金持仓量 {shfe_gold_oi:.0f}")
    if shfe_gold_price:
        evidence_parts.append(f"沪金收盘价 {shfe_gold_price:.2f}")
    if note:
        evidence_parts.append(note)

    evidence = "，".join(evidence_parts) if evidence_parts else "暂无持仓数据"

    key_metrics = {
        "shfe_gold_oi": round(shfe_gold_oi) if shfe_gold_oi else 0,
        "shfe_gold_price": round(shfe_gold_price, 2) if shfe_gold_price else 0,
    }

    # 无 COT 数据时默认中性
    return "neutral", 0.0, evidence, key_metrics


def _analyze_structural_demand(fdata: dict) -> Tuple[str, float, str, dict]:
    """判定结构性需求因子信号

    央行购金、去美元化等长期结构性因素。
    数据季度更新，短期通常无显著变化。
    """
    evidence = "央行购金数据为季度频次，暂无最新数据。结构性需求维持中性假设。"
    return "neutral", 0.0, evidence, {
        "central_bank_gold_t": None,
        "usd_reserve_share": None,
    }


def _analyze_silver_specific(fdata: dict) -> Tuple[str, float, str, dict]:
    """判定银价专用因子信号

    金银比均值回归逻辑：
      - 金银比 > 80 → 白银相对低估，看多白银
      - 金银比 60~80 → 正常范围，中性
      - 金银比 < 50 → 白银相对高估，看空白银
    """
    data = fdata.get("data", {})

    gs_raw = data.get("gold_silver_ratio", {})
    gs_ratio = (
        gs_raw.get("value", 0)
        if isinstance(gs_raw, dict)
        else _safe_float(gs_raw)
    )

    if gs_ratio > 85:
        signal, strength = "bullish", 0.7
    elif gs_ratio > 80:
        signal, strength = "bullish", 0.5
    elif gs_ratio > 75:
        signal, strength = "slightly_bullish", 0.2
    elif gs_ratio > 50:
        signal, strength = "neutral", 0.0
    elif gs_ratio > 40:
        signal, strength = "slightly_bearish", 0.2
    else:
        signal, strength = "bearish", 0.5

    vote_signal = signal
    if signal in ("slightly_bullish",):
        vote_signal, strength = "bullish", 0.1
    elif signal in ("slightly_bearish",):
        vote_signal, strength = "bearish", 0.1

    parts = [f"金银比 {gs_ratio:.1f}"]
    if 55 <= gs_ratio <= 65:
        parts.append("接近历史均值（60-65），处于正常范围。")
    elif gs_ratio > 80:
        parts.append("白银相对低估，均值回归潜力较大。")
    elif gs_ratio > 65:
        parts.append("略高于均值，白银相对黄金略低估。")
    else:
        parts.append("低于均值，白银相对黄金略高估。")

    evidence = "，".join(parts)

    key_metrics = {
        "gold_silver_ratio": round(gs_ratio, 2),
    }

    return vote_signal, round(strength, 2), evidence, key_metrics


# =============================================================================
# 因子分析器注册表
# =============================================================================

FACTOR_ANALYZERS: Dict[str, callable] = {
    "opportunity_cost": _analyze_opportunity_cost,
    "currency": _analyze_currency,
    "safe_haven": _analyze_safe_haven,
    "inflation": _analyze_inflation,
    "positioning": _analyze_positioning,
    "structural_demand": _analyze_structural_demand,
    "silver_specific": _analyze_silver_specific,
}


# =============================================================================
# 动态权重加载
# =============================================================================


def _load_dynamic_weights() -> Dict[str, float]:
    """从 prediction_log.json 读取动态因子权重

    如果文件不存在或读取失败，回退为默认权重。

    Returns:
        因子 ID → 权重 的字典
    """
    if not PREDICTION_LOG_FILE.exists():
        return {fid: fdef["weight"] for fid, fdef in FACTOR_DEFINITIONS.items()}

    try:
        with open(PREDICTION_LOG_FILE, "r", encoding="utf-8") as f:
            log_data = json.load(f)
        weights = log_data.get("factor_weights", {})
        if not weights:
            return {fid: fdef["weight"] for fid, fdef in FACTOR_DEFINITIONS.items()}
        return weights
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取动态权重失败，使用默认权重: %s", e)
        return {fid: fdef["weight"] for fid, fdef in FACTOR_DEFINITIONS.items()}


# =============================================================================
# 信号合成
# =============================================================================


def synthesize_signal(factor_results: List[dict],
                       weights: Optional[Dict[str, float]] = None) -> dict:
    """加权投票制合成综合方向

    Args:
        factor_results: 各因子分析结果列表
        weights: 可选，动态因子权重字典。None 时使用 FACTOR_DEFINITIONS 中的默认权重

    规则：
      bullish_score = Σ(strength_i × weight_i) for signal == bullish
      bearish_score  = Σ(strength_i × weight_i) for signal == bearish

      if bullish_score > bearish_score × 1.5 → bullish
      if bearish_score > bullish_score × 1.5 → bearish
      else → neutral/mixed

      置信度 = 在[0, 1]区间标定
      主导因子 = max(strength) 的非中性因子 ID

    Args:
        factor_results: 各因子分析结果列表
        weights: 可选，动态因子权重字典。None 时使用 FACTOR_DEFINITIONS 中的默认权重

    Returns:
        综合信号字典
    """
    # 使用动态权重（如有），否则回退默认
    active_weights = weights if weights else {
        fid: fdef["weight"] for fid, fdef in FACTOR_DEFINITIONS.items()
    }

    bullish_score = 0.0
    bearish_score = 0.0
    total_active_strength = 0.0
    max_strength = 0.0
    dominant_factor = None

    for f in factor_results:
        fid = f["id"]
        signal = f["signal"]
        strength = f["strength"]
        weight = active_weights.get(fid, 0.5)

        if signal == "bullish":
            weighted = strength * weight
            bullish_score += weighted
            total_active_strength += weighted
        elif signal == "bearish":
            weighted = strength * weight
            bearish_score += weighted
            total_active_strength += weighted

        # 主导因子：strength 最大的非中性因子
        if signal != "neutral" and strength > max_strength:
            max_strength = strength
            dominant_factor = fid

    # ---- 方向判定 ----
    if bullish_score > bearish_score * 1.5:
        direction = "bullish"
    elif bearish_score > bullish_score * 1.5:
        direction = "bearish"
    else:
        direction = "neutral"

    # ---- 置信度 ----
    # 基于：方向优势程度 × 参与投票的因子总强度
    total_score = bullish_score + bearish_score
    if total_score > 0:
        if direction == "bullish":
            dominance = (bullish_score - bearish_score) / bullish_score
        elif direction == "bearish":
            dominance = (bearish_score - bullish_score) / bearish_score
        else:
            # 多空交织时低置信度
            if bullish_score > 0 and bearish_score > 0:
                dominance = 0.0
            else:
                dominance = 0.0

        # 标定置信度
        confidence = dominance * min(total_active_strength / 1.5, 1.0)
        confidence = max(0.0, min(confidence, 1.0))
    else:
        confidence = 0.0

    confidence = round(confidence, 2)

    # ---- label ----
    if direction == "bullish":
        label = "看多"
    elif direction == "bearish":
        label = "看空"
    else:
        if bullish_score > 0 and bearish_score > 0:
            label = "多空交织"
        else:
            label = "中性"

    # ---- 置信度文本标签 ----
    if confidence >= 0.7:
        conf_label = "高"
    elif confidence >= 0.4:
        conf_label = "中"
    elif confidence > 0:
        conf_label = "低"
    else:
        conf_label = "极低"

    return {
        "direction": direction,
        "confidence": confidence,
        "confidence_label": conf_label,
        "label": label,
        "dominant_factor": dominant_factor or "none",
        "scores": {
            "bullish_score": round(bullish_score, 3),
            "bearish_score": round(bearish_score, 3),
        },
    }


# =============================================================================
# 关键点位计算
# =============================================================================


def analyze_key_levels() -> dict:
    """计算金银关键支撑阻力位

    使用 SHFE 国内价格作为主要参考（用户交易标的）。
    利用 COMEX 历史 CSV 估算波动率百分比，应用于 SHFE 价格。

    Returns:
        关键点位字典
    """
    dashboard = _read_json(DASHBOARD_FILE)

    # 获取 SHFE 价格（用户实际交易标的）
    shfe_gold = _safe_float(_get_nested(dashboard, "shfe_gold", "close"))
    shfe_silver = _safe_float(_get_nested(dashboard, "shfe_silver", "close"))

    # 获取 COMEX 价格（用于波动率估算）
    comex_gold = _safe_float(
        _get_nested(dashboard, "gold_futures", "value")
    ) or _safe_float(_get_nested(dashboard, "gold_price", "value"))
    comex_silver = _safe_float(
        _get_nested(dashboard, "silver_futures", "value")
    ) or _safe_float(_get_nested(dashboard, "silver_price", "value"))

    # 计算波动率缓冲区（从 CSV 历史数据估算）
    hist = _read_csv_tail(DATA_HISTORY / "gold_silver_daily.csv", 30)
    gold_buffer = 0.03  # 默认 3%
    silver_buffer = 0.04  # 白银波动更大

    if hist:
        gold_changes, silver_changes = [], []
        prev_g, prev_s = None, None
        for r in hist:
            try:
                g = float(r.get("gold_close", 0))
                s = float(r.get("silver_close", 0))
            except (ValueError, TypeError):
                continue
            if prev_g is not None and g > 0 and prev_g > 0:
                change = abs(g - prev_g) / prev_g
                if change < 0.10:  # 过滤异常
                    gold_changes.append(change)
            if prev_s is not None and s > 0 and prev_s > 0:
                change = abs(s - prev_s) / prev_s
                if change < 0.10:
                    silver_changes.append(change)
            prev_g, prev_s = g, s

        if gold_changes:
            avg_daily = sum(gold_changes) / len(gold_changes)
            # 缓冲区 = 3倍日均波动，限在 2%-10% 之间
            gold_buffer = min(max(avg_daily * 3, 0.02), 0.10)
        if silver_changes:
            avg_daily = sum(silver_changes) / len(silver_changes)
            silver_buffer = min(max(avg_daily * 3, 0.03), 0.12)

    # 优先用 SHFE，回退 COMEX
    ref_gold = shfe_gold if shfe_gold else comex_gold
    ref_silver = shfe_silver if shfe_silver else comex_silver

    return {
        "gold_support": round(ref_gold * (1 - gold_buffer), 1) if ref_gold else 0,
        "gold_resistance": round(ref_gold * (1 + gold_buffer), 1) if ref_gold else 0,
        "silver_support": round(ref_silver * (1 - silver_buffer), 1) if ref_silver else 0,
        "silver_resistance": round(ref_silver * (1 + silver_buffer), 1) if ref_silver else 0,
    }


# =============================================================================
# 风险场景分析
# =============================================================================


def analyze_risks(
    factor_results: List[dict], overall: dict
) -> List[dict]:
    """基于当前因子状态生成风险场景

    Args:
        factor_results: 各因子分析结果
        overall: 综合信号

    Returns:
        风险场景列表
    """
    risks = []
    result_map = {f["id"]: f for f in factor_results}

    # 风险 1：机会成本反转
    oc = result_map.get("opportunity_cost", {})
    if oc.get("signal") == "bullish" and oc.get("strength", 0) > 0.5:
        risks.append({
            "factor": "opportunity_cost",
            "scenario": "美国经济数据超预期，CPI反弹触发加息预期回升，TIPS上行",
            "impact": "黄金承压回调，短期可能下跌3-5%",
        })

    # 风险 2：拥挤交易（无 COT 数据时基于信号判断）
    if overall["direction"] == "bullish" and overall["confidence"] > 0.5:
        risks.append({
            "factor": "positioning",
            "scenario": "市场一致性看多，COT净多头可能接近高位",
            "impact": "一旦触发回调，拥挤平仓可能放大跌幅",
        })

    # 风险 3：地缘风险缓和
    sh = result_map.get("safe_haven", {})
    if sh.get("signal") == "bullish":
        risks.append({
            "factor": "safe_haven",
            "scenario": "地缘局势缓和，避险溢价消退",
            "impact": "黄金失去避险支撑，可能出现回调",
        })

    # 风险 4：美元走强
    cur = result_map.get("currency", {})
    if cur.get("signal") == "neutral":
        risks.append({
            "factor": "currency",
            "scenario": "DXY 反弹至 101 以上",
            "impact": "美元走强对金价形成压力",
        })

    # 风险 5：流动性危机
    if sh.get("key_metrics", {}).get("vix_regime") == "panic":
        risks.append({
            "factor": "safe_haven",
            "scenario": "VIX持续高企可能触发流动性危机，金银同跌",
            "impact": "极端情况下黄金被抛售变现，短期大跌",
        })

    return risks


# =============================================================================
# 与上次对比
# =============================================================================


def compare_with_last(
    current: dict, memo_path: Path = MACRO_MEMO_FILE
) -> dict:
    """对比上次宏观备忘录，分析判断变化

    读取 macro_memo.md，提取上次判断信息，与当前分析对比。

    Args:
        current: 当前分析结果
        memo_path: macro_memo.md 路径

    Returns:
        变化信息字典
    """
    if not memo_path.exists():
        return {
            "status": "new",
            "last_timestamp": None,
            "diff": "首次分析，无上次记录",
            "trigger": "首次运行",
        }

    try:
        text = memo_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "status": "new",
            "last_timestamp": None,
            "diff": "无法读取 macro_memo.md",
            "trigger": "读取失败",
        }

    front = _parse_front_matter(text)
    last_timestamp = front.get("updated", "")

    # 提取上次方向
    last_direction = None
    last_label = None

    # 从 "当前判断" 区域提取
    section_match = re.search(r"## 当前判断\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if section_match:
        section = section_match.group(1)
        # 方向：如 "**方向**: 看多（偏多→看多，上调）"
        dir_match = re.search(r"\*\*方向\*\*\s*[:：]\s*(.+?)(?:\n|$)", section)
        if dir_match:
            last_label = dir_match.group(1).strip()
            # 提取方向关键词
            if "看多" in last_label or "偏多" in last_label:
                last_direction = "bullish"
            elif "看空" in last_label or "偏空" in last_label:
                last_direction = "bearish"

    # 对比
    current_label = current["overall"]["label"]
    current_dir = current["overall"]["direction"]

    if last_dir := last_direction:
        if current_dir == last_dir:
            status = "same"
            diff = f"方向维持 {current_label}，未发生变化"
            trigger = ""
        else:
            status = "changed"
            if last_label:
                diff = f"判断从 {last_label} 转为 {current_label}"
            else:
                diff = f"方向发生变化"
            trigger = "因子信号加权投票结果转变"
    else:
        status = "new"
        diff = "上次无明确方向判断"
        trigger = "首次有效分析"

    return {
        "status": status,
        "last_timestamp": last_timestamp or None,
        "diff": diff,
        "trigger": trigger,
    }


# =============================================================================
# 主分析流程
# =============================================================================


def run_analysis(input_path: Optional[Path] = None) -> dict:
    """执行完整宏观分析

    Args:
        input_path: 可选，指定输入因子 JSON 文件路径

    Returns:
        完整分析结果字典（设计文档 4.1 节格式）
    """
    # 1. 加载因子数据
    if input_path:
        factors_data = _read_json(input_path)
        if not factors_data:
            logger.error("指定输入文件 %s 不存在或格式错误", input_path)
            sys.exit(1)
        logger.info("从 %s 加载因子数据", input_path)
    else:
        factors_data = load_factor_data()

    # 2. 各因子信号判定
    raw_factors = factors_data.get("factors", {})
    if not raw_factors:
        logger.error("因子数据结构无效或为空")
        return _empty_analysis()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    factor_results = []
    opp_signal = "neutral"

    # 2a. 先处理机会成本（供货币因子正交化使用）
    if "opportunity_cost" in raw_factors:
        fid = "opportunity_cost"
        fdef = FACTOR_DEFINITIONS.get(fid, {})
        signal, strength, evidence, km = _analyze_opportunity_cost(
            raw_factors[fid]
        )
        opp_signal = signal
        factor_results.append({
            "id": fid,
            "label": fdef.get("label", fid),
            "signal": signal,
            "strength": strength,
            "evidence": evidence,
            "key_metrics": km,
        })

    # 2b. 处理其余因子
    for fid, analyzer in FACTOR_ANALYZERS.items():
        if fid == "opportunity_cost":
            continue
        if fid not in raw_factors:
            logger.warning("因子 %s 在数据中缺失，跳过", fid)
            continue
        fdef = FACTOR_DEFINITIONS.get(fid, {})
        fdata = raw_factors[fid]

        if fid == "currency":
            signal, strength, evidence, km = analyzer(fdata, opp_signal)
        else:
            signal, strength, evidence, km = analyzer(fdata)

        factor_results.append({
            "id": fid,
            "label": fdef.get("label", fid),
            "signal": signal,
            "strength": strength,
            "evidence": evidence,
            "key_metrics": km,
        })

    # 3. 加载动态因子权重（来自反馈闭环）
    dynamic_weights = _load_dynamic_weights()
    if dynamic_weights:
        logger.info("使用动态因子权重（来自 prediction_log.json）")
        for fid, w in dynamic_weights.items():
            default_w = FACTOR_DEFINITIONS.get(fid, {}).get("weight", 0.5)
            if abs(w - default_w) > 0.01:
                logger.info("  %s: %.2f (默认 %.2f)",
                            FACTOR_DEFINITIONS.get(fid, {}).get("label", fid), w, default_w)

    # 4. 信号合成（传入动态权重）
    overall = synthesize_signal(factor_results, weights=dynamic_weights)

    # 4. 关键点位
    key_levels = analyze_key_levels()

    # 5. 风险场景
    risks = analyze_risks(factor_results, overall)

    # 6. 与上次对比
    change = compare_with_last(
        {"overall": overall},
        MACRO_MEMO_FILE,
    )

    # 7. 组装最终输出
    analysis = {
        "timestamp": now,
        "data_updated_at": factors_data.get("updated_at", now),
        "data_source": factors_data.get("data_source", "unknown"),
        "overall": {
            "direction": overall["direction"],
            "confidence": overall["confidence"],
            "confidence_label": overall["confidence_label"],
            "label": overall["label"],
            "dominant_factor": overall["dominant_factor"],
            "scores": overall["scores"],
        },
        "factors": factor_results,
        "key_levels": key_levels,
        "risks": risks,
        "change_from_last": change,
    }

    return analysis


def _empty_analysis() -> dict:
    """生成空分析结果（数据不可用时的降级输出）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "timestamp": now,
        "data_updated_at": now,
        "data_source": "none",
        "overall": {
            "direction": "neutral",
            "confidence": 0.0,
            "confidence_label": "极低",
            "label": "中性",
            "dominant_factor": "none",
            "scores": {"bullish_score": 0, "bearish_score": 0},
        },
        "factors": [],
        "key_levels": {
            "gold_support": 0,
            "gold_resistance": 0,
            "silver_support": 0,
            "silver_resistance": 0,
        },
        "risks": [
            {
                "factor": "data",
                "scenario": "数据不可用，无法进行有效分析",
                "impact": "建议检查数据采集状态",
            }
        ],
        "change_from_last": {
            "status": "new",
            "last_timestamp": None,
            "diff": "数据不可用",
            "trigger": "无数据",
        },
    }


# =============================================================================
# 输出格式化
# =============================================================================


def format_readable(analysis: dict) -> str:
    """格式化为可读文本输出

    Args:
        analysis: 分析结果字典

    Returns:
        可读文本字符串
    """
    lines = []
    o = analysis["overall"]

    # 标题
    line_break = "=" * 56
    lines.append(line_break)
    lines.append("  宏观综合研判 | analyze_macro.py")
    lines.append(f"  生成时间: {analysis['timestamp']}")
    lines.append(f"  数据时间: {analysis.get('data_updated_at', 'N/A')}")
    lines.append(line_break)
    lines.append("")

    # 综合判断
    dir_symbol = {"bullish": "↑", "bearish": "↓", "neutral": "—"}.get(
        o["direction"], "?"
    )
    dom_label = o["dominant_factor"]
    if dom_label != "none":
        dom_cn = FACTOR_DEFINITIONS.get(dom_label, {}).get("label", dom_label)
    else:
        dom_cn = "无"

    lines.append(f"  综合判断: {o['label']} {dir_symbol}")
    lines.append(f"  置信度:   {o['confidence']*100:.0f}% ({o['confidence_label']})")
    lines.append(f"  主导因子: {dom_cn}")
    lines.append(
        f"  多空分:   {o['scores']['bullish_score']:.2f} / {o['scores']['bearish_score']:.2f}"
    )
    lines.append("")

    # 因子信号
    lines.append("-" * 56)
    lines.append("  因子信号")
    lines.append("-" * 56)
    lines.append(
        f"  {'因子':<12s} {'信号':<8s} {'强度':<6s} {'要点'}"
    )
    lines.append("-" * 56)

    for f in analysis["factors"]:
        sym = {"bullish": "↑", "bearish": "↓", "neutral": "—"}.get(
            f["signal"], "?"
        )
        strength_str = f"{f['strength']:.1f}" if f["strength"] > 0 else "—"
        evidence_short = f["evidence"][:50] + "…" if len(f["evidence"]) > 50 else f["evidence"]
        lines.append(f"  {f['label']:<12s} {sym:<8s} {strength_str:<6s} {evidence_short}")

    lines.append("")

    # 关键点位
    kl = analysis["key_levels"]
    lines.append("-" * 56)
    lines.append("  关键点位")
    lines.append("-" * 56)
    if kl["gold_support"]:
        lines.append(f"  黄金:  支撑 {kl['gold_support']:.1f}  /  阻力 {kl['gold_resistance']:.1f}")
    if kl["silver_support"]:
        lines.append(f"  白银:  支撑 {kl['silver_support']:.1f}  /  阻力 {kl['silver_resistance']:.1f}")
    lines.append("")

    # 风险提示
    if analysis["risks"]:
        lines.append("-" * 56)
        lines.append("  风险提示")
        lines.append("-" * 56)
        for i, r in enumerate(analysis["risks"], 1):
            factor_cn = FACTOR_DEFINITIONS.get(r["factor"], {}).get("label", r["factor"])
            lines.append(f"  {i}. [{factor_cn}] {r['scenario']}")
            lines.append(f"     影响: {r['impact']}")
        lines.append("")

    # 变化
    cl = analysis["change_from_last"]
    lines.append("-" * 56)
    lines.append("  与上次对比")
    lines.append("-" * 56)
    status_cn = {"same": "无变化", "changed": "有变化", "new": "首次分析"}.get(
        cl["status"], cl["status"]
    )
    lines.append(f"  状态: {status_cn}")
    if cl["diff"]:
        lines.append(f"  差异: {cl['diff']}")
    if cl["trigger"]:
        lines.append(f"  触发: {cl['trigger']}")
    if cl.get("last_timestamp"):
        lines.append(f"  上次: {cl['last_timestamp']}")
    lines.append("")

    # 数据来源
    lines.append("-" * 56)
    lines.append(f"  数据来源: {analysis.get('data_source', 'N/A')}")
    lines.append(line_break)

    return "\n".join(lines)


# =============================================================================
# 命令行入口
# =============================================================================


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="宏观综合研判 — 金银价格七因子信号合成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s                            # 输出可读文本
  %(prog)s --json                     # JSON 输出到 stdout
  %(prog)s --output analysis.json     # JSON 输出到文件
  %(prog)s --input factors.json       # 指定输入文件
        """,
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="指定输入因子 JSON 文件（默认从 data/factors/current_factors.json 读取）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="将完整分析结果写入 JSON 文件",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出到 stdout",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="减少日志输出",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """入口函数"""
    args = parse_args(argv)

    if args.quiet:
        logging.getLogger("analyze_macro").setLevel(logging.WARNING)

    # 执行分析
    analysis = run_analysis(args.input)

    # 输出
    if args.output:
        # 确保目录存在
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        print(f"分析结果已写入 {args.output}")

    if args.json:
        print(json.dumps(analysis, ensure_ascii=False, indent=2))
    elif not args.output:
        # 默认：可读文本
        print(format_readable(analysis))


if __name__ == "__main__":
    main()
