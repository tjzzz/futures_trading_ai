#!/usr/bin/env python3
"""
金银现货采集器 — V1

从 gold-api.com 获取金银现货价格（免费层，无需 API Key）。
频率: 5分钟

输出到 dashboard_data.json 的 gold_price / silver_price / gold_silver_ratio 字段。
"""

import time
import requests
from collectors.base import BaseCollector


class GoldSpot(BaseCollector):
    """金银现货实时价格"""

    def __init__(self):
        super().__init__("spot_gold")
        self._max_retries = 3
        self._retry_delay = 2

    def collect(self) -> dict | None:
        self.logger.info(f"=== {self.name} start ===")
        errors = []
        xau_data = xag_data = None

        for attempt in range(self._max_retries):
            if xau_data is None:
                try:
                    r = requests.get("https://api.gold-api.com/price/XAU", timeout=10)
                    r.raise_for_status()
                    xau_data = r.json()
                    price = float(xau_data.get("price", 0))
                    if price <= 0:
                        self.logger.warning(f"XAU 价格无效: {price}")
                        xau_data = None
                except requests.exceptions.RequestException as e:
                    err = f"XAU (尝试 {attempt+1}): {e}"
                    errors.append(err)
                    self.logger.warning(err)

            if xag_data is None:
                try:
                    r = requests.get("https://api.gold-api.com/price/XAG", timeout=10)
                    r.raise_for_status()
                    xag_data = r.json()
                    price = float(xag_data.get("price", 0))
                    if price <= 0:
                        self.logger.warning(f"XAG 价格无效: {price}")
                        xag_data = None
                except requests.exceptions.RequestException as e:
                    err = f"XAG (尝试 {attempt+1}): {e}"
                    errors.append(err)
                    self.logger.warning(err)

            if xau_data and xag_data:
                break
            if attempt < self._max_retries - 1:
                time.sleep(self._retry_delay)

        # 至少需要一种金属的数据
        if not xau_data and not xag_data:
            for e in errors[-3:]:
                self.logger.error(f"  {e}")
            return None

        return self._parse({"xau": xau_data or {}, "xag": xag_data or {}})

    def _parse(self, raw: dict) -> dict:
        gold_usd = float(raw.get("xau", {}).get("price", 0))
        silver_usd = float(raw.get("xag", {}).get("price", 0))
        now = self._now()
        snapshot = {}

        if gold_usd > 0:
            snapshot["gold_price"] = {"value": round(gold_usd, 2), "unit": "USD/oz", "updated_at": now}
        if silver_usd > 0:
            snapshot["silver_price"] = {"value": round(silver_usd, 2), "unit": "USD/oz", "updated_at": now}
        if gold_usd > 0 and silver_usd > 0:
            ratio = round(gold_usd / silver_usd, 2)
            snapshot["gold_silver_ratio"] = {"value": ratio, "updated_at": now}

        if not snapshot:
            self.logger.error("金银价格均为零或空")
            return None

        return {"snapshot": snapshot}


def main():
    result = GoldSpot().collect()
    if result:
        print(f"gold={result['snapshot']['gold_price']['value']}, "
              f"silver={result['snapshot']['silver_price']['value']}, "
              f"ratio={result['snapshot']['gold_silver_ratio']['value']}")
    else:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()
