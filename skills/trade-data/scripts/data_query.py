#!/usr/bin/env python3
"""
V3 Data Query Tool — 封装 V2 数据层供 AI Agent 调用

用法:
    python data_query.py snapshot [--refresh]   — 当前行情快照
    python data_query.py macro [--refresh]      — 宏观数据摘要
    python data_query.py positions              — 查询持仓 (结合 vault memory)
    python data_query.py history <品种> [--refresh] — 历史行情 (gold/silver/silver_ratio)
    python data_query.py events [--date <日期>] — 活跃事件/历史日历
    python data_query.py news [--date <日期>]   — 最新新闻/历史新闻
    python data_query.py analysis               — 运行四象限分析
    python data_query.py monitor                — 阈值监控状态
    python data_query.py factors [因子] [--refresh] — 全部/单因子数据
    python data_query.py technical [品种]       — 全部/单品种技术指标
    python data_query.py news_by_factor <因子>  — 按因子查新闻
    python data_query.py events_by_factor <因子>— 按因子查事件
    python data_query.py realtime <源>          — 实时数据直查（不落盘）

    --date <日期>  查询历史数据 (YYYY-MM-DD 或 "latest")，适用于 news/events
    --refresh      自动刷新过期数据后再查询（运行采集器）

实时数据直查 (realtime):
    gold/silver       → gold-api.com 金银现货
    comex             → AKShare/新浪 COMEX 金银期货
    macro             → Yahoo Finance 宏观指标 (DXY/VIX/GLD/SLV)
    all               → 全部实时数据源

输出: JSON 格式，便于 AI 解析
"""

import json
import csv
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict

CST = timezone(timedelta(hours=8))

# ============ 路径配置 ============

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # scripts -> skills/trade-data/scripts -> repo root
DATA_CURRENT = PROJECT_ROOT / "data/current"
DATA_HISTORY = PROJECT_ROOT / "data/history"
DATA_EVENTS = PROJECT_ROOT / "data/events"

DASHBOARD_FILE = DATA_CURRENT / "dashboard_data.json"
EVENT_FILE = DATA_EVENTS / "event_tracker.json"
MONITOR_FILE = DATA_EVENTS / "monitor_state.json"
NEWS_FILE = DATA_EVENTS / "latest_feed.json"
FACTORS_FILE = PROJECT_ROOT / "data" / "factors" / "current_factors.json"

NEWS_ARCHIVE_DIR = DATA_EVENTS / "news"
CALENDAR_ARCHIVE_DIR = DATA_EVENTS / "calendar"
TRACKER_ARCHIVE_DIR = DATA_EVENTS / "tracker"

HISTORY_FILES = {
    "gold": DATA_HISTORY / "daily" / "gold_silver_daily.csv",
    "silver": DATA_HISTORY / "daily" / "gold_silver_daily.csv",
    "silver_ratio": DATA_HISTORY / "daily" / "gold_silver_daily.csv",
}

# ============ 新鲜度检查 & 自动刷新 ============

AUTO_REFRESH = False  # 由 --refresh 或 --stale 控制


def _parse_args():
    """解析命令行参数，提取 --refresh 标记和命令"""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    return args, flags


def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def _is_today(date_str: str) -> bool:
    """判断日期字符串是否为今天"""
    return date_str[:10] == _today_str()


def _staleness(path: Path, max_minutes: float = 30) -> float | None:
    """返回文件距今多少分钟，None 表示文件不存在"""
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    return age / 60.0


def _check_freshness(path: Path, label: str, max_minutes: float = 30,
                     auto_refresh: bool = False) -> bool:
    """检查数据文件新鲜度。返回 True = 够新，False = 过期。"""
    age_min = _staleness(path, max_minutes)
    if age_min is None:
        print(json.dumps({"warn": f"{label} 文件不存在: {path}", "auto_refresh": auto_refresh}, ensure_ascii=False))
        return _try_refresh(path, label) if auto_refresh else False

    if age_min > max_minutes:
        print(json.dumps({"warn": f"{label} 数据已过期({age_min:.0f}分钟前)", "auto_refresh": auto_refresh}, ensure_ascii=False))
        if auto_refresh:
            return _try_refresh(path, label)
        return False
    return True


