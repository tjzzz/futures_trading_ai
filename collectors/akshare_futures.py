#!/usr/bin/env python3
"""
AKShare COMEX 金银期货采集器 — V1

通过 AKShare 获取 COMEX 黄金/白银期货实时行情。
  主源（Phase 1）: COMEX 黄金(GC) / 白银(SI) — 3秒级刷新
  备用: gold_api.py（XAU/USD 现货验证）

数据来源: 新浪财经外盘期货实时行情
函数: ak.futures_foreign_commodity_realtime(symbol=["GC", "SI"])

返回: 最新价、涨跌幅、开盘价、最高/最低、买价/卖价、持仓量、行情时间

输出到 dashboard_data.json 的字段:
  - gold_futures    → COMEX 黄金期货实时价
  - silver_futures  → COMEX 白银期货实时价
  - gold_silver_ratio → 由 COMEX 金银价计算

用法:
    python -m collectors.akshare_futures                 # COMEX 金银
    python -m collectors.akshare_futures gold            # 仅黄金
    python -m collectors.akshare_futures subscribe       # 查看可订阅品种

频率: 实时（建议 5-30 秒轮询）
"""

import time
from collectors.base import BaseCollector

# ── COMEX 品种代码映射 ──
# (snapshot_key, 新浪显示名称, 订阅代码)
FUTURES_CONTRACTS = [
    ("gold_futures",   "COMEX黄金", "GC"),
    ("silver_futures", "COMEX白银", "SI"),
]

# 兜底：通过 investing.com 获取日频历史
FUTURES_HISTORY = [
    ("黄金",   "gold_futures.csv"),
    ("白银",   "silver_futures.csv"),
]


