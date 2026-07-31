#!/usr/bin/env python3
"""
RSS 新闻采集器 — V1 七因子归类

源:
  cnbc_markets    ✅ (保留) — 金融/商品
  cnbc_economy    ✅ (保留) — 宏观数据
  cnbc_politics   ❌ (删除) — 噪音源（政治人物/国会争斗）
  marketwatch     ⚠️ (过滤) — 只保留宏观/商品/金银关键词命中的
  reuters         ✅ (新增) — 大宗商品，权威免费源

归类: 多关键词组合 + 排除规则，降噪。
频率: 30 分钟
"""

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import xml.etree.ElementTree as ET

from collectors.base import setup_logger, now_cst, PROJECT_ROOT

logger = setup_logger("rss_news")
CST = timezone(timedelta(hours=8))

# ── 文件路径 ──
EVENTS_FILE = PROJECT_ROOT / "data/events/event_tracker.json"
FEED_FILE = PROJECT_ROOT / "data/events/latest_feed.json"
NEWS_ARCHIVE_DIR = PROJECT_ROOT / "data/events/news/"

# ── RSS 源（只保留有价值的） ──
RSS_FEEDS = {
    "cnbc_markets":  "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "cnbc_economy":  "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115",
    "reuters_commodities": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best&best-sectors=commodities-energy",
    "marketwatch":   "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}

# ── 排除规则：命中这些关键词的新闻直接跳过（不采集） ──
# 理由：跟金银交易完全无关的个人理财/娱乐/健康内容
SKIP_KEYWORDS = [
    "glp-1", "wegovy", "weight loss", "medicare", "401(k)", "retirement",
    "screwworm", "jewelry", "bling", "podcast",
    "obama presidential center", "juneteenth",
    "senate primary", "mayoral race",
]

# ── 排除源规则：marketwatch 只保留命中以下关键词的 ──
MARKETWATCH_ALLOW = [
    "gold", "silver", "precious metal", "comex", "fed", "federal reserve",
    "treasury", "yield", "inflation", "cpi", "pce", "nonfarm", "payroll",
    "dollar", "dxy", "vix", "crude", "oil", "commodities", "copper",
    "tariff", "trade war", "recession", "gdp",
]

# ── 七因子关键词映射（组合规则，降低误报） ──
# 规则: 至少命中 2 个不同关键词才算匹配，否则即使命中也只标 low_confidence
FACTOR_RULES = {
    "opportunity_cost": {
        "label": "机会成本",
        "terms": [
            "treasury", "yield", "bond", "10-year", "30-year",
            "tip", "real yield", "interest rate", "fed", "federal reserve",
            "rate cut", "rate hike", "fomc", "monetary policy",
            "discount rate", "sofr", "libor", "warsh",
        ],
        "exclude": [],  # 无排除项
    },
    "currency": {
        "label": "货币",
        "terms": [
            "dollar index", "dxy", "usd", "euro", "yen", "cny",
            "currency", "exchange rate", "forex",
            "de-dollarization", "reserve currency",
        ],
        "exclude": [],
    },
    "safe_haven": {
        "label": "避险需求",
        "terms": [
            "vix", "volatility", "panic", "crash", "crisis", "meltdown",
            "geopolitical", "war", "conflict", "ceasefire", "invasion",
            "sanction", "terror", "nuclear", "military",
            "safe haven", "risk-off", "turmoil", "default",
            "iran", "hormuz", "hezbollah", "middle east",
        ],
        "exclude": ["screwworm", "jewelry"],
    },
    "inflation": {
        "label": "通胀预期",
        "terms": [
            "inflation", "cpi", "pce", "breakeven",
            "oil", "wti", "crude", "energy price", "gasoline",
            "commodity", "supply chain", "shortage", "opec",
        ],
        "exclude": ["glp-1", "wegovy", "weight loss"],
    },
    "positioning": {
        "label": "持仓动量",
        "terms": [
            "comex", "gold future", "silver future", "open interest",
            "gold etf", "gld", "slv", "etf inflow", "etf outflow",
            "speculator", "hedge fund", "positioning", "crowded",
            "short squeeze", "long liquidation", "cftc", "cot",
        ],
        "exclude": [],
    },
    "structural_demand": {
        "label": "结构性需求",
        "terms": [
            "central bank gold", "gold reserve", "pboc gold",
            "de-dollarization", "gold purchase",
            "world gold council", "sovereign gold",
        ],
        "exclude": [],
    },
    "silver_specific": {
        "label": "银价专用",
        "terms": [
            "silver", "gold-silver ratio", "gold silver ratio",
            "solar", "photovoltaic", "industrial demand",
            "silver inventory", "lbma silver",
        ],
        "exclude": [],
    },
}


def fetch_rss(url: str, timeout: int = 15) -> list:
    """抓取单个 RSS 源"""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
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
        logger.warning(f"RSS 抓取失败 ({url}): {e}")
        return []


def should_skip(item: dict) -> bool:
    """判断是否跳过该新闻（噪音过滤）"""
    text = (item.get("title", "") + " " + (item.get("description", "") or "")).lower()
    for kw in SKIP_KEYWORDS:
        if kw in text:
            return True
    return False


def marketwatch_filter(item: dict) -> bool:
    """marketwatch 只保留宏观/商品相关"""
    text = (item.get("title", "") + " " + (item.get("description", "") or "")).lower()
    for kw in MARKETWATCH_ALLOW:
        if kw in text:
            return True
    return False


def classify_to_factors(text: str) -> list[tuple[str, float]]:
    """
    将新闻文本归因到七因子。

    规则:
      - 每个因子至少命中 2 个不同的 term 才算匹配
      - 命中数 2-3 → confidence = 0.6
      - 命中数 4+  → confidence = 0.85
      - 命中 1 个 → 标记 low_confidence (置信度 0.3)
      - 命中排除词 → 跳过该因子

    Returns:
        [(factor_id, confidence), ...]
    """
    text_lower = text.lower()
    results = []

    for factor_id, config in FACTOR_RULES.items():
        # 排除检查
        excluded = any(kw in text_lower for kw in config.get("exclude", []))
        if excluded:
            continue

        # 命中计数
        hits = sum(1 for term in config["terms"] if term in text_lower)

        if hits >= 4:
            confidence = 0.85
        elif hits >= 2:
            confidence = 0.6
        elif hits == 1:
            confidence = 0.3  # low confidence
        else:
            continue

        results.append((factor_id, confidence))

    if not results:
        return [("unclassified", 0.3)]

    return results


def main():
    now = datetime.now(CST)
    today = now.strftime("%Y-%m-%d")
    logger.info("=== 新闻采集 (V1 七因子) %s ===", now.strftime("%Y-%m-%d %H:%M CST"))

    # ── 检查今日是否已归档（复用缓存）──
    archive_path = NEWS_ARCHIVE_DIR / f"{today}.json"
    if archive_path.exists():
        cached = json.loads(archive_path.read_text(encoding="utf-8"))
        logger.info(f"  今日新闻已归档，复用缓存: {today} ({cached.get('total', 0)} 条)")
        # 确保 latest_feed.json 也指向最新
        if not FEED_FILE.exists():
            FEED_FILE.parent.mkdir(parents=True, exist_ok=True)
            FEED_FILE.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"snapshot": {}, "history": []}

    all_items = []
    source_counts = {}

    for source_name, url in RSS_FEEDS.items():
        items = fetch_rss(url)
        logger.info("  %s: %d 条", source_name, len(items))

        skip_count = 0
        after_filter = 0

        for item in items:
            # 跳过噪音
            if should_skip(item):
                skip_count += 1
                continue

            # marketwatch 额外过滤
            if source_name == "marketwatch" and not marketwatch_filter(item):
                skip_count += 1
                continue

            text = (item['title'] + ' ' + (item['description'] or ''))
            factors = classify_to_factors(text)

            # 组装 relevance dict
            relevance = {fid: conf for fid, conf in factors}
            factor_ids = [fid for fid, _ in factors]

            all_items.append({
                "source": source_name,
                "title": item['title'][:200],
                "description": (item['description'] or '')[:300],
                "link": item['link'],
                "pubDate": item['pubDate'],
                "factors": factor_ids,
                "relevance": relevance,
                "fetched_at": now.strftime("%Y-%m-%d %H:%M CST"),
            })
            after_filter += 1

        source_counts[source_name] = {"raw": len(items), "kept": after_filter, "skipped": skip_count}

    # 统计
    total_raw = sum(v["raw"] for v in source_counts.values())
    total_kept = len(all_items)
    for src, cnt in source_counts.items():
        logger.info(f"    {src}: raw={cnt['raw']} → kept={cnt['kept']} (skipped {cnt['skipped']})")
    logger.info(f"  总计: raw={total_raw} → kept={total_kept} (过滤率 {((total_raw-total_kept)/total_raw*100):.0f}%)")

    # 因子分布统计
    factor_count = {}
    for item in all_items:
        for f in item["factors"]:
            factor_count[f] = factor_count.get(f, 0) + 1
    logger.info("  因子分布: %s", {FACTOR_RULES.get(k, {}).get("label", k): v for k, v in sorted(factor_count.items(), key=lambda x: -x[1])})

    # 保存 latest_feed.json
    feed_data = {
        "fetched_at": now.strftime("%Y-%m-%d %H:%M CST"),
        "total": len(all_items),
        "events": all_items[:100],
    }
    FEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEED_FILE.write_text(json.dumps(feed_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 构建 event_tracker.json（活跃事件）
    # 高置信度新闻 → 活跃事件；低置信度但命中因子 → 放入但不升为活跃
    active_events = []
    for item in all_items[:40]:
        factor_ids = item["factors"]
        if "unclassified" in factor_ids and len(factor_ids) == 1:
            continue  # 未归类的跳过
        max_rel = max(item["relevance"].values()) if item["relevance"] else 0
        if max_rel >= 0.4:  # 阈值从 0.6 降至 0.4
            active_events.append({
                "title": item["title"],
                "summary": item["description"][:200],
                "source": item["source"],
                "link": item["link"],
                "pubDate": item["pubDate"],
                "factor_tags": factor_ids,
                "relevance": item["relevance"],
                "impact": None,
                "expiry": None,
            })

    # 因子汇总
    factor_summary = {}
    for item in all_items:
        for f in item["factors"]:
            if f not in factor_summary:
                factor_summary[f] = 0
            factor_summary[f] += 1

    events_data = {
        "active_events": active_events,
        "factor_summary": factor_summary,
        "fetched_at": now.strftime("%Y-%m-%d %H:%M CST"),
        "total": len(all_items),
    }
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(events_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("  活跃事件: %d 条（置信度≥0.4）", len(active_events))

    # ── 写入按日归档 ──
    NEWS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(json.dumps(feed_data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 更新 latest.json
    latest_path = NEWS_ARCHIVE_DIR / "latest.json"
    shutil.copy2(archive_path, latest_path)
    logger.info(f"  📦 新闻归档: {today} ({feed_data['total']} 条)")

    logger.info("✅ 新闻采集完成")
    return {"snapshot": {}, "history": []}


if __name__ == "__main__":
    main()
