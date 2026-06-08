#!/usr/bin/env python3
"""
GLD / SLV ETF 持仓量采集器 — 日频

从 Yahoo Finance 采集 GLD (SPDR Gold Trust) 和 SLV (iShares Silver Trust) ETF 的
持仓量/资产净值数据。输出到 dashboard_data.json 的 gld_holdings 和 slv_holdings 字段。

用法:
    python -m collectors.gld_slv                     # 采集并写入
    python -m collectors.gld_slv --pretty            # 带 stdout 输出

数据来源: Yahoo Finance (GLD / SLV)
频率: 日频（持仓数据通常在交易日结束后更新）
依赖: yfinance (已有)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf
from collectors.base_collector import BaseCollector, now_cst, PROJECT_ROOT

logger = logging.getLogger("gld_slv")
CST = timezone(timedelta(hours=8))

# GLD / SLV ETF 代码
GLD_SYMBOL = "GLD"
SLV_SYMBOL = "SLV"


class GldSlvCollector(BaseCollector):
    """
    GLD / SLV ETF 持仓量采集器。

    通过 yfinance 获取 GLD 和 SLV 的:
    - 最新净值 (NAV) / 收盘价
    - 交易量（作为持仓量变化的代理指标）
    - 日涨跌幅

    分别写入 dashboard_data.json 的 gld_holdings 和 slv_holdings 字段。
    """

    def __init__(self):
        super().__init__("gld_slv")

    def fetch(self) -> dict:
        """
        同时从 yfinance 获取 GLD 和 SLV 的近 5 天行情。

        Returns:
            {"GLD": DataFrame, "SLV": DataFrame, "_failed": [...]}

        Raises:
            RuntimeError: 两者都失败时抛出
        """
        results: dict = {}
        failed: list = []

        for symbol in [GLD_SYMBOL, SLV_SYMBOL]:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="5d", interval="1d")
                if df is not None and not df.empty:
                    results[symbol] = df
                    self.logger.info(f"  {symbol}: {len(df)} 行")
                else:
                    failed.append(symbol)
                    self.logger.warning(f"  {symbol}: 无数据")
            except Exception as e:
                failed.append(symbol)
                self.logger.warning(f"  {symbol} 获取失败: {e}")

        if not results:
            raise RuntimeError("GLD 和 SLV 请求均失败")

        results["_failed"] = failed
        return results

    def parse(self, raw_data: dict) -> dict:
        """
        解析 yfinance 返回的 DataFrame。

        Args:
            raw_data: {"GLD": DataFrame, "SLV": DataFrame, "_failed": [...]}

        Returns:
            遵循 BaseCollector.parse 接口格式
        """
        failed_symbols = raw_data.pop("_failed", [])
        now = self._now()

        extra_snapshots = []
        history_row = {}

        for symbol in [GLD_SYMBOL, SLV_SYMBOL]:
            df = raw_data.get(symbol)
            if df is None or df.empty:
                continue

            try:
                latest = df.iloc[-1]
                price = float(latest.get("Close") or latest.get("close", 0))
                volume = int(latest.get("Volume") or latest.get("volume", 0))

                # 昨日收盘价
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
                    "volume": volume,
                    "source": "yahoo_finance",
                    "updated_at": now,
                    "freshness": "日频",
                }

                if symbol == GLD_SYMBOL:
                    snapshot_key = "gld_holdings"
                else:
                    snapshot_key = "slv_holdings"

                extra_snapshots.append((snapshot_key, entry))
                history_row[f"{snapshot_key}_price"] = price
                history_row[f"{snapshot_key}_volume"] = volume

            except (KeyError, IndexError, ValueError, TypeError) as e:
                self.logger.warning(f"解析 {symbol} 失败: {e}")

        return {
            "snapshot_key": None,
            "snapshot_value": {},
            "extra_snapshots": extra_snapshots,
            "history_row": history_row,
            "grain": "daily",
        }

    def run(self):
        """
        主入口：采集 → 解析 → 写入 dashboard + 历史 CSV。
        """
        self.logger.info(f"=== {self.source_id} start ===")
        try:
            raw = self.fetch()
            result = self.parse(raw)
        except RuntimeError as e:
            self.logger.error(f"采集失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"解析失败: {e}", exc_info=True)
            return False

        extra = result.get("extra_snapshots", [])
        history_row = result.get("history_row", {})

        # 写入 dashboard 快照
        if extra:
            snap_file = PROJECT_ROOT / "data/current/dashboard_data.json"
            data = {}
            if snap_file.exists():
                try:
                    data = json.loads(snap_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, IOError, OSError):
                    data = {}
            for k, v in extra:
                data[k] = v
            data["global_updated_at"] = now_cst()
            try:
                snap_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except (IOError, OSError) as e:
                self.logger.error(f"快照写入失败: {e}")

        # 写入历史 CSV
        if history_row:
            csv_file = PROJECT_ROOT / "data/history/daily" / "gld_slv_holdings.csv"
            row = {"date": now_cst()[:10]}
            row.update(history_row)
            self.write_history_csv(csv_file, row)

        self.logger.info(f"✅ {self.source_id} completed")
        return True


def main():
    parser = argparse.ArgumentParser(description="GLD/SLV ETF 持仓量采集器")
    parser.add_argument("--pretty", action="store_true", help="输出格式化结果到 stdout")
    args = parser.parse_args()

    collector = GldSlvCollector()
    success = collector.run()

    if success and args.pretty:
        snap_file = PROJECT_ROOT / "data/current/dashboard_data.json"
        if snap_file.exists():
            data = json.loads(snap_file.read_text(encoding="utf-8"))
            result = {
                "gld_holdings": data.get("gld_holdings"),
                "slv_holdings": data.get("slv_holdings"),
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
