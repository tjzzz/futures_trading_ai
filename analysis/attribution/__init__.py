"""
归因模块 — 期货交易系统 V2
统计归因 + 事件匹配 + 报告生成
"""

from .engine import AttributionEngine
from .statistical import statistical_attribution
from .event_matcher import match_events
from .report import generate_report

__all__ = [
    "AttributionEngine",
    "statistical_attribution",
    "match_events",
    "generate_report"
]