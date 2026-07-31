#!/usr/bin/env python3
"""
专题事件追踪器 — V1

从 RSS + Calendar 中提取事件更新，按事件生命周期组织。

工作流:
  1. 读取 existing event_tracker.json 中的活跃事件列表
  2. 读取 latest_feed.json 的最新新闻
  3. 读取 calendar_cache.json 的经济日历（如有超预期事件）
  4. 匹配新闻到已有事件 / 创建新事件
  5. 更新事件状态（active/resolved/archived）
  6. 写回 event_tracker.json

频率: 每次 RSS/Calendar 采集后调用
"""

import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from collectors.base import setup_logger, PROJECT_ROOT

logger = setup_logger("topics")
CST = timezone(timedelta(hours=8))

TOPIC_FACTORY = PROJECT_ROOT / "data/events"
EVENT_FILE = TOPIC_FACTORY / "event_tracker.json"
FEED_FILE = TOPIC_FACTORY / "latest_feed.json"
CALENDAR_FILE = TOPIC_FACTORY / "calendar_cache.json"
TRACKER_ARCHIVE_DIR = TOPIC_FACTORY / "tracker/"

# ── 事件关键词 → 事件类型 + 因子标签 ──
# 用于自动创建事件
EVENT_TYPE_RULES = [
    # Fed/政策
    (["fed", "federal reserve", "fomc", "rate cut", "rate hike", "warsh"], "policy_shift", ["opportunity_cost", "currency"]),
    # CPI/通胀
    (["cpi", "inflation", "pce", "consumer price"], "data_release", ["inflation", "opportunity_cost"]),
    # 非农/就业
    (["nonfarm", "payroll", "employment", "unemployment", "jobless"], "data_release", ["opportunity_cost", "safe_haven"]),
    # 地缘（伊朗/中东）
    (["iran", "hormuz", "hezbollah", "middle east", "ceasefire", "nuclear"], "geo_political", ["safe_haven"]),
    # 地缘（其他）
    (["war", "conflict", "sanction", "military", "invasion"], "geo_political", ["safe_haven"]),
    # 原油/能源
    (["opec", "crude", "oil", "energy price", "gasoline"], "supply_shock", ["inflation"]),
    # 金银
    (["gold", "silver", "comex", "precious metal"], "price_anomaly", ["positioning", "silver_specific"]),
    # GDP
    (["gdp", "recession", "economic growth"], "data_release", ["inflation", "safe_haven"]),
    # 机构持仓
    (["cftc", "cot", "gold etf", "silver etf", "gld", "slv", "positioning"], "institutional", ["positioning"]),
]

# ── 永久事件（始终活跃，不自动过期） ──
PERMANENT_EVENTS = {
    "fed_policy_path": {
        "title": "Fed 政策路径跟踪",
        "type": "policy_shift",
        "factor_tags": ["opportunity_cost", "currency"],
    },
    "economic_calendar": {
        "title": "经济数据日历",
        "type": "data_release",
        "factor_tags": ["inflation", "opportunity_cost", "safe_haven"],
    },
}

# ── 当前活跃的专题事件 ──
ACTIVE_TOPICS = {
    "iran_middle_east": {
        "title": "中东/伊朗局势",
        "type": "geo_political",
        "factor_tags": ["safe_haven"],
        "started_at": "2026-06-01",
    },
}

# ── 事件过期阈值（天） ──
EXPIRY_DAYS = {
    "data_release": 3,
    "geo_political": 14,
    "policy_shift": 21,
    "price_anomaly": 1,
    "supply_shock": 7,
    "institutional": 10,
    "permanent": 999,  # 永不自动过期
}


def _now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _today_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _title_to_id(title: str) -> str:
    """从新闻标题生成事件 ID"""
    h = hashlib.md5(title.encode()).hexdigest()[:8]
    return f"evt_{h}"


