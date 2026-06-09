#!/usr/bin/env python3
"""
经济日历采集器 — V1

数据源:
  - 华尔街见闻 (akshare macro_info_ws) — 含今值 vs 预期 vs 前值，重要性评分

工作流:
  1. 获取当日宏观事件
  2. 筛选美国重要性 3+ 的事件
  3. 对比今值 vs 预期 → 标记超预期
  4. 写入 event_tracker.json 的 calendar 字段 + calendar_cache.json

频率: 每日 1 次
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from collectors.base import setup_logger, PROJECT_ROOT

logger = setup_logger("calendar")
CST = timezone(timedelta(hours=8))

EVENTS_FILE = PROJECT_ROOT / "data/events/event_tracker.json"
CALENDAR_CACHE = PROJECT_ROOT / "data/events/calendar_cache.json"


def _now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _today_cst() -> str:
    return datetime.now(CST).strftime("%Y%m%d")


def _load_tracker() -> dict:
    if EVENTS_FILE.exists():
        try:
            return json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"active_events": [], "factor_summary": {}, "calendar": []}


def _save_tracker(data: dict):
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _judge_surprise(event_name: str, actual_str: str, expected_str: str) -> dict:
    """
    判断超预期方向和程度。

    通胀类指标（CPI/PCE）:
      - actual > expected → 超预期偏多 → 利空金银
      - actual < expected → 低于预期 → 利多金银

    就业类指标（非农/初请）:
      - 非农 actual > expected → 经济强劲 → 利空金银
      - 初请 actual > expected → 就业弱 → 利多金银

    其余指标中性判断。

    Returns:
        {"direction": "above/meet/below", "pct_diff": float, "impact": "利多/利空/中性"}
    """
    INFLATION_KEYWORDS = ["cpi", "pce", "通胀", "consumer price"]
    EMPLOYMENT_HAWKISH = ["nonfarm", "payroll", "非农", "unemployment", "失业"]
    EMPLOYMENT_DOVISH = ["jobless", "初请"]

    try:
        actual = float(actual_str) if actual_str and actual_str not in ["", "nan"] else None
        expected = float(expected_str) if expected_str and expected_str not in ["", "nan"] else None
    except (ValueError, TypeError):
        return {"direction": "unknown", "pct_diff": None, "impact": "中性"}

    if actual is None or expected is None or expected == 0:
        return {"direction": "unknown", "pct_diff": None, "impact": "中性"}

    pct_diff = round((actual - expected) / abs(expected) * 100, 1)
    event_lower = event_name.lower()

    # 判断方向
    if pct_diff > 5:  # 超预期 > 5%
        direction = "above"
        # 通胀类超预期 = 利空金银
        if any(kw in event_lower for kw in INFLATION_KEYWORDS):
            impact = "利空"
        elif any(kw in event_lower for kw in EMPLOYMENT_HAWKISH):
            impact = "利空"
        elif any(kw in event_lower for kw in EMPLOYMENT_DOVISH):
            impact = "利多"
        else:
            impact = "中性"
    elif pct_diff < -5:  # 低于预期 > 5%
        direction = "below"
        if any(kw in event_lower for kw in INFLATION_KEYWORDS):
            impact = "利多"
        elif any(kw in event_lower for kw in EMPLOYMENT_HAWKISH):
            impact = "利多"
        elif any(kw in event_lower for kw in EMPLOYMENT_DOVISH):
            impact = "利空"
        else:
            impact = "中性"
    else:
        direction = "meet"
        impact = "中性"

    return {"direction": direction, "pct_diff": pct_diff, "impact": impact}


# ── 关键事件因子映射 ──
# 某些已知事件可预判因子标签
EVENT_FACTOR_MAP = [
    (["cpi", "pce", "通胀", "inflation"], ["inflation"]),
    (["非农", "nonfarm", "payroll", "employment", "失业", "unemployment"], ["opportunity_cost", "safe_haven"]),
    (["fed", "fomc", "美联储", "interest rate", "利率决议"], ["opportunity_cost"]),
    (["gdp"], ["inflation", "safe_haven"]),
    (["初请", "jobless"], ["safe_haven"]),
    (["pmi", "ism", "采购经理"], ["inflation", "positioning"]),
    (["零售", "retail sales"], ["inflation"]),
]


def map_event_to_factors(event_name: str) -> list[str]:
    """根据事件名称映射到因子标签"""
    event_lower = event_name.lower()
    tags = set()
    for keywords, factors in EVENT_FACTOR_MAP:
        if any(kw in event_lower for kw in keywords):
            tags.update(factors)
    return list(tags) if tags else ["unclassified"]


def collect() -> dict | None:
    """采集经济日历并判断超预期"""
    logger.info("=== calendar start ===")
    tracker = _load_tracker()

    try:
        import akshare as ak

        # 华尔街见闻日历（含今值 vs 预期）
        today_str = _today_cst()
        df = ak.macro_info_ws(date=today_str)
        if df is None or df.empty:
            logger.warning("华尔街见闻日历无数据")
            return None

        # 筛选美国重要性 3+ 的事件
        us_important = df[df["地区"].str.contains("美国", na=False) & df["重要性"].astype(str).isin(["3", "4", "5"])]

        calendar_entries = []
        for _, row in us_important.iterrows():
            event_name = str(row.get("事件", ""))
            actual = str(row.get("今值", "")).strip()
            expected = str(row.get("预期", "")).strip()
            previous = str(row.get("前值", "")).strip()
            importance = row.get("重要性")

            surprise = _judge_surprise(event_name, actual, expected)
            factors = map_event_to_factors(event_name)

            entry = {
                "date": str(row.get("时间", ""))[:16],
                "event": event_name,
                "region": "美国",
                "importance": int(float(importance)) if importance else 3,
                "actual": actual,
                "expected": expected,
                "previous": previous,
                "surprise": surprise,
                "factor_tags": factors,
            }
            calendar_entries.append(entry)

        # 记录超预期事件
        surprises = [e for e in calendar_entries if e["surprise"]["direction"] in ("above", "below")]
        if surprises:
            logger.info(f"  ⚡ 超预期事件: {len(surprises)} 条")
            for s in surprises:
                logger.info(f"    {s['date']} {s['event']}: actual={s['actual']} vs expected={s['expected']} → {s['surprise']['impact']}")
        else:
            logger.info("  今日无美国重要超预期事件")

        # 更新 tracker
        tracker["calendar"] = calendar_entries
        tracker["fetched_at"] = _now_cst()
        _save_tracker(tracker)

        logger.info(f"✅ calendar 完成: {len(calendar_entries)} 条")
        return {"snapshot": {}, "history": []}

    except ImportError:
        logger.error("需要安装 akshare: pip install akshare")
        return None
    except Exception as e:
        logger.error(f"日历采集失败: {e}")
        return None


def main():
    collect()


if __name__ == "__main__":
    main()
