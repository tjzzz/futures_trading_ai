#!/usr/bin/env python3
"""
dashboard/app.py — V1 七因子看板
"""

import json
import csv
import io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify

CST = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

app = Flask(__name__)


def read_json(rel_path):
    p = DATA / rel_path
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@app.route("/api/snapshot")
def api_snapshot():
    return jsonify(read_json("current/dashboard_data.json") or {})


@app.route("/api/factors")
def api_factors():
    return jsonify(read_json("factors/current_factors.json") or {})


@app.route("/api/events")
def api_events():
    d = read_json("events/event_tracker.json") or {}
    news = read_json("events/latest_feed.json") or {}
    return jsonify({
        "active_events": d.get("active_events", []),
        "news_count": len(news.get("events", [])),
        "news_fetched_at": news.get("fetched_at", ""),
    })


@app.route("/api/history/<symbol>")
def api_history(symbol):
    path_map = {
        "gold": "history/daily/gold_silver_daily.csv",
        "silver": "history/daily/gold_silver_daily.csv",
        "dxy": "history/daily/dxy.csv",
        "sp500": "history/daily/sp500.csv",
        "vix": "history/daily/vix.csv",
        "tips": "history/daily/tips.csv",
        "treasury": "history/daily/treasury.csv",
    }
    f = path_map.get(symbol)
    if not f:
        return jsonify({"error": "unknown symbol"}), 404
    csv_path = DATA / f
    if not csv_path.exists():
        return jsonify([])
    lines = csv_path.read_text(encoding="utf-8").strip().split("\n")
    if len(lines) < 2:
        return jsonify([])
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    rows = list(reader)
    if symbol in ("gold", "silver"):
        key = "gold_close" if symbol == "gold" else "silver_close"
        vals = [{"d": r["date"], "v": float(r[key])} for r in rows[-90:] if r.get(key)]
    else:
        col = "10yr" if symbol == "treasury" else "close"
        vals = [{"d": r.get("date", ""), "v": float(r.get(col, r.get("value", 0)))} for r in rows[-90:]]
    return jsonify(vals)


@app.route("/api/monitor")
def api_monitor():
    d = read_json("current/dashboard_data.json") or {}
    fields = {}
    for k in ["gold_price", "silver_price", "dxy", "vix", "sp500",
              "treasury_10y", "treasury_30y", "tips_10y",
              "gold_futures", "silver_futures",
              "shfe_gold", "shfe_silver", "usdcnh"]:
        v = d.get(k, {})
        if v:
            fields[k] = {
                "value": v.get("value"),
                "updated_at": v.get("updated_at", v.get("as_of_date", "")),
                "source": v.get("source", ""),
            }
    return jsonify(fields)


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8082
    app.run(host="0.0.0.0", port=port, debug=True)