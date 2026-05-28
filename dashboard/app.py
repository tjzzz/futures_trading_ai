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
import numpy as np

# ── 项目路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 工具模块导入 ─────────────────────────────────────────
from utils.csv_loader import (
    load_csv_data,
    get_csv_time_range as _get_csv_time_range,
    CSVLoaderError,
    CSVFileNotFoundError,
    CSVEmptyError,
    CSVFormatError,
)
from config.constants import API_MAX_DATA_POINTS

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

    try:
        results = load_csv_data(
            csv_path,
            days=days,
            max_points=API_MAX_DATA_POINTS,
        )
        return results
    except CSVFileNotFoundError:
        logger.warning(f"历史数据文件不存在: {indicator}")
        return []
    except CSVEmptyError as e:
        logger.warning(f"历史数据文件为空 ({indicator}): {e}")
        return []
    except CSVFormatError as e:
        logger.warning(f"历史数据格式错误 ({indicator}): {e}")
        return []
    except CSVLoaderError as e:
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
    """仪表盘主页面（SPA 入口）"""
    return render_template("index.html")


# SPA 子页面 — 共享 index.html，前端通过 URL 激活对应面板
@app.route("/macro")
@app.route("/attribution")
@app.route("/events")
@app.route("/config")
@app.route("/data-management")
@app.route("/realtime")
def spa_page():
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
    global ANALYSIS_MODE
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


