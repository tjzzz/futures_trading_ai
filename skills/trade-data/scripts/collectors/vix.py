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
        super().__init__("vix")

    def collect(self) -> dict | None:
        self.logger.info(f"=== {self.name} start ===")

        # T-1 检查
        hist_file = "data/history/daily/vix.csv"
        if not self._needs_update(hist_file, max_stale_days=1):
            self.logger.info("  vix: 数据已更新到 T-1，跳过")
            return None

        try:
            r = requests.get(CBOE_VIX_URL, timeout=15)
            r.raise_for_status()
            return self._parse(r.text, hist_file)
        except requests.RequestException as e:
            self.logger.error(f"CBOE VIX 请求失败: {e}")
            return None

    def _parse(self, raw: str, hist_file: str) -> dict:
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            raise ValueError("VIX CSV 为空")

        # 组装所有行为 dict 列表
        all_rows = []
        for r in rows:
            d = r.get("DATE", "").strip()
            if not d:
                continue
            try:
                all_rows.append({"date": d, "close": float(r.get("CLOSE", 0))})
            except (ValueError, TypeError):
                continue

        if not all_rows:
            raise ValueError("VIX 无有效行")

        latest = all_rows[-1]
        self.logger.info(f"  vix: 全量 {len(all_rows)} 行，覆盖写入")

        return {
            "snapshot": {
                "vix": {
                    "value": float(latest["close"]),
                    "source": "cboe",
                    "as_of_date": latest["date"],
                    "updated_at": self._now(),
                    "freshness": "前一交易日",
                },
            },
            "history": [{
                "file": hist_file, "row": r, "grain": "daily", "mode": "overwrite",
            } for r in all_rows],
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
