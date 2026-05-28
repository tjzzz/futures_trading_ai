#!/usr/bin/env python3
"""
RSS 新闻采集器 — V2 整合版
- 每30分钟采集 CNBC / MarketWatch RSS
- 关键词归因到四象限（绿/蓝/橙/红）
- 强度评级（S/A/B/C）
- 写入：data/events/latest_feed.json + dashboard_data.json

源自 workspace-trade-ai/collectors/news_collector.py
V2 变更：路径从 config 解析，适配 package 结构
"""

import logging
import requests
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from collectors.base_collector import acquire_exclusive_lock, release_exclusive_lock

logger = logging.getLogger("rss_news")

TZ = timezone(timedelta(hours=8))
EVENTS_FILE = PROJECT_ROOT / "data" / "events" / "event_tracker.json"
FEED_FILE = PROJECT_ROOT / "data" / "events" / "latest_feed.json"
DASHBOARD_FILE = PROJECT_ROOT / "data" / "current" / "dashboard_data.json"
DASHBOARD_LOCK = Path("/tmp/futures_trading_dashboard.json.lock")


# ─── 文件锁（复用 base_collector 的排他锁，共享同一锁文件） ────

def _acquire_dashboard_lock(timeout: float = 3.0) -> bool:
    """获取 dashboard 文件锁（委托给 base_collector 的真正排他锁）"""
    return acquire_exclusive_lock(DASHBOARD_LOCK, timeout=timeout, stale_after=10.0)


def _release_dashboard_lock():
    """释放 dashboard 文件锁（委托给 base_collector）"""
    release_exclusive_lock(DASHBOARD_LOCK)

RSS_FEEDS = {
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "cnbc_politics": "https://www.cnbc.com/id/10000113/device/rss/rss.html",
    "cnbc_markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "cnbc_economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115",
}

# 关键词→象限映射
QUADRANT_RULES = {
    "green": {
        "keywords": ["treasury", "bond", "yield", "10-year", "30-year",
                     "dxy", "dollar index", "central bank gold", "credit",
                     "debt ceiling", "treasury bill", "treasury auction",
                     "credit rating", "fitch", "moody", "s&p rating",
                     "sovereign debt", "default risk"],
    },
    "blue": {
        "keywords": ["federal reserve", "fed", "interest rate", "rate cut",
                     "rate hike", "balance sheet", "quantitative easing",
                     "quantitative tightening", "liquidity", "monetary policy",
                     "sofr", "libor", "discount rate"],
    },
    "orange": {
        "keywords": ["iran", "war", "geopolitical", "sanctions", "vix",
                     "s&p 500", "stock market", "crash", "volatility",
                     "safe haven", "conflict", "ceasefire",
                     "military", "defense", "risk", "tariff", "trade war",
                     "terror", "nuclear", "invasion"],
    },
    "red": {
        "keywords": ["comex", "silver", "gold etf", "slv", "gld",
                     "mining", "shortage", "industrial demand", "precious metals",
                     "commodity", "inventory", "supply chain",
                     "copper", "energy", "oil", "gasoline", "inflation"],
    }
}

LEVEL_KEYWORDS_S = [
    "emergency", "default", "collapse", "crisis", "meltdown",
    "emergency meeting", "unprecedented", "systemic",
    "breach", "record high", "record low"
]

LEVEL_KEYWORDS_A = [
    "surge", "plunge", "soar", "tumble", "warning", "alert",
    "major", "significant", "hike", "cut", "break through",
    "break above", "break below", "spike", "crash", "rally",
]


def fetch_rss(url, timeout=15):
    """抓取单个RSS源"""
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item'):
            items.append({
                "title": item.findtext('title', ''),
                "description": item.findtext('description', ''),
                "link": item.findtext('link', ''),
                "pubDate": item.findtext('pubDate', ''),
            })
        return items
    except Exception as e:
        logger.warning("RSS fetch failed (%s): %s", url, e)
        return []


def classify_event(item):
    """将新闻条目归因到象限并评级"""
    text = (item['title'] + ' ' + (item['description'] or '')).lower()

    # 归因象限
    quadrants = []
    for q, rules in QUADRANT_RULES.items():
        for kw in rules['keywords']:
            if kw.lower() in text:
                quadrants.append(q)
                break

    if not quadrants:
        quadrants = ["unclassified"]

    # 强度评级
    level = 'C'
    for kw in LEVEL_KEYWORDS_S:
        if kw in text:
            level = 'S'
            break
    if level == 'C':
        for kw in LEVEL_KEYWORDS_A:
            if kw in text:
                level = 'A'
                break

    return quadrants, level


