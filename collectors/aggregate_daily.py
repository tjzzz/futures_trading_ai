#!/usr/bin/env python3
"""
金银日频数据聚合 — 从 minutely CSV 聚合生成 daily CSV

用途：gold_silver_daily.csv 当前只有表头无数据，本脚本从
     data/history/minutely/gold_silver_minutely.csv 读取逐笔数据，
     按日期聚合为 OHLC 格式，写入 data/history/daily/gold_silver_daily.csv。

注：只追加不存在的日期行，不覆盖已有数据（避免重复）。
"""

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MINUTELY_PATH = PROJECT_ROOT / "data/history/minutely" / "gold_silver_minutely.csv"
DAILY_PATH = PROJECT_ROOT / "data/history/daily" / "gold_silver_daily.csv"


def read_minutely() -> list[dict]:
    """读取 minutely CSV"""
    if not MINUTELY_PATH.exists():
        print(f"[ERROR] minutely CSV not found: {MINUTELY_PATH}")
        return []
    with open(MINUTELY_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def aggregate_daily(rows: list[dict]) -> dict[str, dict]:
    """按日期聚合：取每日期初为开盘，期终为收盘，全天最高最低"""
    daily = {}
    for row in rows:
        ts = row.get("timestamp", "")
        date_key = ts[:10]
        try:
            gold = float(row["gold_usd"])
            silver = float(row["silver_usd"])
            ratio = float(row["ratio"])
        except (ValueError, KeyError, TypeError):
            continue

        if date_key not in daily:
            daily[date_key] = {
                "gold_open": gold, "gold_high": gold, "gold_low": gold, "gold_close": gold,
                "silver_open": silver, "silver_high": silver, "silver_low": silver, "silver_close": silver,
                "ratio_close": ratio,
            }
        else:
            d = daily[date_key]
            d["gold_high"] = max(d["gold_high"], gold)
            d["gold_low"] = min(d["gold_low"], gold)
            d["gold_close"] = gold
            d["silver_high"] = max(d["silver_high"], silver)
            d["silver_low"] = min(d["silver_low"], silver)
            d["silver_close"] = silver
            d["ratio_close"] = ratio

    return daily


def read_existing_dates() -> set[str]:
    """读取已有 daily CSV 中的日期集合"""
    if not DAILY_PATH.exists():
        return set()
    with open(DAILY_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row.get("date", "") for row in reader}


def write_daily(daily: dict[str, dict]):
    """全量重写 daily CSV（追加模式可能导致列不一致，故全量重写）"""
    fieldnames = [
        "date", "gold_close", "silver_close", "ratio_close",
        "gold_open", "gold_high", "gold_low",
        "silver_open", "silver_high", "silver_low",
    ]

    with open(DAILY_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in sorted(daily.keys()):
            row = {"date": d, **daily[d]}
            writer.writerow(row)

    print(f"[OK] 已重写 {len(daily)} 行到 {DAILY_PATH.name}")


def main():
    rows = read_minutely()
    if not rows:
        sys.exit(1)

    daily = aggregate_daily(rows)
    print(f"[INFO] minutely 数据: {len(rows)} 行 → {len(daily)} 天")

    write_daily(daily)

    # 验证
    print(f"\n--- 验证 gold_silver_daily.csv ---")
    with open(DAILY_PATH, "r") as f:
        for line in f:
            print(f"  {line.strip()}")


if __name__ == "__main__":
    main()
