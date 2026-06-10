#!/usr/bin/env python3
"""
国内期货数据采集器 — AKShare / 新浪免费接口

数据源: 新浪主力连续合约 (免费，无需 API Key)
覆盖: 沪金 (AU) / 沪银 (AG) — 日频 OHLC + 持仓量 + 结算价

用法:
    python -m collectors.futures_shfe              # 沪金 + 沪银
    python -m collectors.futures_shfe AU           # 仅沪金
    python -m collectors.futures_shfe AU AG SC     # 指定品种

依赖: pip install akshare
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from collectors.base import BaseCollector
from config import loader

logger = logging.getLogger("futures_shfe")
CST = timezone(timedelta(hours=8))
PROJECT_DIR = Path(__file__).resolve().parent.parent

# 当前关注的品种（后续从 indicator_source.json 扩展）
WATCH_SYMBOLS = ["AU", "AG"]  # 沪金、沪银

# 新浪主力连续合约代码映射（后续可从 loader 读取）
FUTURES_CODE = {
    "AU": "AU0",   # 沪金连续
    "AG": "AG0",   # 沪银连续
    "CU": "CU0",   # 沪铜连续
    "SC": "SC0",   # 原油连续
}

PRICE_MAP = {
    "AU": "shfe_gold",
    "AG": "shfe_silver",
    "CU": "shfe_copper",
}


class ChinaFuturesCollector(BaseCollector):
    """国内期货主力合约采集器 (AKShare / 新浪)"""

    def __init__(self):
        super().__init__("futures_shfe")
        self._ak = None
        try:
            import akshare as ak
            self._ak = ak
        except ImportError:
            logger.error("需要安装 akshare: pip install akshare")

    def fetch(self) -> dict:
        if not self._ak:
            raise RuntimeError("AKShare 未安装")
        result = {}
        for symbol in WATCH_SYMBOLS:
            code = FUTURES_CODE.get(symbol)
            if not code:
                self.logger.warning(f"未知品种: {symbol}")
                continue
            try:
                df = self._ak.futures_main_sina(symbol=code)
                if df is not None and len(df) > 0:
                    result[symbol] = df
                    self.logger.info(f"  {symbol} ({code}): {len(df)} 行")
                else:
                    self.logger.warning(f"  {symbol} ({code}): 无数据")
            except Exception as e:
                self.logger.error(f"  {symbol} 获取失败: {e}")
        return result

    def parse(self, raw: dict) -> dict:
        """解析新浪主力合约数据"""
        snapshot_updates = {}
        history_rows = []

        for symbol, df in raw.items():
            if df is None or df.empty:
                continue

            latest = df.iloc[-1]
            try:
                # 新浪 DataFrame 列: 日期, 开盘价, 最高价, 最低价, 收盘价, 成交量, 持仓量, 结算价, 涨跌幅
                record = {
                    "open": float(latest.get("开盘价", 0)),
                    "high": float(latest.get("最高价", 0)),
                    "low": float(latest.get("最低价", 0)),
                    "close": float(latest.get("收盘价", 0)),
                    "volume": int(latest.get("成交量", 0)),
                    "open_interest": int(latest.get("持仓量", 0)),
                    "settlement": float(latest.get("结算价", 0)),
                    "change_pct": float(latest.get("涨跌幅", 0)),
                    "date": str(latest.get("日期", "")),
                    "source": "akshare",
                    "updated_at": self._now(),
                }
            except (ValueError, TypeError) as e:
                self.logger.warning(f"{symbol} 解析失败: {e}")
                continue

            ind_id = PRICE_MAP.get(symbol)
            if ind_id and loader.get(ind_id):
                sk = loader.get(ind_id)["files"]["snapshot_key"]
                snapshot_updates[sk] = record
            else:
                # fallback: 用 symbol 做 key
                snapshot_updates[f"china_{symbol.lower()}"] = record

            # 历史行
            for _, row in df.iterrows():
                try:
                    date_str = str(row.get("日期", ""))[:10]
                    if not date_str:
                        continue
                    history_rows.append({
                        "date": date_str,
                        "symbol": symbol,
                        "open": float(row.get("开盘价", 0)),
                        "high": float(row.get("最高价", 0)),
                        "low": float(row.get("最低价", 0)),
                        "close": float(row.get("收盘价", 0)),
                        "volume": int(row.get("成交量", 0)),
                        "open_interest": int(row.get("持仓量", 0)),
                        "settlement": float(row.get("结算价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                    })
                except (ValueError, TypeError):
                    continue

        return {
            "snapshot_updates": snapshot_updates,
            "history_rows": history_rows,
        }

    def run(self):
        self.logger.info(f"=== {self.name} start ===")
        try:
            raw = self.fetch()
            if not raw:
                self.logger.warning("无数据")
                return True
            result = self.parse(raw)
        except RuntimeError as e:
            self.logger.error(f"采集失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"解析失败: {e}", exc_info=True)
            return False

        # ── 写入快照 ──
        snap_file = PROJECT_DIR / "data/current/dashboard_data.json"
        if result["snapshot_updates"]:
            data = {}
            if snap_file.exists():
                try:
                    data = json.loads(snap_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, IOError, OSError):
                    data = {}
            data.update(result["snapshot_updates"])
            data["global_updated_at"] = self._now()
            try:
                snap_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except (IOError, OSError) as e:
                self.logger.error(f"快照写入失败: {e}")

        # ── 写入历史 CSV（全量覆盖，新浪返回完整历史） ──
        if result["history_rows"]:
            csv_file = PROJECT_DIR / "data/history/daily" / "china_futures.csv"
            fieldnames = [
                "date", "symbol", "open", "high", "low", "close",
                "volume", "open_interest", "settlement", "change_pct",
            ]
            csv_file.parent.mkdir(parents=True, exist_ok=True)
            import csv
            with open(csv_file, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(result["history_rows"])
            self.logger.info(f"写入 {csv_file.name}: {len(result['history_rows'])} 行")

        self.logger.info(f"✅ {self.name} completed")
        return True

    # ── V1 接口 ──

    def v1_collect(self) -> dict | None:
        """V1 采集接口（被 collectors.run.py 调用）"""
        self.logger.info(f"=== {self.name} v1 start ===")

        # T-1 检查：数据已到前一日则跳过
        hist_file = "data/history/daily/china_futures.csv"
        if not self._needs_update(hist_file, max_stale_days=1):
            self.logger.info("  shfe: 数据已更新到 T-1，跳过")
            return None

        try:
            raw = self.fetch()
            if not raw:
                return None
            result = self.parse(raw)
        except Exception as e:
            self.logger.error(f"采集失败: {e}")
            return None

        snapshot = {}
        for sk, sv in result.get("snapshot_updates", {}).items():
            snapshot[sk] = sv

        history_rows = result.get("history_rows", [])
        if history_rows:
            self.logger.info(f"  shfe: 全量 {len(history_rows)} 行，覆盖写入")

        return {"snapshot": snapshot, "history": [{
            "file": hist_file, "row": r, "grain": "daily", "mode": "overwrite"
        } for r in history_rows]}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="国内期货数据采集")
    parser.add_argument("symbols", nargs="*", default=["AU", "AG"],
                        help="品种代码 (默认: AU AG)")
    args = parser.parse_args()
    global WATCH_SYMBOLS
    WATCH_SYMBOLS = args.symbols
    collector = ChinaFuturesCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
