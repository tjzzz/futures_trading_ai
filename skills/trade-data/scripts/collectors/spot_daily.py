#!/usr/bin/env python3
"""
金银现货日频采集器 — V1

通过 Yahoo v8 chart API 获取 GLD / SLV ETF 的日频 OHLC 数据，
换算为现货金银价格（GLD × 10 → 黄金 USD/oz，SLV → 白银 USD/oz），
写入 gold_silver_daily.csv，覆盖已存在的模拟数据。

ETF 跟踪误差极小（GLD 持仓实物黄金 ~0.1%/年），对宏观分析而言可忽略。
回填模式使用 6mo 范围（覆盖 2025-12 至今），增量模式使用 1mo。

用法:
  python -m collectors.spot_daily              # 增量更新（最近 30 天）
  python -m collectors.spot_daily --backfill   # 回填 2025-12 至今
"""

import argparse
import csv
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

from collectors.base import BaseCollector

# ── 常量 ──
PROJECT_DIR = Path(__file__).resolve().parents[4]
DAILY_CSV = PROJECT_DIR / "data" / "history" / "daily" / "gold_silver_daily.csv"
API_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}

SYMBOLS = {"gold": "GLD", "silver": "SLV"}  # GLD × 10 ≈ 黄金现货 USD/oz, SLV ≈ 白银 USD/oz
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds

FIELD_NAMES = [
    "date", "gold_close", "silver_close", "ratio_close",
    "gold_open", "gold_high", "gold_low",
    "silver_open", "silver_high", "silver_low",
]

CST = timezone(timedelta(hours=8))


def _parse_timestamp(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class SpotDailyCollector(BaseCollector):
    """金银现货日频采集器"""

    def __init__(self):
        super().__init__("spot_daily")
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def collect(self, backfill: bool = False) -> Optional[dict]:
        self.logger.info(f"=== spot_daily {'backfill' if backfill else 'incremental'} ===")

        range_param = "6mo" if backfill else "1mo"
        raw_data = {}

        for i, (metal, symbol) in enumerate(SYMBOLS.items()):
            if i > 0:
                time.sleep(8)  # 两个 symbol 之间间隔，避免 429

            rows = self._fetch_daily(symbol, range_param)
            if not rows:
                self.logger.warning(f"{symbol}({metal}): 无数据")
                continue
            self.logger.info(f"  {symbol}({metal}): {len(rows)} 天 "
                             f"({rows[0]['date']} ~ {rows[-1]['date']})")
            for row in rows:
                date_str = row["date"]
                if date_str not in raw_data:
                    raw_data[date_str] = {"date": date_str}
                multiplier = 10.0 if metal == "gold" else 1.0
                for field in ["open", "high", "low", "close"]:
                    raw_data[date_str][f"{metal}_{field}"] = round(
                        row[field] * multiplier, 2
                    )

        if not raw_data:
            self.logger.error("全部获取失败")
            return None

        # 计算金银比
        rows_out = []
        for date_str in sorted(raw_data.keys()):
            r = raw_data[date_str]
            gc = r.get("gold_close")
            sc = r.get("silver_close")
            r["ratio_close"] = round(gc / sc, 2) if gc and sc else None
            rows_out.append(r)

        merged = self._merge_write(rows_out)
        self.logger.info(f"✅ 写入完成: {merged} 天")
        return {"snapshot": {}, "history": []}

    def _fetch_daily(self, symbol: str, range_param: str) -> list[dict]:
        """从 Yahoo v8 API 获取日频 OHLC，带重试和退避"""
        url = API_BASE.format(symbol=symbol)
        params = {"range": range_param, "interval": "1d", "includePrePost": "false"}

        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self._session.get(url, params=params, timeout=30)
                if r.status_code == 429:
                    wait = RETRY_DELAY * (attempt + 1)
                    self.logger.warning(f"{symbol}: 429, 等待 {wait}s ({attempt+1}/{MAX_RETRIES})")
                    time.sleep(wait)
                    self._session = requests.Session()  # 新连接，避免连接池复用
                    self._session.headers.update(HEADERS)
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except requests.exceptions.ConnectionError as e:
                last_err = e
                wait = RETRY_DELAY * (attempt + 1) * 2
                self.logger.warning(f"{symbol}: 连接错误, 等待 {wait}s ({attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
                self._session = requests.Session()
                self._session.headers.update(HEADERS)
                continue
            except Exception as e:
                last_err = e
                self.logger.warning(f"{symbol}: {e} ({attempt+1}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)
                continue
        else:
            self.logger.error(f"{symbol}: 超过最大重试次数: {last_err}")
            return []

        result = data.get("chart", {}).get("result")
        if not result:
            self.logger.warning(f"{symbol}: result 为空")
            return []

        timestamps = result[0].get("timestamp", [])
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        if not timestamps or not quotes:
            return []

        rows = []
        for i, ts in enumerate(timestamps):
            close = quotes.get("close", [None] * len(timestamps))[i]
            if close is None:
                continue
            rows.append({
                "date": _parse_timestamp(ts),
                "open": float(quotes.get("open", [0])[i] or 0),
                "high": float(quotes.get("high", [0])[i] or 0),
                "low": float(quotes.get("low", [0])[i] or 0),
                "close": float(close),
            })

        return rows

    def _merge_write(self, new_rows: list[dict]) -> int:
        """合并新数据到 CSV（保留已有、覆盖同日期）"""
        existing = {}
        if DAILY_CSV.exists():
            with open(DAILY_CSV, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    existing[row["date"]] = row

        for row in new_rows:
            existing[row["date"]] = {
                "date": row["date"],
                "gold_close": f'{row.get("gold_close", ""):.2f}' if row.get("gold_close") else "",
                "silver_close": f'{row.get("silver_close", ""):.2f}' if row.get("silver_close") else "",
                "ratio_close": f'{row.get("ratio_close", ""):.2f}' if row.get("ratio_close") else "",
                "gold_open": f'{row.get("gold_open", ""):.2f}' if row.get("gold_open") else "",
                "gold_high": f'{row.get("gold_high", ""):.2f}' if row.get("gold_high") else "",
                "gold_low": f'{row.get("gold_low", ""):.2f}' if row.get("gold_low") else "",
                "silver_open": f'{row.get("silver_open", ""):.2f}' if row.get("silver_open") else "",
                "silver_high": f'{row.get("silver_high", ""):.2f}' if row.get("silver_high") else "",
                "silver_low": f'{row.get("silver_low", ""):.2f}' if row.get("silver_low") else "",
            }

        DAILY_CSV.parent.mkdir(parents=True, exist_ok=True)
        sorted_dates = sorted(existing.keys())
        with open(DAILY_CSV, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELD_NAMES)
            w.writeheader()
            for d in sorted_dates:
                w.writerow({"date": d, **existing[d]})
        return len(sorted_dates)


def main():
    parser = argparse.ArgumentParser(description="金银现货日频采集器")
    parser.add_argument("--backfill", action="store_true", help="回填 2025-12 至今")
    args = parser.parse_args()

    collector = SpotDailyCollector()
    result = collector.collect(backfill=args.backfill)
    if result is None:
        import sys
        sys.exit(1)
    print("✅ spot_daily 完成")


if __name__ == "__main__":
    main()