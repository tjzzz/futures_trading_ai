#!/usr/bin/env python3
"""
飞书机器人框架 - 统一的飞书消息处理基类
"""
import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional, Callable, List
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FeishuMessage:
    """飞书消息结构"""
    message_id: str
    chat_id: str
    chat_type: str  # private/group
    sender_id: str
    sender_name: str
    content: str
    message_type: str  # text/image/file
    create_time: int
    raw_event: Dict


class FeishuBot(ABC):
    """飞书机器人基类"""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        encrypt_key: Optional[str] = None,
        verification_token: Optional[str] = None
    ):
        self.app_id = app_id or os.getenv("FEISHU_APP_ID")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
        self.encrypt_key = encrypt_key or os.getenv("FEISHU_ENCRYPT_KEY")
        self.verification_token = verification_token or os.getenv("FEISHU_VERIFICATION_TOKEN")

        self.logger = logging.getLogger(self.__class__.__name__)
        self._command_handlers: Dict[str, Callable] = {}
        self._message_handlers: List[Callable] = []

        # 注册默认处理器
        self._register_default_handlers()

    def _register_default_handlers(self):
        """注册默认命令处理器"""
        self.register_command("帮助", self._handle_help)
        self.register_command("help", self._handle_help)
        self.register_command("状态", self._handle_status)
        self.register_command("status", self._handle_status)

    @abstractmethod
    def get_bot_name(self) -> str:
        """获取机器人名称"""
        pass

    @abstractmethod
    def get_bot_description(self) -> str:
        """获取机器人描述"""
        pass

    @abstractmethod
    def get_commands(self) -> List[Dict[str, str]]:
        """获取支持的命令列表"""
        pass

    def register_command(self, command: str, handler: Callable):
        """注册命令处理器"""
        self._command_handlers[command.lower()] = handler

    def register_message_handler(self, handler: Callable):
        """注册消息处理器"""
        self._message_handlers.append(handler)

    async def handle_event(self, event: Dict) -> Optional[str]:
        """处理飞书事件"""
        try:
            # 验证请求
            if not self._verify_event(event):
                return None

            # 解析消息
            message = self._parse_message(event)
            if not message:
                return None

            self.logger.info(f"收到消息: {message.sender_name}: {message.content[:50]}")

            # 检查是否是@机器人
            if not self._is_mentioned(message):
                return None

            # 提取纯文本内容（去除@部分）
            content = self._extract_text(message)

            # 尝试命令匹配
            response = await self._handle_command(content, message)
            if response:
                return response

            # 使用消息处理器
            for handler in self._message_handlers:
                response = await handler(content, message)
                if response:
                    return response

            # 默认回复
            return self._get_default_reply()

        except Exception as e:
            self.logger.error(f"处理事件失败: {e}")
            return f"处理消息时出错: {str(e)}"

    def _verify_event(self, event: Dict) -> bool:
        """验证事件签名"""
        # 简单验证，生产环境需要完整签名验证
        token = event.get("header", {}).get("token")
        if token and self.verification_token:
            return token == self.verification_token
        return True

    def _parse_message(self, event: Dict) -> Optional[FeishuMessage]:
        """解析飞书消息"""
        try:
            event_data = event.get("event", {})
            message = event_data.get("message", {})
            sender = event_data.get("sender", {}).get("sender_id", {}).get("user_id", "")

            # 获取发送者信息
            sender_name = event_data.get("sender", {}).get("sender_id", {}).get("user_id", "未知")

            # 解析内容
            content = message.get("content", "")
            if isinstance(content, str):
                try:
                    content_obj = json.loads(content)
                    content = content_obj.get("text", "")
                except:
                    pass

            return FeishuMessage(
                message_id=message.get("message_id", ""),
                chat_id=message.get("chat_id", ""),
                chat_type=message.get("chat_type", "private"),
                sender_id=sender,
                sender_name=sender_name,
                content=content,
                message_type=message.get("message_type", "text"),
                create_time=message.get("create_time", 0),
                raw_event=event
            )

        except Exception as e:
            self.logger.error(f"解析消息失败: {e}")
            return None

    def _is_mentioned(self, message: FeishuMessage) -> bool:
        """检查是否@了机器人"""
        # 私聊直接响应
        if message.chat_type == "p2p":
            return True

        # 群聊检查@mentions
        mentions = message.raw_event.get("event", {}).get("message", {}).get("mentions", [])
        for mention in mentions:
            if mention.get("id", {}).get("user_id") == self.app_id:
                return True

        # 检查内容中是否有机器人名称
        bot_name = self.get_bot_name()
        if bot_name in message.content:
            return True

        return False

    def _extract_text(self, message: FeishuMessage) -> str:
        """提取纯文本（去除@部分）"""
        content = message.content

        # 去除@文本
        mentions = message.raw_event.get("event", {}).get("message", {}).get("mentions", [])
        for mention in mentions:
            key = mention.get("key", "")
            name = mention.get("name", "")
            content = content.replace(f"@{name}", "")
            content = content.replace(key, "")

        # 去除机器人名称
        content = content.replace(f"@{self.get_bot_name()}", "")

        return content.strip()

    async def _handle_command(self, content: str, message: FeishuMessage) -> Optional[str]:
        """处理命令"""
        # 提取命令
        parts = content.split(maxsplit=1)
        if not parts:
            return None

        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handler = self._command_handlers.get(command)
        if handler:
            return await handler(args, message)

        return None

    async def _handle_help(self, args: str, message: FeishuMessage) -> str:
        """处理帮助命令"""
        lines = [
            f"## 🤖 {self.get_bot_name()}",
            "",
            f"{self.get_bot_description()}",
            "",
            "### 支持的命令",
        ]

        for cmd in self.get_commands():
            lines.append(f"  **{cmd['name']}** - {cmd['desc']}")

        lines.extend([
            "",
            "### 通用命令",
            "  **帮助** - 显示帮助信息",
            "  **状态** - 查看机器人状态",
        ])

        return "\n".join(lines)

    async def _handle_status(self, args: str, message: FeishuMessage) -> str:
        """处理状态命令"""
        return f"""## 🤖 {self.get_bot_name()} 状态

**状态**: ✅ 运行中
**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _get_default_reply(self) -> str:
        """默认回复"""
        return f"""未识别的命令。