def _try_refresh(path: Path, label: str) -> bool:
    """尝试通过运行采集器刷新数据"""
    print(json.dumps({"info": f"正在刷新 {label}..."}, ensure_ascii=False))
    try:
        if "dashboard_data" in str(path) or "snapshot" in str(path):
            # 实时采集：金银现货、宏观指标
            print(json.dumps({"step": "实时采集 (金银、宏观指标)..."}, ensure_ascii=False))
            r = subprocess.run(
                [sys.executable, "-m", "collectors.run", "realtime"],
                cwd=PROJECT_ROOT, capture_output=False, timeout=120,
            )
            if r.returncode != 0:
                print(json.dumps({"warn": "实时采集部分失败，数据可能不完整"}, ensure_ascii=False))
        if "factors" in str(path):
            # 因子依赖实时数据 + 日频历史数据
            print(json.dumps({"step": "实时采集 (金银、宏观指标)..."}, ensure_ascii=False))
            subprocess.run(
                [sys.executable, "-m", "collectors.run", "realtime"],
                cwd=PROJECT_ROOT, capture_output=False, timeout=120,
            )
            print(json.dumps({"step": "日频采集 (TIPS/美债/VIX/SP500/汇率)..."}, ensure_ascii=False))
            subprocess.run(
                [sys.executable, "-m", "collectors.run", "daily"],
                cwd=PROJECT_ROOT, capture_output=False, timeout=180,
            )
            print(json.dumps({"step": "计算七因子信号+技术指标..."}, ensure_ascii=False))
            subprocess.run(
                [sys.executable, "tools/compute_factors.py"],
                cwd=PROJECT_ROOT, capture_output=False, timeout=120,
            )
        if "events" in str(path) or "news" in str(path) or "latest_feed" in str(path):
            print(json.dumps({"step": "刷新新闻和事件..."}, ensure_ascii=False))
            subprocess.run(
                [sys.executable, "-m", "collectors.run", "realtime"],
                cwd=PROJECT_ROOT, capture_output=False, timeout=120,
            )
        print(json.dumps({"info": f"{label} 刷新完成"}, ensure_ascii=False))
        return True
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": f"{label} 刷新超时"}, ensure_ascii=False))
        return False
    except Exception as e:
        print(json.dumps({"error": f"{label} 刷新失败: {e}"}, ensure_ascii=False))
        return False


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


def cmd_events(date_str: str = ""):
    """活跃事件（默认）或按日期查询历史日历

    Args:
        date_str: ""=活跃事件, "latest"=最新日历归档, "YYYY-MM-DD"=指定日期
    """
    if date_str:
        if date_str == "latest":
            fp = CALENDAR_ARCHIVE_DIR / "latest.json"
        else:
            fp = CALENDAR_ARCHIVE_DIR / f"{date_str}.json"
        if not fp.exists():
            return {"error": f"日历未找到: {date_str}", "path": str(fp)}
        return read_json(fp)

    # 默认：活跃事件（现有行为）
    data = read_json(EVENT_FILE)
    dashboard = read_json(DASHBOARD_FILE)

    events = data if "error" not in data else {}
    if "events" in dashboard:
        events["dashboard_events"] = dashboard["events"]

    return events


def cmd_news(limit: int = 10, date_str: str = ""):
    """最新新闻（默认）或按日期查询历史新闻

    Args:
        limit: 返回条数上限
        date_str: ""=最新, "latest"=最新归档, "YYYY-MM-DD"=指定日期
    """
    if date_str:
        if date_str == "latest":
            fp = NEWS_ARCHIVE_DIR / "latest.json"
        else:
            fp = NEWS_ARCHIVE_DIR / f"{date_str}.json"
        if not fp.exists():
            return {"error": f"新闻未找到: {date_str}", "path": str(fp)}
        data = read_json(fp)
        items = data.get("events", [])
        return {"date": date_str, "total": len(items), "news": items[:limit]}

    # 默认：最新新闻
    data = read_json(NEWS_FILE)
    if "error" in data:
        return data
    items = data if isinstance(data, list) else data.get("items", [])
    return {"total": len(items), "news": items[:limit]}


def cmd_monitor():
    """阈值监控状态"""
    return read_json(MONITOR_FILE)


def cmd_analysis():
    """运行四象限宏观分析 — v2 迁移说明：原 v1 analysis.engine 未随迁，
    由 macro-analysis 块（skills/macro-analysis/scripts/compute_factors.py）替代。"""
    return {"error": "analysis 命令在 v2 已废弃", "hint": "请使用 skills/macro-analysis 的 compute_factors / 七因子归因内核"}


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


