#!/usr/bin/env python3
"""
宏观指标采集器 — 实时市场 + 日频基本面

- 市场 (market): DXY / US10Y / VIX / 黄金期货 / 白银期货 (Yahoo Finance, 5分钟)
- 日频 (daily): 美债收益率 / TIPS / DXY / SP500 / VIX (Treasury/FRED/CBOE, 每日)

用法:
    python -m collectors.macro market              # 仅实时市场
    python -m collectors.macro daily               # 全部日频
    python -m collectors.macro daily treasury      # 日频子项
    python -m collectors.macro all                 # 全部

指标定义见 config/indicator_source.json，符号映射和系列 ID 从 loader 动态读取。
"""

import csv
import io
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from collectors.base_collector import BaseCollector, now_cst, PROJECT_ROOT
from config import loader

logger = logging.getLogger("macro")
CST = timezone(timedelta(hours=8))


# ====================================================================
#  实时市场 (Yahoo Finance via yfinance)
# ====================================================================

import yfinance as yf


class MacroMarket(BaseCollector):
    """宏观市场实时行情 (Yahoo Finance)"""

    def __init__(self):
        super().__init__("yahoo_finance")  # 保持 source_id 不变，兼容现有 CSV

        self._indicator_ids = ["dxy", "treasury_10y", "vix", "gold_futures", "silver_futures"]
        self._symbols = {iid: loader.get(iid)["yahoo_symbol"] for iid in self._indicator_ids}
        self._snapshot_keys = {iid: loader.get(iid)["files"]["snapshot_key"] for iid in self._indicator_ids}
        self._futures = [iid for iid in self._indicator_ids if "futures" in iid]

    def fetch(self):
        results, failed = {}, []
        for iid, symbol in self._symbols.items():
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="2d", interval="1d")
                if df is not None and not df.empty:
                    results[iid] = df
                else:
                    failed.append(iid)
            except Exception as e:
                failed.append(iid)
                self.logger.warning(f"{iid} ({symbol}) fetch failed: {e}")
        if not results:
            raise RuntimeError("所有 Yahoo Finance 请求均失败")
        results["_failed"] = failed
        return results

    def parse(self, raw_data):
        failed_symbols = raw_data.pop("_failed", [])
        snapshot_values, history_row = {}, {}
        now_ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

        for iid in self._indicator_ids:
            df = raw_data.get(iid)
            if df is None or df.empty:
                continue
            try:
                latest = df.iloc[-1]
                price = latest.get("Close") or latest.get("close")
                volume = latest.get("Volume") or latest.get("volume", 0)

                # 昨日收盘价 = 前一交易日的最后一根 Close
                if len(df) >= 2:
                    prev_close = df["Close"].iloc[-2] if "Close" in df else df["close"].iloc[-2]
                else:
                    prev_close = price

                if price is not None:
                    change = price - prev_close if prev_close else None
                    change_pct = (change / prev_close * 100) if prev_close and prev_close != 0 else None
                    entry = {
                        "value": round(price, 4) if price else None,
                        "change": round(change, 4) if change is not None else None,
                        "change_pct": round(change_pct, 2) if change_pct is not None else None,
                        "prev_close": round(prev_close, 4) if prev_close else None,
                        "source": "yahoo_finance", "updated_at": now_ts, "freshness": "实时",
                    }
                    if iid in self._futures and volume:
                        entry["volume"] = int(volume)
                    snapshot_values[iid] = entry
                    history_row[f"{iid}_price"] = price
                    if volume:
                        history_row[f"{iid}_volume"] = int(volume)
            except Exception as e:
                self.logger.warning(f"解析 {iid} 失败: {e}")

        extra = [(self._snapshot_keys.get(k, k), v) for k, v in snapshot_values.items()]
        return {"snapshot_key": None, "snapshot_value": {}, "extra_snapshots": extra,
                "history_row": history_row, "grain": "minutely"}

    def run(self):
        self.logger.info(f"=== {self.source_id} start ===")
        try:
            raw = self.fetch()
            result = self.parse(raw)
        except requests.RequestException as e:
            self.logger.error(f"网络请求失败: {e}"); return False
        except (KeyError, ValueError, TypeError) as e:
            self.logger.error(f"数据解析失败: {e}"); return False
        except RuntimeError as e:
            self.logger.error(f"采集失败: {e}"); return False

        extra = result.get("extra_snapshots", [])
        history_row = result.get("history_row", {})

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
                snap_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except (IOError, OSError) as e:
                self.logger.error(f"Snapshot write failed: {e}")

        if history_row:
            # 原始 CSV
            csv_file = PROJECT_ROOT / f"data/history/minutely/{self.source_id}_minutely.csv"
            row = {"timestamp": now_cst()}
            for iid in self._indicator_ids:
                v = history_row.get(f"{iid}_price") or history_row.get(iid)
                if v is not None:
                    row[iid] = v
            self.write_history_csv(csv_file, row)

            # 扩展 CSV（含交易量）
            ext_file = PROJECT_ROOT / f"data/history/minutely/{self.source_id}_extended_minutely.csv"
            ext_row = {"timestamp": now_cst()}
            for iid in self._indicator_ids:
                ext_row[f"{iid}_price"] = history_row.get(f"{iid}_price")
                if iid in self._futures:
                    vv = history_row.get(f"{iid}_volume")
                    if vv is not None:
                        ext_row[f"{iid}_volume"] = vv
            self.write_history_csv(ext_file, ext_row)

            # 统一金银数据文件
            gold_p = history_row.get("gold_futures_price") or history_row.get("gold_futures")
            silv_p = history_row.get("silver_futures_price") or history_row.get("silver_futures")
            unified = {
                "timestamp": now_cst()[:16] + ":00",
                "gold_usd": gold_p, "silver_usd": silv_p,
                "gold_volume": history_row.get("gold_futures_volume"),
                "silver_volume": history_row.get("silver_futures_volume"),
                "ratio": (gold_p / silv_p) if gold_p and silv_p and silv_p != 0 else None,
            }
            self.write_history_csv(PROJECT_ROOT / "data/history/minutely/unified_gold_silver_volume.csv", unified)

        self.logger.info(f"✅ {self.source_id} completed")
        return True


