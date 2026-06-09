#!/usr/bin/env python3
"""
兜底数据采集器 — V1

当 Yahoo Finance 限流时，从免费公开源补数据：
  - FRED SP500            → 标普500（日频）
  - FRED DTWEXBGS         → 广义美元指数（日频，DXY 替代）
  - FRED DCOILWTICO       → WTI 原油（日频）
  - FRED DCOILBRENTEU     → 布伦特原油（日频）
  - FRED PCOPPUSDM        → 铜价（月度，PPI铜矿石）
  - ExchangeRate-API      → USD/CNY（每日更新）
  - gold-api.com spot     → 金银现货（已有，这里仅作聚合输出）

所有数据写入 dashboard_data.json。
频率: 每日1次（FRED 是 T+1 数据）
"""

import io
import csv

import requests
from collectors.base import BaseCollector

# ── FRED 系列 ──
FRED_TEMPLATE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"

def _fred_url(series_id: str, start: str = "2026-01-01", end: str = "2026-12-31") -> str:
    return FRED_TEMPLATE.replace("{series_id}", series_id).replace("{start}", start).replace("{end}", end)
FRED_SERIES = [
    ("sp500",         "SP500",        "标普500",              "daily",  "延迟1天"),
    ("dxy",           "DTWEXBGS",     "广义美元指数",          "daily",  "延迟1天"),
    ("oil_wti",       "DCOILWTICO",   "WTI原油",              "daily",  "延迟1天"),
    ("oil_brent",     "DCOILBRENTEU", "布伦特原油",            "daily",  "延迟1天"),
    ("copper",        "PCOPPUSDM",    "铜价(PPI)",            "monthly","月度"),
]

# ── ExchangeRate-API（无需 key）──
FX_URL = "https://open.er-api.com/v6/latest/USD"


class FallbackCollector(BaseCollector):
    """兜底数据采集器"""

    def __init__(self):
        super().__init__("fallback")

    def collect(self) -> dict | None:
        self.logger.info(f"=== fallback start ({len(FRED_SERIES)} FRED + FX) ===")
        snapshot = {}
        history = []
        errors = []

        # ── FRED 系列 ──
        for snap_key, series_id, name, freq, freshness in FRED_SERIES:
            try:
                url = _fred_url(series_id)
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                lines = r.text.strip().split("\n")
                if len(lines) < 2:
                    errors.append(f"{name}({series_id}): 空数据")
                    continue

                # 解析全部行
                all_rows = []
                for line in lines[1:]:
                    parts = line.strip().split(",")
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
                    errors.append(f"{name}({series_id}): 无有效行")
                    continue

                latest = all_rows[-1]
                snapshot[snap_key] = {
                    "value": round(latest["value"], 2),
                    "source": "fred",
                    "as_of_date": latest["date"],
                    "updated_at": self._now(),
                    "freshness": freshness,
                }

                # 日频仅写最新行（避免重复追加全量历史）
                history.append({
                    "file": f"data/history/daily/{snap_key}.csv",
                    "row": latest,
                    "grain": "daily",
                })

                self.logger.info(f"  {name}: {latest['date']} = {latest['value']:.2f}")

            except Exception as e:
                errors.append(f"{name}({series_id}): {e}")

        # ── USD/CNY（ExchangeRate-API）──
        try:
            r = requests.get(FX_URL, timeout=10)
            r.raise_for_status()
            data = r.json()
            cny = data.get("rates", {}).get("CNY")
            if cny:
                snapshot["usdcnh"] = {
                    "value": round(float(cny), 4),
                    "source": "exchangerate-api (open.er-api.com)",
                    "updated_at": self._now(),
                    "freshness": "每日更新",
                }
                self.logger.info(f"  USD/CNY: {float(cny):.4f}")
            else:
                errors.append("USD/CNY: rates.CNY 为空")
        except Exception as e:
            errors.append(f"USD/CNY: {e}")

        if not snapshot:
            self.logger.error("全部兜底采集失败")
            for e in errors:
                self.logger.error(f"  {e}")
            return None

        if errors:
            self.logger.warning(f"部分成功 — {', '.join(errors[:3])}")

        self.logger.info(f"✅ fallback 完成: {len(snapshot)} 个字段")
        return {"snapshot": snapshot, "history": history}


def main():
    result = FallbackCollector().collect()
    if result:
        for k, v in result["snapshot"].items():
            val = v.get("value", "?")
            src = v.get("source", "?")
            print(f"  {k}: {val} ({src})")
    else:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()
