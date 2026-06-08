#!/usr/bin/env python3
"""
金银数据采集器 — 实时现货 + 日线 OHLC

- 实时 (spot):  金银现货价格 (gold-api.com, 5分钟)
- 日线 (daily): 金银日线 OHLC (Yahoo Finance GC=F / SI=F, 1天)

用法:
    python -m collectors.bullion spot              # 实时采集
    python -m collectors.bullion daily             # 今日日线
    python -m collectors.bullion daily --backfill  # 回填近1年历史日线
"""

import csv
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yfinance as yf
from collectors.base_collector import BaseCollector
from config import loader

logger = logging.getLogger("bullion")


# ====================================================================
#  实时现货 (gold-api.com, 5分钟)
# ====================================================================

class BullionSpot(BaseCollector):
    """金银现货实时价格"""

    def __init__(self):
        super().__init__("gold_silver")
        self._gold = loader.get("gold")
        self._silver = loader.get("silver")
        self._ratio = loader.get("ratio")

    def fetch(self):
        import time
        max_retries, retry_delay = 3, 2
        last_error = None
        for attempt in range(max_retries):
            try:
                xau = requests.get("https://api.gold-api.com/price/XAU", timeout=10)
                xau.raise_for_status()
                xag = requests.get("https://api.gold-api.com/price/XAG", timeout=10)
                xag.raise_for_status()
                return {"xau": xau.json(), "xag": xag.json()}
            except requests.exceptions.RequestException as e:
                last_error = f"网络异常 (尝试 {attempt+1}/{max_retries}): {e}"
                self.logger.warning(last_error)
            except Exception as e:
                last_error = f"未知错误 (尝试 {attempt+1}/{max_retries}): {e}"
                self.logger.error(last_error)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        raise RuntimeError(f"获取金银价格失败: {last_error}")

    def parse(self, raw):
        gold_usd = float(raw["xau"].get("price", 0))
        silver_usd = float(raw["xag"].get("price", 0))
        ratio = round(gold_usd / silver_usd, 2) if silver_usd else 0
        now = self._now()

        g_sk = self._gold["files"]["snapshot_key"]
        s_sk = self._silver["files"]["snapshot_key"]
        r_sk = self._ratio["files"]["snapshot_key"]
        g_f = self._gold["files"]["minutely"]["field"]
        s_f = self._silver["files"]["minutely"]["field"]
        r_f = self._ratio["files"]["minutely"]["field"]

        return {
            "snapshot_key": g_sk,
            "snapshot_value": {"value": round(gold_usd, 2), "unit": "USD/oz", "updated_at": now},
            "extra_snapshots": [
                (s_sk, {"value": round(silver_usd, 2), "unit": "USD/oz", "updated_at": now}),
                (r_sk, {"value": ratio, "updated_at": now}),
            ],
            "history_row": {g_f: round(gold_usd, 2), s_f: round(silver_usd, 2), r_f: ratio},
            "grain": "minutely",
        }


# ====================================================================
#  日线 OHLC (Yahoo Finance GC=F / SI=F 日频)
# ====================================================================

PROJECT_DIR = Path(__file__).resolve().parent.parent
DAILY_CSV = PROJECT_DIR / "data" / "history" / "daily" / "gold_silver_daily.csv"
CST = timezone(timedelta(hours=8))

DAILY_FIELDS = [
    "date", "gold_close", "silver_close", "ratio_close",
    "gold_open", "gold_high", "gold_low",
    "silver_open", "silver_high", "silver_low",
]


def _fetch_yahoo_daily(symbol: str, period_str: str = "1y") -> list:
    """从 yfinance 获取日线 OHLCV 数据"""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period_str, interval="1d")
    if df.empty:
        return []
    rows = []
    for date_idx, row in df.iterrows():
        rows.append({
            "date": date_idx.strftime("%Y-%m-%d"),
            "open": row["Open"], "high": row["High"],
            "low": row["Low"], "close": row["Close"],
        })
    return rows


def run_daily(backfill: bool = False):
    """从 Yahoo Finance 获取金银日线数据"""
    today = datetime.now(CST).strftime("%Y-%m-%d")
    range_str = "1y" if backfill else "5d"

    logger.info(f"=== bullion daily (Yahoo Finance) ===")
    try:
        gold_bars = _fetch_yahoo_daily("GC=F", range_str)
        silver_bars = _fetch_yahoo_daily("SI=F", range_str)
    except Exception as e:
        logger.error(f"Yahoo Finance 日线获取失败: {e}")
        return

    if not gold_bars or not silver_bars:
        logger.warning("未获取到日线数据")
        return

    # 合并金银数据为 gold_silver_daily.csv 格式
    gold_map = {b["date"]: b for b in gold_bars}
    silver_map = {b["date"]: b for b in silver_bars}
    all_dates = sorted(set(gold_map.keys()) & set(silver_map.keys()))

    if not all_dates:
        logger.warning("金银日期无交集，跳过")
        return

    # 读取已有数据
    existing = {}
    if DAILY_CSV.exists():
        with open(DAILY_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["date"]] = row

    # 合并新数据
    new_count = 0
    for d in all_dates:
        if d in existing:
            continue  # 跳过已存在的日期
        g, s = gold_map[d], silver_map[d]
        gold_close = round(g["close"], 2)
        silver_close = round(s["close"], 2)
        existing[d] = {
            "date": d,
            "gold_close": gold_close, "silver_close": silver_close,
            "ratio_close": round(gold_close / silver_close, 2) if silver_close else 0,
            "gold_open": round(g["open"], 2), "gold_high": round(g["high"], 2), "gold_low": round(g["low"], 2),
            "silver_open": round(s["open"], 2), "silver_high": round(s["high"], 2), "silver_low": round(s["low"], 2),
        }
        new_count += 1

    # 写入
    DAILY_CSV.parent.mkdir(parents=True, exist_ok=True)
    sorted_dates = sorted(existing.keys())
    with open(DAILY_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_FIELDS)
        w.writeheader()
        for d in sorted_dates:
            w.writerow(existing[d])

    logger.info(f"gold_silver_daily.csv: {len(sorted_dates)} 行 (新增 {new_count})")
    logger.info(f"  范围: {sorted_dates[0]} ~ {sorted_dates[-1]}")


# ====================================================================
#  CLI
# ====================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="金银数据采集器")
    parser.add_argument("mode", nargs="?", default="spot", choices=["spot", "daily"],
                        help="spot=实时采集(5分钟), daily=日线OHLC")
    parser.add_argument("--backfill", action="store_true", help="回填近1年日线历史")
    args = parser.parse_args()

    if args.mode == "spot":
        BullionSpot().run()
    elif args.mode == "daily":
        run_daily(backfill=args.backfill)


if __name__ == "__main__":
    main()
