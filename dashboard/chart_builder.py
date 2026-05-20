#!/usr/bin/env python3
"""
chart_builder.py — V2 整合版
数据中台绘图工具，从历史CSV读取数据，生成趋势图。

支持多种指标组合，中文标题正常显示。

源自 workspace-trade-ai/collectors/chart_builder.py
V2 变更：路径从 config 解析
"""

import csv
import logging
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import rcParams

logger = logging.getLogger("chart_builder")

try:
    from config import PROJECT_ROOT
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 中文字体 ──────────────────────────────
_FONT_CANDIDATES = [
    # Linux — wqy
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    # Linux — noto
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    # macOS — 系统原生中文
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    # macOS — macOS 15 Sequoia 可能的位置
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/STHeiti.ttf",
    # macOS — Homebrew 安装的 wqy
    "/opt/homebrew/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "/opt/homebrew/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
]

rcParams["axes.unicode_minus"] = False

_CN_FONT_FOUND = os.environ.get("MPL_CN_FONT")
if not _CN_FONT_FOUND:
    for fp in _FONT_CANDIDATES:
        if Path(fp).exists():
            from matplotlib.font_manager import FontProperties
            _CN_FONT = FontProperties(fname=fp)
            _CN_FONT_FOUND = fp
            break
    if not _CN_FONT_FOUND:
        _CN_FONT = None
        _CN_FONT_FOUND = False
else:
    from matplotlib.font_manager import FontProperties
    _CN_FONT = FontProperties(fname=_CN_FONT_FOUND)

rcParams["font.family"] = "sans-serif"

CST = timezone(timedelta(hours=8))
OUTPUT_DIR = PROJECT_ROOT / "dashboard"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def now_cst():
    return datetime.now(CST)


def read_csv(csv_rel: str, date_col="date", val_col=None):
    """读取历史CSV，返回(dates[], values[])"""
    path = PROJECT_ROOT / csv_rel
    if not path.exists():
        logger.warning("文件不存在: %s", path)
        return [], []

    dates, values = [], []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return [], []
        keys = reader.fieldnames

        if not val_col:
            val_col = [k for k in keys if k != date_col][0]

        for row in reader:
            d = row.get(date_col, "")
            if val_col == "ratio":
                v = row.get("ratio", row.get("ratio_close", ""))
            elif isinstance(val_col, list):
                v = {k: row.get(k, "") for k in val_col}
                dates.append(d)
                values.append(v)
                continue
            else:
                v = row.get(val_col, "")

            if d and v:
                try:
                    dates.append(d)
                    values.append(float(v))
                except ValueError:
                    continue

    return dates, values


