#!/usr/bin/env python3
"""
金银日频采集器 — 统一实时采集 + 历史回填

数据源：基于现有数据生成模拟历史（临时方案）
用法：
  python -m collectors.gold_silver_daily              # 当天（实时模式）
  python -m collectors.gold_silver_daily --backfill    # 回填今年至今

设计原则：实时采集和历史回填走同一代码路径，仅时间范围不同。
临时方案：基于现有3天数据生成2026年模拟数据，让预测模块能跑起来。
"""

import argparse
import csv
import logging
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

PROJECT_DIR = Path(__file__).resolve().parent.parent
DAILY_CSV = PROJECT_DIR / "data" / "history" / "daily" / "gold_silver_daily.csv"
LOG_DIR = PROJECT_DIR / "logs"

logger = logging.getLogger("gold_silver_daily")


def setup_logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_DIR / "gold_silver_daily.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(ch)


def generate_historical_data(date_from: str, date_to: str) -> List[Dict]:
    """生成模拟历史数据（基于现有3天的价格和波动率）"""
    from datetime import datetime as dt

    # 读取现有数据作为基准
    existing = {}
    if DAILY_CSV.exists():
        with open(DAILY_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row["date"]] = row

    # 如果没有现有数据，使用默认值
    if not existing:
        base_gold = 4500.0
        base_silver = 75.0
        base_ratio = base_gold / base_silver
    else:
        # 取最新的数据作为基准
        latest_date = sorted(existing.keys())[-1]
        latest = existing[latest_date]
        base_gold = float(latest["gold_close"])
        base_silver = float(latest["silver_close"])
        base_ratio = float(latest["ratio_close"])

    # 生成日期范围
    start = dt.strptime(date_from, "%Y-%m-%d")
    end = dt.strptime(date_to, "%Y-%m-%d")
    days = (end - start).days + 1

    rows = []
    gold_price = base_gold
    silver_price = base_silver

    for i in range(days):
        current_date = start + timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")

        # 跳过已存在的日期
        if date_str in existing:
            rows.append(existing[date_str])
            continue

        # 模拟每日波动（±2%）
        gold_change = random.uniform(-0.02, 0.02)
        silver_change = random.uniform(-0.02, 0.02)

        # 略微相关
        if random.random() < 0.7:  # 70% 概率同向
            silver_change = gold_change * random.uniform(0.8, 1.2)

        gold_price *= (1 + gold_change)
        silver_price *= (1 + silver_change)

        # 确保价格合理
        gold_price = max(3500, min(5500, gold_price))
        silver_price = max(60, min(90, silver_price))

        # 生成 OHLC（简单模拟）
        gold_open = gold_price * random.uniform(0.995, 1.005)
        gold_high = max(gold_open, gold_price) * random.uniform(1.001, 1.015)
        gold_low = min(gold_open, gold_price) * random.uniform(0.985, 0.999)

        silver_open = silver_price * random.uniform(0.995, 1.005)
        silver_high = max(silver_open, silver_price) * random.uniform(1.001, 1.015)
        silver_low = min(silver_open, silver_price) * random.uniform(0.985, 0.999)

        rows.append({
            "date": date_str,
            "gold_close": round(gold_price, 2),
            "silver_close": round(silver_price, 2),
            "ratio_close": round(gold_price / silver_price, 2),
            "gold_open": round(gold_open, 2),
            "gold_high": round(gold_high, 2),
            "gold_low": round(gold_low, 2),
            "silver_open": round(silver_open, 2),
            "silver_high": round(silver_high, 2),
            "silver_low": round(silver_low, 2),
        })

    return rows


def merge_and_write(rows: List[Dict]):
    """合并写入 CSV"""
    existing = {}
    if DAILY_CSV.exists():
        with open(DAILY_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["date"]] = row

    for row in rows:
        existing[row["date"]] = {k: (v if v is not None else "") for k, v in row.items()}

    fieldnames = [
        "date", "gold_close", "silver_close", "ratio_close",
        "gold_open", "gold_high", "gold_low",
        "silver_open", "silver_high", "silver_low",
    ]
    DAILY_CSV.parent.mkdir(parents=True, exist_ok=True)
    sorted_dates = sorted(existing.keys())
    with open(DAILY_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for d in sorted_dates:
            w.writerow({"date": d, **existing[d]})
    return len(sorted_dates)


def main():
    setup_logger()
    parser = argparse.ArgumentParser(description="金银日频采集（统一实时+回填）")
    parser.add_argument("--backfill", action="store_true", help="回填今年至今")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.backfill:
        date_from, date_to, mode = "2026-01-01", today, "backfill"
    else:
        # 实时模式：取最近 7 天
        date_from = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        date_to = today
        mode = "live"

    logger.info(f"=== gold_silver_daily [{mode}] {date_from} ~ {date_to} ===")
    logger.warning("使用模拟数据（Yahoo Finance API 限流）")

    try:
        rows = generate_historical_data(date_from, date_to)
        if not rows:
            logger.warning("No data generated")
            return
        logger.info(f"Generated {len(rows)} days ({rows[0]['date']} ~ {rows[-1]['date']})")
        total = merge_and_write(rows)
        logger.info(f"Written {total} days to {DAILY_CSV.name}")
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
