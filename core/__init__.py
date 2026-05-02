"""
核心模块 - Agent架构与消息总线
整合自 futures_trading_system 和 futures_trading_skills
"""
from .base_agent import BaseAgent, Message
from .message_bus import MessageBus
from .skill_agent import SkillAgent

__all__ = ["BaseAgent", "Message", "MessageBus", "SkillAgent"]
