#!/usr/bin/env python3
"""
dashboard/app.py — V2 仪表盘 Flask 后端

提供 REST API 对接 analysis 引擎和 data/ 数据中台。
端口：8082

API 端点：
  GET  /                         → 仪表盘主页面
  GET  /api/data                 → 当前数据快照 (dashboard_data.json)
  GET  /api/macro                → 四象限综合分析 (analysis.analyze())
  GET  /api/history?indicator=X&days=Y → 指定指标历史趋势
  POST /api/attribution          → 指标归因查询
  GET  /api/events               → 活跃事件列表
  GET  /api/config               → 读取当前配置
  POST /api/config               → 更新配置
  GET  /api/chart/<type>?days=Y  → matplotlib 图表 PNG
"""

import sys
import json
import csv
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

# ── 项目路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import (
    Flask, jsonify, request, render_template, send_file, abort
)

from config import (
    ANALYSIS_MODE, DATA_DIR, PROJECT_ROOT as CFG_ROOT,
    LLM_API_KEY, LLM_API_URL, LLM_MODEL,
    V2_COMMANDS, COLLECTOR_INTERVALS,
)
from analysis import Analysis
from collectors.rss_news import load_events

# ── 日志 ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dashboard")

# ── Flask App ───────────────────────────────────────────
app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "dashboard" / "templates"),
    static_folder=str(PROJECT_ROOT / "dashboard" / "static"),
)

# 全局分析引擎实例（延迟初始化，避免导入失败）
_analysis_engine: Optional[Analysis] = None

def get_engine() -> Analysis:
    global _analysis_engine
    if _analysis_engine is None:
        try:
            _analysis_engine = Analysis()
            logger.info("分析引擎初始化成功")
        except Exception as e:
            logger.error(f"分析引擎初始化失败: {e}")
            raise
    return _analysis_engine


# ── 工具函数 ────────────────────────────────────────────

def read_json(rel_path: str) -> Dict[str, Any]:
    """安全读取 JSON 文件"""
    path = CFG_ROOT / rel_path
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"读取 {path} 失败: {e}")
        return {}


def read_history_csv(indicator: str, days: int = 90) -> List[Dict[str, Any]]:
    """从 CSV 读取历史数据

    自动处理以下格式：
      - 日期列：YYYY-MM-DD 或 MM/DD/YYYY
      - 数值列：value / close / gold_usd / silver_usd / ratio
      - 多列 CSV（如 treasury: 10yr,20yr,30yr），取 indicator 同名列或首列
    """
    csv_path = DATA_DIR / "history" / "daily" / f"{indicator}.csv"
    # 尝试 minutely 目录
    if not csv_path.exists():
        csv_path = DATA_DIR / "history" / "minutely" / f"{indicator}_minutely.csv"
    if not csv_path.exists():
        return []

    def _parse_date(s: str) -> Optional[datetime]:
        """兼容 YYYY-MM-DD 和 MM/DD/YYYY"""
        s = s[:10].strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    try:
        results = []
        cutoff = datetime.now() - timedelta(days=days)
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []

            # 确定数值列名优先级
            fieldnames_lower = [c.lower().strip() for c in reader.fieldnames]
            value_candidates = ("value", "close", indicator.lower(),
                                "gold_usd", "silver_usd", "ratio", "ratio_close")

            # 找到 row 中第一个存在的候选列
            def _get_val(row_dict) -> Optional[float]:
                for vk in value_candidates:
                    if vk in row_dict and row_dict[vk]:
                        # 处理 treasury 多列情况：若候选列 = indicator 且不存在，跳过
                        try:
                            return float(row_dict[vk])
                        except (ValueError, TypeError):
                            continue
                # fallback: 尝试第一个数值列
                for k, v in row_dict.items():
                    if k in ("date", "timestamp"):
                        continue
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        continue
                return None

            for row in reader:
                date_str = row.get("date") or row.get("timestamp", "")
                if not date_str:
                    continue

                d = _parse_date(date_str)
                if d is None:
                    continue

                val = _get_val(row)

                if d >= cutoff:
                    results.append({
                        "date": d.strftime("%Y-%m-%d"),
                        "value": val,
                    })
        return results[-200:]  # 最多 200 个点
    except Exception as e:
        logger.warning(f"读取历史数据失败 ({indicator}): {e}")
        return []


def get_active_events() -> Dict[str, Any]:
    """获取活跃事件列表"""
    events = load_events()
    return {
        "active_s": [
            {"title": e["title"], "level": "S", "description": (e.get("summary") or e.get("description", ""))[:100]}
            for e in events.get("active_events", []) if e.get("level") == "S"
        ],
        "active_a": [
            {"title": e["title"], "level": "A", "description": (e.get("summary") or e.get("description", ""))[:100]}
            for e in events.get("active_events", []) if e.get("level") == "A"
        ],
        "quadrant_summary": events.get("quadrant_summary", {}),
        "total_s": sum(1 for e in events.get("active_events", []) if e.get("level") == "S"),
        "total_a": sum(1 for e in events.get("active_events", []) if e.get("level") == "A"),
        "updated_at": events.get("fetched_at", ""),
    }


