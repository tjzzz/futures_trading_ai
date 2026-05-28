"""
预测模块主入口 — 统一调度三周期预测与融合

调用方式：
    from analysis.prediction import PredictionEngine
    engine = PredictionEngine()
    result = engine.predict(symbol="gold", horizon="all")
"""

import logging
from typing import Dict, Optional

from .technical import ShortTermPredictor
from .macro import MidTermPredictor
from .fundamental import LongTermPredictor
from .fusion import PredictionFusionEngine

logger = logging.getLogger(__name__)


class PredictionEngine:
    """预测引擎主入口"""

    def __init__(self, data_dir: str = None):
        self.short_term = ShortTermPredictor(data_dir)
        self.mid_term = MidTermPredictor(data_dir)
        self.long_term = LongTermPredictor(data_dir)
        self.fusion = PredictionFusionEngine(data_dir)

    def predict(self, symbol: str = "gold", horizon: str = "all") -> Dict:
        """
        统一预测入口

        参数：
            symbol: gold / silver
            horizon: short / mid / long / all
        """
        if horizon == "short":
            return self.short_term.predict(symbol=symbol)
        elif horizon == "mid":
            return self.mid_term.predict()
        elif horizon == "long":
            return self.long_term.predict()
        else:
            return self.fusion.fuse(symbol=symbol)

    def predict_short(self, symbol: str = "gold") -> Dict:
        """仅短期预测"""
        return self.short_term.predict(symbol=symbol)

    def predict_mid(self) -> Dict:
        """仅中期预测"""
        return self.mid_term.predict()

    def predict_long(self) -> Dict:
        """仅长期预测"""
        return self.long_term.predict()
