#!/usr/bin/env python3
"""
统一采集总管

按依赖顺序执行所有采集器，统一合并 snapshot 写入。

数据源状态（2026-06-09）:
  【实时】新浪外盘期货（COMEX 金银）、gold-api（现货）、yfinance（兜底）
  【日频】FRED（SP500/DXY/原油/铜/TIPS）、U.S. Treasury（美债）、CBOE（VIX）、Yahoo（金银日频）、新浪国内期货（沪金沪银）
  【新闻】CNBC/MarketWatch RSS + 本地日历
  【已放弃】AKShare 系列（东方财富被封禁，investing.com API 废弃）

用法:
    python -m collectors.run                   # 全部运行（默认）
    python -m collectors.run realtime          # 仅实时（futures_sina + spot_gold）
    python -m collectors.run daily             # 仅日频
    python -m collectors.run backfill          # 历史回填
"""

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import collectors.spot_gold as spot_gold
import collectors.spot_daily as spot_daily
import collectors.yfinance as yfinance
import collectors.treasury as treasury
import collectors.macro_tips as macro_tips
import collectors.vix as vix_collector
import collectors.macro_index as macro_index
import collectors.macro_nfp as macro_nfp
import collectors.futures_shfe as shfe_fut

# ── 新闻管道（news/ 包）──
import collectors.news.rss as rss_news
import collectors.news.calendar as news_calendar
import collectors.news.topics as news_topics

# ── 主源：新浪外盘期货（COMEX 金银）──
import collectors.futures_sina as sina_fut

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_FILE = PROJECT_ROOT / "data/current/dashboard_data.json"
CST = timezone(timedelta(hours=8))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════
#  后端频控配置
# ══════════════════════════════════════════════════════════════

BACKEND_INTERVAL = {
    "sina":          0.5,    # 新浪财经 — 几乎无限制，秒级轮询可用
    "shmet":         1.0,    # 上海金属网 — 宽松
    "wallstreetcn": 600.0,   # 华尔街见闻 — 10 分钟以上
    "baidu":        120.0,   # 百度财经 — 2 分钟以上
    "goldapi":       1.0,    # gold-api.com — 宽松
    "yfinance":      15.0,   # Yahoo Finance — 严格，频繁触发 429
    "fred":          1.0,    # FRED CSV — 宽松
    "ustreasury":    1.0,    # U.S. Treasury CSV — 宽松
    "cboe":          1.0,    # CBOE CSV — 宽松
    "exchangerate":  1.0,    # ExchangeRate-API — 宽松
    "rss":           30.0,   # RSS Feed — 30 秒以上
    "local":         0.0,    # 本地计算 — 无网络请求
}

# 每个采集器对应的后端（按最严格的后端标明）
COLLECTOR_BACKEND = {
    "futures_sina":   "sina",
    "spot_gold":      "goldapi",
    "spot_daily":     "yfinance",
    "yfinance":       "yfinance",
    "treasury":       "ustreasury",
    "macro_tips":     "fred",
    "macro_nfp":      "fred",
    "vix":            "cboe",
    "macro_index":    "fred",
    "futures_shfe":   "sina",
    "news_rss":       "rss",
    "news_calendar":  "local",
    "news_topics":    "local",
}

_last_call_time: dict[str, float] = defaultdict(float)


def _rate_limit(backend: str):
    """按后端的频控要求等待"""
    if backend == "local":
        return
    interval = BACKEND_INTERVAL.get(backend, 1.0)
    elapsed = time.time() - _last_call_time.get(backend, 0.0)
    if elapsed < interval:
        sleep_time = interval - elapsed
        time.sleep(sleep_time)


# ══════════════════════════════════════════════════════════════

def _log(msg: str):
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def _safe_write_snapshot(updates: dict):
    """原子写入 dashboard_data.json"""
    if not updates:
        return
    data = {}
    if SNAPSHOT_FILE.exists():
        try:
            data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data.update(updates)
    data["global_updated_at"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    tmp = SNAPSHOT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SNAPSHOT_FILE)


