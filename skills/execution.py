#!/usr/bin/env python3
"""
交易执行技能
整合自:
- futures_trading_skills/trade-execution-skill/scripts/execution.py
- futures_trading_system/agents/trade_execution_agent.py
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import asyncio

from core import SkillAgent, Message
from shared import DataClient


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class Order:
    """订单"""
    order_id: str
    symbol: str
    direction: str  # long/short
    order_type: str
    volume: int
    price: float = 0
    filled_volume: int = 0
    avg_price: float = 0
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class ExecutionPlan:
    """执行计划"""
    symbol: str
    direction: str
    total_volume: int
    strategy: str
    slices: List[Dict] = field(default_factory=list)
    estimated_duration: int = 0  # 预计执行时间（秒）


class ExecutionSkill(SkillAgent):
    """
    交易执行技能
    功能:
    1. 订单执行（市价、限价）
    2. 拆单策略（TWAP、VWAP）
    3. 订单管理
    4. 执行报告
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("trade_execution", config)

        # 配置
        self.default_strategy = config.get("default_strategy", "twap")
        self.twap_interval = config.get("twap_interval", 60)
        self.vwap_buckets = config.get("vwap_buckets", 10)

        # 订单管理
        self._orders: Dict[str, Order] = {}
        self._order_counter = 0

        # 注册命令
        self._register_commands()

        # 注册消息处理器
        self.register_handler("execute_order", self._on_execute_order)
        self.register_handler("cancel_order", self._on_cancel_order)

    def _register_commands(self):
        """注册命令"""
        self.register_command("下单", self._cmd_order, "模拟下单，如: 下单 AU 多 2 750")
        self.register_command("撤单", self._cmd_cancel, "撤销订单，如: 撤单 ORDER001")
        self.register_command("持仓", self._cmd_positions, "查看持仓")
        self.register_command("订单", self._cmd_orders, "查看订单列表")
        self.register_command("twap", self._cmd_twap, "TWAP拆单，如: twap AU 多 10")

    # ==================== 订单执行 ====================

    def create_order(
        self,
        symbol: str,
        direction: str,
        volume: int,
        price: float = 0,
        order_type: str = "limit"
    ) -> Order:
        """创建订单"""
        self._order_counter += 1
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{self._order_counter:04d}"

        order = Order(
            order_id=order_id,
            symbol=symbol.upper(),
            direction=direction,
            order_type=order_type,
            volume=volume,
            price=price,
            status="pending"
        )

        self._orders[order_id] = order
        self.logger.info(f"创建订单: {order_id}")
        return order

    def execute_order(self, order_id: str) -> bool:
        """执行订单（模拟）"""
        order = self._orders.get(order_id)
        if not order:
            return False

        # 模拟执行
        order.status = "filled"
        order.filled_volume = order.volume
        order.avg_price = order.price if order.price > 0 else 750  # 模拟价格
        order.updated_at = datetime.now().isoformat()

        self.logger.info(f"订单执行完成: {order_id}")
        return True

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        order = self._orders.get(order_id)
        if not order:
            return False

        if order.status in ["pending", "partial"]:
            order.status = "cancelled"
            order.updated_at = datetime.now().isoformat()
            self.logger.info(f"订单已撤销: {order_id}")
            return True

        return False

    # ==================== 拆单策略 ====================

    def create_twap_plan(
        self,
        symbol: str,
        direction: str,
        total_volume: int,
        duration: int = 300,
        slices: int = 5
    ) -> ExecutionPlan:
        """
        创建TWAP执行计划

        Args:
            symbol: 品种
            direction: 方向
            total_volume: 总数量
            duration: 执行时长（秒）
            slices: 拆分次数
        """
        symbol = symbol.upper()
        interval = duration // slices
        volume_per_slice = total_volume // slices
        remainder = total_volume % slices

        plan = ExecutionPlan(
            symbol=symbol,
            direction=direction,
            total_volume=total_volume,
            strategy="TWAP",
            estimated_duration=duration
        )

        for i in range(slices):
            vol = volume_per_slice + (1 if i < remainder else 0)
            plan.slices.append({
                "slice_id": i + 1,
                "volume": vol,
                "delay": i * interval,
                "status": "pending"
            })

        return plan

    def create_vwap_plan(
        self,
        symbol: str,
        direction: str,
        total_volume: int,
        buckets: int = 10
    ) -> ExecutionPlan:
        """
        创建VWAP执行计划

        Args:
            symbol: 品种
            direction: 方向
            total_volume: 总数量
            buckets: 时间段数
        """
        symbol = symbol.upper()

        # 模拟成交量分布（实际应从历史数据计算）
        # 通常开盘和收盘成交量较大
        weights = [1.5, 1.2, 1.0, 0.8, 0.7, 0.7, 0.8, 1.0, 1.2, 1.5]
        total_weight = sum(weights[:buckets])

        plan = ExecutionPlan(
            symbol=symbol,
            direction=direction,
            total_volume=total_volume,
            strategy="VWAP",
            estimated_duration=buckets * 180  # 每段3分钟
        )

        for i in range(buckets):
            vol = int(total_volume * weights[i] / total_weight)
            plan.slices.append({
                "slice_id": i + 1,
                "volume": vol,
                "time_bucket": i + 1,
                "status": "pending"
            })

        return plan

    async def execute_twap(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """执行TWAP计划"""
        results = []

        for slice_info in plan.slices:
            # 创建子订单
            order = self.create_order(
                symbol=plan.symbol,
                direction=plan.direction,
                volume=slice_info["volume"]
            )

            # 模拟延迟
            await asyncio.sleep(0.1)

            # 执行
            self.execute_order(order.order_id)

            results.append({
                "slice_id": slice_info["slice_id"],
                "order_id": order.order_id,
                "volume": slice_info["volume"],
                "status": "filled"
            })

        return {
            "plan_id": f"TWAP{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "symbol": plan.symbol,
            "total_volume": plan.total_volume,
            "filled_volume": sum(r["volume"] for r in results),
            "slices": results,
            "avg_price": 750  # 模拟
        }

    # ==================== 消息处理器 ====================

    async def _on_execute_order(self, data: Dict):
        """处理执行订单请求"""
        order = self.create_order(
            symbol=data.get("symbol", ""),
            direction=data.get("direction", "long"),
            volume=data.get("volume", 0),
            price=data.get("price", 0),
            order_type=data.get("order_type", "limit")
        )

        # 模拟执行
        self.execute_order(order.order_id)

        await self.send_message(
            "order_executed",
            {
                "order_id": order.order_id,
                "status": order.status,
                "filled_volume": order.filled_volume,
                "avg_price": order.avg_price
            },
            target=data.get("requester")
        )

    async def _on_cancel_order(self, data: Dict):
        """处理撤单请求"""
        order_id = data.get("order_id", "")
        success = self.cancel_order(order_id)

        await self.send_message(
            "order_cancelled",
            {"order_id": order_id, "success": success},
            target=data.get("requester")
        )

    # ==================== 飞书命令 ====================

    async def _cmd_order(self, args: str, user_id: str, chat_id: str) -> str:
        """下单命令"""
        parts = args.split()

        if len(parts) < 3:
            return """用法: 下单 品种 方向 手数 [价格]

示例:
  下单 AU 多 2
  下单 AU 多 2 750.50
  下单 RB 空 5 3800
"""

        symbol = parts[0].upper()
        direction_map = {"多": "long", "long": "long", "做多": "long",
                        "空": "short", "short": "short", "做空": "short"}
        direction = direction_map.get(parts[1], parts[1])
        volume = int(parts[2])
        price = float(parts[3]) if len(parts) > 3 else 0

        order = self.create_order(symbol, direction, volume, price, "limit" if price > 0 else "market")
        self.execute_order(order.order_id)

        lines = [
            f"## 📋 订单已创建",
            "",
            f"**订单号**: {order.order_id}",
            f"**品种**: {symbol}",
            f"**方向**: {'做多 📈' if direction == 'long' else '做空 📉'}",
            f"**手数**: {volume}",
            f"**价格**: {price if price > 0 else '市价'}",
            f"**状态**: ✅ 已成交",
        ]

        if order.avg_price > 0:
            lines.append(f"**成交均价**: {order.avg_price:.2f}")

        lines.extend([
            "",
            "⚠️ 模拟交易，仅供测试",
        ])

        return "\n".join(lines)

    async def _cmd_cancel(self, args: str, user_id: str, chat_id: str) -> str:
        """撤单命令"""
        order_id = args.strip()

        if not order_id:
            return "用法: 撤单 订单号"

        success = self.cancel_order(order_id)

        if success:
            return f"✅ 订单 {order_id} 已撤销"
        else:
            return f"❌ 无法撤销订单 {order_id}（可能不存在或已成交）"

    async def _cmd_positions(self, args: str, user_id: str, chat_id: str) -> str:
        """持仓命令"""
        lines = [
            "## 📊 当前持仓",
            "",
            "暂无持仓（模拟模式）",
            "",
            "使用 **下单** 命令创建模拟订单"
        ]
        return "\n".join(lines)

    async def _cmd_orders(self, args: str, user_id: str, chat_id: str) -> str:
        """订单列表命令"""
        recent_orders = sorted(
            self._orders.values(),
            key=lambda o: o.created_at,
            reverse=True
        )[:10]

        if not recent_orders:
            return "暂无订单记录"

        lines = ["## 📋 最近订单", ""]

        for order in recent_orders:
            status_emoji = {
                "filled": "✅",
                "pending": "⏳",
                "cancelled": "❌"
            }.get(order.status, "❓")

            lines.append(f"{status_emoji} {order.order_id} {order.symbol}")
            lines.append(f"   {order.direction} | {order.volume}手 @ {order.avg_price or order.price or '市价'}")

        return "\n".join(lines)

    async def _cmd_twap(self, args: str, user_id: str, chat_id: str) -> str:
        """TWAP命令"""
        parts = args.split()

        if len(parts) < 3:
            return """用法: twap 品种 方向 总手数 [段数]

示例:
  twap AU 多 10
  twap AU 多 10 5
"""

        symbol = parts[0].upper()
        direction_map = {"多": "long", "空": "short"}
        direction = direction_map.get(parts[1], parts[1])
        total_volume = int(parts[2])
        slices = int(parts[3]) if len(parts) > 3 else 5

        plan = self.create_twap_plan(symbol, direction, total_volume, slices=slices)

        lines = [
            f"## ⏱️ TWAP 执行计划",
            "",
            f"**品种**: {symbol}",
            f"**方向**: {'做多' if direction == 'long' else '做空'}",
            f"**总手数**: {total_volume}",
            f"**拆分段数**: {len(plan.slices)}",
            f"**预计耗时**: {plan.estimated_duration} 秒",
            "",
            "**拆分详情**:",
        ]

        for s in plan.slices:
            lines.append(f"  第{s['slice_id']}段: {s['volume']}手 (+{s['delay']}秒)")

        lines.extend([
            "",
            "💡 实际执行需要接入CTP实盘接口"
        ])

        return "\n".join(lines)

    # ==================== Agent生命周期 ====================

    async def initialize(self):
        """初始化"""
        await super().initialize()
        self.logger.info("交易执行技能初始化完成")


# 兼容旧代码
TradeExecutionAgent = ExecutionSkill