def _match_event_type(title: str, desc: str) -> tuple[str, str, list[str]]:
    """匹配事件类型和因子标签"""
    text = (title + " " + (desc or "")).lower()
    for keywords, evt_type, factors in EVENT_TYPE_RULES:
        if any(kw in text for kw in keywords):
            return evt_type, factors, keywords
    return "price_anomaly", ["safe_haven"], []


def _create_event_from_news(item: dict) -> dict:
    """根据新闻条目创建新事件"""
    title = item.get("title", "")
    desc = item.get("description", "")
    evt_type, factors, matched_kw = _match_event_type(title, desc)

    return {
        "event_id": _title_to_id(title),
        "title": title[:80],
        "type": evt_type,
        "status": "active",
        "severity": "medium",
        "factor_tags": factors,
        "started_at": _today_cst(),
        "expected_expiry": None,
        "sources": [item.get("source", "rss")],
        "matched_keywords": matched_kw,
        "timeline": [{
            "date": _today_cst(),
            "headline": title[:120],
            "detail": desc[:200] if desc else "",
            "source": item.get("source", "rss"),
            "impact": None,
        }],
        "key_levels": {},
        "next_focus": None,
        "narrative_change": None,
    }


def _init_permanent_events(tracker: dict):
    """初始化永久事件（如果不存在）"""
    existing_ids = set()
    for e in tracker.get("active_events", []):
        eid = e.get("event_id")
        if eid:
            existing_ids.add(eid)
        else:
            # 旧格式（来自 rss.py 的活跃事件），分配 event_id
            e["event_id"] = _title_to_id(e.get("title", ""))
    for evt_id, config in PERMANENT_EVENTS.items():
        if evt_id not in existing_ids:
            tracker["active_events"].append({
                "event_id": evt_id,
                "title": config["title"],
                "type": "permanent",
                "status": "active",
                "severity": "medium",
                "factor_tags": config["factor_tags"],
                "started_at": _today_cst(),
                "expected_expiry": None,
                "sources": ["system"],
                "timeline": [],
                "key_levels": {},
                "next_focus": None,
                "narrative_change": None,
            })
            logger.info(f"  初始化永久事件: {config['title']}")

    for evt_id, config in ACTIVE_TOPICS.items():
        if evt_id not in existing_ids:
            tracker["active_events"].append({
                "event_id": evt_id,
                "title": config["title"],
                "type": config["type"],
                "status": "active",
                "severity": "high",
                "factor_tags": config["factor_tags"],
                "started_at": config.get("started_at", _today_cst()),
                "expected_expiry": None,
                "sources": ["manual"],
                "timeline": [],
                "key_levels": {},
                "next_focus": None,
                "narrative_change": None,
            })
            logger.info(f"  初始化活跃专题: {config['title']}")
    return tracker


def _match_existing_event(news_item: dict, events: list) -> tuple[bool, int]:
    """
    判断新闻是否匹配已有事件。

    Returns:
        (matched, event_index)
    """
    text = (news_item.get("title", "") + " " + (news_item.get("description", "") or "")).lower()

    for i, evt in enumerate(events):
        if evt.get("type") == "permanent":
            # 永久事件：检查 factor_tags 是否有交集
            news_factors = set(news_item.get("factors", []))
            evt_factors = set(evt.get("factor_tags", []))
            if news_factors & evt_factors:
                return True, i

        # 普通事件：检查关键词匹配
        evt_title = evt.get("title", "").lower()
        # 如果事件标题中的关键词出现在新闻中
        event_keywords = evt_title.replace("—", " ").replace("–", " ").split()
        meaningful_kw = [w for w in event_keywords if len(w) > 3]
        if meaningful_kw and any(kw in text for kw in meaningful_kw):
            return True, i

        # 检查 matched_keywords
        matched = evt.get("matched_keywords", [])
        if matched and any(kw in text for kw in matched):
            return True, i

    return False, -1