def _safe_write_history(history: list):
    """追加/覆盖写入历史 CSV"""
    import csv
    # 按文件分组（收集所有 mode="overwrite" 文件的行，先清空再写）
    file_groups: dict = {}
    for h in history:
        fp = str(PROJECT_ROOT / h["file"])
        if fp not in file_groups:
            file_groups[fp] = {"rows": [], "mode": "a"}
        file_groups[fp]["rows"].append(h["row"])
        if h.get("mode") == "overwrite":
            file_groups[fp]["mode"] = "w"

    for fp_str, group in file_groups.items():
        file_path = Path(fp_str)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        mode = group["mode"]
        rows = group["rows"]
        if not rows:
            continue
        try:
            with open(file_path, mode, newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                if mode == "w":
                    writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            if mode == "w":
                file_label = file_path.name
                _log(f"  ✏️ {file_label}: 覆盖写入 {len(rows)} 行")
        except Exception as e:
            _log(f"  ⚠️ 历史写入失败 {file_path.name}: {e}")


def _run_collector(name: str, collector_func, snapshot: bool = True, history: bool = True,
                   skip_on_fail: bool = False) -> bool:
    """通用采集执行包装"""
    _log(f"采集: {name}")
    t0 = time.time()
    try:
        backend = COLLECTOR_BACKEND.get(name, "local")
        _rate_limit(backend)

        result = collector_func()
        _last_call_time[backend] = time.time()

        if result is None:
            if skip_on_fail:
                _log(f"  ⚠️ {name} 跳过")
                return True
            _log(f"  ❌ {name} 失败")
            return False
        if snapshot and result.get("snapshot"):
            before = len(result["snapshot"])
            _safe_write_snapshot(result["snapshot"])
            _log(f"  ✅ snapshot: {before} 个字段")
        if history and result.get("history"):
            _safe_write_history(result["history"])
            _log(f"  ✅ history: {len(result['history'])} 行")
        elapsed = time.time() - t0
        _log(f"  ✅ {name} 完成 ({elapsed:.1f}s)")
        return True
    except Exception as e:
        if skip_on_fail:
            _log(f"  ⚠️ {name} 异常(已跳过): {e}")
            return True
        _log(f"  ❌ {name} 异常: {e}")
        return False


# ══════════════════════════════════════════════════════════════
#  采集器定义
# ══════════════════════════════════════════════════════════════

REALTIME_COLLECTORS = [
    # ── 主源：COMEX 金银实时（新浪外盘期货，秒级刷新）──
    ("futures_sina",        lambda: sina_fut.AKShareFuturesCollector().collect_realtime(), True, True, False),

    # ── 兜底：gold-api 现货验证 ──
    ("spot_gold",           lambda: spot_gold.GoldSpot().collect(), True, True, True),

    # ── 兜底：yfinance（常 429，跳过不影响）──
    ("yfinance",            lambda: yfinance.YFinanceBatch().collect(), True, True, True),
]

DAILY_COLLECTORS = [
    # ── 兜底：U.S. Treasury 美债收益率 ──
    ("treasury",            lambda: treasury.Treasuries().collect(), True, True, True),

    # ── 兜底：FRED 宏观（TIPS/CPI/PCE/信用利差）──
    ("macro_tips",          lambda: macro_tips.FredCollector().collect(), True, True, False),

    # ── FRED 非农就业（PAYEMS）──
    ("macro_nfp",           lambda: macro_nfp.NfpCollector().collect(), True, True, True),

    # ── 兜底：CBOE VIX ──
    ("vix",                 lambda: vix_collector.CboeVix().collect(), True, True, True),

    # ── 兜底：FRED 指数（SP500/DXY/原油/铜/汇率）──
    ("macro_index",         lambda: macro_index.FallbackCollector().collect(), True, True, True),

    # ── 日频：金银现货（Yahoo GLD/SLV → daily CSV）──
    ("spot_daily",          lambda: spot_daily.SpotDailyCollector().collect(), False, False, True),

    # ── 上期所沪金沪银（新浪国内期货）──
    ("futures_shfe",        lambda: shfe_fut.ChinaFuturesCollector().v1_collect(), True, True, False),

    # ── 新闻管道：RSS → 日历 → 事件汇聚 ──
    ("news_rss",            lambda: rss_news.main(), True, False, True),
    ("news_calendar",       lambda: news_calendar.collect(), True, False, True),
    ("news_topics",         lambda: news_topics.process(), True, False, True),
]


def run_all():
    """执行全部采集器"""
    _log("=" * 50)
    _log("V2 全面数据采集（兜底优先）")
    _log("=" * 50)

    ok = 0
    fail = 0

    _log("\n── 实时采集 ──")
    for name, fn, snap, hist, skip in REALTIME_COLLECTORS:
        if _run_collector(name, fn, snap, hist, skip_on_fail=skip):
            ok += 1
        else:
            fail += 1

    _log("\n── 日频采集 ──")
    for name, fn, snap, hist, skip in DAILY_COLLECTORS:
        if _run_collector(name, fn, snap, hist, skip_on_fail=skip):
            ok += 1
        else:
            fail += 1

    _log("=" * 50)
    _log(f"完成: ✅ {ok} 成功 | ❌ {fail} 失败")
    _log("=" * 50)
    return fail == 0


def run_realtime():
    """仅实时采集"""
    _log("── 实时采集（futures_sina, spot_gold, yfinance）──")
    for name, fn, snap, hist, skip in REALTIME_COLLECTORS:
        _run_collector(name, fn, snap, hist, skip_on_fail=skip)


def run_daily():
    """仅日频采集"""
    _log("── 日频采集 ──")
    for name, fn, snap, hist, skip in DAILY_COLLECTORS:
        _run_collector(name, fn, snap, hist, skip_on_fail=skip)


def run_backfill():
    """历史回填：一次性拉取 2026 年所有日频数据"""
    import collectors.backfill as bf
    _log("── 历史回填 ──")
    bf.main()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V2 统一数据采集总管")
    parser.add_argument("mode", nargs="?", default="all",
                        choices=["all", "realtime", "daily", "backfill"],
                        help="all=全部, realtime=仅实时, daily=仅日频, backfill=历史回填")
    args = parser.parse_args()

    modes = {
        "all": run_all,
        "realtime": run_realtime,
        "daily": run_daily,
        "backfill": run_backfill,
    }
    fn = modes.get(args.mode, run_all)
    ok = fn()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()