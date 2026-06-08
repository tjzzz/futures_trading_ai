#!/usr/bin/env python3
"""
V3 Data Query Tool — 封装 V2 数据层供 AI Agent 调用

用法:
    python data_query.py snapshot          — 当前行情快照
    python data_query.py macro             — 宏观数据摘要
    python data_query.py positions         — 查询持仓 (结合 vault memory)
    python data_query.py history <品种>     — 历史行情 (gold/silver/silver_ratio)
    python data_query.py events            — 活跃事件
    python data_query.py news              — 最新新闻
    python data_query.py analysis          — 运行四象限分析
    python data_query.py monitor           — 阈值监控状态
    python data_query.py factors           — 全部因子数据
    python data_query.py factors <factor>  — 单因子
    python data_query.py news_by_factor <factor>      — 按因子查新闻
    python data_query.py events_by_factor <factor>    — 按因子查事件

输出: JSON 格式，便于 AI 解析
"""

import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict

# ============ 路径配置 ============

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CURRENT = PROJECT_ROOT / "data/current"
DATA_HISTORY = PROJECT_ROOT / "data/history"
DATA_EVENTS = PROJECT_ROOT / "data/events"

DASHBOARD_FILE = DATA_CURRENT / "dashboard_data.json"
EVENT_FILE = DATA_EVENTS / "event_tracker.json"
MONITOR_FILE = DATA_EVENTS / "monitor_state.json"
NEWS_FILE = DATA_EVENTS / "latest_feed.json"
FACTORS_FILE = PROJECT_ROOT / "data" / "factors" / "current_factors.json"

HISTORY_FILES = {
    "gold": DATA_HISTORY / "daily" / "gold_silver_daily.csv",
    "silver": DATA_HISTORY / "daily" / "gold_silver_daily.csv",
    "silver_ratio": DATA_HISTORY / "daily" / "gold_silver_daily.csv",
}


# ============ 读取函数 ============


def read_json(path: Path) -> dict:
    """读取 JSON 文件，失败返回空字典"""
    if not path.exists():
        return {"error": f"文件不存在: {path}"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"读取失败: {e}"}


def read_csv_first_n(path: Path, n: int = 30) -> List[dict]:
    """读取 CSV 前 n 行（最近 n 条）"""
    if not path.exists():
        return [{"error": f"文件不存在: {path}"}]
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # 倒序返回（最近的在前）
        return rows[-n:][::-1]
    except Exception as e:
        return [{"error": f"读取失败: {e}"}]


# ============ 因子 → 四象限映射 ============

FACTOR_TO_QUADRANT = {
    "opportunity_cost": ["blue"],
    "currency": ["green"],
    "safe_haven": ["orange"],
    "inflation": ["green"],
    "positioning": ["blue"],
    "structural_demand": ["red"],
    "silver_specific": ["red"],
}


# ============ 查询命令 ============


def cmd_snapshot():
    """当前行情快照"""
    data = read_json(DASHBOARD_FILE)

    # 筛选关键字段，避免信息过载
    keys = [
        "gold_price", "silver_price", "gold_silver_ratio",
        "treasury_10y", "dxy", "vix", "sp500",
        "gold_futures", "silver_futures",
        "shfe_gold", "shfe_silver",
    ]
    snapshot = {}
    for k in keys:
        if k in data and data[k]:
            snapshot[k] = data[k]

    if "events" in data:
        snapshot["events_summary"] = {
            "quadrant_events": {
                q: data["events"]["quadrant_events"].get(q, {})
                for q in ["green", "blue", "orange", "red"]
            }
        }

    return snapshot


def cmd_macro():
    """宏观数据摘要"""
    data = read_json(DASHBOARD_FILE)
    macro_keys = ["treasury_10y", "treasury_30y", "tips_10y", "dxy", "vix", "sp500"]
    macro = {k: data.get(k) for k in macro_keys if data.get(k)}
    return macro


def cmd_history(symbol: str, days: int = 30):
    """查询品种历史行情"""
    file_map = {
        "gold": ("gold_close", "gold_open", "gold_high", "gold_low"),
        "silver": ("silver_close", "silver_open", "silver_high", "silver_low"),
        "silver_ratio": ("ratio_close",),
    }

    if symbol not in file_map:
        return {"error": f"未知品种: {symbol}，可选: {list(file_map.keys())}"}

    path = HISTORY_FILES.get(symbol)
    if not path or not path.exists():
        return {"error": f"历史数据文件不存在: {path}"}

    cols = file_map[symbol]
    rows = read_csv_first_n(path, n=days)

    result = []
    for row in rows:
        if "error" in row:
            return row
        entry = {"date": row.get("date", "")}
        for col in cols:
            try:
                entry[col] = float(row.get(col, 0))
            except (ValueError, TypeError):
                entry[col] = None
        result.append(entry)

    return {"symbol": symbol, "days": days, "data": result}


def cmd_events():
    """活跃事件"""
    data = read_json(EVENT_FILE)
    dashboard = read_json(DASHBOARD_FILE)

    events = data if "error" not in data else {}
    if "events" in dashboard:
        events["dashboard_events"] = dashboard["events"]

    return events


def cmd_news(limit: int = 10):
    """最新新闻"""
    data = read_json(NEWS_FILE)
    if "error" in data:
        return data
    items = data if isinstance(data, list) else data.get("items", [])
    return {"total": len(items), "news": items[:limit]}


