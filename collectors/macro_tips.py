#!/usr/bin/env python3
"""
FRED 系列采集器 — V1 日频

采集 FRED 的多个关键系列：
  - DFII10   → TIPS 10Y 实际利率（核心）
  - CPIAUCSL → CPI 同比（月度）
  - PCEPILFE → 核心 PCE 同比（月度）
  - BAMLH0A0HYM2 → 高收益信用利差（日频）

FRED URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd=...&coed=...

频率: 每日1次
"""

import csv
import io
from datetime import datetime, timezone, timedelta

import requests
from collectors.base import BaseCollector

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
CST = timezone(timedelta(hours=8))

# ── FRED 系列定义 ──
# (series_id, name, snapshot_key, history_file, history_fields, freshness_label)
FRED_SERIES = [
    ("DFII10",    "TIPS 10Y",         "tips_10y",   "tips.csv",    ["value"], "延迟1~2天"),
    ("BAMLH0A0HYM2", "HY Credit Spread", "credit_spread", "credit_hy.csv", ["value"], "延迟1天"),
    ("CPIAUCSL",  "CPI YoY",          "cpi_yoy",    "cpi.csv",     ["value"], "月度"),
    ("PCEPILFE",  "Core PCE",         "pce_core",   "pce_core.csv",["value"], "月度"),
]

# 月度指标的特殊处理
MONTHLY_SERIES = {"CPIAUCSL", "PCEPILFE"}


class FredCollector(BaseCollector):
    """FRED 多系列采集器"""

    def __init__(self):
        super().__init__("macro_tips")

    def collect(self) -> dict | None:
        self.logger.info(f"=== {self.name} start ({len(FRED_SERIES)} series) ===")

        # T-1 检查：日频系列
        daily_series = [(s_id, name, snap_key, hist_f, fields, fresh)
                        for s_id, name, snap_key, hist_f, fields, fresh in FRED_SERIES
                        if s_id not in MONTHLY_SERIES]
        all_fresh = all(
            not self._needs_update(f"data/history/daily/{hf}", max_stale_days=1)
            for _, _, _, hf, _, _ in daily_series
        )
        if all_fresh and daily_series:
            self.logger.info("  macro_tips: 全部日频系列已更新到 T-1，跳过")
            return None

        snapshot = {}
        history = []
        errors = []

        for series_id, name, snap_key, hist_file, fields, freshness in FRED_SERIES:
            try:
                hist_path = f"data/history/daily/{hist_file}"
                url = FRED_URL.format(series_id=series_id, start="2026-01-01", end="2026-12-31")
                self.logger.info(f"  {name}: 请求 2026 全量")
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                result = self._parse_single(series_id, name, snap_key, hist_path, freshness, r.text)
                if result:
                    s, h = result
                    snapshot.update(s)
                    if h:
                        history.extend(h)
                else:
                    errors.append(f"{name}({series_id}): 无数据")
            except Exception as e:
                errors.append(f"{name}({series_id}): {e}")

        if not snapshot:
            self.logger.error("全部 FRED 系列采集失败")
            for e in errors:
                self.logger.error(f"  {e}")
            return None

        if errors:
            self.logger.warning(f"部分成功: {len(snapshot)}/{len(FRED_SERIES)} — {', '.join(errors[:3])}")

        self.logger.info(f"✅ {self.name} 完成: {len(snapshot)} 个系列")
        return {"snapshot": snapshot, "history": history}

    def _parse_single(self, series_id: str, name: str, snap_key: str,
                       hist_file: str, freshness: str, raw: str) -> tuple | None:
        """解析单个 FRED 系列"""
        lines = raw.strip().split("\n")
        if len(lines) < 2:
            return None

        is_monthly = series_id in MONTHLY_SERIES

        if is_monthly:
            parts = lines[-1].split(",")
            if len(parts) < 2:
                return None
            value = float(parts[1].strip())
            date_str = parts[0].strip()

            snapshot = {
                snap_key: {
                    "value": round(value, 2),
                    "source": "fred",
                    "as_of_date": date_str,
                    "updated_at": self._now(),
                    "freshness": freshness,
                },
            }
            history = [{
                "file": hist_file,
                "row": {"date": date_str, "value": value},
                "grain": "daily",
            }]
            return snapshot, history
        else:
            all_rows = []
            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) < 2:
                    continue
                try:
                    val = float(parts[1].strip())
                    dt = parts[0].strip()
                    if dt.startswith("2026"):
                        all_rows.append({"date": dt, "value": val})
                except (ValueError, TypeError):
                    continue

            if not all_rows:
                return None

            latest = all_rows[-1]
            self.logger.info(f"  {name}: {latest['date']} = {latest['value']:.2f} (全量 {len(all_rows)} 行)")

            snapshot = {
                snap_key: {
                    "value": round(latest["value"], 2),
                    "source": "fred",
                    "as_of_date": latest["date"],
                    "updated_at": self._now(),
                    "freshness": freshness,
                },
            }
            history = [{
                "file": hist_file, "row": r, "grain": "daily", "mode": "overwrite",
            } for r in all_rows]
            return snapshot, history


def main():
    result = FredCollector().collect()
    if result:
        for k, v in result["snapshot"].items():
            print(f"  {k}: {v.get('value', '?')} (as of {v.get('as_of_date', '?')})")
    else:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()