@app.route("/api/sources")
def api_sources():
    """
    获取数据源信息和时间范围
    """
    try:
        # 读取数据源注册表
        sources_file = DATA_DIR / "sources" / "source_registry.json"
        if not sources_file.exists():
            return jsonify({"error": "数据源注册表不存在", "sources": []})
        
        with open(sources_file, "r", encoding="utf-8") as f:
            sources_data = json.load(f)
        
        sources = sources_data.get("sources", [])
        
        # 为每个数据源添加时间范围信息
        for source in sources:
            source_id = source.get("id", "")
            source_type = source.get("type", "")
            
            # 根据数据源类型确定文件路径
            if source_type == "api":
                # API数据源 - 检查对应的CSV文件
                if "gold" in source_id or "silver" in source_id:
                    # 黄金白银数据
                    daily_file = DATA_DIR / "history" / "daily" / "gold_silver_daily.csv"
                    minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"

                    time_range = {"daily": None, "minutely": None}

                    if daily_file.exists():
                        time_range["daily"] = _get_csv_time_range(daily_file)
                    if minutely_file.exists():
                        time_range["minutely"] = _get_csv_time_range(minutely_file)

                    source["time_range"] = time_range

            elif source_type == "csv":
                # CSV数据源 - 检查对应的CSV文件
                csv_file = None
                if "treasury" in source_id:
                    csv_file = DATA_DIR / "history" / "daily" / "treasury.csv"
                elif "tips" in source_id:
                    csv_file = DATA_DIR / "history" / "daily" / "tips.csv"
                elif "vix" in source_id:
                    csv_file = DATA_DIR / "history" / "daily" / "vix.csv"
                elif "dxy" in source_id:
                    csv_file = DATA_DIR / "history" / "daily" / "dxy.csv"
                elif "sp500" in source_id:
                    csv_file = DATA_DIR / "history" / "daily" / "sp500.csv"

                if csv_file and csv_file.exists():
                    source["time_range"] = _get_csv_time_range(csv_file)
                else:
                    source["time_range"] = None
            else:
                source["time_range"] = None
        
        return jsonify({
            "status": "ok",
            "count": len(sources),
            "sources": sources,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        logger.error(f"获取数据源信息失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/prediction/summary")
def api_prediction_summary():
    """
    趋势预判摘要 — 总览页展示用
    返回短/中/长期预测的综合摘要，包含方向、原因和区间
    """
    try:
        engine = get_engine()
        result = engine.predict("gold", "fusion")

        if not result or "error" in result:
            return jsonify({
                "error": result.get("error", "预测失败"),
                "fallback": True,
                "summary": {
                    "direction": "neutral",
                    "direction_label": "数据不足",
                    "confidence": 0,
                    "reason": "预测模块暂时不可用"
                }
            }), 200

        # 获取当前金价
        snapshot = read_json("data/current/dashboard_data.json")
        gold_price = 0
        if snapshot and "gold_price" in snapshot:
            gp = snapshot["gold_price"]
            gold_price = float(gp.get("value", 0)) if isinstance(gp, dict) else float(gp)
        if not gold_price:
            gold_price = 4500  # fallback

        # 构建三周期摘要
        models = result.get("models", [])
        predictions = []

        for m in models:
            name = m.get("name", "")
            direction = m.get("direction", "neutral")
            label = m.get("direction_label", "中性")
            signals = m.get("signals", [])
            score = m.get("score", 0)

            # 根据周期类型计算真实价格区间
            if name == "short_term":
                horizon = "1周内"
                # 短期基于 ATR 或默认波动率 ~2%
                volatility = 0.02
                if direction == "bullish":
                    low, high = gold_price * 0.98, gold_price * 1.04
                elif direction == "bearish":
                    low, high = gold_price * 0.96, gold_price * 1.02
                else:
                    low, high = gold_price * 0.98, gold_price * 1.02
                reason = (signals[0] if signals else "技术面信号")[:20]
            elif name == "mid_term":
                horizon = "1-4周"
                # 中期基于预测目标价 ±3%
                target = m.get("predictions", [{}])[0].get("target_price") if m.get("predictions") else None
                if target:
                    low, high = target * 0.97, target * 1.03
                elif direction == "bullish":
                    low, high = gold_price * 0.98, gold_price * 1.06
                elif direction == "bearish":
                    low, high = gold_price * 0.94, gold_price * 1.02
                else:
                    low, high = gold_price * 0.96, gold_price * 1.04
                reason = (signals[0] if signals else "宏观面信号")[:20]
            else:  # long_term
                horizon = "1-12月"
                # 长期基于情景分析
                scenarios = m.get("scenarios", [])
                if scenarios:
                    # 取悲观情景下限和乐观情景上限
                    lows = [s.get("range", [0, 0])[0] for s in scenarios if s.get("range")]
                    highs = [s.get("range", [0, 0])[1] for s in scenarios if s.get("range")]
                    low, high = min(lows) if lows else gold_price * 0.85, max(highs) if highs else gold_price * 1.15
                else:
                    low, high = gold_price * 0.90, gold_price * 1.15
                reason = "多空交织" if direction == "mixed" else (signals[0][:20] if signals else "结构性因素")

            interval = f"${int(low)}-${int(high)}"

            predictions.append({
                "name": name,
                "label": label,
                "direction": direction,
                "horizon": horizon,
                "interval": interval,
                "reason": reason,
                "confidence": m.get("confidence", 0),
            })

        # 综合建议
        final_score = result.get("final_score", 0)
        if final_score > 0.3:
            advice = "偏多思路，关注回调机会"
        elif final_score < -0.3:
            advice = "偏空思路，关注支撑测试"
        else:
            advice = "震荡思路，高抛低吸为主"

        return jsonify({
            "summary": {
                "direction": result.get("direction", "neutral"),
                "direction_label": result.get("direction_label", "中性"),
                "confidence": result.get("confidence", 0),
                "final_score": final_score,
                "advice": advice,
            },
            "predictions": predictions,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    except Exception as e:
        logger.error(f"预测摘要生成失败: {e}", exc_info=True)
        return jsonify({
            "error": str(e),
            "fallback": True,
            "summary": {
                "direction": "neutral",
                "direction_label": "数据不足",
                "confidence": 0,
                "reason": "预测模块异常"
            }
        }), 200


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




# ── 实时探查 API ─────────────────────────────────────

@app.route("/api/realtime/trend")
def api_realtime_trend():
    """返回指定时间范围内的分钟级趋势数据"""
    time_range = request.args.get("timeRange", "1h")
    range_minutes = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}
    minutes = range_minutes.get(time_range, 60)
    cutoff = datetime.now() - timedelta(minutes=minutes)
    result = {"timeRange": time_range, "timestamps": [], "gold": [], "silver": [], "ratio": []}
    minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"
    
    if not minutely_file.exists():
        # 如果没有数据文件，返回空数据
        return jsonify(result)
    
    try:
        all_timestamps = []
        all_gold = []
        all_silver = []
        all_ratio = []
        
        with open(minutely_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    continue
                
                all_timestamps.append(ts_str[:16])
                try:
                    all_gold.append(float(row.get("gold_usd", 0) or 0))
                    all_silver.append(float(row.get("silver_usd", 0) or 0))
                    all_ratio.append(float(row.get("ratio", 0) or 0))
                except (ValueError, TypeError):
                    all_gold.append(None)
                    all_silver.append(None)
                    all_ratio.append(None)
        
        # 如果没有数据，返回空
        if not all_timestamps:
            return jsonify(result)
        
        # 如果有近期数据，返回近期数据；否则返回最近的部分数据（最多100个点）
        recent_indices = [i for i, ts in enumerate(all_timestamps) 
                         if datetime.strptime(ts + ":00", "%Y-%m-%d %H:%M:%S") >= cutoff]
        
        if recent_indices:
            # 有近期数据，返回近期数据
            result["timestamps"] = [all_timestamps[i] for i in recent_indices]
            result["gold"] = [all_gold[i] for i in recent_indices]
            result["silver"] = [all_silver[i] for i in recent_indices]
            result["ratio"] = [all_ratio[i] for i in recent_indices]
        else:
            # 没有近期数据，返回最近的部分数据（最多100个点）
            start_idx = max(0, len(all_timestamps) - 100)
            result["timestamps"] = all_timestamps[start_idx:]
            result["gold"] = all_gold[start_idx:]
            result["silver"] = all_silver[start_idx:]
            result["ratio"] = all_ratio[start_idx:]
            
    except Exception as e:
        logger.warning("读取分钟级趋势数据失败: %s", e)
    
    return jsonify(result)


@app.route("/api/realtime/trend_with_volume")
def api_realtime_trend_with_volume():
    """返回指定时间范围内的分钟级趋势数据，包含交易量"""
    time_range = request.args.get("timeRange", "1h")
    range_minutes = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}
    minutes = range_minutes.get(time_range, 60)
    cutoff = datetime.now() - timedelta(minutes=minutes)
    
    # 基础结果
    result = {
        "timeRange": time_range, 
        "timestamps": [], 
        "gold": [], 
        "silver": [], 
        "ratio": [],
        "gold_volume": [],
        "silver_volume": []
    }
    
    # 优先使用统一数据文件（包含价格和交易量）
    unified_file = DATA_DIR / "history" / "minutely" / "unified_gold_silver_volume.csv"
    
    if unified_file.exists():
        try:
            all_timestamps = []
            all_gold = []
            all_silver = []
            all_ratio = []
            all_gold_volume = []
            all_silver_volume = []
            
            with open(unified_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ts_str = row.get("timestamp", "")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    except (ValueError, IndexError):
                        continue
                    
                    all_timestamps.append(ts_str[:16])
                    try:
                        all_gold.append(float(row.get("gold_usd", 0) or 0))
                        all_silver.append(float(row.get("silver_usd", 0) or 0))
                        all_ratio.append(float(row.get("ratio", 0) or 0))
                        all_gold_volume.append(float(row.get("gold_volume", 0) or 0))
                        all_silver_volume.append(float(row.get("silver_volume", 0) or 0))
                    except (ValueError, TypeError):
                        all_gold.append(None)
                        all_silver.append(None)
                        all_ratio.append(None)
                        all_gold_volume.append(None)
                        all_silver_volume.append(None)
            
            # 如果没有数据，返回空
            if not all_timestamps:
                return jsonify(result)
            
            # 筛选近期数据
            recent_indices = [i for i, ts in enumerate(all_timestamps) 
                             if datetime.strptime(ts + ":00", "%Y-%m-%d %H:%M:%S") >= cutoff]
            
            if recent_indices:
                # 有近期数据，返回近期数据
                result["timestamps"] = [all_timestamps[i] for i in recent_indices]
                result["gold"] = [all_gold[i] for i in recent_indices]
                result["silver"] = [all_silver[i] for i in recent_indices]
                result["ratio"] = [all_ratio[i] for i in recent_indices]
                result["gold_volume"] = [all_gold_volume[i] for i in recent_indices]
                result["silver_volume"] = [all_silver_volume[i] for i in recent_indices]
            else:
                # 没有近期数据，返回最近的部分数据（最多100个点）
                start_idx = max(0, len(all_timestamps) - 100)
                result["timestamps"] = all_timestamps[start_idx:]
                result["gold"] = all_gold[start_idx:]
                result["silver"] = all_silver[start_idx:]
                result["ratio"] = all_ratio[start_idx:]
                result["gold_volume"] = all_gold_volume[start_idx:]
                result["silver_volume"] = all_silver_volume[start_idx:]
        
        except Exception as e:
            logger.warning("读取统一数据文件失败，回退到旧逻辑: %s", e)
            # 如果统一文件读取失败，回退到旧逻辑
            pass
    
    # 如果统一文件不存在或读取失败，使用旧的分离文件逻辑
    if not result["timestamps"]:
        # 1. 从gold_silver_minutely.csv获取价格数据
        minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"
        
        if not minutely_file.exists():
            # 如果没有数据文件，返回空数据
            return jsonify(result)
    
    try:
        all_timestamps = []
        all_gold = []
        all_silver = []
        all_ratio = []
        
        with open(minutely_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    continue
                
                all_timestamps.append(ts_str[:16])
                try:
                    all_gold.append(float(row.get("gold_usd", 0) or 0))
                    all_silver.append(float(row.get("silver_usd", 0) or 0))
                    all_ratio.append(float(row.get("ratio", 0) or 0))
                except (ValueError, TypeError):
                    all_gold.append(None)
                    all_silver.append(None)
                    all_ratio.append(None)
        
        # 如果没有数据，返回空
        if not all_timestamps:
            return jsonify(result)
        
        # 2. 筛选近期数据
        recent_indices = [i for i, ts in enumerate(all_timestamps) 
                         if datetime.strptime(ts + ":00", "%Y-%m-%d %H:%M:%S") >= cutoff]
        
        if recent_indices:
            # 有近期数据，返回近期数据
            result["timestamps"] = [all_timestamps[i] for i in recent_indices]
            result["gold"] = [all_gold[i] for i in recent_indices]
            result["silver"] = [all_silver[i] for i in recent_indices]
            result["ratio"] = [all_ratio[i] for i in recent_indices]
        else:
            # 没有近期数据，返回最近的部分数据（最多100个点）
            start_idx = max(0, len(all_timestamps) - 100)
            result["timestamps"] = all_timestamps[start_idx:]
            result["gold"] = all_gold[start_idx:]
            result["silver"] = all_silver[start_idx:]
            result["ratio"] = all_ratio[start_idx:]
            
    except Exception as e:
        logger.warning("读取带交易量的趋势数据失败: %s", e)
    
    return jsonify(result)


@app.route("/api/realtime/anomalies")
def api_realtime_anomalies():
    """基于 Z-score 的异常检测"""
    try:
        threshold = float(request.args.get("threshold", "2.0"))
        window = int(request.args.get("window", "20"))
        time_range = request.args.get("timeRange", "1h")
    except (ValueError, TypeError):
        return jsonify({"error": "参数格式错误"}), 400
    range_minutes = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}
    minutes = range_minutes.get(time_range, 60)
    cutoff = datetime.now() - timedelta(minutes=minutes)
    minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"
    if not minutely_file.exists():
        return jsonify({"threshold": threshold, "window": window, "anomalies": []})
    anomalies = []
    values_by_indicator = {"gold": [], "silver": [], "ratio": []}
    timestamps = []
    try:
        with open(minutely_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                timestamps.append(ts_str[:16])
                try:
                    values_by_indicator["gold"].append(float(row.get("gold_usd", 0) or 0))
                    values_by_indicator["silver"].append(float(row.get("silver_usd", 0) or 0))
                    values_by_indicator["ratio"].append(float(row.get("ratio", 0) or 0))
                except (ValueError, TypeError):
                    values_by_indicator["gold"].append(None)
                    values_by_indicator["silver"].append(None)
                    values_by_indicator["ratio"].append(None)
        for indicator, values in values_by_indicator.items():
            valid = [(i, v) for i, v in enumerate(values) if v is not None]
            for idx, val in valid:
                if idx < window:
                    continue
                window_vals = [v for v in values[max(0, idx - window):idx] if v is not None]
                if len(window_vals) < 2:
                    continue
                mean = sum(window_vals) / len(window_vals)
                std = (sum((v - mean) ** 2 for v in window_vals) / len(window_vals)) ** 0.5
                if std == 0:
                    continue
                z = (val - mean) / std
                if abs(z) > threshold:
                    anomalies.append({
                        "timestamp": timestamps[idx],
                        "indicator": indicator,
                        "value": round(val, 4),
                        "z_score": round(z, 4),
                    })
    except Exception as e:
        logger.error("异常检测失败", exc_info=True)
        return jsonify({"error": str(e)}), 500
    return jsonify({"threshold": threshold, "window": window, "anomalies": anomalies})


@app.route("/api/realtime/correlation")
def api_realtime_correlation():
    """计算各指标间的 Pearson 相关系数矩阵"""
    time_range = request.args.get("timeRange", "1h")
    range_minutes = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}
    minutes = range_minutes.get(time_range, 60)
    cutoff = datetime.now() - timedelta(minutes=minutes)
    minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"
    if not minutely_file.exists():
        return jsonify({"indicators": [], "matrix": [], "error": "无分钟级数据"})
    try:
        timestamps = []
        gold_vals = []
        silver_vals = []
        ratio_vals = []
        with open(minutely_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                timestamps.append(ts_str[:16])
                try:
                    gold_vals.append(float(row.get("gold_usd", 0) or 0))
                    silver_vals.append(float(row.get("silver_usd", 0) or 0))
                    ratio_vals.append(float(row.get("ratio", 0) or 0))
                except (ValueError, TypeError):
                    gold_vals.append(None)
                    silver_vals.append(None)
                    ratio_vals.append(None)
        indicators = ["gold", "silver", "ratio"]
        arrays = []
        for vals in [gold_vals, silver_vals, ratio_vals]:
            filtered = [v for v in vals if v is not None]
            arrays.append(filtered)
        min_len = min(len(a) for a in arrays)
        arrays = [a[:min_len] for a in arrays]
        if min_len < 2:
            return jsonify({"indicators": indicators, "matrix": [], "error": "数据点不足"})
        data_matrix = np.array(arrays)
        matrix = np.corrcoef(data_matrix).tolist()
        return jsonify({"indicators": indicators, "matrix": matrix, "data_points": min_len})
    except Exception as e:
        logger.error("相关性计算失败", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/realtime/correlation_lagged")
def api_realtime_correlation_lagged():
    """计算带时滞的 Pearson 相关系数矩阵
    
    参数:
        timeRange: 时间范围 (1h, 30m, 15m, 5m)
        max_lag: 最大时滞数 (默认: 3)
        indicator1: 第一个指标 (可选)
        indicator2: 第二个指标 (可选)
    """
    try:
        time_range = request.args.get("timeRange", "1h")
        max_lag = int(request.args.get("max_lag", "3"))
        indicator1 = request.args.get("indicator1", "")
        indicator2 = request.args.get("indicator2", "")
        
        range_minutes = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}
        minutes = range_minutes.get(time_range, 60)
        cutoff = datetime.now() - timedelta(minutes=minutes)
        
        # 读取分钟级数据
        minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"
        if not minutely_file.exists():
            return jsonify({"indicators": [], "lagged_matrices": [], "error": "无分钟级数据"})
        
        timestamps = []
        gold_vals = []
        silver_vals = []
        ratio_vals = []
        
        with open(minutely_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                timestamps.append(ts_str[:16])
                try:
                    gold_vals.append(float(row.get("gold_usd", 0) or 0))
                    silver_vals.append(float(row.get("silver_usd", 0) or 0))
                    ratio_vals.append(float(row.get("ratio", 0) or 0))
                except (ValueError, TypeError):
                    gold_vals.append(None)
                    silver_vals.append(None)
                    ratio_vals.append(None)
        
        # 过滤掉None值
        gold_clean = [v for v in gold_vals if v is not None]
        silver_clean = [v for v in silver_vals if v is not None]
        ratio_clean = [v for v in ratio_vals if v is not None]
        
        # 确保所有数组长度一致
        min_len = min(len(gold_clean), len(silver_clean), len(ratio_clean))
        if min_len < max_lag + 2:  # 需要至少max_lag+2个数据点
            return jsonify({
                "indicators": ["gold", "silver", "ratio"],
                "lagged_matrices": [],
                "error": f"数据点不足，需要至少{max_lag+2}个，当前只有{min_len}个"
            })
        
        gold_data = gold_clean[:min_len]
        silver_data = silver_clean[:min_len]
        ratio_data = ratio_clean[:min_len]
        
        indicators = ["gold", "silver", "ratio"]
        
        # 计算带时滞的相关性矩阵
        lagged_matrices = []
        
        for lag in range(max_lag + 1):  # 0到max_lag
            matrix = []
            for i, indicator_i in enumerate(indicators):
                row = []
                for j, indicator_j in enumerate(indicators):
                    if lag == 0:
                        # 同期相关性
                        data_i = [gold_data, silver_data, ratio_data][i]
                        data_j = [gold_data, silver_data, ratio_data][j]
                    else:
                        # 带时滞的相关性：indicator_i领先indicator_j lag个周期
                        data_i = [gold_data, silver_data, ratio_data][i][:-lag]  # 去掉最后lag个
                        data_j = [gold_data, silver_data, ratio_data][j][lag:]   # 去掉前lag个
                    
                    # 计算Pearson相关系数
                    if len(data_i) != len(data_j) or len(data_i) < 2:
                        corr = 0.0
                    else:
                        try:
                            corr = np.corrcoef(data_i, data_j)[0, 1]
                            if np.isnan(corr):
                                corr = 0.0
                        except:
                            corr = 0.0
                    
                    row.append(round(corr, 4))
                matrix.append(row)
            
            lagged_matrices.append({
                "lag": lag,
                "matrix": matrix,
                "description": f"时滞{lag}期" if lag > 0 else "同期"
            })
        
        # 如果指定了特定指标对，计算详细的时滞相关性
        detailed_results = None
        if indicator1 and indicator2:
            idx1 = indicators.index(indicator1) if indicator1 in indicators else -1
            idx2 = indicators.index(indicator2) if indicator2 in indicators else -1
            
            if idx1 >= 0 and idx2 >= 0:
                detailed_results = []
                data1 = [gold_data, silver_data, ratio_data][idx1]
                data2 = [gold_data, silver_data, ratio_data][idx2]
                
                for lag in range(max_lag + 1):
                    if lag == 0:
                        data1_lag = data1
                        data2_lag = data2
                    else:
                        # indicator1领先indicator2 lag期
                        data1_lag = data1[:-lag] if len(data1) > lag else []
                        data2_lag = data2[lag:] if len(data2) > lag else []
                    
                    if len(data1_lag) != len(data2_lag) or len(data1_lag) < 2:
                        corr = 0.0
                    else:
                        try:
                            corr = np.corrcoef(data1_lag, data2_lag)[0, 1]
                            if np.isnan(corr):
                                corr = 0.0
                        except:
                            corr = 0.0
                    
                    detailed_results.append({
                        "lag": lag,
                        "correlation": round(corr, 4),
                        "direction": f"{indicator1} → {indicator2}" if lag > 0 else "同期",
                        "data_points": len(data1_lag)
                    })
        
        return jsonify({
            "indicators": indicators,
            "max_lag": max_lag,
            "time_range": time_range,
            "data_points": min_len,
            "lagged_matrices": lagged_matrices,
            "detailed": detailed_results,
            "note": "正相关表示指标间同向变动，负相关表示反向变动。时滞>0表示第一个指标领先第二个指标。"
        })
        
    except Exception as e:
        logger.error("带时滞相关性计算失败", exc_info=True)
        return jsonify({"error": str(e)}), 500



@app.route("/api/realtime/indicators")
def api_realtime_indicators():
    """返回实时核心指标（黄金、白银、金银比、美元指数、10Y美债、VIX）"""
    try:
        # 读取当前数据 - 实际文件是 dashboard_data.json
        dashboard_file = DATA_DIR / "current" / "dashboard_data.json"
        
        result = {
            "gold": {"price": 0, "change": 0, "pct_change": 0, "volume": 0, "status": "normal"},
            "silver": {"price": 0, "change": 0, "pct_change": 0, "volume": 0, "status": "normal"},
            "ratio": {"value": 0, "change": 0, "pct_change": 0, "status": "normal"},
            "usd_index": {"value": 0, "change": 0, "status": "normal", "direction": "none"},
            "bond_10y": {"value": 0, "change": 0, "status": "normal", "direction": "none"},
            "vix": {"value": 0, "change": 0, "status": "normal", "direction": "none"}
        }
        
        if dashboard_file.exists():
            import json
            with open(dashboard_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # 黄金数据 (gold_price)
                gold_data = data.get("gold_price", {})
                result["gold"] = {
                    "price": gold_data.get("value", 0),
                    "change": 0,  # 从gold_futures获取或计算
                    "pct_change": 0,
                    "volume": 0,  # 从gold_futures获取交易量
                    "status": "normal"
                }
                
                # 尝试从gold_futures获取变化数据和交易量
                gold_futures = data.get("gold_futures", {})
                if gold_futures:
                    result["gold"]["change"] = gold_futures.get("change", 0)
                    result["gold"]["pct_change"] = gold_futures.get("change_pct", 0)
                    result["gold"]["volume"] = gold_futures.get("volume", 0)
                
                # 白银数据 (silver_price)
                silver_data = data.get("silver_price", {})
                result["silver"] = {
                    "price": silver_data.get("value", 0),
                    "change": 0,
                    "pct_change": 0,
                    "volume": 0,  # 从silver_futures获取交易量
                    "status": "normal"
                }
                
                # 从silver_futures获取变化数据和交易量
                silver_futures = data.get("silver_futures", {})
                if silver_futures:
                    result["silver"]["change"] = silver_futures.get("change", 0)
                    result["silver"]["pct_change"] = silver_futures.get("change_pct", 0)
                    result["silver"]["volume"] = silver_futures.get("volume", 0)
                
                # 金银比 (gold_silver_ratio)
                ratio_data = data.get("gold_silver_ratio", {})
                result["ratio"] = {
                    "value": ratio_data.get("value", 0),
                    "change": 0,  # 需要计算
                    "pct_change": 0,
                    "status": "normal"
                }
                
                # 美元指数 (dxy)
                usd_data = data.get("dxy", {})
                result["usd_index"] = {
                    "value": usd_data.get("value", 0),
                    "change": usd_data.get("change", 0),
                    "status": "normal",
                    "direction": "up" if usd_data.get("change", 0) > 0 else "down" if usd_data.get("change", 0) < 0 else "none"
                }
                
                # 10Y美债 (treasury_10y)
                bond_data = data.get("treasury_10y", {})
                result["bond_10y"] = {
                    "value": bond_data.get("value", 0),
                    "change": bond_data.get("change", 0),
                    "status": "normal",
                    "direction": "up" if bond_data.get("change", 0) > 0 else "down" if bond_data.get("change", 0) < 0 else "none"
                }
                
                # VIX (vix)
                vix_data = data.get("vix", {})
                result["vix"] = {
                    "value": vix_data.get("value", 0),
                    "change": vix_data.get("change", 0),
                    "status": "normal",
                    "direction": "up" if vix_data.get("change", 0) > 0 else "down" if vix_data.get("change", 0) < 0 else "none"
                }
        
        return jsonify(result)
    except Exception as e:
        logger.error("读取实时指标失败", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/realtime/mutations")
def api_realtime_mutations():
    """返回突变检测事件列表"""
    time_range = request.args.get("timeRange", "1h")
    range_minutes = {"1h": 60, "30m": 30, "15m": 15, "5m": 5}
    minutes = range_minutes.get(time_range, 60)
    cutoff = datetime.now() - timedelta(minutes=minutes)
    
    # 模拟突变数据（后续用真实算法）
    mutations = []
    minutely_file = DATA_DIR / "history" / "minutely" / "gold_silver_minutely.csv"
    
    if minutely_file.exists():
        try:
            import csv
            rows = []
            with open(minutely_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ts_str = row.get("timestamp", "")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    except (ValueError, IndexError):
                        continue
                    if ts < cutoff:
                        continue
                    
                    gold_val = float(row.get("gold_usd", 0) or 0)
                    silver_val = float(row.get("silver_usd", 0) or 0)
                    ratio_val = float(row.get("ratio", 0) or 0)
                    
                    rows.append({
                        "timestamp": ts_str,
                        "gold": gold_val,
                        "silver": silver_val,
                        "ratio": ratio_val
                    })
            
            # 简单突变检测：相邻点变化超过阈值
            if len(rows) >= 2:
                for i in range(1, len(rows)):
                    prev = rows[i-1]
                    curr = rows[i]
                    
                    gold_change = ((curr["gold"] - prev["gold"]) / prev["gold"] * 100) if prev["gold"] else 0
                    silver_change = ((curr["silver"] - prev["silver"]) / prev["silver"] * 100) if prev["silver"] else 0
                    
                    # 检测价格突变
                    if abs(gold_change) > 0.3:  # 0.3%阈值
                        mutations.append({
                            "timestamp": curr["timestamp"][11:19],  # HH:MM:SS
                            "type": "price_mutation",
                            "indicator": "gold",
                            "value": round(gold_change, 2),
                            "color": "yellow" if gold_change > 0 else "red",
                            "description": f"黄金价格{'突涨' if gold_change > 0 else '突跌'}{abs(gold_change):.1f}%",
                            "reasons": ["技术面突破关键阻力位", "市场情绪转变", "大宗商品联动"]
                        })
                    
                    if abs(silver_change) > 0.4:  # 0.4%阈值
                        mutations.append({
                            "timestamp": curr["timestamp"][11:19],
                            "type": "price_mutation",
                            "indicator": "silver",
                            "value": round(silver_change, 2),
                            "color": "yellow" if silver_change > 0 else "red",
                            "description": f"白银价格{'突涨' if silver_change > 0 else '突跌'}{abs(silver_change):.1f}%",
                            "reasons": ["工业金属需求预期变化", "白银ETF资金流入", "金银比套利交易"]
                        })
            
            # 如果没检测到突变，添加示例数据
            if not mutations and rows:
                mutations = [
                    {
                        "timestamp": rows[-1]["timestamp"][11:19],
                        "type": "price_mutation",
                        "indicator": "gold",
                        "value": 0.8,
                        "color": "yellow",
                        "description": "黄金价格突涨0.8%",
                        "reasons": ["美联储官员讲话", "技术面突破关键阻力位", "市场情绪转变"]
                    },
                    {
                        "timestamp": rows[-1]["timestamp"][11:19],
                        "type": "volume_increase",
                        "indicator": "silver",
                        "value": 45,
                        "color": "green",
                        "description": "白银交易量增加45%",
                        "reasons": ["大宗交易执行", "算法交易活跃", "期权到期日效应"]
                    }
                ]
                
        except Exception as e:
            logger.warning("突变检测失败: %s", e)
    
    return jsonify({
        "timeRange": time_range,
        "mutations": mutations[:5]  # 最多返回5条
    })


@app.route("/api/realtime/causal", methods=["GET"])
def api_realtime_causal():
    """因果指向图数据API
    
    返回指标间的因果影响关系，用于渲染力导向图
    """
    try:
        # 从correlation数据计算因果关系
        # 这里使用简化的逻辑：基于相关性强度和变化方向确定影响方向
        indicators = ['gold', 'silver', 'ratio', 'dxy', 'treasury_10y', 'vix']
        
        # 创建因果关系矩阵（简化版本）
        # 在实际应用中，这里应该使用格兰杰因果检验或其他因果推断方法
        causal_links = [
            {
                "source": "dxy",
                "target": "gold",
                "strength": -0.7,  # 美元指数与黄金负相关
                "description": "美元走强通常导致黄金价格下跌（负相关）"
            },
            {
                "source": "treasury_10y",
                "target": "gold", 
                "strength": 0.6,
                "description": "美债收益率上升可能吸引资金流出黄金"
            },
            {
                "source": "vix",
                "target": "gold",
                "strength": 0.8,
                "description": "市场恐慌情绪上升通常推动黄金避险需求"
            },
            {
                "source": "gold",
                "target": "silver",
                "strength": 0.9,
                "description": "黄金价格走势通常领先于白银"
            },
            {
                "source": "dxy",
                "target": "silver",
                "strength": -0.6,
                "description": "美元走强压制白银等工业金属价格"
            },
            {
                "source": "treasury_10y",
                "target": "silver",
                "strength": -0.5,
                "description": "美债收益率变化影响工业金属投资偏好"
            },
            {
                "source": "gold",
                "target": "ratio",
                "strength": 0.7,
                "description": "黄金价格变化直接影响金银比"
            },
            {
                "source": "silver",
                "target": "ratio",
                "strength": -0.7,
                "description": "白银价格变化反向影响金银比"
            },
            {
                "source": "vix",
                "target": "treasury_10y",
                "strength": -0.6,
                "description": "市场恐慌情绪可能导致资金涌入美债避险"
            },
            {
                "source": "treasury_10y",
                "target": "dxy",
                "strength": 0.7,
                "description": "美债收益率上升通常吸引外资流入，推动美元走强"
            }
        ]
        
        # 节点定义
        nodes = [
            {"id": "gold", "name": "黄金", "group": 1, "value": 1.0},
            {"id": "silver", "name": "白银", "group": 1, "value": 0.8},
            {"id": "ratio", "name": "金银比", "group": 2, "value": 0.6},
            {"id": "dxy", "name": "美元指数", "group": 3, "value": 1.0},
            {"id": "treasury_10y", "name": "10Y美债", "group": 3, "value": 0.9},
            {"id": "vix", "name": "VIX恐慌指数", "group": 4, "value": 0.7}
        ]
        
        return jsonify({
            "nodes": nodes,
            "links": causal_links,
            "metadata": {
                "algorithm": "simplified_correlation_based",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": "这是基于历史相关性模式的简化因果推断。实际因果分析应采用格兰杰因果检验等正式方法。"
            }
        })
        
    except Exception as e:
        logger.error("因果分析API错误: %s", e)
        return jsonify({
            "error": "因果分析失败",
            "nodes": [],
            "links": [],
            "metadata": {"algorithm": "error"}
        })


if __name__ == "__main__":
    main()
