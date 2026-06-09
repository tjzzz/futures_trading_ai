#!/usr/bin/env python3
"""
Yahoo Finance 批量采集器 — V1

直连 Yahoo v8 chart API，仅采集 yfinance 独有的数据源（其他指标各有独立采集器兜底）。
覆盖: DXY / VIX / GLD / SLV / FedWatch 概率（5 ticker）

其他指标 fallback:
  - 美债收益率 → treasuries.py (U.S. Treasury)
  - SP500 → fallback.py (FRED)
  - WTI/布伦特/铜 → fallback.py (FRED)
  - USD/CNY → fallback.py (ExchangeRate-API)
  - 金银期货 → akshare_futures.py (新浪)

频率: 5 分钟（5 ticker 几乎不触发 429）
"""

import json
import time
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

from collectors.base import BaseCollector, now_cst

CST = timezone(timedelta(hours=8))

# ── Ticker 定义 ──
# 仅保留 yfinance 独有的数据源（其他各有独立 fallback）
# DXY 保留：FRED 无精确 DXY 序列，VIX 保留：CBOE 写 vix_daily 键不兼容
TICKERS = [
    ("dxy",           "DX-Y.NYB", "dxy"),
    ("vix",           "^VIX",     "vix"),
    ("gld_holdings",  "GLD",      "gld_holdings"),
    ("slv_holdings",  "SLV",      "slv_holdings"),
    ("fedwatch_prob", "FF=F",     "fedfunds"),
]

FOMC_DATES_2026 = [
    "2026-01-28", "2026-03-18", "2026-05-07", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-05", "2026-12-16",
]
CURRENT_FED_RATE = 4.50