def parse_date(d: str):
    """兼容多种日期格式"""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(d, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


def filter_days(dates, values, days=90):
    """按天数过滤"""
    cut = now_cst() - timedelta(days=days)
    out_d, out_v = [], []
    for d, v in zip(dates, values):
        dt = parse_date(d)
        if dt and dt >= cut:
            out_d.append(dt)
            out_v.append(v)
    return out_d, out_v


def save_chart(fig, name: str):
    """保存图表到dashboard目录"""
    fname = f"chart_{name}.png"
    path = OUTPUT_DIR / fname
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("图表已保存: %s", path)
    return path


def _cn_set(ax, title, fontsize=16):
    """用FontProperties设置中文标题"""
    if _CN_FONT:
        ax.set_title(title, fontsize=fontsize, fontweight="bold", fontproperties=_CN_FONT)
    else:
        ax.set_title(title, fontsize=fontsize, fontweight="bold")


# ── 各图表函数 ──────────────────────────────

def chart_treasury(days=90):
    """美债收益率曲线"""
    path = PROJECT_ROOT / "data/history/daily/treasury.csv"
    dates, y10, y30, y2, y5 = [], [], [], [], []

    if not path.exists():
        logger.info("无美债数据，尝试从 Treasury 源拉取")
        import requests, io
        url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026"
        r = requests.get(url, timeout=15)
        reader = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            d = parse_date(row.get("Date", ""))
            if d:
                dates.append(d)
                y10.append(float(row.get("10 Yr", 0)))
                y30.append(float(row.get("30 Yr", 0)))
                y2.append(float(row.get("2 Yr", 0)))
                try:
                    y5.append(float(row.get("5 Yr", 0)))
                except:
                    y5.append(0)
        dates.reverse()
        y10.reverse()
        y30.reverse()
        y2.reverse()
        y5.reverse()
    else:
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = parse_date(row.get("date", ""))
                if d:
                    dates.append(d)
                    y10.append(float(row.get("10yr", 0)))
                    y30.append(float(row.get("30yr", 0)))
                    y2.append(float(row.get("2yr", 0)))
                    y5.append(float(row.get("5yr", 0)))

    # 过滤天数
    cut = now_cst() - timedelta(days=days)
    pairs = [(d, a, b, c, e) for d, a, b, c, e in zip(dates, y10, y30, y2, y5) if d >= cut]
    if not pairs:
        logger.warning("过滤后无数据（days=%d）", days)
        return
    dates, y10, y30, y2, y5 = zip(*pairs)

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(dates, y10, label="10Y", linewidth=2, color="#f97316")
    ax.plot(dates, y30, label="30Y", linewidth=2, color="#ef4444")
    ax.plot(dates, y2, label="2Y", linewidth=1.5, color="#3b82f6")
    ax.plot(dates, y5, label="5Y", linewidth=1.5, color="#22c55e")

    ax.axhline(y=4.5, color="#f97316", linestyle="--", alpha=0.5, linewidth=1)
    ax.axhline(y=5.0, color="#ef4444", linestyle="--", alpha=0.5, linewidth=1)
    ax.text(dates[-1], 4.52, "4.5%", fontsize=9, color="#f97316")

    _cn_set(ax, "美债收益率趋势", 16)
    ax.set_ylabel("Yield (%)", fontsize=12)
    ax.legend(fontsize=11, loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate()

    return save_chart(fig, "treasury")


def chart_single(csv_rel, title_cn, title_en, val_col, color, ylabel, days=90, fmt=".2f", date_col="date"):
    """通用单一指标趋势图"""
    dates_raw, values_raw = read_csv(csv_rel, val_col=val_col, date_col=date_col)
    if not dates_raw:
        logger.warning("%s 无数据", title_cn)
        return

    dates, values = filter_days(dates_raw, values_raw, days)
    if not dates:
        parsed = [(parse_date(d), v) for d, v in zip(dates_raw, values_raw)]
        parsed = [(d, v) for d, v in parsed if d is not None]
        if not parsed:
            logger.warning("%s 无有效日期", title_cn)
            return
        dates, values = zip(*parsed)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(dates, values, linewidth=2, color=color)
    ax.fill_between(dates, values, alpha=0.1, color=color)

    latest = values[-1]
    ax.annotate(f"{latest:{fmt}}", xy=(dates[-1], latest),
                xytext=(8, 3), textcoords="offset points",
                fontsize=12, fontweight="bold", color=color)

    _cn_set(ax, title_cn, 16)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()

    return save_chart(fig, csv_rel.split("/")[-1].replace(".csv", ""))


def _read_gold_silver_data(days=90):
    """读取金银数据，优先日线，回退到分钟级"""
    ds, golds = read_csv("data/history/daily/gold_silver_daily.csv", val_col="gold_close")
    _, silvers = read_csv("data/history/daily/gold_silver_daily.csv", val_col="silver_close")
    _, ratios = read_csv("data/history/daily/gold_silver_daily.csv", val_col="ratio_close")

    if not ds:
        ds, golds = read_csv("data/history/minutely/gold_silver_minutely.csv",
                             date_col="timestamp", val_col="gold_usd")
        _, silvers = read_csv("data/history/minutely/gold_silver_minutely.csv",
                              date_col="timestamp", val_col="silver_usd")
        _, ratios = read_csv("data/history/minutely/gold_silver_minutely.csv",
                             date_col="timestamp", val_col="ratio")

    if ds:
        dates = [parse_date(d) for d in ds]
        dates = [d for d in dates if d]
        if dates:
            return dates, golds, silvers, ratios
    return [], [], [], []


def chart_gold_silver(days=90):
    """金银价格+比价三线图"""
    dates, golds, silvers, ratios = _read_gold_silver_data(days)
    if not dates:
        logger.warning("金银无数据")
        return

    cut = now_cst() - timedelta(days=days)
    pairs = [(d, g, s, r) for d, g, s, r in zip(dates, golds, silvers, ratios) if d >= cut]
    if not pairs:
        pairs = list(zip(dates, golds, silvers, ratios))
    dates, golds, silvers, ratios = zip(*pairs)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    ax1.plot(dates, golds, label="Gold (USD/oz)", linewidth=2, color="#f59e0b")
    ax1.plot(dates, silvers, label="Silver (USD/oz)", linewidth=2, color="#94a3b8")
    ax1.set_ylabel("Price (USD)", fontsize=12)
    ax1.legend(fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.annotate(f"${golds[-1]:.2f}", xy=(dates[-1], golds[-1]),
                 fontsize=11, fontweight="bold", color="#f59e0b")
    ax1.annotate(f"${silvers[-1]:.2f}", xy=(dates[-1], silvers[-1]),
                 fontsize=11, fontweight="bold", color="#94a3b8")

    ax2.plot(dates, ratios, linewidth=2, color="#8b5cf6")
    ax2.fill_between(dates, ratios, alpha=0.1, color="#8b5cf6")
    ax2.axhline(y=80, linestyle="--", alpha=0.3, color="#ef4444")
    ax2.axhline(y=50, linestyle="--", alpha=0.3, color="#22c55e")
    ax2.set_ylabel("Ratio", fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.annotate(f"{ratios[-1]:.1f}", xy=(dates[-1], ratios[-1]),
                 fontsize=11, fontweight="bold", color="#8b5cf6")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()

    _cn_set(ax1, "金银价格与比价趋势", 16)

    return save_chart(fig, "gold_silver")


# ── 主入口 ──────────────────────────────

CHARTS = {
    "treasury":    ("美债收益率", chart_treasury),
    "vix":         ("VIX恐慌指数", lambda days=90: chart_single("data/history/daily/vix.csv",
                        "VIX恐慌指数", "VIX Index", "close", "#ef4444", "VIX", days)),
    "dxy":         ("美元指数", lambda days=90: chart_single("data/history/daily/dxy.csv",
                        "美元指数 (DXY)", "US Dollar Index", "value", "#3b82f6", "DXY", days)),
    "tips":        ("实际利率", lambda days=90: chart_single("data/history/daily/tips.csv",
                        "实际利率 (TIPS)", "Real Yield TIPS", "value", "#f97316", "%", days)),
    "sp500":       ("标普500", lambda days=90: chart_single("data/history/daily/sp500.csv",
                        "标普500指数", "S&P 500", "value", "#22c55e", "Index", days)),
    "gsr":         ("金银比", lambda days=90: chart_single("data/history/minutely/gold_silver_minutely.csv",
                        "金银比", "Gold/Silver Ratio", "ratio", "#8b5cf6", "Ratio", days,
                        date_col="timestamp")),
    "gold":        ("伦敦金", lambda days=90: chart_single("data/history/minutely/gold_silver_minutely.csv",
                        "伦敦金价格", "Gold Price", "gold_usd", "#f59e0b", "USD/oz", days, ".2f",
                        date_col="timestamp")),
    "silver":      ("伦敦银", lambda days=90: chart_single("data/history/minutely/gold_silver_minutely.csv",
                        "伦敦银价格", "Silver Price", "silver_usd", "#94a3b8", "USD/oz", days, ".2f",
                        date_col="timestamp")),
    "gold_silver": ("金银比价", chart_gold_silver),
}


def list_charts():
    print("可用的图表类型:")
    for k, (desc, _) in CHARTS.items():
        print(f"  {k:15s} → {desc}")
    print()
    print("用法: python3 -m dashboard.chart_builder <chart_type> [days]")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        list_charts()
        return

    chart_type = sys.argv[1]
    days = 90
    if len(sys.argv) >= 3:
        try:
            days = int(sys.argv[2])
        except ValueError:
            pass

    if chart_type not in CHARTS:
        logger.error("未知图表类型: %s", chart_type)
        list_charts()
        return

    desc, fn = CHARTS[chart_type]
    logger.info("生成图表: %s (近%d天)", desc, days)
    fn(days)


if __name__ == "__main__":
    main()
