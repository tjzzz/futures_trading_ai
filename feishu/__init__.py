"""
feishu — 飞书集成模块

推送：push_morning_brief / push_anomaly_alert / push_event_reminder / push_text
消息：send_message（底层）
"""

from .push import (
    send_message,
    push_morning_brief,
    push_anomaly_alert,
    push_event_reminder,
    push_text,
)

__all__ = [
    "send_message",
    "push_morning_brief",
    "push_anomaly_alert",
    "push_event_reminder",
    "push_text",
]
