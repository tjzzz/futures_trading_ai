#!/usr/bin/env python3
"""
2026年历史数据回填脚本 — V2 整合版
一次性拉取2026年度各日频指标的完整历史数据，写入 daily/*.csv
覆盖：Treasury / TIPS / DXY / SP500 / VIX

源自 workspace-trade-ai/collectors/backfill_2026.py
V2 变更：路径从 config 解析
"""

import csv
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data/history/daily"
CST = timezone(timedelta(hours=8))

# ---------- 数据源URL ----------
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/2026/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value=2026"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def write_csv(filepath, fieldnames, rows):
    """覆盖写入CSV。如果rows为空则跳过。"""
    if not rows:
        print(f"  ⚠️ No data to write for {filepath.name}, skipped")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✅ Wrote {len(rows)} rows to {filepath.name}")


# ========== 1. Treasury ==========
def backfill_treasury():
    print("\n=== Treasury ===")
    print(f"  Downloading from Treasury API...")
    r = requests.get(TREASURY_URL, timeout=30)
    r.encoding = "utf-8"
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    if not rows:
        print("  ⚠️ Empty response")
        return

    # Treasury CSV：第一行是最新，最后行是最旧
    # 日期格式 MM/DD/YYYY，需转为 YYYY-MM-DD
    rows.reverse()

    result = []
    for row in rows:
        raw_date = row.get("Date", "")
        try:
            date_str = datetime.strptime(raw_date.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if date_str >= "2026-01-01" and date_str <= "2026-12-31":
            try:
                result.append({
                    "date": date_str,
                    "10yr": float(row.get("10 Yr", "") or 0),
                    "30yr": float(row.get("30 Yr", "") or 0),
                    "2yr": float(row.get("2 Yr", "") or 0),
                })
            except (ValueError, TypeError):
                continue

    write_csv(DATA_DIR / "treasury.csv", ["date", "10yr", "30yr", "2yr"], result)
    if result:
        print(f"  Treasury: {len(result)} daily records (from {result[0]['date']} to {result[-1]['date']})")


# ========== 2. FRED Series ==========
FRED_SERIES = {
    "tips": {"id": "DFII10", "name": "TIPS 10Y", "header": "value"},
    "dxy": {"id": "DTWEXBGS", "name": "DXY USD Index", "header": "value"},
    "sp500": {"id": "SP500", "name": "S&P 500", "header": "value"},
}


def backfill_fred(series_key: str):
    info = FRED_SERIES[series_key]
    print(f"\n=== {info['name']} ({series_key}) ===")
    url = FRED_URL.format(series_id=info["id"], start="2026-01-01", end="2026-12-31")
    print(f"  Downloading from FRED...")
    r = requests.get(url, timeout=30)
    lines = r.text.strip().split("\n")

    if len(lines) < 2:
        print("  ⚠️ Empty response")
        return

    # FRED CSV: 第一行 header, 之后每行 DATE,VALUE ; 最新在最后一行
    result = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date_str = parts[0].strip()
        try:
            val = float(parts[1].strip())
        except (ValueError, TypeError):
            continue
        # 只取2026年
        if date_str.startswith("2026"):
            result.append({"date": date_str, "value": val})

    # 按日期正序
    result.sort(key=lambda r: r["date"])

    write_csv(DATA_DIR / f"{series_key}.csv", ["date", "value"], result)
    if result:
        print(f"  {info['name']}: {len(result)} records ({result[0]['date']} ~ {result[-1]['date']})")


# ========== 3. VIX ==========
def backfill_vix():
    print("\n=== VIX ===")
    print(f"  Downloading from CBOE...")
    r = requests.get(CBOE_VIX_URL, timeout=30)
    lines = r.text.strip().split("\n")

    if len(lines) < 2:
        print("  ⚠️ Empty response")
        return

    # CBOE VIX CSV header: DATE,OPEN,HIGH,LOW,CLOSE
    result = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 5:
            continue
        date_str = parts[0].strip()
        if "2026" in date_str:
            try:
                close = float(parts[4].strip())
                result.append({"date": date_str, "close": close})
            except (ValueError, TypeError):
                continue

    result.sort(key=lambda r: r["date"])

    write_csv(DATA_DIR / "vix.csv", ["date", "close"], result)
    if result:
        print(f"  VIX: {len(result)} records ({result[0]['date']} ~ {result[-1]['date']})")


# ========== Main ==========
def main():
    print("=" * 50)
    print("  2026 Historical Daily Data Backfill")
    print(f"  Started at: {now_str()}")
    print("=" * 50)

    errors = []

    try:
        backfill_treasury()
    except Exception as e:
        errors.append(("treasury", str(e)))

    for sk in ["tips", "dxy", "sp500"]:
        try:
            backfill_fred(sk)
        except Exception as e:
            errors.append((sk, str(e)))

    try:
        backfill_vix()
    except Exception as e:
        errors.append(("vix", str(e)))

    print("\n" + "=" * 50)
    print("  Summary")
    print("=" * 50)
    if errors:
        print("  Errors:")
        for name, err in errors:
            print(f"    ❌ {name}: {err}")
    else:
        print("  ✅ All backfills completed successfully!")
    print(f"  Finished at: {now_str()}")


if __name__ == "__main__":
    main()