def process():
    """主流程"""
    logger.info("=== topics start ===")

    # 加载数据
    tracker = _load_json(EVENT_FILE)
    if not tracker.get("active_events"):
        tracker = {"active_events": [], "calendar": [], "fetched_at": _now_cst()}

    # 初始化永久事件 + 活跃专题
    tracker = _init_permanent_events(tracker)
    events = tracker["active_events"]
    today = _today_cst()

    # 加载最新新闻
    feed = _load_json(FEED_FILE)
    news_items = feed.get("events", [])

    # 加载经济日历
    calendar_entries = tracker.get("calendar", [])

    new_event_count = 0
    matched_count = 0
    ignored_count = 0

    for item in news_items:
        # 跳过 unclassified
        factors = item.get("factors", [])
        if "unclassified" in factors and len(factors) == 1:
            ignored_count += 1
            continue

        # 尝试匹配已有事件
        matched, idx = _match_existing_event(item, events)

        if matched:
            # 追加到已有事件的 timeline（去重）
            evt = events[idx]
            headline = item.get("title", "")[:120]
            existing_headlines = {t.get("headline", "") for t in evt.get("timeline", [])}
            if headline not in existing_headlines:
                evt.setdefault("timeline", []).append({
                    "date": today,
                    "headline": headline,
                    "detail": (item.get("description", "") or "")[:200],
                    "source": item.get("source", "rss"),
                    "impact": None,
                })
                # 限制 timeline 长度
                if len(evt["timeline"]) > 20:
                    evt["timeline"] = evt["timeline"][-20:]
                matched_count += 1
        else:
            # 创建新事件
            new_event = _create_event_from_news(item)
            events.append(new_event)
            new_event_count += 1

    # 事件过期处理
    today_dt = datetime.now(CST)
    expiry_count = 0
    for evt in events:
        if evt.get("type") == "permanent":
            continue

        if evt.get("status") != "active":
            # status 不存在（旧格式）→ 设为 active
            evt.setdefault("status", "active")
            continue

        started = evt.get("started_at")
        if not started:
            continue

        try:
            start_dt = datetime.strptime(started[:10], "%Y-%m-%d")
            days_active = (today_dt - start_dt).days
            max_days = EXPIRY_DAYS.get(evt.get("type", "data_release"), 7)
            if days_active > max_days:
                evt["status"] = "resolved"
                evt.setdefault("resolved_at", today)
                expiry_count += 1
                logger.info(f"  事件过期: {evt['title'][:40]} (活跃 {days_active}天, 阈值 {max_days}天)")
        except (ValueError, TypeError):
            continue

    # 限制事件总数
    if len(events) > 50:
        # 保留活跃 + 最近的 resolved
        active = [e for e in events if e["status"] == "active"]
        resolved = [e for e in events if e["status"] != "active"]
        resolved.sort(key=lambda e: e.get("resolved_at", ""), reverse=True)
        events = active + resolved[:20]

    tracker["active_events"] = events
    tracker["fetched_at"] = _now_cst()
    _save_json(EVENT_FILE, tracker)

    # ── 写入按日快照归档 ──
    today = _today_cst()
    TRACKER_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "date": today,
        "fetched_at": _now_cst(),
        "total_events": len(events),
        "active_count": len([e for e in events if e["status"] == "active"]),
        "resolved_count": len([e for e in events if e["status"] != "active"]),
        "events": events,
    }
    archive_path = TRACKER_ARCHIVE_DIR / f"{today}.json"
    archive_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    # 更新 latest.json
    latest_path = TRACKER_ARCHIVE_DIR / "latest.json"
    shutil.copy2(archive_path, latest_path)
    logger.info(f"  📦 事件跟踪归档: {today} ({len(events)} 事件)")

    logger.info(f"  新增事件: {new_event_count} / 匹配追加: {matched_count} / 忽略: {ignored_count}")
    logger.info(f"  活跃事件计: {len([e for e in events if e['status'] == 'active'])} / 总计: {len(events)}")
    logger.info("✅ topics 完成")
    return {"snapshot": {}, "history": []}


def main():
    process()


if __name__ == "__main__":
    main()
