#!/usr/bin/env python3
"""
M3 行情概览 — 行情快照生成器（可移植内核）

取数 → 输出结构化快照（JSON + Markdown 一屏速读），供看板"一、行情概览与信息资讯"写回。
核心品种：沪金 / 沪银 / 沪锌（辅助）+ 金银比；附带外盘（现货金/银）与关键宏观（DXY/VIX，尽力而为）。

用法:
    python market_snapshot.py [--json] [--markdown] [--out <path.md>]

输出:
    --json     快照 JSON 到 stdout
    --markdown Markdown 一屏速读到 stdout
    --out      Markdown 同时写文件（默认写 data/snapshots/market_YYYYMMDD_HHMM.md）

依赖: akshare（仅取数层需要；数据解析部分纯标准库）
可移植性: 给别人 = scripts 内核 + requirements（akshare）
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

CST_HOURS = 8

# ============ 取数（akshare，尽力而为，单源失败不阻断整体） ============

def _safe(fn, *args, **kwargs):
    """安全包装：取数失败返回 None，不抛异常中断整体快照"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"error": str(e)}


def fetch_shfe_realtime(symbol: str):
    """akshare futures_zh_realtime：symbol 取 '白银'/'黄金'/'沪锌'"""
    import akshare as ak
    df = ak.futures_zh_realtime(symbol=symbol)
    if df is None or df.empty:
        return None
    # 优先主连（*0），否则取第一行
    main = df[df["symbol"].str.endswith("0")] if "symbol" in df.columns else None
    row = main.iloc[0] if main is not None and not main.empty else df.iloc[0]
    return {
        "name": row.get("name", symbol),
        "trade": _to_float(row.get("trade")),
        "changepercent": _to_float(row.get("changepercent")),
        "open": _to_float(row.get("open")),
        "high": _to_float(row.get("high")),
        "low": _to_float(row.get("low")),
        "volume": _to_int(row.get("volume")),
        "position": _to_int(row.get("position")),
        "ticktime": str(row.get("ticktime", "")),
        "tradedate": str(row.get("tradedate", "")),
    }


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def fetch_spot():
    """现货金/银（gold-api.com 免费源，尽力而为）"""
    import urllib.request

    url = "https://api.gold-api.com/price/XAU"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            g = json.loads(r.read().decode())
        with urllib.request.urlopen(url.replace("XAU", "XAG"), timeout=8) as r:
            s = json.loads(r.read().decode())
        ratio = (g.get("price") / s.get("price")) if g.get("price") and s.get("price") else None
        return {
            "spot_gold": g.get("price"),
            "spot_silver": s.get("price"),
            "gold_silver_ratio": round(ratio, 2) if ratio else None,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_macro():
    """DXY / VIX 尽力而为（新浪实时源）"""
    import urllib.request

    out = {}
    # 新浪美元指数 / VIX
    try:
        url = "https://hq.sinajs.cn/list=DINIW,VIX"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("gbk", errors="ignore")
        for line in raw.strip().splitlines():
            if "DINIW" in line:
                parts = line.split('"')[1].split(",")
                out["dxy"] = _to_float(parts[1]) if len(parts) > 1 else None
            elif "VIX" in line:
                parts = line.split('"')[1].split(",")
                out["vix"] = _to_float(parts[0]) if parts else None
    except Exception as e:
        out["macro_error"] = str(e)
    return out


# ============ 组装快照 ============

def build_snapshot() -> dict:
    now = datetime.now()
    snap = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "shfe": {
            "silver": _safe(fetch_shfe_realtime, "白银"),
            "gold": _safe(fetch_shfe_realtime, "黄金"),
            "zinc": _safe(fetch_shfe_realtime, "沪锌"),
        },
        "spot": _safe(fetch_spot),
        "macro": _safe(fetch_macro),
    }
    return snap


def render_markdown(snap: dict) -> str:
    now = snap["generated_at"]
    lines = [f"## 行情快照 · {now}", ""]
    shfe = snap.get("shfe", {})
    for key, label in [("silver", "沪银"), ("gold", "沪金"), ("zinc", "沪锌")]:
        d = shfe.get(key)
        if not d or "error" in d:
            lines.append(f"- {label}：暂无数据{('（' + d['error'] + '）') if d and 'error' in d else ''}")
            continue
        chg = d.get("changepercent")
        chg_s = f"{chg:+.2f}%" if chg is not None else "—"
        lines.append(
            f"- {label} {d.get('name','')}：{d.get('trade')}（{chg_s}） "
            f"高 {d.get('high')} / 低 {d.get('low')} / 持仓 {d.get('position')} 手 / {d.get('ticktime','')}"
        )
    spot = snap.get("spot")
    if spot and "error" not in spot:
        lines.append("")
        lines.append(
            f"- 现货：金 {spot.get('spot_gold')} / 银 {spot.get('spot_silver')} / 金银比 {spot.get('gold_silver_ratio')}"
        )
    macro = snap.get("macro")
    if macro and "error" not in macro and (macro.get("dxy") or macro.get("vix")):
        lines.append(f"- 宏观：DXY {macro.get('dxy')} / VIX {macro.get('vix')}")
    lines.append("")
    lines.append("> 数据源：akshare（SHFE 实时）+ gold-api + 新浪；生成时点快照，仅作速读参考。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="M3 行情快照")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--markdown", action="store_true", help="输出 Markdown")
    ap.add_argument("--out", type=str, default=None, help="Markdown 写文件路径")
    args = ap.parse_args()

    snap = build_snapshot()

    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return

    md = render_markdown(snap)
    print(md)

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md, encoding="utf-8")
        print(f"\n[written] {p}", file=sys.stderr)
    elif not args.markdown:
        # 默认落盘 data/snapshots/
        repo = Path(__file__).resolve().parents[3]  # skills/market-overview/scripts -> 仓库根
        default = repo / "data" / "snapshots" / f"market_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        default.parent.mkdir(parents=True, exist_ok=True)
        default.write_text(md, encoding="utf-8")
        print(f"\n[written] {default}", file=sys.stderr)


if __name__ == "__main__":
    main()
