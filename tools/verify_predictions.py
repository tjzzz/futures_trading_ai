#!/usr/bin/env python3
"""
预判验证与因子权重调整工具 — 反馈闭环的核心

功能:
  1. 读取 prediction_log.json，检查是否有未验证的预判
  2. 查询当前金银价格，验证方向 + 区间命中
  3. 追加验证结果到 prediction_log.json
  4. 计算滚动统计（方向准确率、区间命中率、因子准确率）
  5. 自动调整因子权重
  6. 输出可读偏差报告

用法:
    python tools/verify_predictions.py                    # 完整验证流程
    python tools/verify_predictions.py --stats-only       # 仅统计，不验证
    python tools/verify_predictions.py --reset-weights    # 重置权重为默认值

框架文档:
  docs/2_预判验证与反馈闭环机制.md
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verify_predictions")

# ─── 项目路径 ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CURRENT = PROJECT_ROOT / "data" / "current"
DATA_FACTORS = PROJECT_ROOT / "data" / "factors"
DASHBOARD_FILE = DATA_CURRENT / "dashboard_data.json"
PREDICTION_LOG_FILE = DATA_FACTORS / "prediction_log.json"

# ─── 默认因子权重（与 analyze_macro.py 一致） ─────────────────────────

DEFAULT_FACTOR_WEIGHTS: Dict[str, float] = {
    "opportunity_cost": 1.0,
    "currency": 0.6,
    "safe_haven": 0.8,
    "inflation": 0.6,
    "positioning": 0.5,
    "structural_demand": 0.4,
    "silver_specific": 0.3,
}

FACTOR_LABELS: Dict[str, str] = {
    "opportunity_cost": "机会成本",
    "currency": "货币",
    "safe_haven": "避险需求",
    "inflation": "通胀预期",
    "positioning": "持仓动量",
    "structural_demand": "结构性需求",
    "silver_specific": "银价专用",
}

# ─── 权重调整参数 ─────────────────────────────────────────────────────

WEIGHT_ADJUST_PARAMS = {
    "reward_threshold": 0.80,      # 准确率 >= 80% → 奖励
    "keep_threshold": 0.60,        # 准确率 >= 60% → 保持
    "penalty_threshold": 0.40,     # 准确率 >= 40% → 轻度惩罚
    "reward_factor": 1.10,         # 奖励乘数
    "penalty_factor": 0.90,        # 轻度惩罚乘数
    "severe_penalty_factor": 0.75, # 严重惩罚乘数
    "weight_min": 0.10,            # 权重下限
    "weight_max_multiplier": 1.5,  # 权重上限 = 默认值 × 此数
    "stats_window_initial": 10,    # 累积<10条时用全部数据
    "stats_window_mid": 10,        # 10~19条用最近10条
    "stats_window_final": 20,      # >=20条用最近20条
}

# ─── 验证参数 ──────────────────────────────────────────────────────────

VERIFY_PARAMS = {
    "direction_threshold": 0.005,  # 0.5% 价格变化才算有效方向
    "range_tolerance": 0.10,       # 超出区间 10% 内视为边缘
    "skip_minutes": 10,            # 距分析不到 10 分钟不验证
    "force_minutes": 60,           # 距分析超过 60 分钟必须验证
}


# ====================================================================
#  读写工具
# ====================================================================


def _read_json(path: Path) -> dict:
    """安全读取 JSON，失败返回空字典"""
    if not path.exists():
        logger.debug("文件不存在: %s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return {}


def _write_json(path: Path, data: dict) -> bool:
    """安全写入 JSON"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        logger.error("写入 %s 失败: %s", path, e)
        return False


