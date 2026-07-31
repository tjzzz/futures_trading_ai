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
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from collectors.base import setup_logger, PROJECT_ROOT

logger = setup_logger("calendar")
CST = timezone(timedelta(hours=8))

EVENTS_FILE = PROJECT_ROOT / "data/events/event_tracker.json"
CALENDAR_CACHE = PROJECT_ROOT / "data/events/calendar_cache.json"
CALENDAR_ARCHIVE_DIR = PROJECT_ROOT / "data/events/calendar/"


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


def collect(days_ahead: int = 7) -> dict | None:
    """采集经济日历并判断超预期

    Args:
        days_ahead: 预拉未来 N 天的日历（默认7天, 含今天）
    """
    logger.info("=== calendar start ===")
    tracker = _load_tracker()
    today = datetime.now(CST)
    today_str = today.strftime("%Y-%m-%d")

    # ── 检查今日日历是否已归档（复用缓存）──
    archive_path = CALENDAR_ARCHIVE_DIR / f"{today_str}.json"
    if archive_path.exists():
        cached = json.loads(archive_path.read_text(encoding="utf-8"))
        logger.info(f"  今日日历已归档，复用缓存: {today_str} ({cached.get('total', 0)} 条)")
        # 恢复 tracker 中的 calendar 字段
        if not tracker.get("calendar"):
            tracker["calendar"] = cached.get("events", [])
            tracker["fetched_at"] = cached.get("fetched_at", "")
            _save_tracker(tracker)
        return {"snapshot": {}, "history": []}

    try:
        import akshare as ak

        today = datetime.now(CST)
        all_calendar = []
        fetched_dates = []

        for offset in range(days_ahead):
            target_date = today + timedelta(days=offset)
            date_str = target_date.strftime("%Y%m%d")
            date_label = target_date.strftime("%Y-%m-%d")

            try:
                df = ak.macro_info_ws(date=date_str)
            except Exception as e:
                logger.warning(f"  {date_label}: 采集失败 - {e}")
                continue

            if df is None or df.empty:
                logger.info(f"  {date_label}: 无数据")
                continue

            fetched_dates.append(date_label)

            # 筛选美国重要性 3+ 的事件
            us_important = df[
                df["地区"].str.contains("美国", na=False) &
                df["重要性"].astype(str).isin(["3", "4", "5"])
            ]

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
                all_calendar.append(entry)

        # 记录超预期事件（仅当天）
        today_entries = [e for e in all_calendar if e["date"].startswith(today.strftime("%Y-%m-%d"))]
        surprises = [e for e in today_entries if e["surprise"]["direction"] in ("above", "below")]
        if surprises:
            logger.info(f"  ⚡ 超预期事件: {len(surprises)} 条")
            for s in surprises:
                logger.info(f"    {s['date']} {s['event']}: actual={s['actual']} vs expected={s['expected']} → {s['surprise']['impact']}")
        else:
            logger.info("  今日无美国重要超预期事件")

        # 按时间排序，去重
        seen = set()
        deduped = []
        for e in all_calendar:
            key = (e["date"], e["event"])
            if key not in seen:
                seen.add(key)
                deduped.append(e)
            else:
                logger.info(f"  去重: {e['date']} {e['event']}")
        all_calendar = deduped
        all_calendar.sort(key=lambda x: x["date"])

        # 更新 tracker
        tracker["calendar"] = all_calendar
        tracker["calendar_date_range"] = f"{fetched_dates[0]} ~ {fetched_dates[-1]}" if fetched_dates else "无数据"
        tracker["fetched_at"] = _now_cst()
        _save_tracker(tracker)

        # ── 按日归档：将已过去的事件归档到各自日期的文件 ──
        CALENDAR_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        today_dt = datetime.now(CST)
        passed_events = [e for e in all_calendar if e["date"][:10] < today_str]
        upcoming_events = [e for e in all_calendar if e["date"][:10] >= today_str]

        # 按日期分组归档
        from collections import defaultdict
        by_date = defaultdict(list)
        for e in passed_events:
            date_key = e["date"][:10]
            by_date[date_key].append(e)

        for date_key, items in by_date.items():
            archive_fp = CALENDAR_ARCHIVE_DIR / f"{date_key}.json"
            existing = []
            if archive_fp.exists():
                existing = json.loads(archive_fp.read_text(encoding="utf-8")).get("events", [])
            merged = { (e["date"], e["event"]): e for e in existing }
            for e in items:
                merged[(e["date"], e["event"])] = e
            archive_data = {
                "date": date_key,
                "total": len(merged),
                "events": list(merged.values()),
                "archived_at": _now_cst(),
            }
            archive_fp.write_text(json.dumps(archive_data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"  📦 日历归档: {date_key} ({len(items)} 条)")

        # 更新 cache — 只保留今日及未来事件
        cal_cache = {
            "date": today_str,
            "date_range": tracker["calendar_date_range"],
            "total": len(upcoming_events),
            "events": upcoming_events,
            "fetched_at": _now_cst(),
        }
        CALENDAR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CALENDAR_CACHE.write_text(json.dumps(cal_cache, ensure_ascii=False, indent=2), encoding="utf-8")

        # 更新 latest.json
        today_archive = CALENDAR_ARCHIVE_DIR / f"{today_str}.json"
        today_archive_data = {
            "date": today_str,
            "total": len(passed_events) + len(upcoming_events),
            "events": all_calendar,
            "fetched_at": _now_cst(),
        }
        today_archive.write_text(json.dumps(today_archive_data, ensure_ascii=False, indent=2), encoding="utf-8")
        latest_path = CALENDAR_ARCHIVE_DIR / "latest.json"
        shutil.copy2(today_archive, latest_path)

        logger.info(f"✅ calendar 完成: {len(all_calendar)} 条 (范围: {tracker['calendar_date_range']})")
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
