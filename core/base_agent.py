"""
Agent基类 - 整合system和skills的Agent架构
支持两种模式：
1. 消息驱动模式 - 用于交易系统内部
2. Skill模式 - 用于飞书机器人交互
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
from datetime import datetime
import asyncio
import logging
from dataclasses import dataclass


@dataclass
class AgentState:
    """Agent状态"""
    initialized: bool = False
    running: bool = False
    last_activity: Optional[str] = None
    error_count: int = 0


class BaseAgent(ABC):
    """
    统一Agent基类
    同时支持消息总线模式和直接调用模式
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.message_bus: Optional[Any] = None
        self.logger = logging.getLogger(f"agent.{name}")

        # 状态管理
        self._state = AgentState()
        self._message_queue: asyncio.Queue = asyncio.Queue()

        # 消息处理器注册
        self._handlers: Dict[str, Callable] = {}

    def set_message_bus(self, message_bus):
        """设置消息总线"""
        self.message_bus = message_bus

    async def send_message(self, msg_type: str, data: Dict[str, Any], target: Optional[str] = None):
        """发送消息到消息总线"""
        if self.message_bus is None:
            self.logger.warning("消息总线未设置，无法发送消息")
            return

        from .message_bus import Message
        message = Message(
            msg_type=msg_type,
            sender=self.name,
            data=data
        )
        await self.message_bus.publish(message, target)

    async def receive_message(self, message):
        """接收消息"""
        await self._message_queue.put(message)

    def register_handler(self, msg_type: str, handler: Callable):
        """注册消息处理器"""
        self._handlers[msg_type] = handler
        self.logger.debug(f"注册处理器: {msg_type}")

    async def process_message(self, message):
        """处理消息 - 支持动态处理器"""
        handler = self._handlers.get(message.msg_type)
        if handler:
            try:
                await handler(message.data)
            except Exception as e:
                self.logger.error(f"处理消息 [{message.msg_type}] 异常: {e}")
                self._state.error_count += 1
        else:
            # 子类自定义处理
            await self._handle_message(message)

    @abstractmethod
    async def _handle_message(self, message):
        """子类必须实现的消息处理逻辑"""
        pass

    async def initialize(self):
        """初始化 - 可被子类覆盖"""
        self._state.initialized = True
        self._state.last_activity = datetime.now().isoformat()
        self.logger.info(f"Agent [{self.name}] 初始化完成")

        # 订阅消息
        if self.message_bus:
            self.message_bus.subscribe_agent(self.name, self.receive_message)

    async def start(self):
        """启动Agent - 消息循环"""
        self._state.running = True
        self.logger.info(f"Agent [{self.name}] 启动")

        while self._state.running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0
                )
                self._state.last_activity = datetime.now().isoformat()
                await self.process_message(message)
            except asyncio.TimeoutError:
                await self._on_idle()
            except Exception as e:
                self.logger.error(f"Agent [{self.name}] 处理消息异常: {e}")
                self._state.error_count += 1

    async def stop(self):
        """停止Agent"""
        self._state.running = False
        self.logger.info(f"Agent [{self.name}] 停止")

    async def _on_idle(self):
        """空闲时回调 - 可被子类覆盖"""
        pass

    def get_state(self) -> Dict[str, Any]:
        """获取Agent状态"""
        return {
            "name": self.name,
            "initialized": self._state.initialized,
            "running": self._state.running,
            "last_activity": self._state.last_activity,
            "error_count": self._state.error_count
        }

    def is_healthy(self) -> bool:
        """检查Agent健康状态"""
        return self._state.initialized and self._state.error_count < 10