def cmd_technical(symbol: str = "") -> dict:
    """查询技术指标

    从 current_factors.json 读取 compute_factors.py 计算的指标数据。

    指标: MA20/60/200, RSI(14), MACD(12,26,9), ATR(14), ADX(14)

    品种: shfe_gold, shfe_silver, spot_gold, spot_silver

    Args:
        symbol: 可选，指定品种

    用法:
        python data_query.py technical              # 所有品种
        python data_query.py technical shfe_gold    # 沪金
    """
    data = read_json(FACTORS_FILE)
    if "error" in data:
        return data

    technicals = data.get("technicals", {})
    if not technicals:
        return {"error": "无技术指标数据，请先运行 compute_factors.py"}

    valid_symbols = list(technicals.keys())

    if symbol:
        if symbol not in technicals:
            return {
                "error": f"未知品种: {symbol}",
                "available": valid_symbols,
            }
        return {
            "updated_at": data.get("updated_at"),
            "symbol": symbol,
            "technicals": technicals[symbol],
        }

    # 返回精简版
    summary = {}
    for sym, tech in technicals.items():
        if isinstance(tech, dict) and "error" not in tech:
            summary[sym] = {
                "price": tech.get("price"),
                "ma20": tech.get("ma20"),
                "ma60": tech.get("ma60"),
                "rsi_14": tech.get("rsi_14"),
                "macd_histogram": tech.get("macd", {}).get("histogram") if isinstance(tech.get("macd"), dict) else None,
                "atr_14": tech.get("atr_14"),
                "adx_14": tech.get("adx_14"),
            }
        else:
            summary[sym] = {"error": tech.get("error", "未知错误")}

    return {
        "updated_at": data.get("updated_at"),
        "symbol_count": len(technicals),
        "technicals": summary,
    }


def cmd_realtime(source: str = "all") -> dict:
    """实时数据直查 — 不落盘，直接调用采集器"""
    result = {}

    if source in ("gold", "silver", "all"):
        try:
            from collectors.spot_gold import GoldSpot
            spot = GoldSpot().collect()
            if spot:
                for k, v in spot.get("snapshot", {}).items():
                    result[k] = v
                result["_spot_gold"] = "ok"
            else:
                result["_spot_gold"] = "fail"
        except Exception as e:
            result["_spot_gold"] = f"error: {e}"

    if source in ("comex", "all"):
        try:
            from collectors.futures_sina import AKShareFuturesCollector
            comex = AKShareFuturesCollector().collect_realtime()
            if comex:
                for k, v in comex.get("snapshot", {}).items():
                    result[k] = v
                result["_comex"] = "ok"
            else:
                result["_comex"] = "fail"
        except Exception as e:
            result["_comex"] = f"error: {e}"

    if source in ("macro", "all"):
        try:
            from collectors.yfinance import YFinanceBatch
            macro = YFinanceBatch().collect()
            if macro:
                for k, v in macro.get("snapshot", {}).items():
                    result[k] = v
                result["_macro"] = "ok"
            else:
                result["_macro"] = "fail"
        except Exception as e:
            result["_macro"] = f"error: {e}"

    result["_queried_at"] = _now_str()
    result["_source"] = source
    return result


def main():
    args, flags = _parse_args()
    AUTO_REFRESH = "--refresh" in flags

    if not args:
        print(__doc__)
        sys.exit(1)

    command = args[0]

    # 提取 --date 参数（支持 --date=YYYY-MM-DD 或 --date YYYY-MM-DD）
    date_str = ""
    raw = sys.argv[1:]
    for i, token in enumerate(raw):
        if token == "--date" and i + 1 < len(raw):
            date_str = raw[i + 1]
            break
        if token.startswith("--date="):
            date_str = token.split("=", 1)[1]
            break

    # ── 新鲜度检查（部分命令支持）──
    freshness_checks = {
        "snapshot": (DASHBOARD_FILE, "dashboard_data"),
        "macro": (DASHBOARD_FILE, "dashboard_data"),
        "events": (EVENT_FILE, "events"),
        "news": (NEWS_FILE, "news"),
        "factors": (FACTORS_FILE, "factors"),
        "technical": (FACTORS_FILE, "factors"),
    }

    if command in freshness_checks:
        fpath, label = freshness_checks[command]
        _check_freshness(fpath, label, auto_refresh=AUTO_REFRESH)

    handlers = {
        "snapshot": lambda: cmd_snapshot(),
        "macro": lambda: cmd_macro(),
        "positions": lambda: {"error": "请通过 agent memory 查询持仓"},
        "history": lambda: cmd_history(args[1]) if len(args) > 1 else {"error": "请指定品种: gold/silver/silver_ratio"},
        "events": lambda: cmd_events(date_str),
        "news": lambda: cmd_news(date_str=date_str),
        "monitor": lambda: cmd_monitor(),
        "analysis": lambda: cmd_analysis(),
        "factors": lambda: cmd_factors(args[1] if len(args) > 1 else ""),
        "technical": lambda: cmd_technical(args[1] if len(args) > 1 else ""),
        "news_by_factor": lambda: cmd_news_by_factor(args[1]) if len(args) > 1 else {"error": "请指定因子 ID，如: safe_haven"},
        "events_by_factor": lambda: cmd_events_by_factor(args[1]) if len(args) > 1 else {"error": "请指定因子 ID，如: positioning"},
        "realtime": lambda: cmd_realtime(args[1] if len(args) > 1 else "all"),
    }

    if command not in handlers:
        print(f"未知命令: {command}\n")
        print(__doc__)
        sys.exit(1)

    result = handlers[command]()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