# ====================================================================
#  日频基本面 (原 daily.py)
# ====================================================================

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/2026/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value=2026"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


class MacroTreasury(BaseCollector):
    """美债收益率曲线"""

    def __init__(self):
        super().__init__("treasury")

    def fetch(self):
        r = requests.get(TREASURY_URL, timeout=15)
        r.encoding = "utf-8"
        return r.text

    def parse(self, raw):
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows:
            raise ValueError("Empty treasury CSV")
        latest = rows[0]
        return {
            "snapshot_key": "treasury",
            "snapshot_value": {
                "10yr": float(latest.get("10 Yr", 0)),
                "30yr": float(latest.get("30 Yr", 0)),
                "2yr": float(latest.get("2 Yr", 0)),
                "source": "ustreasury", "as_of_date": latest.get("Date", ""),
                "updated_at": self._now(), "freshness": "昨日数据",
            },
            "history_row": {"10yr": float(latest.get("10 Yr", 0)),
                            "30yr": float(latest.get("30 Yr", 0)),
                            "2yr": float(latest.get("2 Yr", 0))},
            "grain": "daily",
        }


class MacroFRED(BaseCollector):
    """FRED 系列指标：TIPS / DXY / SP500"""

    def __init__(self, series_key: str):
        col = loader.collectors.get("collectors.macro", {})
        fred_map = col.get("output", {}).get("fred_series", {})
        if series_key not in fred_map:
            raise ValueError(f"Unknown FRED series: {series_key}, choices: {list(fred_map.keys())}")
        self.series_key = series_key
        self.series_info = fred_map[series_key]
        # 从 fred_series 定义中获取指标 ID（如 "tips" → "tips_10y"）
        ind_id = self.series_info.get("indicator", series_key)
        ind = loader.get(ind_id)
        self._snapshot_key = ind["files"]["snapshot_key"] if ind else series_key
        super().__init__(series_key)

    def fetch(self):
        url = FRED_URL.format(series_id=self.series_info["id"], start="2026-01-01", end="2026-12-31")
        return requests.get(url, timeout=15).text

    def parse(self, raw):
        lines = raw.strip().split("\n")
        if len(lines) < 2:
            raise ValueError(f"Empty FRED CSV for {self.series_key}")
        parts = lines[-1].split(",")
        if len(parts) < 2:
            raise ValueError(f"Bad format: {lines[-1]}")
        value = float(parts[1].strip())
        freshness = {"tips": "延迟2天", "dxy": "延迟1~5天", "sp500": "延迟1天"}
        return {
            "snapshot_key": self._snapshot_key,
            "snapshot_value": {"value": value, "source": "fred",
                               "as_of_date": parts[0].strip(),
                               "updated_at": self._now(),
                               "freshness": freshness.get(self.series_key, "")},
            "history_row": {"value": value},
            "grain": "daily",
        }


class MacroVIX(BaseCollector):
    """CBOE VIX 恐慌指数"""

    def __init__(self):
        super().__init__("vix")

    def fetch(self):
        return requests.get(CBOE_VIX_URL, timeout=15).text

    def parse(self, raw):
        lines = raw.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("Empty VIX CSV")
        parts = lines[-1].split(",")
        if len(parts) < 5:
            raise ValueError(f"Bad VIX line: {lines[-1]}")
        return {
            "snapshot_key": "vix",
            "snapshot_value": {"value": float(parts[4].strip()), "source": "cboe",
                               "as_of_date": parts[0].strip(),
                               "updated_at": self._now(), "freshness": "前一交易日"},
            "history_row": {"close": float(parts[4].strip())},
            "grain": "daily",
        }


def run_daily(sub=None):
    """批量运行日频采集器"""
    all_collectors = [
        ("treasury", MacroTreasury()),
        ("tips", MacroFRED("tips")),
        ("dxy", MacroFRED("dxy")),
        ("sp500", MacroFRED("sp500")),
        ("vix", MacroVIX()),
    ]
    if sub:
        targets = [t for t in all_collectors if t[0] == sub]
        if not targets:
            logger.warning(f"Unknown daily sub-collector: {sub}")
            return
    else:
        targets = all_collectors

    results = {}
    for name, c in targets:
        results[name] = "✅" if c.run() else "❌"
    logger.info("\n=== Daily Collectors Summary ===")
    for name, status in results.items():
        logger.info("  %s: %s", name, status)


def run_market():
    """运行实时市场采集器"""
    MacroMarket().run()


# ====================================================================
#  CLI
# ====================================================================

def main():
    if len(sys.argv) < 2:
        print("用法: python -m collectors.macro {market|daily|all} [sub]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "market":
        run_market()
    elif cmd == "daily":
        run_daily(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "all":
        run_market()
        run_daily()
    else:
        print(f"未知命令: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
