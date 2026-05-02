"""
统一消息总线 - 整合本地async和Redis实现
根据配置自动选择后端
"""
import asyncio
import json
import logging
from typing import Dict, List, Callable, Optional, Set, Any
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class Message:
    """消息类 - Agent间通信的基本单位"""
    msg_type: str
    sender: str
    data: Dict[str, Any]
    timestamp: Optional[str] = None
    target: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Message":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class MessageBus:
    """
    统一消息总线
    支持两种模式：
    1. 本地模式（async）- 单机使用
    2. Redis模式 - 分布式/多进程使用
    """

    def __init__(self, mode: str = "local", redis_url: str = "redis://localhost:6379/0"):
        self.mode = mode
        self.logger = logging.getLogger("MessageBus")

        # 本地模式
        self._type_subscribers: Dict[str, List[str]] = defaultdict(list)
        self._agent_subscribers: Dict[str, Callable] = {}
        self._broadcast_subscribers: Set[str] = set()

        # Redis模式
        self.redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._handlers: Dict[str, Callable] = {}

        if mode == "redis":
            self._init_redis()

    def _init_redis(self):
        """初始化Redis连接"""
        try:
            import redis as redis_lib
            self._redis = redis_lib.from_url(self.redis_url)
            self._pubsub = self._redis.pubsub()
            self.logger.info("Redis消息总线初始化成功")
        except ImportError:
            self.logger.warning("redis未安装，回退到本地模式")
            self.mode = "local"
        except Exception as e:
            self.logger.error(f"Redis连接失败: {e}，回退到本地模式")
            self.mode = "local"

    # ==================== 本地模式方法 ====================

    def subscribe_by_type(self, agent_name: str, msg_types: List[str]):
        """按消息类型订阅（本地模式）"""
        if self.mode == "local":
            for msg_type in msg_types:
                if agent_name not in self._type_subscribers[msg_type]:
                    self._type_subscribers[msg_type].append(agent_name)
                    self.logger.debug(f"Agent [{agent_name}] 订阅消息类型: {msg_type}")

    def subscribe_agent(self, agent_name: str, callback: Callable):
        """注册Agent回调函数（本地模式）"""
        if self.mode == "local":
            self._agent_subscribers[agent_name] = callback
            self.logger.info(f"Agent [{agent_name}] 注册到消息总线")

    def subscribe_broadcast(self, agent_name: str):
        """订阅广播消息（本地模式）"""
        if self.mode == "local":
            self._broadcast_subscribers.add(agent_name)
            self.logger.info(f"Agent [{agent_name}] 订阅广播消息")

    # ==================== Redis模式方法 ====================

    def subscribe(self, channel: str, handler: Callable):
        """订阅频道（Redis模式）"""
        if self.mode == "redis" and self._pubsub:
            self._pubsub.subscribe(channel)
            self._handlers[channel] = handler
            self.logger.info(f"订阅频道: {channel}")

    def publish_to_channel(self, channel: str, message: Dict[str, Any]) -> bool:
        """发布消息到频道（Redis模式）"""
        if self.mode == "redis" and self._redis:
            try:
                message["timestamp"] = datetime.now().isoformat()
                self._redis.publish(channel, json.dumps(message, ensure_ascii=False))
                return True
            except Exception as e:
                self.logger.error(f"发布消息失败: {e}")
                return False
        return False

    # ==================== 统一发布接口 ====================

    async def publish(self, message: Message, target: Optional[str] = None):
        """
        发布消息 - 统一接口
        根据模式自动选择本地或Redis发送
        """
        message.target = target or message.target

        if self.mode == "redis":
            # Redis模式：序列化后发送
            self.publish_to_channel(
                f"trading:{message.msg_type}",
                message.to_dict()
            )
            return

        # 本地模式
        self.logger.debug(
            f"发布消息: [{message.msg_type}] from [{message.sender}] -> {target or 'broadcast'}"
        )

        # 点对点发送
        if target:
            if target in self._agent_subscribers:
                callback = self._agent_subscribers[target]
                await callback(message)
            return

        # 按类型分发
        recipients = set()
        if message.msg_type in self._type_subscribers:
            recipients.update(self._type_subscribers[message.msg_type])

        # 广播给订阅者
        recipients.update(self._broadcast_subscribers)

        # 排除发送者
        recipients.discard(message.sender)

        # 并发发送
        tasks = []
        for agent_name in recipients:
            if agent_name in self._agent_subscribers:
                callback = self._agent_subscribers[agent_name]
                tasks.append(callback(message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ==================== 辅助方法 ====================

    def unsubscribe(self, agent_name: str):
        """取消订阅"""
        if self.mode == "local":
            # 从类型订阅中移除
            for msg_type in self._type_subscribers:
                if agent_name in self._type_subscribers[msg_type]:
                    self._type_subscribers[msg_type].remove(agent_name)

            # 从Agent订阅中移除
            if agent_name in self._agent_subscribers:
                del self._agent_subscribers[agent_name]

            # 从广播订阅中移除
            self._broadcast_subscribers.discard(agent_name)

        self.logger.info(f"Agent [{agent_name}] 取消订阅")

    def get_subscribers(self, msg_type: str) -> List[str]:
        """获取某消息类型的订阅者"""
        if self.mode == "local":
            return self._type_subscribers.get(msg_type, [])
        return []

    def start_redis_listener(self):
        """启动Redis监听线程"""
        if self.mode == "redis":
            import threading
            thread = threading.Thread(target=self._listen_redis, daemon=True)
            thread.start()
            return thread

    def _listen_redis(self):
        """Redis监听循环"""
        if not self._pubsub:
            return

        for message in self._pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")

                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                try:
                    msg = json.loads(data)
                    handler = self._handlers.get(channel)
                    if handler:
                        handler(msg)
                except Exception as e:
                    self.logger.error(f"处理Redis消息失败: {e}")


# 预定义频道（兼容旧代码）
CHANNELS = {
    "trading:signals": "交易信号频道",
    "trading:orders": "订单状态频道",
    "trading:positions": "持仓更新频道",
    "trading:alerts": "风险预警频道",
    "trading:logs": "交易日志频道",
}
