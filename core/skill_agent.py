"""
SkillAgent - 整合飞书机器人和Agent架构
既可以通过消息总线与其他Agent通信，又可以通过飞书与用户交互
"""
from typing import Dict, Any, List, Optional, Callable
import asyncio
import json
from datetime import datetime
import logging

from .base_agent import BaseAgent
from .message_bus import Message


class SkillAgent(BaseAgent):
    """
    SkillAgent基类
    同时支持：
    1. Agent间通信（通过MessageBus）
    2. 飞书机器人交互（通过命令注册）
    3. 命令行调用
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(name, config)

        # 飞书命令注册
        self._commands: Dict[str, Callable] = {}
        self._command_help: Dict[str, str] = {}

        # 数据客户端（可选）
        self._data_client = None

    # ==================== 命令注册（飞书接口）====================

    def register_command(self, command: str, handler: Callable, help_text: str = ""):
        """注册飞书命令"""
        self._commands[command] = handler
        self._command_help[command] = help_text or f"执行{command}命令"
        self.logger.debug(f"注册命令: {command}")

    def get_commands(self) -> List[Dict[str, str]]:
        """获取命令列表（用于飞书帮助）"""
        return [
            {"name": cmd, "desc": help_text}
            for cmd, help_text in self._command_help.items()
        ]

    def get_bot_name(self) -> str:
        """获取机器人名称"""
        return f"{self.name}机器人"

    def get_bot_description(self) -> str:
        """获取机器人描述"""
        return f"{self.name}功能机器人"

    # ==================== 飞书消息处理 ====================

    async def handle_feishu_message(self, text: str, user_id: str = "", chat_id: str = "") -> str:
        """
        处理飞书消息
        解析命令并调用对应处理器
        """
        text = text.strip()

        # 提取命令
        parts = text.split(maxsplit=1)
        if not parts:
            return await self._show_help()

        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        # 处理帮助命令
        if command in ["帮助", "help", "?"]:
            return await self._show_help()

        # 查找命令处理器
        handler = self._commands.get(command)
        if handler:
            try:
                return await handler(args, user_id, chat_id)
            except Exception as e:
                self.logger.error(f"处理命令 [{command}] 失败: {e}")
                return f"❌ 执行命令失败: {str(e)}"

        # 未知命令，尝试默认处理
        return await self._handle_default(text, user_id, chat_id)

    async def _show_help(self) -> str:
        """显示帮助信息"""
        lines = [
            f"## {self.get_bot_name()}",
            "",
            self.get_bot_description(),
            "",
            "**可用命令**:"
        ]

        for cmd_info in self.get_commands():
            lines.append(f"  • {cmd_info['name']}: {cmd_info['desc']}")

        return "\n".join(lines)

    async def _handle_default(self, text: str, user_id: str, chat_id: str) -> str:
        """默认消息处理 - 子类可覆盖"""
        return f"未知命令: {text}\n请输入「帮助」查看可用命令"

    # ==================== 数据客户端集成 ====================

    def set_data_client(self, data_client):
        """设置数据客户端"""
        self._data_client = data_client

    def get_data_client(self):
        """获取数据客户端"""
        return self._data_client

    # ==================== Agent消息处理 ====================

    async def _handle_message(self, message: Message):
        """处理来自消息总线的消息"""
        # 将消息总线消息转发到对应的处理方法
        handler = self._handlers.get(message.msg_type)
        if handler:
            await handler(message.data)
        else:
            self.logger.debug(f"未处理的消息类型: {message.msg_type}")

    # ==================== 工具方法 ====================

    def format_number(self, num: float, decimals: int = 2) -> str:
        """格式化数字"""
        if num is None:
            return "N/A"
        return f"{num:.{decimals}f}"

    def format_pct(self, num: float) -> str:
        """格式化百分比"""
        if num is None:
            return "N/A"
        sign = "+" if num > 0 else ""
        return f"{sign}{num:.2f}%"

    def format_datetime(self, dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M") -> str:
        """格式化日期时间"""
        if dt is None:
            dt = datetime.now()
        return dt.strftime(fmt)

    def safe_json_loads(self, text: str) -> Optional[Dict]:
        """安全解析JSON"""
        try:
            return json.loads(text)
        except:
            return None
