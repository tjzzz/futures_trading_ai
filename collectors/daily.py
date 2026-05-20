#!/usr/bin/env python3
"""
日频采集器 — V2 整合版
- 美债收益率曲线（10Y/30Y/2Y）：U.S. Treasury CSV
- 实际利率 TIPS / DXY 美元指数 / S&P 500：FRED CSV
- VIX 恐慌指数：CBOE

源自 workspace-trade-ai/collectors/daily_collector.py
V2 变更：导入路径适配 package 结构
"""

import csv
import io
import logging
import sys
from datetime import datetime, timezone, timedelta

import requests
from collectors.base_collector import BaseCollector

logger = logging.getLogger("daily")


TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/2026/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value=2026"
)

# FRED系列：以CSV形式获取，无需API Key
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"

CST = timezone(timedelta(hours=8))


class TreasuryCollector(BaseCollector):
    """美债收益率曲线"""

    def __init__(self):
        super().__init__("treasury")

    def fetch(self):
        r = requests.get(TREASURY_URL, timeout=15)
        r.encoding = "utf-8"
        return r.text

    def parse(self, raw):
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            raise ValueError("Empty treasury CSV")

        # CSV第一行是最新数据
        latest = rows[0]

        return {
            "snapshot_key": "treasury",
            "snapshot_value": {
                "10yr": float(latest.get("10 Yr", 0)),
                "30yr": float(latest.get("30 Yr", 0)),
                "2yr": float(latest.get("2 Yr", 0)),
                "source": "ustreasury",
                "as_of_date": latest.get("Date", ""),
                "updated_at": self._now(),
                "freshness": "昨日数据",
            },
            "history_row": {
                "10yr": float(latest.get("10 Yr", 0)),
                "30yr": float(latest.get("30 Yr", 0)),
                "2yr": float(latest.get("2 Yr", 0)),
            },
            "grain": "daily",
        }


class FREDCollector(BaseCollector):
    """FRED系列指标：TIPS / DXY / SP500"""

    SERIES_MAP = {
        "tips": {"id": "DFII10", "name": "10-Year TIPS", "snapshot_key": "tips_10y", "source_id": "tips"},
        "dxy": {"id": "DTWEXBGS", "name": "USD Index", "snapshot_key": "dxy", "source_id": "dxy"},
        "sp500": {"id": "SP500", "name": "S&P 500", "snapshot_key": "sp500", "source_id": "sp500"},
    }

    def __init__(self, series_key: str):
        if series_key not in self.SERIES_MAP:
            raise ValueError(f"Unknown series: {series_key}, choices: {list(self.SERIES_MAP.keys())}")
        self.series_key = series_key
        self.series_info = self.SERIES_MAP[series_key]
        super().__init__(self.series_info["source_id"])

    def fetch(self):
        series_id = self.series_info["id"]
        url = FRED_URL.format(series_id=series_id, start="2026-01-01", end="2026-12-31")
        r = requests.get(url, timeout=15)
        return r.text

    def parse(self, raw):
        lines = raw.strip().split("\n")
        if len(lines) < 2:
            raise ValueError(f"Empty FRED CSV for {self.series_key}")

        # 最后一行是最新数据
        last_line = lines[-1]
        parts = last_line.split(",")
        if len(parts) < 2:
            raise ValueError(f"Bad format: {last_line}")
        as_of_date = parts[0].strip()
        value = float(parts[1].strip())

        freshness_map = {
            "tips": "延迟2天",
            "dxy": "延迟1~5天",
            "sp500": "延迟1天",
        }

        return {
            "snapshot_key": self.series_info["snapshot_key"],
            "snapshot_value": {
                "value": value,
                "source": "fred",
                "as_of_date": as_of_date,
                "updated_at": self._now(),
                "freshness": freshness_map.get(self.series_key, ""),
            },
            "history_row": {
                "value": value,
            },
            "grain": "daily",
        }


class VIXCollector(BaseCollector):
    """CBOE VIX 恐慌指数"""

    def __init__(self):
        super().__init__("vix")

    def fetch(self):
        r = requests.get(CBOE_VIX_URL, timeout=15)
        return r.text

    def parse(self, raw):
        lines = raw.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("Empty VIX CSV")

        # 跳过表头，取最后一行（最新收盘）
        last_line = lines[-1]
        parts = last_line.split(",")
        if len(parts) < 5:
            raise ValueError(f"Bad VIX line: {last_line}")
        date_str = parts[0].strip()
        close = float(parts[4].strip())

        return {
            "snapshot_key": "vix",
            "snapshot_value": {
                "value": close,
                "source": "cboe",
                "as_of_date": date_str,
                "updated_at": self._now(),
                "freshness": "前一交易日",
            },
            "history_row": {
                "close": close,
            },
            "grain": "daily",
        }


# ---- 批量运行入口 ----
def run_all_daily():
    collectors = [
        TreasuryCollector(),
        FREDCollector("tips"),
        FREDCollector("dxy"),
        FREDCollector("sp500"),
        VIXCollector(),
    ]
    results = {}
    for c in collectors:
        ok = c.run()
        results[c.source_id] = "✅" if ok else "❌"
    logger.info("\n=== Daily Collectors Summary ===")
    for name, status in results.items():
        logger.info("  %s: %s", name, status)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "all":
            run_all_daily()
        elif arg in ("treasury", "tips", "dxy", "sp500", "vix"):
            cls_map = {
                "treasury": TreasuryCollector,
                "tips": lambda: FREDCollector("tips"),
                "dxy": lambda: FREDCollector("dxy"),
                "sp500": lambda: FREDCollector("sp500"),
                "vix": VIXCollector,
            }
            cls_map[arg]().run()
        else:
            logger.warning("Unknown collector: %s", arg)
    else:
        run_all_daily()