请发送 **帮助** 查看可用命令。
或尝试以下格式：
{self.get_command_examples()}
"""

    @abstractmethod
    def get_command_examples(self) -> str:
        """获取命令示例"""
        pass

    async def send_message(self, chat_id: str, content: str, msg_type: str = "text"):
        """发送消息到飞书（需要实现HTTP调用）"""
        # 生产环境需要实现真实的飞书API调用
        self.logger.info(f"发送消息到 {chat_id}: {content[:100]}")
        return True

    def format_markdown(self, content: str) -> str:
        """格式化Markdown消息"""
        # 限制长度
        max_length = 3000
        if len(content) > max_length:
            content = content[:max_length] + "\n\n... (内容已截断)"

        return content


class FeishuWebhookServer:
    """飞书 Webhook 服务器"""

    def __init__(self, port: int = 8080):
        self.port = port
        self.bots: Dict[str, FeishuBot] = {}
        self.logger = logging.getLogger("FeishuWebhookServer")

    def register_bot(self, path: str, bot: FeishuBot):
        """注册机器人"""
        self.bots[path] = bot
        self.logger.info(f"注册机器人 {bot.get_bot_name()} 到路径: {path}")

    async def handle_request(self, path: str, body: Dict) -> Optional[str]:
        """处理请求"""
        bot = self.bots.get(path)
        if not bot:
            self.logger.warning(f"未找到路径 {path} 对应的机器人")
            return None

        return await bot.handle_event(body)


# 简化的适配器工厂
def create_simple_adapter(skill_handler: Callable, bot_name: str, description: str) -> FeishuBot:
    """创建简单的飞书适配器"""

    class SimpleAdapter(FeishuBot):
        def get_bot_name(self) -> str:
            return bot_name

        def get_bot_description(self) -> str:
            return description

        def get_commands(self) -> List[Dict[str, str]]:
            return [
                {"name": "分析", "desc": "执行分析"},
                {"name": "帮助", "desc": "显示帮助"}
            ]

        def get_command_examples(self) -> str:
            return "  分析 AU"

    adapter = SimpleAdapter()
    adapter.register_message_handler(skill_handler)
    return adapter


if __name__ == "__main__":
    # 测试基类
    logging.basicConfig(level=logging.INFO)

    class TestBot(FeishuBot):
        def get_bot_name(self) -> str:
            return "测试机器人"

        def get_bot_description(self) -> str:
            return "这是一个测试机器人"

        def get_commands(self) -> List[Dict[str, str]]:
            return [
                {"name": "测试", "desc": "执行测试"},
                {"name": "帮助", "desc": "显示帮助"}
            ]

        def get_command_examples(self) -> str:
            return "  测试 参数"

    bot = TestBot()

    # 模拟事件
    test_event = {
        "header": {"token": ""},
        "event": {
            "message": {
                "message_id": "test123",
                "chat_id": "chat123",
                "chat_type": "p2p",
                "content": '{"text": "帮助"}',
                "message_type": "text",
                "create_time": 1234567890
            },
            "sender": {
                "sender_id": {"user_id": "user123"}
            }
        }
    }

    response = asyncio.run(bot.handle_event(test_event))
    print("\n响应:")
    print(response)