# ── API 路由 ────────────────────────────────────────────

@app.route("/")
def index():
    """仪表盘主页面"""
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    """
    当前数据快照
    返回 dashboard_data.json 的完整内容
    """
    data = read_json("data/current/dashboard_data.json")
    if not data:
        return jsonify({"error": "数据尚未采集", "status": "no_data"}), 200
    return jsonify(data)


@app.route("/api/macro")
def api_macro():
    """
    四象限综合分析
    返回 analysis.analyze() 的结构化结果
    """
    try:
        engine = get_engine()
        result = engine.analyze()
        if hasattr(result, "__dataclass_fields__"):
            # dataclass → dict
            import dataclasses
            result = dataclasses.asdict(result)
        return jsonify(result)
    except Exception as e:
        logger.error(f"宏观分析失败: {e}", exc_info=True)
        return jsonify({"error": str(e), "mode": ANALYSIS_MODE}), 500


@app.route("/api/history")
def api_history():
    """
    指定指标历史趋势

    Query params:
        indicator (str): 指标名称（如 treasury, vix, dxy, gold_silver）
        days (int):      回溯天数，默认 90
    """
    indicator = request.args.get("indicator", "")
    days_str = request.args.get("days", "90")
    try:
        days = int(days_str)
    except ValueError:
        days = 90

    if not indicator:
        return jsonify({"error": "缺少 indicator 参数"}), 400

    # 尝试从 analysis engine 获取
    try:
        engine = get_engine()
        data = engine.get_trend(indicator, days)
    except Exception:
        # fallback: 直接读 CSV
        data = read_history_csv(indicator, days)

    return jsonify({
        "indicator": indicator,
        "days": days,
        "data_points": len(data),
        "data": data,
    })


@app.route("/api/attribution", methods=["POST"])
def api_attribution():
    """
    指标归因查询

    Body (JSON):
        indicator (str): 指标名称
        start (str):     开始日期 (YYYY-MM-DD)
        end (str):       结束日期 (YYYY-MM-DD)
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "请求体不能为空"}), 400

    indicator = body.get("indicator", "")
    start = body.get("start", "")
    end = body.get("end", "")

    if not indicator or not start or not end:
        return jsonify({"error": "缺少必填参数: indicator, start, end"}), 400

    try:
        engine = get_engine()
        result = engine.query_indicator(indicator, start, end)
        return jsonify(result)
    except Exception as e:
        logger.error(f"归因查询失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/events")
def api_events():
    """
    活跃事件列表
    从 event_tracker.json 读取并聚合
    """
    events = get_active_events()
    return jsonify(events)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """
    配置读取/更新

    GET  → 返回当前配置
    POST → 更新配置（仅支持 ANALYSIS_MODE 切换）
    """
    if request.method == "POST":
        body = request.get_json(silent=True)
        if body:
            mode = body.get("analysis_mode", "").lower()
            if mode in ("rules", "llm"):
                # 运行时模式切换：同时更新 config 模块 + 当前模块
                import config as cfg
                cfg.ANALYSIS_MODE = mode
                ANALYSIS_MODE = mode

                logger.info(f"分析模式切换为: {mode}")
                return jsonify({"status": "ok", "analysis_mode": mode})

            elif "v2_commands" in body:
                # 保留扩展接口
                pass

        return jsonify({"status": "ignored", "note": "无有效配置项"})

    # GET: 返回当前配置
    config = {
        "analysis_mode": ANALYSIS_MODE,
        "llm_configured": bool(LLM_API_KEY and LLM_API_URL),
        "llm_model": LLM_MODEL,
        "v2_commands": V2_COMMANDS,
        "collector_intervals": COLLECTOR_INTERVALS,
    }
    return jsonify(config)


@app.route("/api/health")
def api_health():
    """健康检查"""
    data_exists = (CFG_ROOT / "data" / "current" / "dashboard_data.json").exists()
    return jsonify({
        "status": "ok",
        "data_ready": data_exists,
        "analysis_mode": ANALYSIS_MODE,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ── 启动 ────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="期货交易系统 — 仪表盘")
    parser.add_argument("--port", "-p", type=int, default=8082,
                        help="服务端口（默认 8082）")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="开启调试模式")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  期货 AI 交易体系 — 仪表盘 V2")
    logger.info("=" * 60)
    logger.info(f"  监听端口: {args.port}")
    logger.info(f"  分析模式: {ANALYSIS_MODE}")
    logger.info(f"  仪表盘:   http://localhost:{args.port}")
    logger.info(f"  API:      http://localhost:{args.port}/api/data")
    logger.info("=" * 60)

    app.run(host="127.0.0.1", port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
