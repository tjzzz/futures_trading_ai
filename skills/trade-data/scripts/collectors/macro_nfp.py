#!/usr/bin/env python3
"""
非农就业采集器 — V1 日频

采集 FRED PAYEMS（All Employees: Total Nonfarm）→ 月度就业人数绝对值，
计算月度变化量（大非农新增就业），
从 calendar_cache.json 提取 NFP 预期差。

频率: 每日1次（PAYEMS 月度更新，但 FRED CSV 可随时请求）
"""

import csv
import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from collectors.base import BaseCollector, PROJECT_ROOT

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
CST = timezone(timedelta(hours=8))

# FRED 系列：PAYEMS — 非农就业人数（月度）
NFP_SERIES_ID = "PAYEMS"
NFP_NAME = "Nonfarm Payrolls"

# 日历缓存路径
CALENDAR_CACHE = PROJECT_ROOT / "data/events/calendar_cache.json"

# NFP 匹配关键词
NFP_KEYWORDS = ["nonfarm", "非农", "payroll"]


class NfpCollector(BaseCollector):
    """非农就业采集器"""

    def __init__(self):
        super().__init__("macro_nfp")

    def collect(self) -> dict | None:
        self.logger.info(f"=== {self.name} start ===")

        # T-90 检查：PAYEMS 月度更新，允许最多 90 天不更新
        hist_path = f"data/history/daily/nfp_surprise.csv"
        if not self._needs_update(hist_path, max_stale_days=90):
            self.logger.info("  nfp: 已更新到最近月份，跳过")
            return None

        snapshot = {}
        history = []

        # ── 1. 采集 FRED PAYEMS ──
        try:
            url = FRED_URL.format(series_id=NFP_SERIES_ID, start="2025-01-01", end="2026-12-31")
            self.logger.info(f"  PAYEMS: 请求 2025-2026 全量")
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            result = self._parse_payems(r.text)
            if result:
                nfp_level, nfp_change, records = result
                snapshot.update(nfp_level)
                snapshot.update(nfp_change)
                history.extend(records)
                self.logger.info(f"  PAYEMS: level={nfp_level['nfp_level']['value']:.0f}K, change={nfp_change['nfp_change']['value']:.0f}K")
            else:
                self.logger.error("  PAYEMS: 解析失败")
                return None
        except Exception as e:
            self.logger.error(f"  PAYEMS 采集失败: {e}")
            return None

        # ── 2. 从 calendar_cache.json 提取 NFP 预期差 ──
        try:
            surprise_result = self._extract_nfp_surprise()
            if surprise_result:
                snapshot.update(surprise_result)
                self.logger.info(f"  NFP surprise: {surprise_result.get('nfp_surprise_pct', {}).get('value', 'N/A')}%")
            else:
                self.logger.info("  NFP surprise: 日历中无 NFP 事件或数据不完整")
        except Exception as e:
            self.logger.warning(f"  NFP surprise 提取失败: {e}")

        self.logger.info(f"✅ {self.name} 完成")
        return {"snapshot": snapshot, "history": history}

    def _parse_payems(self, raw: str) -> tuple | None:
        """
        解析 PAYEMS CSV，返回 (nfp_level_dict, nfp_change_dict, history_records)

        月度数据格式（与 MONTHLY_SERIES 处理方式一致）:
            DATE,VALUE
            2025-01-01,158743.0
            2025-02-01,158956.0
        """
        lines = raw.strip().split("\n")
        if len(lines) < 3:
            return None

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
                all_rows.append({"date": dt, "value": val})
            except (ValueError, TypeError):
                continue

        if len(all_rows) < 2:
            return None

        # 按日期排序
        all_rows.sort(key=lambda r: r["date"])

        latest = all_rows[-1]
        prev = all_rows[-2]

        # 计算月度变化（大非农新增就业）
        # PAYEMS 以千人为单位，直接相减得到千人变动
        nfp_change_val = latest["value"] - prev["value"]

        self.logger.info(f"  PAYEMS: {latest['date']} = {latest['value']:.0f}K, "
                         f"上月 {prev['date']} = {prev['value']:.0f}K, "
                         f"变化 {nfp_change_val:+.0f}K")

        nfp_level_dict = {
            "nfp_level": {
                "value": round(latest["value"]),
                "source": "fred",
                "as_of_date": latest["date"],
                "updated_at": self._now(),
                "freshness": "月度",
            },
        }

        nfp_change_dict = {
            "nfp_change": {
                "value": round(nfp_change_val),
                "source": "fred(calc)",
                "as_of_date": latest["date"],
                "updated_at": self._now(),
                "description": f"{latest['date']} vs {prev['date']} 月度变化",
            },
        }

        # 历史记录：包含 level, change, 以及占位的 surprise（由日历填充）
        history_records = []
        for i in range(1, len(all_rows)):
            change_val = all_rows[i]["value"] - all_rows[i - 1]["value"]
            history_records.append({
                "file": "data/history/daily/nfp_surprise.csv",
                "row": {
                    "date": all_rows[i]["date"],
                    "nfp_level": round(all_rows[i]["value"]),
                    "nfp_change": round(change_val),
                    "surprise_pct": "",  # 由日历填充
                },
                "grain": "daily",
                "mode": "overwrite",
            })

        return nfp_level_dict, nfp_change_dict, history_records

    def _extract_nfp_surprise(self) -> dict | None:
        """
        从 calendar_cache.json 提取 NFP 事件的预期差。

        Returns:
            {"nfp_surprise_pct": {"value": float, "source": "calendar(calc)", ...}}
            None: 未找到 NFP 事件或数据不完整
        """
        if not CALENDAR_CACHE.exists():
            self.logger.info("  calendar_cache.json 不存在")
            return None

        try:
            cache = json.loads(CALENDAR_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.logger.warning("  calendar_cache.json 读取失败")
            return None

        events = cache.get("events", [])
        if not events:
            return None

        # 查找 NFP 事件
        nfp_events = []
        for e in events:
            event_name = e.get("event", "")
            event_lower = event_name.lower()
            if any(kw in event_lower for kw in NFP_KEYWORDS):
                nfp_events.append(e)

        if not nfp_events:
            return None

        # 取最新的 NFP 事件
        latest_nfp = nfp_events[-1]
        actual_str = latest_nfp.get("actual", "")
        expected_str = latest_nfp.get("expected", "")

        # 判断是否有有效数据
        actual = None
        expected = None
        try:
            if actual_str and actual_str not in ("", "nan"):
                actual = float(actual_str)
            if expected_str and expected_str not in ("", "nan"):
                expected = float(expected_str)
        except (ValueError, TypeError):
            pass

        if actual is None or expected is None or expected == 0:
            self.logger.info(f"  NFP 事件 '{latest_nfp.get('event', '')}' 数据不完整: "
                             f"actual={actual_str}, expected={expected_str}")
            return None

        surprise_pct = round((actual - expected) / abs(expected) * 100, 2)

        self.logger.info(f"  NFP surprise: {latest_nfp['event']}: "
                         f"actual={actual}, expected={expected}, "
                         f"surprise={surprise_pct:+.2f}%")

        return {
            "nfp_surprise_pct": {
                "value": surprise_pct,
                "source": "calendar(calc)",
                "event": latest_nfp.get("event", ""),
                "actual": actual,
                "expected": expected,
                "event_date": latest_nfp.get("date", ""),
                "updated_at": self._now(),
            },
        }


def main():
    result = NfpCollector().collect()
    if result:
        for k, v in result["snapshot"].items():
            if isinstance(v, dict):
                print(f"  {k}: {v.get('value', '?')} (as of {v.get('as_of_date', v.get('event_date', '?'))})")
            else:
                print(f"  {k}: {v}")
    else:
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()