#!/usr/bin/env python3
"""
CBOE VIX 日频采集器 — V1

从 CBOE 下载 VIX 日频历史 CSV（延迟比 yfinance 实时数据稳定）。
输出到 dashboard_data.json 的 vix 字段（作为日频基准值，yfinance 提供日内值）。

频率: 每日1次
"""

import csv
import io

import requests
from collectors.base import BaseCollector

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


class CboeVix(BaseCollector):
    """CBOE VIX 日频"""

    def __init__(self):
        super().__init__("cboe_vix")

    def collect(self) -> dict | None:
        self.logger.info("=== cboe_vix start ===")
        try:
            r = requests.get(CBOE_VIX_URL, timeout=15)
            r.raise_for_status()
            return self._parse(r.text)
        except requests.RequestException as e:
            self.logger.error(f"CBOE VIX 请求失败: {e}")
            return None

    def _parse(self, raw: str) -> dict:
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            raise ValueError("VIX CSV 为空")

        latest = rows[-1]
        close = float(latest.get("CLOSE", 0))
        date_str = latest.get("DATE", "").strip()

        return {
            "snapshot": {
                "vix": {
                    "value": close,
                    "source": "cboe",
                    "as_of_date": date_str,
                    "updated_at": self._now(),
                    "freshness": "前一交易日",
                },
            },
            "history": [{
                "file": "data/history/daily/vix.csv",
                "row": {"date": date_str, "close": close},
                "grain": "daily",
            }],
        }


def main():
    result = CboeVix().collect()
    if result:
        v = result["snapshot"]["vix"]
        print(f"VIX={v['value']} (as of {v['as_of_date']})")
    else:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()
