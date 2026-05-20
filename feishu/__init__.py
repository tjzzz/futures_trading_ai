#!/usr/bin/env python3
"""
飞书集成模块 - V2 架构
提供飞书 Webhook 消息解析、V2 命令路由功能
"""
from .handlers import extract_user_message, is_v2_command, handle_v2_command, V2_COMMANDS

__all__ = [
    "extract_user_message",
    "is_v2_command",
    "handle_v2_command",
    "V2_COMMANDS",
]