def _safe_float(v, default: float = 0.0) -> float:
    """安全转为 float"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return _safe_float(v.get("value"), default)
    if isinstance(v, str):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default
    return default


def _get_gold_silver_prices() -> Tuple[Optional[float], Optional[float]]:
    """从 dashboard_data.json 读取当前金银价格

    Returns:
        (gold_price, silver_price) — 优先 COMEX 期货，回退现货
    """
    dashboard = _read_json(DASHBOARD_FILE)
    if not dashboard:
        return None, None

    gold = _safe_float(dashboard.get("gold_futures", {}).get("value")) or \
           _safe_float(dashboard.get("gold_price", {}).get("value")) or None

    silver = _safe_float(dashboard.get("silver_futures", {}).get("value")) or \
             _safe_float(dashboard.get("silver_price", {}).get("value")) or None

    return gold, silver


# ====================================================================
#  预判记录管理
# ====================================================================


def load_prediction_log() -> dict:
    """加载预测日志，不存在则返回默认结构"""
    log = _read_json(PREDICTION_LOG_FILE)
    if not log:
        log = {
            "predictions": [],
            "factor_weights": dict(DEFAULT_FACTOR_WEIGHTS),
            "weight_adjustment_log": [],
            "accuracy_stats": {
                "total_verified": 0,
                "direction_correct": 0,
                "direction_accuracy": None,
                "range_correct": 0,
                "range_accuracy": None,
                "by_factor": {},
            },
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    # 确保字段存在
    if "weight_adjustment_log" not in log:
        log["weight_adjustment_log"] = []
    # 确保所有权重字段存在
    weights = log.get("factor_weights", {})
    for k, v in DEFAULT_FACTOR_WEIGHTS.items():
        if k not in weights:
            weights[k] = v
    log["factor_weights"] = weights
    return log


def save_prediction_log(log: dict) -> bool:
    """保存预测日志"""
    log["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _write_json(PREDICTION_LOG_FILE, log)


def append_prediction(log: dict, prediction: dict) -> int:
    """追加新的预判记录

    Args:
        log: 预测日志
        prediction: 预判字典

    Returns:
        分配的 ID
    """
    predictions = log.setdefault("predictions", [])
    next_id = max((p.get("id", 0) for p in predictions), default=0) + 1
    prediction["id"] = next_id
    prediction["verified"] = False
    prediction["verification"] = None
    predictions.append(prediction)
    return next_id


# ====================================================================
#  验证逻辑
# ====================================================================


def verify_prediction(
    prediction: dict, gold_current: Optional[float], silver_current: Optional[float]
) -> Optional[dict]:
    """验证单条预判

    验证方向 + 区间命中。

    Args:
        prediction: 预判记录
        gold_current: 当前黄金价格
        silver_current: 当前白银价格

    Returns:
        验证结果字典，如果无法验证则返回 None
    """
    direction = prediction.get("direction", "neutral")
    gold_low = prediction.get("gold_range_low")
    gold_high = prediction.get("gold_range_high")
    gold_analysis = prediction.get("gold_price_at_analysis")

    if gold_current is None:
        logger.warning("无法获取黄金当前价格，跳过验证")
        return None

    if not all([gold_low, gold_high, gold_analysis]):
        logger.warning("预判数据不完整（缺少区间或分析时价格），跳过验证")
        return None

    # ── 方向验证 ──
    gold_change_pct = (gold_current - gold_analysis) / gold_analysis if gold_analysis else 0
    direction_correct = None

    if abs(gold_change_pct) < VERIFY_PARAMS["direction_threshold"]:
        # 价格变化太小，视为无方向
        direction_correct = True if direction == "neutral" else None
    else:
        actual_direction = "bullish" if gold_change_pct > 0 else "bearish"
        direction_correct = (direction == actual_direction)

    # ── 区间验证 ──
    range_correct = None
    range_deviation = None
    if gold_current >= gold_low and gold_current <= gold_high:
        range_correct = True
        range_deviation = 0.0
    else:
        range_span = gold_high - gold_low
        if range_span > 0:
            # 计算偏离程度
            if gold_current < gold_low:
                range_deviation = (gold_low - gold_current) / range_span
            else:
                range_deviation = (gold_current - gold_high) / range_span

        if range_deviation is not None and range_deviation < VERIFY_PARAMS["range_tolerance"]:
            range_correct = "edge"  # 边缘命中
        else:
            range_correct = False

    return {
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "gold_price_analysis": gold_analysis,
        "gold_price_current": round(gold_current, 1),
        "gold_change_pct": round(gold_change_pct * 100, 2),
        "silver_price_current": round(silver_current, 1) if silver_current else None,
        "direction_correct": direction_correct,
        "range_correct": range_correct,
        "range_deviation": round(range_deviation, 4) if range_deviation is not None else None,
    }


# ====================================================================
#  滚动统计
# ====================================================================


def compute_stats_window(total_count: int) -> int:
    """根据累计预判数确定统计窗口"""
    if total_count >= 20:
        return VERIFY_PARAMS["stats_window_final"]  # 20
    elif total_count >= 10:
        return VERIFY_PARAMS["stats_window_mid"]   # 10
    else:
        return total_count  # 全部


def compute_accuracy_stats(log: dict) -> dict:
    """计算滚动统计

    基于已验证的预判，按窗口大小滚动统计。

    Args:
        log: 预测日志

    Returns:
        统计结果字典
    """
    predictions = log.get("predictions", [])
    verified = [p for p in predictions if p.get("verified") and p.get("verification")]

    if not verified:
        return _empty_stats()

    window = compute_stats_window(len(verified))
    recent = verified[-window:]  # 用最近的 N 条

    # ── 总体统计 ──
    total = len(recent)
    dir_correct = sum(
        1 for p in recent
        if p["verification"]["direction_correct"] is True
    )
    dir_total = sum(
        1 for p in recent
        if p["verification"]["direction_correct"] is not None
    )

    range_correct = sum(
        1 for p in recent
        if p["verification"]["range_correct"] is True
    )
    range_total = total  # 区间验证始终有结果

    dir_accuracy = round(dir_correct / dir_total, 4) if dir_total > 0 else None
    range_accuracy = round(range_correct / range_total, 4) if range_total > 0 else None

    # ── 按因子统计 ──
    by_factor: Dict[str, dict] = {}
    for p in recent:
        factor = p.get("dominant_factor")
        if not factor:
            continue
        if factor not in by_factor:
            by_factor[factor] = {"correct": 0, "total": 0}
        by_factor[factor]["total"] += 1
        if p["verification"]["direction_correct"] is True:
            by_factor[factor]["correct"] += 1

    # 计算因子准确率
    for fid, stat in by_factor.items():
        stat["accuracy"] = round(stat["correct"] / stat["total"], 4) if stat["total"] > 0 else None

    return {
        "window": window,
        "total_verified": total,
        "direction_correct": dir_correct,
        "direction_total": dir_total,
        "direction_accuracy": dir_accuracy,
        "range_correct": range_correct,
        "range_total": range_total,
        "range_accuracy": range_accuracy,
        "by_factor": by_factor,
    }


def _empty_stats() -> dict:
    return {
        "window": 0,
        "total_verified": 0,
        "direction_correct": 0,
        "direction_total": 0,
        "direction_accuracy": None,
        "range_correct": 0,
        "range_total": 0,
        "range_accuracy": None,
        "by_factor": {},
    }


# ====================================================================
#  因子权重调整
# ====================================================================


def adjust_weights(log: dict, stats: dict) -> dict:
    """根据准确率自动调整因子权重

    Args:
        log: 预测日志（含当前权重）
        stats: 滚动统计结果

    Returns:
        调整后的权重字典
    """
    current_weights = dict(log.get("factor_weights", {}))
    by_factor = stats.get("by_factor", {})

    if not by_factor:
        # 没有因子维度统计，保持当前权重
        return current_weights

    params = WEIGHT_ADJUST_PARAMS
    adjusted = {}
    changes = []

    for fid, default_weight in DEFAULT_FACTOR_WEIGHTS.items():
        current_w = current_weights.get(fid, default_weight)
        factor_stat = by_factor.get(fid)

        if not factor_stat or factor_stat.get("total", 0) == 0:
            # 该因子从未主导过，保持当前权重
            adjusted[fid] = current_w
            continue

        accuracy = factor_stat.get("accuracy")

        if accuracy is None:
            adjusted[fid] = current_w
            continue

        # 调整
        new_weight = current_w
        note = ""

        if accuracy >= params["reward_threshold"]:
            new_weight = current_w * params["reward_factor"]
            note = f"准确率 {accuracy:.0%} >= {params['reward_threshold']:.0%}，奖励"
        elif accuracy >= params["keep_threshold"]:
            new_weight = current_w  # 不变
            note = f"准确率 {accuracy:.0%} >= {params['keep_threshold']:.0%}，保持"
        elif accuracy >= params["penalty_threshold"]:
            new_weight = current_w * params["penalty_factor"]
            note = f"准确率 {accuracy:.0%} >= {params['penalty_threshold']:.0%}，轻度惩罚"
        else:
            new_weight = current_w * params["severe_penalty_factor"]
            note = f"准确率 {accuracy:.0%} < {params['penalty_threshold']:.0%}，严重惩罚"

        # 限幅
        weight_max = default_weight * params["weight_max_multiplier"]
        new_weight = max(params["weight_min"], min(new_weight, weight_max))
        new_weight = round(new_weight, 2)

        if abs(new_weight - current_w) > 0.01:
            changes.append({
                "factor": fid,
                "label": FACTOR_LABELS.get(fid, fid),
                "from": round(current_w, 2),
                "to": new_weight,
                "reason": note,
                "accuracy": accuracy,
                "total": factor_stat["total"],
            })

        adjusted[fid] = new_weight

    # 如果有变化，记录调整日志
    if changes:
        adjustment_log = log.setdefault("weight_adjustment_log", [])
        adjustment_log.append({
            "adjusted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "changes": changes,
        })
        # 限制日志长度
        if len(adjustment_log) > 50:
            log["weight_adjustment_log"] = adjustment_log[-50:]

    return adjusted


# ====================================================================
#  输出格式化
# ====================================================================


def format_stats_report(stats: dict, weights: dict) -> str:
    """格式化为可读的偏差报告

    Args:
        stats: 滚动统计
        weights: 调整后的权重

    Returns:
        格式化的报告字符串
    """
    lines = []
    lines.append("📊 预判偏差报告")
    lines.append("=" * 48)

    if stats["total_verified"] == 0:
        lines.append("尚无已验证的预判，使用默认权重。")
        lines.append("")
        lines.append("当前权重:")
        for fid, w in weights.items():
            label = FACTOR_LABELS.get(fid, fid)
            lines.append(f"  {label:<10s}: {w:.2f}")
        return "\n".join(lines)

    # 统计概览
    dir_acc = stats["direction_accuracy"]
    range_acc = stats["range_accuracy"]
    dir_str = f"{dir_acc:.0%}" if dir_acc is not None else "—"
    range_str = f"{range_acc:.0%}" if range_acc is not None else "—"

    lines.append(f"  窗口: 最近 {stats['window']} 次")
    lines.append(f"  方向准确率: {dir_str}  ({stats['direction_correct']}/{stats['direction_total']})")
    lines.append(f"  区间命中率: {range_str}  ({stats['range_correct']}/{stats['range_total']})")
    lines.append("")

    # 因子准确率
    lines.append("── 因子准确率 ──")
    by_factor = stats.get("by_factor", {})
    if by_factor:
        for fid in ["opportunity_cost", "safe_haven", "currency",
                     "inflation", "positioning", "structural_demand", "silver_specific"]:
            fstat = by_factor.get(fid)
            if fstat and fstat["total"] > 0:
                acc = fstat["accuracy"]
                acc_str = f"{acc:.0%}" if acc is not None else "—"
                bar = _accuracy_bar(acc) if acc else "     "
                label = FACTOR_LABELS.get(fid, fid)
                lines.append(f"  {label:<10s}: {acc_str} ({fstat['correct']}/{fstat['total']}) {bar}")
    lines.append("")

    # 权重变化
    lines.append("── 因子权重 ──")
    for fid in ["opportunity_cost", "safe_haven", "currency",
                 "inflation", "positioning", "structural_demand", "silver_specific"]:
        w = weights.get(fid, DEFAULT_FACTOR_WEIGHTS.get(fid, 0.5))
        default_w = DEFAULT_FACTOR_WEIGHTS.get(fid, 0.5)
        label = FACTOR_LABELS.get(fid, fid)
        if w != default_w:
            arrow = "↑" if w > default_w else "↓"
            lines.append(f"  {label:<10s}: {w:.2f} ({arrow} {'%+.0f%%' % ((w/default_w - 1) * 100)})")
        else:
            lines.append(f"  {label:<10s}: {w:.2f}  (默认)")
    lines.append("")

    return "\n".join(lines)


def _accuracy_bar(accuracy: Optional[float], width: int = 5) -> str:
    """生成准确率可视化条"""
    if accuracy is None:
        return " " * width
    filled = max(0, min(int(accuracy * width), width))
    return "█" * filled + "░" * (width - filled)


# ====================================================================
#  追加预判（Agent 调用接口）
# ====================================================================


def add_prediction_entry(
    direction: str,
    confidence: float,
    dominant_factor: str,
    dominant_cycle: str,
    gold_price: float,
    gold_range_low: float,
    gold_range_high: float,
    silver_price: Optional[float] = None,
    silver_range_low: Optional[float] = None,
    silver_range_high: Optional[float] = None,
) -> int:
    """Agent 分析完成后调用，追加预判记录

    Args:
        direction: 预判方向 ("bullish" / "bearish" / "neutral")
        confidence: 置信度 (0-1)
        dominant_factor: 主导因子 ID
        dominant_cycle: 主导周期
        gold_price: 分析时的黄金价格（当前价）
        gold_range_low: 黄金预判区间下限
        gold_range_high: 黄金预判区间上限
        silver_price: 分析时的白银价格
        silver_range_low: 白银预判区间下限
        silver_range_high: 白银预判区间上限

    Returns:
        预判 ID
    """
    log = load_prediction_log()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prediction = {
        "created_at": now,
        "direction": direction,
        "confidence": confidence,
        "dominant_factor": dominant_factor,
        "dominant_cycle": dominant_cycle,
        "gold_price_at_analysis": gold_price,
        "gold_range_low": gold_range_low,
        "gold_range_high": gold_range_high,
        "silver_price_at_analysis": silver_price,
        "silver_range_low": silver_range_low,
        "silver_range_high": silver_range_high,
    }
    pred_id = append_prediction(log, prediction)
    save_prediction_log(log)
    logger.info("已追加预判 #%d", pred_id)
    return pred_id


# ====================================================================
#  主流程
# ====================================================================


def run_verification() -> dict:
    """执行完整的验证流程

    Returns:
        {
            "report": <格式化报告文本>,
            "stats": <统计结果>,
            "weights": <调整后的权重>,
            "verified_count": <本次验证的预判数>,
        }
    """
    log = load_prediction_log()
    predictions = log.get("predictions", [])

    # 1. 找到未验证的预判
    unverified = [p for p in predictions if not p.get("verified")]
    verified_count = 0

    if unverified:
        # 2. 获取当前价格
        gold_price, silver_price = _get_gold_silver_prices()

        if gold_price is not None:
            for pred in unverified:
                result = verify_prediction(pred, gold_price, silver_price)
                if result:
                    pred["verified"] = True
                    pred["verification"] = result
                    verified_count += 1

            if verified_count > 0:
                logger.info("完成 %d 条预判验证", verified_count)
        else:
            logger.warning("无法获取当前价格，跳过验证")

    # 3. 计算滚动统计
    stats = compute_accuracy_stats(log)

    # 4. 调整因子权重
    adjusted_weights = adjust_weights(log, stats)

    # 5. 更新权重到日志
    log["factor_weights"] = adjusted_weights
    log["accuracy_stats"] = stats

    # 6. 保存
    save_prediction_log(log)

    # 7. 生成报告
    report = format_stats_report(stats, adjusted_weights)

    return {
        "report": report,
        "stats": stats,
        "weights": adjusted_weights,
        "verified_count": verified_count,
    }


# ====================================================================
#  CLI
# ====================================================================


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="预判验证与因子权重调整工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s                        # 完整验证流程
  %(prog)s --stats-only           # 仅输出统计，不验证
  %(prog)s --reset-weights        # 重置权重为默认值
        """,
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="仅输出统计，不进行验证",
    )
    parser.add_argument(
        "--reset-weights", action="store_true",
        help="重置因子权重为默认值",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式输出结果",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    if args.reset_weights:
        log = load_prediction_log()
        log["factor_weights"] = dict(DEFAULT_FACTOR_WEIGHTS)
        log["weight_adjustment_log"].append({
            "adjusted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "changes": [{"reason": "手动重置为默认值"}],
        })
        save_prediction_log(log)
        print("✅ 因子权重已重置为默认值")
        return

    if args.stats_only:
        log = load_prediction_log()
        stats = compute_accuracy_stats(log)
        weights = log.get("factor_weights", DEFAULT_FACTOR_WEIGHTS)
        report = format_stats_report(stats, weights)
        if args.json:
            print(json.dumps({"stats": stats, "weights": weights},
                             ensure_ascii=False, indent=2))
        else:
            print(report)
        return

    # 完整验证流程
    result = run_verification()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["report"])
        if result["verified_count"] > 0:
            print(f"✅ 本次验证: {result['verified_count']} 条")


if __name__ == "__main__":
    main()