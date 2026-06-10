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
        super().__init__("treasury")

    def collect(self) -> dict | None:
        self.logger.info(f"=== {self.name} start ===")

        # T-1 检查
        hist_file = "data/history/daily/treasury.csv"
        if not self._needs_update(hist_file, max_stale_days=1):
            self.logger.info("  treasury: 数据已更新到 T-1，跳过")
            return None

        try:
            r = requests.get(TREASURY_URL, timeout=15)
            r.encoding = "utf-8"
            r.raise_for_status()
            return self._parse(r.text, hist_file)
        except requests.RequestException as e:
            self.logger.error(f"Treasury 请求失败: {e}")
            return None

    def _parse(self, raw: str, hist_file: str) -> dict:
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows:
            raise ValueError("Treasury CSV 为空")
        # Treasury CSV 最新在前，反转成按日期升序
        rows.reverse()
        now = self._now()

        # 取最新一条做 snapshot
        latest = rows[-1]
        csv_date = latest.get("Date", self._today())

        # 组装所有行为 dict 列表
        all_rows = []
        for r in rows:
            d = r.get("Date", "").strip()
            if not d:
                continue
            try:
                all_rows.append({
                    "date": d,
                    "10yr": float(r.get("10 Yr", 0)),
                    "30yr": float(r.get("30 Yr", 0)),
                    "2yr": float(r.get("2 Yr", 0)),
                })
            except (ValueError, TypeError):
                continue

        self.logger.info(f"  treasury: 全量 {len(all_rows)} 行，覆盖写入")

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
                    "change": None,
                    "change_pct": None,
                    "prev_close": None,
                    "source": "ustreasury",
                    "updated_at": now,
                    "freshness": "昨日数据",
                },
            },
            "history": [{
                "file": hist_file, "row": r, "grain": "daily", "mode": "overwrite",
            } for r in all_rows],
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
