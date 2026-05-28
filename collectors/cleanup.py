#!/usr/bin/env python3
"""
数据清理脚本 — V2 整合版
每天凌晨执行
1. 从 minutely/gold_silver_minutely.csv 删除7天前的数据
2. 将当日数据聚合写入 daily/gold_silver_daily.csv

源自 workspace-trade-ai/collectors/cleanup.py
V2 变更：路径从 config 解析
"""

import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CST = timezone(timedelta(hours=8))

MINUTELY_CSV = PROJECT_ROOT / "data/history/minutely/gold_silver_minutely.csv"
DAILY_CSV = PROJECT_ROOT / "data/history/daily/gold_silver_daily.csv"


def now_cst():
    return datetime.now(CST)


def today_str():
    return now_cst().strftime("%Y-%m-%d")


def cleanup():
    today = today_str()
    cutoff = (now_cst() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    if not MINUTELY_CSV.exists():
        print(f"⚠️ {MINUTELY_CSV} not found")
        return

    # 读取所有行
    with open(MINUTELY_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("⚠️ No minutely data")
        return

    fieldnames = reader.fieldnames or ["timestamp", "gold_usd", "silver_usd", "ratio"]

    # 分两组：保留的和今日的
    keep_rows = []
    today_rows = []
    for row in rows:
        ts = row.get("timestamp", "")
        if ts < cutoff:
            continue  # 丢弃
        keep_rows.append(row)
        if ts.startswith(today):
            today_rows.append(row)

    # 写回minutely（仅保留7天内）
    with open(MINUTELY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(keep_rows)

    before_count = len(rows)
    deleted = before_count - len(keep_rows)
    print(f"✅ Minutely cleanup: {before_count} → {len(keep_rows)} rows (deleted {deleted})")

    # 聚合今日数据写入daily
    if today_rows:
        gold_values = [float(r["gold_usd"]) for r in today_rows if r.get("gold_usd")]
        silver_values = [float(r["silver_usd"]) for r in today_rows if r.get("silver_usd")]
        ratios = [float(r["ratio"]) for r in today_rows if r.get("ratio")]

        if gold_values:
            daily_row = {
                "date": today,
                "gold_close": round(gold_values[-1], 2),
                "silver_close": round(silver_values[-1], 2),
                "ratio_close": round(ratios[-1], 2) if ratios else 0,
                "gold_open": round(gold_values[0], 2),
                "gold_high": round(max(gold_values), 2),
                "gold_low": round(min(gold_values), 2),
                "silver_open": round(silver_values[0], 2),
                "silver_high": round(max(silver_values), 2),
                "silver_low": round(min(silver_values), 2),
            }

            # 检查是否已经写入过当日数据
            already_exists = False
            if DAILY_CSV.exists():
                with open(DAILY_CSV, "r", encoding="utf-8") as f:
                    existing = list(csv.DictReader(f))
                    for row in existing:
                        if row.get("date") == today:
                            already_exists = True
                            break

            if not already_exists:
                exists = DAILY_CSV.exists()
                with open(DAILY_CSV, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=list(daily_row.keys()))
                    if not exists:
                        writer.writeheader()
                    writer.writerow(daily_row)
                print(f"✅ Daily aggregated: {today} close={daily_row['gold_close']}")
            else:
                print(f"ℹ️ Daily data for {today} already exists, skipped")


if __name__ == "__main__":
    cleanup()