def load_events():
    """加载已有事件追踪数据"""
    try:
        with open(EVENTS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"active_events": [], "events_to_watch": [],
                "quadrant_summary": {}}


def save_events(data):
    """保存事件数据"""
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_dashboard_events(events):
    """将事件摘要写入dashboard_data.json（带文件锁）"""
    if not _acquire_dashboard_lock(timeout=3.0):
        logger.warning("无法获取 dashboard 文件锁，跳过事件更新")
        return

    try:
        try:
            with open(DASHBOARD_FILE, 'r') as f:
                dashboard = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            dashboard = {}

        dashboard["events"] = {
            "active_s": [e["title"] for e in events.get("active_events", [])
                         if e["level"] == "S"],
            "active_a": [e["title"] for e in events.get("active_events", [])
                         if e["level"] == "A"],
            "quadrant_events": events.get("quadrant_summary", {}),
            "updated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M CST")
        }

        with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
            json.dump(dashboard, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("更新 dashboard 事件失败: %s", e)
    finally:
        _release_dashboard_lock()


def main():
    now = datetime.now(TZ)
    logger.info("=== 新闻采集 %s ===", now.strftime("%Y-%m-%d %H:%M CST"))

    all_items = []
    for name, url in RSS_FEEDS.items():
        items = fetch_rss(url)
        logger.info("  %s: %d items", name, len(items))
        for item in items:
            quadrants, level = classify_event(item)
            all_items.append({
                "source": name,
                "title": item['title'][:200],
                "description": (item['description'] or '')[:300],
                "link": item['link'],
                "pubDate": item['pubDate'],
                "quadrant": quadrants,
                "level": level,
                "fetched_at": now.strftime("%Y-%m-%d %H:%M CST"),
            })

    # 排序
    level_order = {"S": 0, "A": 1, "B": 2, "C": 3, "unclassified": 4}
    all_items.sort(key=lambda x: level_order.get(x['level'], 9))

    # 保存原始feed
    feed_data = {
        "fetched_at": now.strftime("%Y-%m-%d %H:%M CST"),
        "total": len(all_items),
        "events": all_items[:100],
    }
    FEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FEED_FILE, 'w', encoding='utf-8') as f:
        json.dump(feed_data, f, ensure_ascii=False, indent=2)

    # 统计
    levels = {"S": 0, "A": 0, "B": 0, "C": 0}
    for item in all_items:
        lvl = item['level']
        if lvl in levels:
            levels[lvl] += 1

    logger.info("  汇总: S=%d A=%d B=%d C=%d 总计=%d", levels['S'], levels['A'], levels['B'], levels['C'], len(all_items))

    # ── 构建事件追踪数据 ──
    # 筛选 S/A 级事件作为活跃事件
    active_events = [
        {
            "title": item["title"],
            "summary": item["description"][:200],
            "level": item["level"],
            "quadrant": item["quadrant"],
            "source": item["source"],
            "link": item["link"],
            "pubDate": item["pubDate"],
            "detected_at": now.strftime("%Y-%m-%d %H:%M CST"),
        }
        for item in all_items
        if item["level"] in ("S", "A")
    ]

    # 象限汇总
    quadrant_summary = {}
    for item in all_items:
        for q in item["quadrant"]:
            quadrant_summary[q] = quadrant_summary.get(q, 0) + 1

    events_data = {
        "active_events": active_events,
        "events_to_watch": [
            {"title": item["title"], "level": item["level"], "quadrant": item["quadrant"]}
            for item in all_items[:20]
        ],
        "quadrant_summary": quadrant_summary,
        "fetched_at": now.strftime("%Y-%m-%d %H:%M CST"),
        "total": len(all_items),
    }
    save_events(events_data)
    s_count = sum(1 for e in active_events if e['level'] == 'S')
    a_count = sum(1 for e in active_events if e['level'] == 'A')
    logger.info("  活跃事件: S=%d A=%d", s_count, a_count)

    # 更新dashboard事件摘要
    update_dashboard_events(events_data)

    logger.info("✅ 完成")


if __name__ == "__main__":
    main()