def cmd_monitor():
    """阈值监控状态"""
    return read_json(MONITOR_FILE)


def cmd_analysis():
    """运行四象限宏观分析 (通过 V2 analysis 引擎)"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from analysis.engine import Analysis

        engine = Analysis()
        result = engine.analyze()
        return result
    except ImportError as e:
        return {"error": f"无法加载分析引擎: {e}", "hint": "请确保 V2 项目依赖已安装"}
    except Exception as e:
        return {"error": f"分析失败: {e}"}


def cmd_factors(factor_id: str = "") -> dict:
    """查询因子对齐数据

    Args:
        factor_id: 可选，指定因子 ID（opportunity_cost / currency / ...）

    用法:
        python data_query.py factors              # 所有因子
        python data_query.py factors opportunity_cost  # 单因子
    """
    data = read_json(FACTORS_FILE)
    if "error" in data:
        return data

    factors = data.get("factors", {})
    valid_factors = list(factors.keys())

    if factor_id:
        if factor_id not in factors:
            return {
                "error": f"未知因子: {factor_id}",
                "available": valid_factors,
            }
        return {
            "updated_at": data.get("updated_at"),
            "factor": factor_id,
            "label": factors[factor_id].get("label"),
            "signal": factors[factor_id].get("signal"),
            "data": factors[factor_id].get("data", {}),
        }

    # 返回精简版（仅包含 label, signal, 字段数）
    summary = {}
    for fid, finfo in factors.items():
        summary[fid] = {
            "label": finfo.get("label"),
            "signal": finfo.get("signal"),
            "fields": list(finfo.get("data", {}).keys()),
            "field_count": len(finfo.get("data", {})),
        }

    return {
        "updated_at": data.get("updated_at"),
        "factor_count": len(factors),
        "factors": summary,
        "event_count": len(data.get("events", [])),
    }


def cmd_news_by_factor(factor_id: str, limit: int = 10) -> dict:
    """按因子查询相关新闻

    通过因子 → 四象限映射，从 latest_feed.json 中筛选相关新闻。

    Args:
        factor_id: 因子 ID
        limit: 最多返回条数
    """
    # 验证因子
    valid_factors = list(FACTOR_TO_QUADRANT.keys())
    if factor_id not in FACTOR_TO_QUADRANT:
        return {
            "error": f"未知因子: {factor_id}",
            "available_factors": valid_factors,
        }

    quadrants = FACTOR_TO_QUADRANT[factor_id]

    # 读取新闻
    news_data = read_json(NEWS_FILE)
    if "error" in news_data:
        return news_data

    items = news_data if isinstance(news_data, list) else news_data.get("events", [])
    if not items:
        items = news_data if isinstance(news_data, list) else news_data.get("items", [])

    # 筛选匹配象限的新闻
    matched = []
    for item in items:
        item_quadrants = item.get("quadrant", [])
        if isinstance(item_quadrants, list):
            if any(q in quadrants for q in item_quadrants):
                matched.append(item)
        elif isinstance(item_quadrants, str):
            if item_quadrants in quadrants:
                matched.append(item)

    return {
        "factor": factor_id,
        "quadrant": quadrants,
        "total_matched": len(matched),
        "news": matched[:limit],
    }


def cmd_events_by_factor(factor_id: str, limit: int = 10) -> dict:
    """按因子查询相关事件

    事件从 event_tracker.json 读取，通过因子标签映射或四象限标签匹配。

    Args:
        factor_id: 因子 ID
        limit: 最多返回条数
    """
    valid_factors = list(FACTOR_TO_QUADRANT.keys())
    if factor_id not in FACTOR_TO_QUADRANT:
        return {
            "error": f"未知因子: {factor_id}",
            "available_factors": valid_factors,
        }

    quadrants = FACTOR_TO_QUADRANT[factor_id]

    event_data = read_json(EVENT_FILE)
    if "error" in event_data:
        return event_data

    active_events = event_data.get("active_events", [])

    # 按象限标签匹配事件
    matched = []
    for evt in active_events:
        evt_quadrants = evt.get("quadrant", [])
        if isinstance(evt_quadrants, list):
            if any(q in quadrants for q in evt_quadrants):
                matched.append(evt)
        elif isinstance(evt_quadrants, str):
            if evt_quadrants in quadrants:
                matched.append(evt)

    return {
        "factor": factor_id,
        "quadrant": quadrants,
        "total_matched": len(matched),
        "events": matched[:limit],
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    handlers = {
        "snapshot": lambda: cmd_snapshot(),
        "macro": lambda: cmd_macro(),
        "history": lambda: cmd_history(sys.argv[2]) if len(sys.argv) > 2 else {"error": "请指定品种: gold/silver/silver_ratio"},
        "events": lambda: cmd_events(),
        "news": lambda: cmd_news(),
        "monitor": lambda: cmd_monitor(),
        "analysis": lambda: cmd_analysis(),
        "factors": lambda: cmd_factors(sys.argv[2] if len(sys.argv) > 2 else ""),
        "news_by_factor": lambda: cmd_news_by_factor(sys.argv[2]) if len(sys.argv) > 2 else {"error": "请指定因子 ID，如: safe_haven"},
        "events_by_factor": lambda: cmd_events_by_factor(sys.argv[2]) if len(sys.argv) > 2 else {"error": "请指定因子 ID，如: positioning"},
    }

    if command not in handlers:
        print(f"未知命令: {command}\n")
        print(__doc__)
        sys.exit(1)

    result = handlers[command]()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
