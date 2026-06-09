#!/usr/bin/env python3
"""
美债收益率曲线采集器 — V1 日频

从 U.S. Treasury 官网下载每日收益率数据（T+1）。
输出到 dashboard_data.json 的 treasury / treasury_10y 字段。

频率: 每日1次
"""

import csv
import io

import requests
from collectors.base import BaseCollector

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/2026/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value=2026"
)


class Treasuries(BaseCollector):
    """美债收益率曲线"""

    def __init__(self):
        super().__init__("treasuries")

    def collect(self) -> dict | None:
        self.logger.info("=== treasuries start ===")
        try:
            r = requests.get(TREASURY_URL, timeout=15)
            r.encoding = "utf-8"
            r.raise_for_status()
            return self._parse(r.text)
        except requests.RequestException as e:
            self.logger.error(f"Treasury 请求失败: {e}")
            return None

    def _parse(self, raw: str) -> dict:
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows:
            raise ValueError("Treasury CSV 为空")
        latest = rows[0]
        now = self._now()

        csv_date = latest.get("Date", self._today())
        return {
            "snapshot": {
                "treasury": {
                    "10yr": float(latest.get("10 Yr", 0)),
                    "30yr": float(latest.get("30 Yr", 0)),
                    "2yr": float(latest.get("2 Yr", 0)),
                    "source": "ustreasury",
                    "as_of_date": csv_date,
                    "updated_at": now,
                    "freshness": "昨日数据",
                },
                "treasury_10y": {
                    "value": float(latest.get("10 Yr", 0)),
                    "change": None,  # 无昨日对比算不出日变化
                    "change_pct": None,
                    "prev_close": None,
                    "source": "ustreasury",
                    "updated_at": now,
                    "freshness": "昨日数据",
                },
            },
            "history": [{
                "file": "data/history/daily/treasury.csv",
                "row": {
                    "date": csv_date,
                    "10yr": float(latest.get("10 Yr", 0)),
                    "30yr": float(latest.get("30 Yr", 0)),
                    "2yr": float(latest.get("2 Yr", 0)),
                },
                "grain": "daily",
            }],
        }


def main():
    result = Treasuries().collect()
    if result:
        t = result["snapshot"]["treasury"]
        print(f"US10Y={t['10yr']}%, US30Y={t['30yr']}%, US2Y={t['2yr']}%")
    else:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()