API_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class YFinanceBatch(BaseCollector):
    """Yahoo Finance 批量采集器"""

    def __init__(self):
        super().__init__("yfinance_batch")

    def collect(self) -> dict | None:
        self.logger.info(f"=== yfinance_batch start ({len(TICKERS)} ticker) ===")

        # 尝试 1: 直接调 Yahoo v8 chart API
        result = self._collect_via_api()
        if result:
            return result

        # 尝试 2: 等 60 秒后重试（之前限流了）
        self.logger.info("等待 60 秒后重试...")
        time.sleep(60)
        result = self._collect_via_api()
        if result:
            return result

        # 尝试 3: 回退 yfinance
        self.logger.info("回退到 yfinance...")
        return self._collect_via_yfinance()

    def _collect_via_api(self) -> dict | None:
        """通过 Yahoo v8 chart API 逐个获取"""
        snapshot = {}
        history_rows = []
        errors = []

        for snap_key, symbol, hist_field in TICKERS:
            try:
                price, prev_close, volume = self._fetch_one_via_api(symbol)
                if price is None:
                    errors.append(f"{snap_key}({symbol}): 无数据")
                    continue

                entry = self._make_entry(price, prev_close, volume)
                snapshot[snap_key] = entry
                history_rows.append({
                    "file": "data/history/minutely/yfinance_minutely.csv",
                    "row": {"timestamp": now_cst(), hist_field: price},
                })
            except Exception as e:
                errors.append(f"{snap_key}({symbol}): {e}")
                continue

            time.sleep(0.5)

        if not snapshot:
            self.logger.warning("v8 API 全失败")
            for e in errors:
                self.logger.warning(f"  {e}")
            return None

        # FedWatch 概率
        if "fedwatch_prob" in snapshot:
            ff_price = snapshot["fedwatch_prob"].get("value", 0)
            fw = self._calc_fedwatch(ff_price)
            if fw:
                snapshot["fedwatch_prob"] = fw

        history = [{"file": h["file"], "row": h["row"], "grain": "minutely"} for h in history_rows]

        if errors:
            self.logger.warning(f"部分风险: {len(snapshot)}/{len(TICKERS)} — {', '.join(errors[:3])}")
        self.logger.info(f"v8 API 采集完成: {len(snapshot)}/{len(TICKERS)}")
        return {"snapshot": snapshot, "history": history}

    def _fetch_one_via_api(self, symbol: str) -> tuple:
        """获取单个 ticker 实时价格，返回 (price, prev_close, volume)"""
        url = API_BASE.format(symbol=symbol)
        params = {"range": "5d", "interval": "1d", "includePrePost": "false"}
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            return None, None, None

        meta = result[0].get("meta", {})
        prices = result[0].get("indicators", {}).get("quote", [{}])[0]
        timestamps = result[0].get("timestamp", [])

        if not timestamps or not prices:
            return None, None, None

        # 取最新
        idx = -1
        close = prices.get("close", [])
        volume = prices.get("volume", [])
        price_val = float(close[idx]) if close and idx < len(close) and close[idx] is not None else float(meta.get("regularMarketPrice", 0))
        vol_val = int(volume[idx]) if volume and idx < len(volume) and volume[idx] is not None else 0
        prev_close_val = float(close[-2]) if len(close) >= 2 and close[-2] is not None else float(meta.get("chartPreviousClose", price_val))
        return price_val, prev_close_val, vol_val

    def _collect_via_yfinance(self) -> dict | None:
        """回退：用 yfinance 批量下载"""
        symbols = [t[1] for t in TICKERS]
        try:
            df = yf.download(symbols, period="5d", interval="1d", group_by="ticker",
                             threads=False, progress=False, auto_adjust=True)
        except Exception as e:
            self.logger.error(f"yf.download 也失败: {e}")
            return self._fallback_ticker()

        if df is None or df.empty:
            self.logger.error("yf.download 空数据")
            return self._fallback_ticker()

        import pandas as pd
        snapshot = {}
        history_rows = []
        errors = []

        for snap_key, symbol, hist_field in TICKERS:
            try:
                if isinstance(df.columns, pd.MultiIndex) and symbol in df.columns.get_level_values(1):
                    ticker_df = df.xs(symbol, axis=1, level=1)
                elif hasattr(df, "columns") and symbol in df.columns:
                    ticker_df = df[symbol]
                else:
                    ticker_df = df

                latest = ticker_df.iloc[-1]
                close = latest.get("Close") or latest.get("close")
                if close is None or close == 0:
                    errors.append(f"{snap_key}: price=0")
                    continue
                price = float(close)
                vol = int(latest.get("Volume") or latest.get("volume", 0))
                prev = float(ticker_df["Close"].iloc[-2]) if len(ticker_df) >= 2 and "Close" in ticker_df else price

                snapshot[snap_key] = self._make_entry(price, prev, vol)
                history_rows.append({"file": "data/history/minutely/yfinance_minutely.csv",
                                     "row": {"timestamp": now_cst(), hist_field: price}})
            except Exception as e:
                errors.append(f"{snap_key}: {e}")

        if "fedwatch_prob" in snapshot:
            fw = self._calc_fedwatch(snapshot["fedwatch_prob"].get("value", 0))
            if fw:
                snapshot["fedwatch_prob"] = fw

        history = [{"file": h["file"], "row": h["row"], "grain": "minutely"} for h in history_rows]
        self.logger.info(f"yfinance 回退完成: {len(snapshot)}/{len(TICKERS)}")
        return {"snapshot": snapshot, "history": history} if snapshot else None

    def _fallback_ticker(self) -> dict | None:
        """终极回退：逐个 Ticker() 带间隔"""
        snapshot = {}
        history_rows = []
        errors = []
        for snap_key, symbol, hist_field in TICKERS:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="5d", interval="1d")
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    price = float(latest.get("Close") or latest.get("close", 0))
                    vol = int(latest.get("Volume") or latest.get("volume", 0))
                    prev = float(df["Close"].iloc[-2]) if len(df) >= 2 and "Close" in df else price
                    snapshot[snap_key] = self._make_entry(price, prev, vol)
                    history_rows.append({"file": "data/history/minutely/yfinance_minutely.csv",
                                         "row": {"timestamp": now_cst(), hist_field: price}})
                else:
                    errors.append(f"{snap_key}: 无数据")
            except Exception as e:
                errors.append(f"{snap_key}: {e}")
            time.sleep(1.5)
        if "fedwatch_prob" in snapshot:
            fw = self._calc_fedwatch(snapshot["fedwatch_prob"].get("value", 0))
            if fw:
                snapshot["fedwatch_prob"] = fw
        history = [{"file": h["file"], "row": h["row"], "grain": "minutely"} for h in history_rows]
        if not snapshot:
            self.logger.error("终极回退全部失败")
            for e in errors:
                self.logger.error(f"  {e}")
        return {"snapshot": snapshot, "history": history} if snapshot else None

    def _make_entry(self, price: float, prev_close: float, volume: int) -> dict:
        change = round(price - prev_close, 4) if prev_close else None
        change_pct = round((change / prev_close) * 100, 2) if prev_close and prev_close != 0 else None
        entry = {
            "value": round(price, 2),
            "change": change, "change_pct": change_pct,
            "prev_close": round(prev_close, 2),
            "source": "yahoo_finance", "updated_at": now_cst(), "freshness": "实时",
        }
        if volume:
            entry["volume"] = volume
        return entry

    def _calc_fedwatch(self, ff_price: float) -> dict | None:
        if not ff_price or ff_price <= 0:
            return None
        implied_rate = 100.0 - ff_price
        gap = implied_rate - CURRENT_FED_RATE
        max_prob = min(abs(gap) / 0.25, 1.0)
        result = {"implied_rate": round(implied_rate, 2),
                  "next_meeting": self._next_fomc(),
                  "source": "yahoo_finance (FF=F)", "updated_at": now_cst()}
        if gap < -0.05:
            cut_50bp = round(min((abs(gap) - 0.25) / 0.25, 1.0), 4) if abs(gap) > 0.25 else 0
            result.update({"cut_50bp": max(0, cut_50bp), "cut_25bp": round(max_prob - cut_50bp, 4),
                           "hold": max(0, round(1 - max_prob, 4)), "hike_25bp": 0, "hike_50bp": 0})
        elif gap > 0.05:
            hike_50bp = round(min((abs(gap) - 0.25) / 0.25, 1.0), 4) if abs(gap) > 0.25 else 0
            result.update({"cut_25bp": 0, "cut_50bp": 0, "hold": max(0, round(1 - max_prob, 4)),
                           "hike_25bp": round(max_prob - hike_50bp, 4), "hike_50bp": max(0, hike_50bp)})
        else:
            result.update({"cut_25bp": 0, "cut_50bp": 0, "hold": 1.0, "hike_25bp": 0, "hike_50bp": 0})
        return result

    def _next_fomc(self) -> str:
        today = datetime.now(CST).strftime("%Y-%m-%d")
        for d in FOMC_DATES_2026:
            if d >= today:
                return d
        return FOMC_DATES_2026[-1]


def main():
    result = YFinanceBatch().collect()
    if result is None:
        import sys; sys.exit(1)
    print(f"✅ {len(result['snapshot'])} keys")
    for k, v in result["snapshot"].items():
        if isinstance(v, dict):
            print(f"  {k}: {v.get('value', '?')}")


if __name__ == "__main__":
    main()
