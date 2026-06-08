#!/usr/bin/env python3
"""
持仓品种归因分析脚本 — 针对持仓品种的驱动因素分析和风险评估

定位：
  对某个持仓品种做归因分析，回答"这个持仓为什么涨/跌"和"风险如何"。
  可作为 AI Agent 的工具调用，也可独立运行输出可读文本。

用法:
  python tools/analyze_position.py --symbol shfe_gold    # 沪金归因
  python tools/analyze_position.py --symbol all           # 全部持仓
  python tools/analyze_position.py --symbol shfe_gold --json  # JSON 输出

支持品种:
  shfe_gold   沪金 (上海期货交易所)
  shfe_silver 沪银 (上海期货交易所)
  gold        COMEX 黄金
  silver      COMEX 白银

内部逻辑:
  1. 从 wiki_trade/memory/positions.md 读取持仓信息
  2. 从 dashboard_data.json 获取当前行情
  3. 调用 analyze_macro.py 的因子分析结果进行归因
  4. 计算风险评估（距止损距离、最大浮亏、建议）
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("analyze_position")

# =============================================================================
# 路径配置
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"
DATA_CURRENT = PROJECT_ROOT / "data" / "current"
DATA_HISTORY = PROJECT_ROOT / "data" / "history" / "daily"

DASHBOARD_FILE = DATA_CURRENT / "dashboard_data.json"

VAULT_ROOT = Path(
    "/Users/zhenzhenzheng/Library/Mobile Documents/"
    "com~apple~CloudDocs/Obsidian/blog_zhenzhen"
)
POSITIONS_FILE = VAULT_ROOT / "wiki_trade" / "memory" / "positions.md"

# =============================================================================
# 品种映射
# =============================================================================

# 命令行符号 -> 持仓文件中的品种关键字映射
SYMBOL_PATTERNS: Dict[str, str] = {
    "shfe_gold": "沪金",
    "shfe_silver": "沪银",
    "gold": "黄金",
    "silver": "白银",
}

# 命令行符号 -> dashboard_data.json 中的键名
DASHBOARD_KEYS: Dict[str, str] = {
    "shfe_gold": "shfe_gold",
    "shfe_silver": "shfe_silver",
    "gold": "gold_futures",
    "silver": "silver_futures",
}

# 因子关联 — 不同品种的主要驱动因子
SYMBOL_FACTORS: Dict[str, list] = {
    "shfe_gold": ["opportunity_cost", "currency", "safe_haven", "inflation", "positioning"],
    "shfe_silver": ["silver_specific", "safe_haven", "opportunity_cost", "inflation", "positioning"],
    "gold": ["opportunity_cost", "currency", "safe_haven", "inflation", "positioning"],
    "silver": ["silver_specific", "safe_haven", "opportunity_cost", "inflation", "positioning"],
}

# =============================================================================
# 工具函数
# =============================================================================


def _safe_float(v, default: float = 0.0) -> float:
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
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, {})
        else:
            return default
    return current if current != {} else default


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return {}


# =============================================================================
# 持仓解析
# =============================================================================


def parse_position_table(text: str) -> List[dict]:
    """从 positions.md 的 Markdown 表格中解析持仓列表

    Args:
        text: positions.md 完整内容

    Returns:
        持仓记录列表，每条含 direction/lots/cost/stop_loss/take_profit 等
    """
    positions = []
    in_table = False
    headers = []
    data_lines = []

    for line in text.split("\n"):
        stripped = line.strip()
        # 检测表格头
        if stripped.startswith("| 品种"):
            in_table = True
            headers = [h.strip() for h in stripped.strip("|").split("|")]
            continue
        # 跳过分隔行
        if in_table and re.match(r"^\|[\s\-:]+\|", stripped):
            continue
        # 表格数据行
        if in_table and stripped.startswith("|"):
            row_end = stripped.find("|", 1)
            if row_end == -1:
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            data_lines.append(dict(zip(headers, cells)))
        elif in_table and not stripped:
            in_table = False

    # 解析数据
    for row in data_lines:
        product = row.get("品种", "").strip()
        direction = row.get("方向", "").strip()
        status = row.get("状态", "").strip()

        # 跳过空仓/无持仓行
        if product in ("—", "-", "") or direction in ("—", "-", ""):
            continue
        if status == "空仓":
            continue

        try:
            lots = float(row.get("手数", "0").strip().replace(",", ""))
        except (ValueError, TypeError):
            lots = 0
        try:
            cost = float(row.get("开仓价", "0").strip().replace(",", ""))
        except (ValueError, TypeError):
            cost = 0.0
        try:
            stop_loss = float(row.get("止损", "0").strip().replace(",", ""))
        except (ValueError, TypeError):
            stop_loss = 0.0
        try:
            take_profit = float(row.get("止盈", "0").strip().replace(",", ""))
        except (ValueError, TypeError):
            take_profit = 0.0

        # 方向标准化
        dir_normalized = "long" if direction in ("多", "long", "Long") else "short"

        positions.append({
            "product": product,
            "direction": dir_normalized,
            "lots": lots,
            "cost": cost,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "open_date": row.get("开仓日期", "").strip(),
            "reason": row.get("开仓理由", "").strip(),
            "status": status.strip(),
            "_raw_row": row,
        })

    return positions


def load_positions() -> List[dict]:
    """读取 positions.md 并解析为结构化数据

    Returns:
        持仓列表
    """
    if not POSITIONS_FILE.exists():
        logger.warning("持仓文件不存在: %s", POSITIONS_FILE)
        return []

    try:
        text = POSITIONS_FILE.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("读取持仓文件失败: %s", e)
        return []

    positions = parse_position_table(text)
    return positions


# =============================================================================
# 品种匹配
# =============================================================================


def match_symbol_to_position(
    symbol: str, positions: List[dict]
) -> Optional[dict]:
    """将命令行符号匹配到持仓记录

    Args:
        symbol: 命令行传入的品种标识
        positions: 持仓列表

    Returns:
        匹配的持仓记录，未找到返回 None
    """
    if symbol == "all":
        # 仅在有持仓时返回全部
        active = [p for p in positions if p["lots"] > 0]
        return active if active else None

    pattern = SYMBOL_PATTERNS.get(symbol, symbol)
    for p in positions:
        if pattern in p.get("product", ""):
            return [p]
    return None


def get_symbol_price(symbol: str, dashboard: dict) -> dict:
    """从 dashboard 获取品种行情

    Args:
        symbol: 品种标识
        dashboard: dashboard 数据

    Returns:
        行情字典
    """
    key = DASHBOARD_KEYS.get(symbol, symbol)
    raw = dashboard.get(key, {})

    if key == "shfe_gold":
        return {
            "price": _safe_float(_get_nested(dashboard, "shfe_gold", "close")),
            "open": _safe_float(_get_nested(dashboard, "shfe_gold", "open")),
            "high": _safe_float(_get_nested(dashboard, "shfe_gold", "high")),
            "low": _safe_float(_get_nested(dashboard, "shfe_gold", "low")),
            "volume": _safe_float(_get_nested(dashboard, "shfe_gold", "volume")),
            "open_interest": _safe_float(_get_nested(dashboard, "shfe_gold", "open_interest")),
            "change_pct": _safe_float(_get_nested(dashboard, "shfe_gold", "change_pct")),
            "unit": "¥/克",
            "source": "akshare",
        }
    elif key == "shfe_silver":
        return {
            "price": _safe_float(_get_nested(dashboard, "shfe_silver", "close")),
            "open": _safe_float(_get_nested(dashboard, "shfe_silver", "open")),
            "high": _safe_float(_get_nested(dashboard, "shfe_silver", "high")),
            "low": _safe_float(_get_nested(dashboard, "shfe_silver", "low")),
            "volume": _safe_float(_get_nested(dashboard, "shfe_silver", "volume")),
            "open_interest": _safe_float(_get_nested(dashboard, "shfe_silver", "open_interest")),
            "change_pct": _safe_float(_get_nested(dashboard, "shfe_silver", "change_pct")),
            "unit": "¥/千克",
            "source": "akshare",
        }
    elif key == "gold_futures":
        return {
            "price": _safe_float(_get_nested(dashboard, "gold_futures", "value")),
            "change": _safe_float(_get_nested(dashboard, "gold_futures", "change")),
            "change_pct": _safe_float(_get_nested(dashboard, "gold_futures", "change_pct")),
            "volume": _safe_float(_get_nested(dashboard, "gold_futures", "volume")),
            "unit": "USD/oz",
            "source": "yahoo_finance",
        }
    elif key == "silver_futures":
        return {
            "price": _safe_float(_get_nested(dashboard, "silver_futures", "value")),
            "change": _safe_float(_get_nested(dashboard, "silver_futures", "change")),
            "change_pct": _safe_float(_get_nested(dashboard, "silver_futures", "change_pct")),
            "volume": _safe_float(_get_nested(dashboard, "silver_futures", "volume")),
            "unit": "USD/oz",
            "source": "yahoo_finance",
        }

    return {"price": 0, "unit": "unknown"}


# =============================================================================
# 因子归因分析
# =============================================================================


def load_factor_analysis() -> dict:
    """调用 analyze_macro.py 获取宏观因子分析结果

    通过子进程调用 analyze_macro.py --json 获取 JSON 输出。

    Returns:
        因子分析结果字典
    """
    macro_script = TOOLS_DIR / "analyze_macro.py"
    if not macro_script.exists():
        logger.warning("analyze_macro.py 不存在，无法获取因子数据")
        return {}

    try:
        result = subprocess_run(
            [sys.executable, str(macro_script), "--json", "--quiet"],
        )
        if result:
            return json.loads(result)
    except Exception as e:
        logger.warning("调用 analyze_macro.py 失败: %s", e)

    return {}


def subprocess_run(cmd: List[str]) -> Optional[str]:
    """运行子进程并返回 stdout

    Args:
        cmd: 命令列表

    Returns:
        stdout 字符串，失败返回 None
    """
    import subprocess

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout
        logger.warning("命令失败: %s", proc.stderr[:200])
    except Exception as e:
        logger.warning("执行异常: %s", e)
    return None


def get_primary_driver(
    symbol: str, factor_analysis: dict, price_data: dict
) -> Tuple[str, str]:
    """确定品种的主要驱动因子

    Args:
        symbol: 品种标识
        factor_analysis: analyze_macro.py 的分析结果
        price_data: 品种行情数据

    Returns:
        (primary_driver_id, detail_text)
    """
    if not factor_analysis:
        return "unknown", "无法获取因子分析数据"

    factors = factor_analysis.get("factors", [])
    factor_map = {f["id"]: f for f in factors}

    # 按品种优先级获取因子
    relevant = SYMBOL_FACTORS.get(symbol, ["opportunity_cost", "safe_haven"])

    # 找信号最强且非中性的因子
    best_factor = None
    best_strength = 0.0
    for fid in relevant:
        f = factor_map.get(fid, {})
        signal = f.get("signal", "neutral")
        strength = f.get("strength", 0)
        if signal != "neutral" and strength > best_strength:
            best_strength = strength
            best_factor = f

    if not best_factor:
        return "none", "当前无显著驱动因子，价格变动可能来自技术面或市场噪声。"

    primary_id = best_factor["id"]
    label = best_factor.get("label", primary_id)
    signal = best_factor.get("signal", "neutral")
    evidence = best_factor.get("evidence", "")

    signal_cn = {"bullish": "看多", "bearish": "看空"}.get(signal, "中性")

    detail_parts = []
    detail_parts.append(f"今日主要受【{label}】因子驱动，当前信号为{signal_cn}")
    detail_parts.append(f"（强度 {best_strength}）。")
    if evidence:
        short_ev = evidence[:80]
        detail_parts.append(f"依据：{short_ev}")

    # 补充次要因子
    secondary = None
    for fid in relevant:
        if fid == primary_id:
            continue
        f = factor_map.get(fid, {})
        if f.get("signal") != "neutral" and f.get("strength", 0) > 0.1:
            secondary = f
            break

    if secondary:
        detail_parts.append(
            f"次要驱动：{secondary.get('label', secondary['id'])}"
            f"（信号{'看多' if secondary['signal']=='bullish' else '看空'}，"
            f"强度 {secondary['strength']}）。"
        )

    detail = "".join(detail_parts)
    return primary_id, detail


# =============================================================================
# 风险评估
# =============================================================================


def assess_risk(
    position: dict, price_data: dict, factor_analysis: dict
) -> dict:
    """计算持仓风险评估

    Args:
        position: 持仓记录
        price_data: 行情数据
        factor_analysis: 因子分析结果

    Returns:
        风险评估字典
    """
    direction = position["direction"]
    cost = position["cost"]
    stop_loss = position.get("stop_loss", 0)
    take_profit = position.get("take_profit", 0)
    current_price = price_data.get("price", 0)

    if not current_price or not cost:
        return {
            "max_drawdown_from_entry": 0,
            "current_stop_distance": 0,
            "floating_pnl_pct": 0,
            "suggestion": "缺少价格数据，无法进行风险评估",
        }

    # 浮动盈亏
    if direction == "long":
        floating_pnl_pct = round((current_price - cost) / cost * 100, 2)
    else:
        floating_pnl_pct = round((cost - current_price) / cost * 100, 2)

    # 距止损距离
    if stop_loss > 0:
        if direction == "long":
            stop_distance_pct = round(
                (current_price - stop_loss) / current_price * 100, 2
            )
            # 最大回撤（从开仓到止损）
            drawdown = round(
                (cost - stop_loss) / cost * 100, 2
            ) if cost > 0 else 0
        else:
            stop_distance_pct = round(
                (stop_loss - current_price) / current_price * 100, 2
            )
            drawdown = round(
                (stop_loss - cost) / cost * 100, 2
            ) if cost > 0 else 0
    else:
        stop_distance_pct = None
        drawdown = 0

    # 距止盈距离
    if take_profit > 0:
        if direction == "long":
            tp_distance = round((take_profit - current_price) / current_price * 100, 2)
        else:
            tp_distance = round((current_price - take_profit) / current_price * 100, 2)
    else:
        tp_distance = None

    # 生成建议
    suggestion = _generate_suggestion(
        direction, floating_pnl_pct, stop_distance_pct, drawdown,
        factor_analysis,
    )

    return {
        "max_drawdown_from_entry": round(max(drawdown, abs(floating_pnl_pct) if floating_pnl_pct < 0 else 0), 2),
        "current_stop_distance": stop_distance_pct,
        "floating_pnl_pct": floating_pnl_pct,
        "take_profit_distance": tp_distance,
        "suggestion": suggestion,
    }


def _generate_suggestion(
    direction: str,
    floating_pnl: float,
    stop_distance: Optional[float],
    drawdown: float,
    factor_analysis: dict,
) -> str:
    """基于综合情况生成持仓建议

    Args:
        direction: 持仓方向
        floating_pnl: 浮动盈亏百分比
        stop_distance: 距止损百分比
        drawdown: 最大回撤
        factor_analysis: 因子分析

    Returns:
        建议文本
    """
    suggestions = []

    # 止损相关
    if stop_distance is not None:
        if stop_distance < 0.5:
            suggestions.append(f"⚠️ 距止损仅 {stop_distance:.1f}%，建议密切关注，考虑是否需要调整止损位。")
        elif stop_distance < 1.0:
            suggestions.append(f"距止损 {stop_distance:.1f}%，止损位合理。")
        else:
            suggestions.append(f"距止损 {stop_distance:.1f}%，止损空间充足。")
    else:
        suggestions.append("未设置止损，建议设置止损位以防风险。")

    # 浮动盈亏相关
    if floating_pnl > 5:
        suggestions.append(f"当前浮盈 {floating_pnl:.1f}%，可考虑逐步移动止损锁定利润。")
    elif floating_pnl < -5:
        suggestions.append(f"当前浮亏 {floating_pnl:.1f}%，检查开仓逻辑是否仍然成立。")

    # 因子参考
    if factor_analysis:
        overall = factor_analysis.get("overall", {})
        direction_map = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
        macro_dir = direction_map.get(overall.get("direction", "neutral"), "中性")
        confidence = overall.get("confidence", 0) * 100

        if direction == "long":
            if overall.get("direction") == "bullish":
                suggestions.append(f"宏观判断{macro_dir}（置信度{confidence:.0f}%），与持仓方向一致。")
            elif overall.get("direction") == "bearish":
                suggestions.append(f"⚠️ 宏观判断{macro_dir}（置信度{confidence:.0f}%），与持仓方向相反，需警惕逆势风险。")
            else:
                suggestions.append(f"宏观判断{macro_dir}（置信度{confidence:.0f}%），持仓方向无明确宏观支撑。")
        else:  # short
            if overall.get("direction") == "bearish":
                suggestions.append(f"宏观判断{macro_dir}（置信度{confidence:.0f}%），与持仓方向一致。")
            elif overall.get("direction") == "bullish":
                suggestions.append(f"⚠️ 宏观判断{macro_dir}（置信度{confidence:.0f}%），与持仓方向相反，需警惕逆势风险。")
            else:
                suggestions.append(f"宏观判断{macro_dir}（置信度{confidence:.0f}%），持仓方向无明确宏观支撑。")

    return " ".join(suggestions)


# =============================================================================
# 单品种归因分析
# =============================================================================


def analyze_symbol(symbol: str) -> dict:
    """对一个品种执行归因分析

    Args:
        symbol: 品种标识 (shfe_gold / shfe_silver / gold / silver / all)

    Returns:
        分析结果字典
    """
    # 1. 加载数据
    dashboard = _read_json(DASHBOARD_FILE)
    positions = load_positions()
    factor_analysis = load_factor_analysis()

    if not positions:
        return {
            "symbol": symbol,
            "status": "no_position",
            "message": "当前无持仓记录",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 2. 匹配持仓
    matched = match_symbol_to_position(symbol, positions)

    if not matched:
        if symbol == "all":
            return {
                "symbol": "all",
                "status": "no_active_position",
                "message": "当前无活跃持仓",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        else:
            return {
                "symbol": symbol,
                "status": "not_found",
                "message": f"未找到品种 {symbol} 的持仓记录",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    # 3. 对每个匹配的持仓进行分析
    results = []
    for pos in matched:
        result = _analyze_single_position(pos, symbol, dashboard, factor_analysis)
        results.append(result)

    if symbol == "all" and len(results) == 1:
        return results[0]

    return {"symbol": "all", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "positions": results}


def _analyze_single_position(
    position: dict,
    symbol: str,
    dashboard: dict,
    factor_analysis: dict,
) -> dict:
    """分析单个持仓

    Args:
        position: 持仓记录
        symbol: 品种标识
        dashboard: 行情数据
        factor_analysis: 因子分析结果

    Returns:
        分析结果
    """
    # 获取行情
    price_data = get_symbol_price(symbol, dashboard)
    current_price = price_data.get("price", 0)

    # 找到实际的品种标识（从持仓映射）
    product = position.get("product", "")

    # 归因
    primary_driver, detail = get_primary_driver(symbol, factor_analysis, price_data)

    # 风险评估
    risk = assess_risk(position, price_data, factor_analysis)

    # 组装输出
    result = {
        "symbol": symbol,
        "product": product,
        "price": current_price,
        "daily_change_pct": price_data.get("change_pct", 0),
        "price_unit": price_data.get("unit", ""),
        "position": {
            "direction": position["direction"],
            "lots": position["lots"],
            "cost": position["cost"],
            "open_date": position.get("open_date", ""),
            "stop_loss": position.get("stop_loss", 0),
            "take_profit": position.get("take_profit", 0),
            "reason": position.get("reason", ""),
        },
        "pnl": {
            "floating_pct": risk["floating_pnl_pct"],
            "floating_abs": round(
                current_price - position["cost"], 2
            ) if current_price and position["cost"] else 0,
        },
        "attribution": {
            "primary_driver": primary_driver,
            "detail": detail,
        },
        "risk_assessment": {
            "max_drawdown_from_entry": risk["max_drawdown_from_entry"],
            "current_stop_distance": risk["current_stop_distance"],
            "take_profit_distance": risk["take_profit_distance"],
            "suggestion": risk["suggestion"],
        },
    }

    return result


# =============================================================================
# 输出格式化
# =============================================================================


def format_readable(result: dict) -> str:
    """格式化为可读文本输出

    Args:
        result: 分析结果字典（单个品种或 all）

    Returns:
        可读文本字符串
    """
    lines = []
    line_break = "=" * 56
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append(line_break)
    lines.append("  持仓归因分析 | analyze_position.py")
    lines.append(f"  生成时间: {now}")
    lines.append(line_break)
    lines.append("")

    # 空持仓
    if "status" in result and result.get("status") in ("no_position", "no_active_position"):
        lines.append(f"  📭 {result.get('message', '当前无持仓')}")
        lines.append("")
        lines.append(line_break)
        return "\n".join(lines)

    # 多品种
    if "positions" in result:
        lines.append(f"  📊 全部持仓分析")
        lines.append("")
        for i, pos_result in enumerate(result["positions"], 1):
            lines.append(f"  --- 持仓 #{i} ---")
            lines.extend(_format_single(pos_result).split("\n"))
            lines.append("")
        lines.append(line_break)
        return "\n".join(lines)

    # 单品种
    lines.extend(_format_single(result).split("\n"))
    lines.append(line_break)
    return "\n".join(lines)


def _format_single(result: dict) -> List[str]:
    """格式化单个品种分析为文本行

    Args:
        result: 单品种分析结果

    Returns:
        文本行列表
    """
    lines = []
    p = result["position"]
    pnl = result.get("pnl", {})
    attr = result.get("attribution", {})
    risk = result.get("risk_assessment", {})

    # 仓位信息
    dir_symbol = {"long": "多 ↑", "short": "空 ↓"}.get(p.get("direction", ""), "?")
    line_short = "-" * 56

    lines.append(f"  品种: {result.get('product', result['symbol'])}")
    lines.append(f"  当前价: {result['price']:.2f} {result.get('price_unit', '')}")
    lines.append(f"  日涨跌: {result.get('daily_change_pct', 0):+.2f}%")
    lines.append(line_short)
    lines.append(f"  持仓: {dir_symbol} | {p.get('lots', 0)}手 | 开仓价 {p.get('cost', 0):.2f}")
    lines.append(f"  开仓: {p.get('open_date', 'N/A')} | 理由: {p.get('reason', 'N/A')}")
    lines.append(f"  止损: {p.get('stop_loss', '未设置')} | 止盈: {p.get('take_profit', '未设置')}")
    lines.append(line_short)

    # 盈亏
    pnl_pct = pnl.get("floating_pct", 0)
    pnl_sym = "+" if pnl_pct >= 0 else ""
    lines.append(f"  浮动盈亏: {pnl_sym}{pnl_pct:.2f}%")
    if risk.get("max_drawdown_from_entry"):
        lines.append(f"  最大回撤: {risk['max_drawdown_from_entry']:.2f}%")
    lines.append(line_short)

    # 归因
    driver_label = attr.get("primary_driver", "unknown")
    if driver_label != "unknown" and driver_label != "none":
        # 找中文标签
        factor_labels = {
            "opportunity_cost": "机会成本",
            "currency": "货币",
            "safe_haven": "避险需求",
            "inflation": "通胀预期",
            "positioning": "持仓动量",
            "structural_demand": "结构性需求",
            "silver_specific": "银价专用",
        }
        driver_cn = factor_labels.get(driver_label, driver_label)
        lines.append(f"  主要驱动: {driver_cn}")
        detail = attr.get("detail", "")
        if detail:
            lines.append(f"  归因详情: {detail[:120]}")
    else:
        lines.append(f"  主要驱动: 无显著因子信号")
    lines.append(line_short)

    # 风险评估
    lines.append(f"  距止损: {risk.get('current_stop_distance', '未设置')}")
    if risk.get("take_profit_distance") is not None:
        lines.append(f"  距止盈: {risk['take_profit_distance']:.2f}%")
    lines.append("")
    suggestion = risk.get("suggestion", "")
    if suggestion:
        lines.append(f"  💡 建议: {suggestion}")
    lines.append("")

    return lines


# =============================================================================
# 命令行入口
# =============================================================================


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="持仓品种归因分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s --symbol shfe_gold        # 沪金归因（可读文本）
  %(prog)s --symbol all              # 全部持仓
  %(prog)s --symbol gold --json      # COMEX 黄金 JSON 输出
        """,
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="all",
        choices=["shfe_gold", "shfe_silver", "gold", "silver", "all"],
        help="品种标识（默认: all）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 输出到 stdout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="将结果写入 JSON 文件",
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
        logging.getLogger("analyze_position").setLevel(logging.WARNING)
        logging.getLogger("analyze_macro").setLevel(logging.WARNING)

    # 执行分析
    result = analyze_symbol(args.symbol)

    # 输出
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"分析结果已写入 {args.output}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_readable(result))


if __name__ == "__main__":
    main()
