#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prediction_stats.py — 可验证假设命中率统计（复盘归因内核）
v2-agent-team M5「复盘归因」可移植内核（纯 Python 标准库 + akshare 可选）。

用途：
  把分析/预案中的可验证假设（H1/H2/H3…）结构化记录，到验证窗口用实时价结算
  方向/区间命中，输出命中率统计 —— 让"判断准不准"用数据说话。

用法：
  python skills/review/scripts/prediction_stats.py --add --label 定价重心切就业 --direction bullish --target silver --price 62.51 --low 60 --high 65 --by 2026-08-08
  python skills/review/scripts/prediction_stats.py --verify [--prices gold,silver]
  python skills/review/scripts/prediction_stats.py --stats
"""

import argparse
import json
import sys
from datetime import datetime, date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # skills/review/scripts → 仓库根
DATA_FILE = REPO_ROOT / "data" / "predictions.json"

DIRECTION_CN = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}


def load() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"hypotheses": []}


def save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_prices() -> dict:
    """akshare 拉当前金银价（现货），失败返回空。"""
    try:
        import akshare as ak
        df = ak.spot_forex_spot_pair("USDX")
        # 兜底：直接用新浪外盘接口取 COMEX 金银
        g = ak.futures_foreign_commodity_realtime(symbol="GC")
        s = ak.futures_foreign_commodity_realtime(symbol="SI")
        gold = float(g["current_price"].iloc[0]) if len(g) else None
        silver = float(s["current_price"].iloc[0]) if len(s) else None
        return {"gold": gold, "silver": silver}
    except Exception as e:
        print(f"[warn] akshare 取价失败: {e}", file=sys.stderr)
        return {}


def verify(h, prices: dict) -> dict:
    """结算单条假设：方向 + 区间命中。"""
    sym = h.get("target_symbol", "silver")
    p = prices.get(sym)
    if p is None:
        return {"status": "no_price", "result": None}
    base = h.get("price_at_analysis")
    direction = h.get("direction")
    rl, rh = h.get("range_low"), h.get("range_high")

    # 方向
    if base and direction != "neutral":
        chg = (p - base) / base
        actual = "bullish" if chg > 0 else "bearish"
        dir_hit = (direction == actual) if abs(chg) > 0.005 else None
    else:
        dir_hit = None

    # 区间
    if rl is not None and rh is not None:
        range_hit = rl <= p <= rh
    else:
        range_hit = None

    return {
        "status": "verified",
        "price_now": round(p, 2),
        "direction_hit": dir_hit,
        "range_hit": range_hit,
        "verified_at": datetime.now().strftime("%Y-%m-%d"),
    }


def main():
    ap = argparse.ArgumentParser(description="可验证假设命中率统计")
    ap.add_argument("--add", action="store_true", help="追加假设")
    ap.add_argument("--label", help="假设标签，如 定价重心切就业")
    ap.add_argument("--direction", choices=["bullish", "bearish", "neutral"], help="方向（对金银）")
    ap.add_argument("--target", choices=["silver", "gold"], default="silver")
    ap.add_argument("--price", type=float, help="分析时价格")
    ap.add_argument("--low", type=float, help="区间下限")
    ap.add_argument("--high", type=float, help="区间上限")
    ap.add_argument("--by", help="验证窗口截止 YYYY-MM-DD")
    ap.add_argument("--verify", action="store_true", help="结算过期未验证假设")
    ap.add_argument("--stats", action="store_true", help="输出统计")
    ap.add_argument("--prices", help="手传当前价 gold,silver（跳过 akshare）")
    args = ap.parse_args()

    data = load()
    hyps = data["hypotheses"]

    if args.add:
        if not all([args.label, args.direction, args.price, args.low, args.high, args.by]):
            ap.error("--add 需要 --label --direction --price --low --high --by")
        h = {
            "id": f"{args.label}-{len(hyps)+1}",
            "created_at": date.today().isoformat(),
            "label": args.label,
            "direction": args.direction,
            "target_symbol": args.target,
            "price_at_analysis": args.price,
            "range_low": args.low,
            "range_high": args.high,
            "verify_by": args.by,
            "verified": False,
            "result": None,
        }
        hyps.append(h)
        save(data)
        print(f"✅ 已记录假设 #{h['id']}（{h['label']}，窗口至 {h['verify_by']}）")
        return

    if args.verify:
        prices = {}
        if args.prices:
            g, s = args.prices.split(",")
            prices = {"gold": float(g), "silver": float(s)}
        else:
            prices = fetch_prices()
        today = date.today().isoformat()
        n_verified = 0
        for h in hyps:
            if h.get("verified") or h.get("verify_by", "") > today:
                continue
            r = verify(h, prices)
            if r["status"] == "verified":
                h["verified"] = True
                h["result"] = r
                n_verified += 1
                dir_txt = {True: "✅方向中", False: "❌方向偏", None: "—方向"}[r["direction_hit"]]
                rng_txt = {True: "✅区间中", False: "❌区间偏", None: "—"}[r["range_hit"]]
                print(f"  #{h['id']} {h['label']}: 现价 {r['price_now']} {dir_txt} / {rng_txt}")
        if n_verified == 0:
            print("无到期未验证假设（或缺少价格）。")
        else:
            save(data)
            print(f"✅ 已结算 {n_verified} 条")
        return

    if args.stats or not (args.add or args.verify):
        verified = [h for h in hyps if h.get("verified") and h.get("result")]
        print(f"📊 假设命中率统计（共 {len(hyps)} 条，已验证 {len(verified)} 条）")
        print("=" * 48)
        if not verified:
            print("尚无已验证假设。用 --add 记录后 --verify 结算。")
            return
        dir_hits = sum(1 for h in verified if h["result"]["direction_hit"] is True)
        dir_total = sum(1 for h in verified if h["result"]["direction_hit"] is not None)
        rng_hits = sum(1 for h in verified if h["result"]["range_hit"] is True)
        rng_total = len(verified)
        print(f"  方向命中率: {dir_hits}/{dir_total} = {dir_hits/dir_total:.0%}" if dir_total else "  方向命中率: 无方向样本")
        print(f"  区间命中率: {rng_hits}/{rng_total} = {rng_hits/rng_total:.0%}" if rng_total else "  区间命中率: —")
        print("")
        print("  未命中明细：")
        for h in verified:
            r = h["result"]
            dir_txt = {True: "✅", False: "❌", None: "—"}[r["direction_hit"]]
            rng_txt = {True: "✅", False: "❌", None: "—"}[r["range_hit"]]
            print(f"    #{h['id']} {h['label']}: 方向{dir_txt} 区间{rng_txt}（{h['direction']}@{h.get('price_at_analysis')} → 现 {r['price_now']}）")
        return


if __name__ == "__main__":
    main()
