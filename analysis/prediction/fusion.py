"""预测融合引擎 — 多模型加权融合与置信度计算

整合短/中/长期预测结果，生成综合预测结论。
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from .technical import ShortTermPredictor
from .macro import MidTermPredictor
from .fundamental import LongTermPredictor

logger = logging.getLogger(__name__)


class PredictionFusionEngine:
    """多模型融合引擎"""

    # 各周期模型的基础权重（可被动态调整覆盖）
    DEFAULT_WEIGHTS = {
        "short_term": {"weight": 0.35, "label": "短期技术面"},
        "mid_term": {"weight": 0.40, "label": "中期宏观面"},
        "long_term": {"weight": 0.25, "label": "长期基本面"},
    }

    def __init__(self, data_dir: str = None):
        self.short = ShortTermPredictor(data_dir)
        self.mid = MidTermPredictor(data_dir)
        self.long = LongTermPredictor(data_dir)
        self.weights = self.DEFAULT_WEIGHTS.copy()

    def fuse(self, symbol: str = "gold") -> Dict:
        """融合三周期预测"""
        try:
            short_r = self.short.predict(symbol=symbol)
        except Exception as e:
            logger.error(f"短期预测失败: {e}")
            short_r = {"error": str(e), "direction": "neutral", "score": 0, "confidence": 0}

        try:
            mid_r = self.mid.predict()
        except Exception as e:
            logger.error(f"中期预测失败: {e}")
            mid_r = {"error": str(e), "direction": "neutral", "score": 0, "confidence": 0}

        try:
            long_r = self.long.predict()
        except Exception as e:
            logger.error(f"长期预测失败: {e}")
            long_r = {"error": str(e), "direction": "neutral", "score": 0, "confidence": 0}

        # 方向数值映射
        dir_map = {
            "bullish": 1, "slightly_bullish": 0.5, "neutral": 0,
            "slightly_bearish": -0.5, "bearish": -1, "mixed": 0,
        }

        models = [
            ("short_term", short_r),
            ("mid_term", mid_r),
            ("long_term", long_r),
        ]

        total_weight = 0
        weighted_score = 0
        details = []

        for name, result in models:
            cfg = self.weights[name]
            w = cfg["weight"]
            label = cfg["label"]

            direction = result.get("direction", "neutral")
            score = dir_map.get(direction, 0)
            conf = result.get("confidence", 0.5)
            has_indicators = "indicators" in result

            effective_score = score * conf
            weighted_score += effective_score * w
            total_weight += w

            details.append({
                "name": name,
                "label": label,
                "direction": direction,
                "direction_label": result.get("direction_label", ""),
                "score": result.get("score", 0),
                "confidence": conf,
                "weight": w,
                "weighted_score": round(effective_score * w, 3),
                "signals": result.get("signals", []),
                "has_indicators": has_indicators,
                "error": result.get("error"),
            })

        # 综合得分
        if total_weight > 0:
            final_score = weighted_score / total_weight
        else:
            final_score = 0

        # 综合方向
        if final_score > 0.4:
            direction, label = "bullish", "看多"
        elif final_score < -0.4:
            direction, label = "bearish", "看空"
        elif final_score > 0.15:
            direction, label = "slightly_bullish", "略偏多"
        elif final_score < -0.15:
            direction, label = "slightly_bearish", "略偏空"
        else:
            direction, label = "neutral", "震荡"

        # 综合置信度
        avg_conf = sum(
            details[i]["confidence"] * self.weights[details[i]["name"]]["weight"]
            for i in range(len(details))
        ) / total_weight if total_weight > 0 else 0

        return {
            "direction": direction,
            "direction_label": label,
            "final_score": round(final_score, 2),
            "confidence": round(avg_conf, 2),
            "model_weights": self.weights,
            "models": details,
            "predictions": self._merge_predictions([short_r, mid_r, long_r]),
            "timestamp": datetime.now().isoformat(),
        }

    def _merge_predictions(self, results: List[Dict]) -> List[Dict]:
        """合并各周期的预测列表"""
        merged = []
        for r in results:
            for p in r.get("predictions", []):
                if p not in merged:
                    merged.append(p)
        return merged