class AKShareFuturesCollector(BaseCollector):
    """COMEX 金银期货实时/日频采集器"""

    def __init__(self):
        super().__init__("akshare_futures")

    def collect(self) -> dict | None:
        """主采集入口 — 实时行情 + 日频历史"""
        ak = self._get_akshare()
        if ak is None:
            return None

        # Phase 1: 实时行情
        snapshot = self._collect_realtime(ak)

        # Phase 2: 补充日频历史（如果快照成功）
        history = self._collect_history(ak)

        if not snapshot:
            self.logger.error("COMEX 金银实时行情采集失败")
            return None

        self.logger.info(f"✅ akshare_futures 完成")
        return {"snapshot": snapshot, "history": history or []}

    def collect_realtime(self) -> dict | None:
        """仅实时行情（供 run.py realtime 模式调用）"""
        ak = self._get_akshare()
        if ak is None:
            return None
        snapshot = self._collect_realtime(ak)
        if not snapshot:
            return None
        return {"snapshot": snapshot, "history": []}

    def _collect_realtime(self, ak) -> dict:
        """获取 COMEX 金银实时行情"""
        self.logger.info("  -> 实时行情...")

        try:
            # 获取所有外盘品种的订阅列表
            try:
                subscribe_list = ak.futures_foreign_commodity_subscribe_exchange_symbol()
                self.logger.debug(f"  可订阅品种: {len(subscribe_list)}")
            except Exception:
                # 如果无法获取列表，使用默认代码
                subscribe_list = ["GC", "SI"]

            # 获取实时行情
            df = ak.futures_foreign_commodity_realtime(symbol=["GC", "SI"])
            if df is None or df.empty:
                self.logger.error("实时行情为空")
                return {}

            now = self._now()
            snapshot = {}
            gold_price = None
            silver_price = None

            for snap_key, display_name, _ in FUTURES_CONTRACTS:
                try:
                    match = df[df["名称"] == display_name]
                    if match.empty:
                        self.logger.warning(f"  {display_name}: 未找到")
                        continue

                    row = match.iloc[0]
                    price = float(row.get("最新价", 0))
                    if price == 0:
                        self.logger.warning(f"  {display_name}: price=0")
                        continue

                    change_pct = float(row.get("涨跌幅", 0) or 0)
                    open_px = float(row.get("开盘价", 0) or 0)
                    high = float(row.get("最高价", 0) or 0)
                    low = float(row.get("最低价", 0) or 0)
                    prev_close = float(row.get("昨日结算价", 0) or 0)
                    oi = float(row.get("持仓量", 0) or 0)
                    bid = float(row.get("买价", 0) or 0)
                    ask = float(row.get("卖价", 0) or 0)
                    quote_time = str(row.get("行情时间", ""))

                    snapshot[snap_key] = {
                        "value": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "open": round(open_px, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "prev_close": round(prev_close, 2),
                        "open_interest": int(oi),
                        "bid": round(bid, 2) if bid else None,
                        "ask": round(ask, 2) if ask else None,
                        "source": "akshare_sina_foreign",
                        "quote_time": quote_time,
                        "updated_at": now,
                        "freshness": "实时",
                    }

                    if display_name == "COMEX黄金":
                        gold_price = price
                    elif display_name == "COMEX白银":
                        silver_price = price

                    self.logger.info(f"  {display_name}: {price} ({change_pct:+.2f}%) @ {quote_time}")

                except Exception as e:
                    self.logger.warning(f"  {display_name} 解析失败: {e}")

            # 计算金银比
            if gold_price and silver_price and silver_price > 0:
                ratio = round(gold_price / silver_price, 2)
                snapshot["gold_silver_ratio"] = {
                    "value": ratio,
                    "source": "akshare_sina_foreign (COMEX derived)",
                    "updated_at": now,
                    "freshness": "实时",
                }
                self.logger.info(f"  金银比: {ratio} (COMEX derived)")

            return snapshot

        except Exception as e:
            self.logger.error(f"实时行情采集失败: {e}", exc_info=True)
            return {}

    def _collect_history(self, ak) -> list:
        """通过 investing.com 获取日频历史"""
        self.logger.info("  -> 日频历史...")
        history = []

        for name, hist_file in FUTURES_HISTORY:
            try:
                df = ak.futures_foreign_hist(
                    symbol=name,
                    start_date="2020-01-01",
                    end_date="2026-06-08",
                )
                if df is None or df.empty:
                    self.logger.warning(f"  {name} 历史为空")
                    continue

                count = 0
                for _, row in df.iterrows():
                    d = str(row.get("日期", ""))[:10]
                    if not d:
                        continue
                    close = float(row.get("收盘", 0) or 0)
                    if close == 0:
                        continue
                    history.append({
                        "file": f"data/history/daily/{hist_file}",
                        "row": {
                            "date": d,
                            "open": float(row.get("开盘", 0) or 0),
                            "high": float(row.get("最高", 0) or 0),
                            "low": float(row.get("最低", 0) or 0),
                            "close": close,
                            "volume": float(row.get("成交量", 0) or 0),
                        },
                        "grain": "daily",
                    })
                    count += 1

                self.logger.info(f"  {name}: {count} 行历史")

            except Exception as e:
                self.logger.warning(f"  {name} 历史采集失败: {e}")

        return history

    def _get_akshare(self):
        try:
            import akshare as ak
            return ak
        except ImportError:
            self.logger.error("akshare 未安装，请执行: pip install akshare")
            return None


def main():
    import sys
    args = sys.argv[1:]

    if "subscribe" in args:
        # 查看可订阅品种
        try:
            import akshare as ak
            df = ak.futures_foreign_commodity_subscribe_exchange_symbol()
            print(df.to_string())
        except Exception as e:
            print(f"获取订阅列表失败: {e}")
        return

    if "gold" in args:
        # 仅黄金
        collector = AKShareFuturesCollector()
        result = collector.collect_realtime()
        if result:
            g = result["snapshot"].get("gold_futures", {})
            print(f"COMEX黄金: {g.get('value')} ({g.get('change_pct'):+.2f}%) @ {g.get('quote_time')}")
        return

    # 默认全量
    result = AKShareFuturesCollector().collect()
    if result:
        for k, v in result["snapshot"].items():
            val = v.get("value", "?")
            print(f"  {k}: {val}")
        print(f"  history: {len(result.get('history', []))} rows")
    else:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()
