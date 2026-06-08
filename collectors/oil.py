#!/usr/bin/env python3
"""
WTI 原油价格采集器 — 实时（同 macro collector 频率）

从 Yahoo Finance 采集 WTI 原油期货价格 (CL=F)。
输出到 dashboard_data.json 的 oil_wti 字段。
尽可能复用 macro.py 的模式（yfinance 实时采集）。

用法:
    python -m collectors.oil                # 采集并写入

依赖: yfinance (已有)
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf
from collectors.base_collector import BaseCollector, now_cst, PROJECT_ROOT

logger = logging.getLogger("oil")
CST = timezone(timedelta(hours=8))

# WTI 原油期货代码
WTI_SYMBOL = "CL=F"


class OilCollector(BaseCollector):
    """
    WTI 原油期货价格采集器。

    从 Yahoo Finance 采集 WTI 原油 (CL=F) 的实时价格、涨跌幅和交易量。
    数据写入 dashboard_data.json 的 oil_wti 字段，
    同时记录到 minutely 历史 CSV。
    """

    def __init__(self):
        super().__init__("oil")

    def fetch(self):
        """
        从 yfinance 获取 WTI 原油期货 2 日行情数据。

        Returns:
            pandas DataFrame 包含 OHLCV 数据

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            ticker = yf.Ticker(WTI_SYMBOL)
            df = ticker.history(period="2d", interval="1d")
            if df is None or df.empty:
                raise RuntimeError(f"{WTI_SYMBOL} 无数据返回")
            return df
        except Exception as e:
            raise RuntimeError(f"获取 WTI 原油 {WTI_SYMBOL} 失败: {e}")

    def parse(self, raw_data):
        """
        解析 yfinance 返回的 DataFrame。

        Args:
            raw_data: pandas DataFrame

        Returns:
            dict: {
                "snapshot_key": "oil_wti",
                "snapshot_value": {...},
                "extra_snapshots": [],
                "history_row": {...},
                "grain": "minutely"
            }
        """
        df = raw_data
        now = self._now()

        try:
            latest = df.iloc[-1]
            price = float(latest.get("Close") or latest.get("close", 0))
            volume = int(latest.get("Volume") or latest.get("volume", 0))

            # 昨日收盘
            if len(df) >= 2:
                prev_close = float(
                    df["Close"].iloc[-2] if "Close" in df
                    else df["close"].iloc[-2]
                )
            else:
                prev_close = price

            change = round(price - prev_close, 2) if prev_close else None
            change_pct = (
                round((change / prev_close) * 100, 2)
                if prev_close and prev_close != 0
                else None
            )

            entry = {
                "value": round(price, 2),
                "change": change,
                "change_pct": change_pct,
                "prev_close": round(prev_close, 2),
                "volume": volume,
                "source": "yahoo_finance",
                "updated_at": now,
                "freshness": "实时",
            }

            return {
                "snapshot_key": "oil_wti",
                "snapshot_value": entry,
                "extra_snapshots": [],
                "history_row": {
                    "oil_wti_price": price,
                    "oil_wti_volume": volume,
                },
                "grain": "minutely",
            }

        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise RuntimeError(f"解析 WTI 数据失败: {e}")

    def run(self):
        """
        主入口：采集 → 解析 → 写入 dashboard + 历史 CSV。

        遵循 base_collector.run() 的流程但做了精简，
        保持与 macro.py 一致的日志格式。
        """
        self.logger.info(f"=== {self.source_id} start ===")
        try:
            raw = self.fetch()
            result = self.parse(raw)
        except RuntimeError as e:
            self.logger.error(f"采集失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"解析失败: {e}")
            return False

        # 写入 dashboard 快照
        snapshot_key = result.get("snapshot_key")
        snapshot_value = result.get("snapshot_value", {})
        if snapshot_key and snapshot_value:
            self.write_snapshot({snapshot_key: snapshot_value})

        # 写入历史 CSV
        history_row = result.get("history_row", {})
        if history_row:
            csv_file = PROJECT_ROOT / "data/history/minutely" / "oil_minutely.csv"
            row = {"timestamp": now_cst()}
            row.update(history_row)
            self.write_history_csv(csv_file, row)

        self.logger.info(f"✅ {self.source_id} completed")
        return True


def main():
    collector = OilCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
