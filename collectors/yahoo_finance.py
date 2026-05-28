#!/usr/bin/env python3
"""
高频数据采集器 — Yahoo Finance 实时行情
- 每5分钟采集 DXY / US10Y / VIX / 黄金期货 / 白银期货
- 写入 dashboard_data.json（快照）
- 追加到 data/history/minutely/yahoo_finance_minutely.csv（分钟级历史）

Yahoo Finance API（免费，无需 Key）：
  https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}?range=1d&interval=5m

Symbol 映射：
  ^TNX      → US10Y 收益率
  DX-Y.NYB  → 美元指数 DXY
  GC=F      → COMEX 黄金期货
  SI=F      → COMEX 白银期货
  ^VIX      → VIX 恐慌指数
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from collectors.base_collector import BaseCollector, now_cst, PROJECT_ROOT

# ── Yahoo Finance Symbol 配置 ─────────────────────────
SYMBOLS = {
    "dxy":           {"yahoo": "DX-Y.NYB", "name": "美元指数 DXY"},
    "us10y":         {"yahoo": "^TNX",     "name": "US10Y 美债收益率"},
    "vix":           {"yahoo": "^VIX",     "name": "VIX 恐慌指数"},
    "gold_futures":  {"yahoo": "GC=F",     "name": "COMEX 黄金期货"},
    "silver_futures":{"yahoo": "SI=F",     "name": "COMEX 白银期货"},
}

# Yahoo Finance API
YF_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

CST = timezone(timedelta(hours=8))


class YahooFinanceCollector(BaseCollector):
    """Yahoo Finance 高频行情采集器"""

    def __init__(self):
        super().__init__("yahoo_finance")

    def fetch(self):
        """并行拉取所有指标的最新行情"""
        results = {}
        failed = []

        for key, cfg in SYMBOLS.items():
            url = YF_URL.format(symbol=cfg["yahoo"])
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    results[key] = r.json()
                else:
                    failed.append(key)
                    self.logger.warning(f"{key} HTTP {r.status_code}")
            except Exception as e:
                failed.append(key)
                self.logger.warning(f"{key} fetch failed: {e}")

        if not results:
            raise RuntimeError("所有 Yahoo Finance 请求均失败")

        results["_failed"] = failed
        return results

    def parse(self, raw_data):
        """解析 Yahoo Finance 响应，返回快照和历史行"""
        failed = raw_data.pop("_failed", [])
        snapshot_values = {}
        history_row = {}
        now_ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

        for key in SYMBOLS:
            data = raw_data.get(key)
            if not data:
                continue

            try:
                result = data.get("chart", {}).get("result", [{}])[0]
                meta = result.get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("previousClose")
                volume = meta.get("regularMarketVolume")

                if price is not None:
                    change = price - prev_close if prev_close else None
                    change_pct = (change / prev_close * 100) if prev_close and prev_close != 0 else None

                    # 快照值
                    snapshot_entry = {
                        "value": round(price, 4) if price else None,
                        "change": round(change, 4) if change is not None else None,
                        "change_pct": round(change_pct, 2) if change_pct is not None else None,
                        "prev_close": round(prev_close, 4) if prev_close else None,
                        "source": "yahoo_finance",
                        "updated_at": now_ts,
                        "freshness": "实时",
                    }

                    # 为期货添加交易量数据
                    if key in ["gold_futures", "silver_futures"] and volume is not None:
                        snapshot_entry["volume"] = int(volume)

                    snapshot_values[key] = snapshot_entry

                    # 历史行 - 包含价格和交易量
                    history_row[f"{key}_price"] = price
                    if volume is not None:
                        history_row[f"{key}_volume"] = int(volume)

            except Exception as e:
                self.logger.warning(f"解析 {key} 失败: {e}")

        # 字段名映射（Yahoo 内部名 → dashboard 字段名）
        FIELD_MAP = {
            "dxy": "dxy",
            "us10y": "treasury_10y",
            "vix": "vix",
            "gold_futures": "gold_futures",
            "silver_futures": "silver_futures",
        }

        # 构建 extra_snapshots 列表
        extra_snapshots = []
        for internal_key, val in snapshot_values.items():
            dashboard_key = FIELD_MAP.get(internal_key, internal_key)
            extra_snapshots.append((dashboard_key, val))

        # 返回标准格式，让基类 run() 处理
        return {
            "snapshot_key": None,  # 使用 extra_snapshots 替代
            "snapshot_value": {},
            "extra_snapshots": extra_snapshots,
            "history_row": history_row,
            "grain": "minutely",
        }

    def run(self):
        """覆盖基类 run，批量写入所有快照字段（单次读写，无需锁）"""
        self.logger.info(f"=== {self.source_id} start ===")
        try:
            raw = self.fetch()
            result = self.parse(raw)
        except requests.RequestException as e:
            self.logger.error(f"网络请求失败: {e}")
            return False
        except (KeyError, ValueError, TypeError) as e:
            self.logger.error(f"数据解析失败: {e}")
            return False
        except RuntimeError as e:
            self.logger.error(f"采集失败: {e}")
            return False

        extra_snapshots = result.get("extra_snapshots", [])
        history_row = result.get("history_row", {})
        grain = result.get("grain", "minutely")

        # ── 直接读写快照文件（无锁争用，iCloud 兼容）──
        if extra_snapshots:
            SNAPSHOT_FILE = Path(__file__).resolve().parent.parent / "data/current/dashboard_data.json"
            data = {}
            if SNAPSHOT_FILE.exists():
                try:
                    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, IOError, OSError):
                    data = {}

            # 批量更新所有快照字段
            for key, val in extra_snapshots:
                data[key] = val

            data["global_updated_at"] = now_cst()
            try:
                with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.logger.info(f"Snapshot updated: {[k for k, v in extra_snapshots]}")
            except (IOError, OSError) as e:
                self.logger.error(f"Snapshot write failed: {e}")

        # ── 写入分钟级历史 ──
        if history_row:
            # 1. 写入原始CSV文件（保持向后兼容）
            csv_file = PROJECT_ROOT / "data/history/minutely" / f"{self.source_id}_minutely.csv"
            
            # 重新组织历史行，确保字段顺序一致
            ordered_row = {"timestamp": now_cst()}
            
            # 添加价格数据
            for key in ["dxy", "us10y", "vix", "gold_futures", "silver_futures"]:
                price_key = f"{key}_price"
                if price_key in history_row:
                    ordered_row[key] = history_row[price_key]
                elif key in history_row:  # 向后兼容
                    ordered_row[key] = history_row[key]
            
            self.write_history_csv(csv_file, ordered_row)
            self.logger.info(f"History appended to {csv_file.name}")
            
            # 2. 写入包含交易量的扩展CSV文件（用于实时探查）
            extended_csv_file = PROJECT_ROOT / "data/history/minutely" / f"{self.source_id}_extended_minutely.csv"
            
            # 创建扩展历史行
            extended_row = {"timestamp": now_cst()}
            
            # 添加价格数据
            for key in ["dxy", "us10y", "vix", "gold_futures", "silver_futures"]:
                price_key = f"{key}_price"
                if price_key in history_row:
                    extended_row[f"{key}_price"] = history_row[price_key]
                elif key in history_row:  # 向后兼容
                    extended_row[f"{key}_price"] = history_row[key]
            
            # 添加交易量数据
            for key in ["us10y", "vix", "gold_futures", "silver_futures"]:
                volume_key = f"{key}_volume"
                if volume_key in history_row and history_row[volume_key] is not None:
                    extended_row[f"{key}_volume"] = history_row[volume_key]
            
            self.write_history_csv(extended_csv_file, extended_row)
            self.logger.info(f"Extended history appended to {extended_csv_file.name}")
            
            # 3. 创建统一时间戳的黄金白银数据文件（与gold_silver采集器格式对齐）
            unified_file = PROJECT_ROOT / "data/history/minutely" / "unified_gold_silver_volume.csv"
            
            # 标准化时间戳：去除秒部分，只保留到分钟
            timestamp_minute = now_cst()[:16] + ":00"  # 格式: "2026-05-21 15:47:00"
            
            # 获取黄金和白银价格（从history_row）
            gold_price = None
            silver_price = None
            
            if "gold_futures_price" in history_row:
                gold_price = history_row["gold_futures_price"]
            elif "gold_futures" in history_row:
                gold_price = history_row["gold_futures"]
                
            if "silver_futures_price" in history_row:
                silver_price = history_row["silver_futures_price"]
            elif "silver_futures" in history_row:
                silver_price = history_row["silver_futures"]
            
            # 获取交易量
            gold_volume = history_row.get("gold_futures_volume")
            silver_volume = history_row.get("silver_futures_volume")
            
            # 计算金银比（如果都有价格）
            ratio = None
            if gold_price is not None and silver_price is not None and silver_price != 0:
                ratio = gold_price / silver_price
            
            # 创建统一数据行
            unified_row = {
                "timestamp": timestamp_minute,
                "gold_usd": gold_price,
                "silver_usd": silver_price,
                "gold_volume": gold_volume,
                "silver_volume": silver_volume,
                "ratio": ratio
            }
            
            # 写入统一文件
            self.write_history_csv(unified_file, unified_row)
            self.logger.info(f"Unified gold/silver data appended to {unified_file.name}")

        self.logger.info(f"✅ {self.source_id} completed")
        return True


def main():
    """命令行入口"""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    collector = YahooFinanceCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
