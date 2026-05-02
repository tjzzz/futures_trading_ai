#!/usr/bin/env python3
"""
风险管理技能
整合自:
- futures_trading_skills/risk-management-skill/scripts/risk.py
- futures_trading_system/agents/risk_management_agent.py
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import logging
import math

from core import SkillAgent, Message
from shared import DataClient


@dataclass
class PositionSizing:
    """仓位计算结果"""
    symbol: str
    suggested_lots: int
    max_lots: int
    risk_per_lot: float
    total_risk: float
    method: str
    confidence: float


@dataclass
class RiskCheck:
    """风险检查结果"""
    symbol: str
    direction: str
    allowed: bool
    reason: str
    risk_level: str
    stop_loss: float
    position_size: int
    risk_amount: float
    risk_percent: float


class RiskSkill(SkillAgent):
    """
    风险管理技能
    功能:
    1. 仓位计算（凯利公式、固定风险、固定比例）
    2. 止损计算
    3. 风险检查
    4. 组合风险评估
    """

    # 品种乘数配置（合约大小 × 最小变动价位）
    CONTRACT_CONFIGS = {
        "AU": {"multiplier": 1000, "min_move": 0.02, "margin_rate": 0.1},
        "AG": {"multiplier": 15, "min_move": 1, "margin_rate": 0.12},
        "CU": {"multiplier": 5, "min_move": 10, "margin_rate": 0.12},
        "AL": {"multiplier": 5, "min_move": 5, "margin_rate": 0.12},
        "ZN": {"multiplier": 5, "min_move": 5, "margin_rate": 0.12},
        "RB": {"multiplier": 10, "min_move": 1, "margin_rate": 0.13},
        "HC": {"multiplier": 10, "min_move": 1, "margin_rate": 0.13},
        "SC": {"multiplier": 1000, "min_move": 0.1, "margin_rate": 0.15},
        "M": {"multiplier": 10, "min_move": 1, "margin_rate": 0.12},
        "Y": {"multiplier": 10, "min_move": 2, "margin_rate": 0.12},
        "I": {"multiplier": 100, "min_move": 0.5, "margin_rate": 0.15},
        "SR": {"multiplier": 10, "min_move": 1, "margin_rate": 0.12},
        "CF": {"multiplier": 5, "min_move": 5, "margin_rate": 0.12},
        "TA": {"multiplier": 5, "min_move": 2, "margin_rate": 0.12},
        "MA": {"multiplier": 10, "min_move": 1, "margin_rate": 0.12},
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("risk_management", config)

        # 风控参数
        self.max_position_pct = config.get("max_position_pct", 0.3)
        self.max_single_loss_pct = config.get("max_single_loss_pct", 0.02)
        self.default_stop_loss_atr = config.get("default_stop_loss_atr", 2.0)
        self.max_daily_loss_pct = config.get("max_daily_loss_pct", 0.05)

        # 当前持仓
        self._positions: Dict[str, Dict] = {}
        self._daily_pnl = 0
        self._daily_trades = 0

        # 注册命令
        self._register_commands()

        # 注册消息处理器
        self.register_handler("position_request", self._on_position_request)
        self.register_handler("risk_check", self._on_risk_check)

    def _register_commands(self):
        """注册命令"""
        self.register_command("仓位", self._cmd_position, "计算建议仓位，如: 仓位 AU 100000 750")
        self.register_command("止损", self._cmd_stop_loss, "计算止损位，如: 止损 AU 750")
        self.register_command("风控", self._cmd_risk_check, "风险检查")
        self.register_command("凯利", self._cmd_kelly, "凯利公式计算")

    # ==================== 仓位计算 ====================

    def calculate_position(
        self,
        symbol: str,
        account_value: float,
        price: float,
        atr: float,
        win_rate: float = 0.5,
        payoff_ratio: float = 2.0,
        method: str = "fixed_risk"
    ) -> PositionSizing:
        """
        计算建议仓位

        Args:
            symbol: 品种代码
            account_value: 账户总价值
            price: 当前价格
            atr: ATR值
            win_rate: 胜率（凯利公式使用）
            payoff_ratio: 盈亏比（凯利公式使用）
            method: 计算方法 - fixed_risk, kelly, fixed_fraction
        """
        symbol = symbol.upper()
        config = self.CONTRACT_CONFIGS.get(symbol, {"multiplier": 10, "min_move": 1, "margin_rate": 0.1})

        # 计算每手价值
        contract_value = price * config["multiplier"]

        # 计算每手风险（基于ATR）
        risk_per_lot = atr * config["multiplier"] * self.default_stop_loss_atr

        suggested_lots = 0
        confidence = 0.5

        if method == "fixed_risk":
            # 固定风险法
            max_risk_amount = account_value * self.max_single_loss_pct
            suggested_lots = int(max_risk_amount / risk_per_lot) if risk_per_lot > 0 else 0
            confidence = 0.7

        elif method == "kelly":
            # 凯利公式
            kelly_pct = self._kelly_formula(win_rate, payoff_ratio)
            suggested_lots = int(account_value * kelly_pct / contract_value)
            confidence = win_rate

        elif method == "fixed_fraction":
            # 固定比例法
            fraction = min(0.1, self.max_position_pct / 2)  # 更保守
            suggested_lots = int(account_value * fraction / contract_value)
            confidence = 0.6

        # 限制最大仓位
        max_margin_usage = account_value * self.max_position_pct
        max_lots_by_margin = int(max_margin_usage / (contract_value * config["margin_rate"]))

        max_lots = min(max_lots_by_margin, suggested_lots * 2)
        suggested_lots = min(suggested_lots, max_lots)

        # 确保至少0手
        suggested_lots = max(0, suggested_lots)

        total_risk = suggested_lots * risk_per_lot

        return PositionSizing(
            symbol=symbol,
            suggested_lots=suggested_lots,
            max_lots=max_lots,
            risk_per_lot=risk_per_lot,
            total_risk=total_risk,
            method=method,
            confidence=confidence
        )

    def _kelly_formula(self, win_rate: float, payoff_ratio: float) -> float:
        """
        凯利公式
        f* = (p*b - q) / b
        其中:
        p = 胜率
        q = 败率 = 1-p
        b = 盈亏比
        """
        if payoff_ratio <= 0:
            return 0

        kelly = (win_rate * payoff_ratio - (1 - win_rate)) / payoff_ratio

        # 使用半凯利（更保守）
        return max(0, kelly * 0.5)

    # ==================== 止损计算 ====================

    def calculate_stop_loss(
        self,
        symbol: str,
        entry_price: float,
        direction: str,
        atr: float,
        method: str = "atr"
    ) -> Dict[str, Any]:
        """
        计算止损位

        Args:
            symbol: 品种代码
            entry_price: 入场价格
            direction: 方向 - long/short
            atr: ATR值
            method: 计算方法 - atr, percentage, fixed
        """
        symbol = symbol.upper()
        result = {
            "symbol": symbol,
            "entry_price": entry_price,
            "direction": direction,
            "method": method,
            "stop_loss": 0,
            "risk_amount": 0,
            "risk_percent": 0
        }

        if method == "atr":
            # ATR倍数法
            stop_distance = atr * self.default_stop_loss_atr
        elif method == "percentage":
            # 固定百分比
            stop_distance = entry_price * 0.02  # 2%
        else:
            stop_distance = atr * 2

        if direction == "long":
            result["stop_loss"] = entry_price - stop_distance
        else:
            result["stop_loss"] = entry_price + stop_distance

        result["risk_amount"] = stop_distance
        result["risk_percent"] = (stop_distance / entry_price) * 100

        return result

    # ==================== 风险检查 ====================

    def check_risk(
        self,
        symbol: str,
        direction: str,
        lots: int,
        entry_price: float,
        account_value: float,
        atr: float
    ) -> RiskCheck:
        """检查交易风险"""
        symbol = symbol.upper()

        reasons = []
        risk_level = "low"

        # 检查日亏损限制
        daily_loss_pct = abs(self._daily_pnl) / account_value if account_value > 0 else 0
        if daily_loss_pct >= self.max_daily_loss_pct:
            return RiskCheck(
                symbol=symbol,
                direction=direction,
                allowed=False,
                reason="日亏损限制已达上限",
                risk_level="critical",
                stop_loss=0,
                position_size=0,
                risk_amount=0,
                risk_percent=0
            )

        # 计算仓位风险
        position = self.calculate_position(symbol, account_value, entry_price, atr)

        if lots > position.max_lots:
            reasons.append(f"仓位超过最大限制({position.max_lots}手)")
            risk_level = "high"

        # 计算止损
        stop_result = self.calculate_stop_loss(symbol, entry_price, direction, atr)
        stop_loss = stop_result["stop_loss"]
        risk_amount = stop_result["risk_amount"] * lots
        risk_percent = (risk_amount / account_value) * 100

        if risk_percent > self.max_single_loss_pct * 100 * 1.5:
            reasons.append("单笔风险过高")
            risk_level = "high"
        elif risk_percent > self.max_single_loss_pct * 100:
            reasons.append("单笔风险偏高")
            risk_level = "medium"

        # 检查同向持仓
        existing = self._positions.get(symbol)
        if existing and existing.get("direction") == direction:
            reasons.append("已有同向持仓")
            risk_level = "medium"

        allowed = len(reasons) == 0

        return RiskCheck(
            symbol=symbol,
            direction=direction,
            allowed=allowed,
            reason="; ".join(reasons) if reasons else "通过",
            risk_level=risk_level,
            stop_loss=stop_loss,
            position_size=lots,
            risk_amount=risk_amount,
            risk_percent=risk_percent
        )

    # ==================== 消息处理器 ====================

    async def _on_position_request(self, data: Dict):
        """处理仓位请求"""
        symbol = data.get("symbol")
        account_value = data.get("account_value", 100000)
        price = data.get("price", 0)
        atr = data.get("atr", price * 0.01)
        method = data.get("method", "fixed_risk")

        if symbol and price > 0:
            result = self.calculate_position(symbol, account_value, price, atr, method=method)
            await self.send_message(
                "position_response",
                {
                    "symbol": symbol,
                    "suggested_lots": result.suggested_lots,
                    "risk_amount": result.total_risk,
                    "method": method
                },
                target=data.get("requester")
            )

    async def _on_risk_check(self, data: Dict):
        """处理风险检查请求"""
        result = self.check_risk(
            symbol=data.get("symbol", ""),
            direction=data.get("direction", "long"),
            lots=data.get("lots", 0),
            entry_price=data.get("entry_price", 0),
            account_value=data.get("account_value", 100000),
            atr=data.get("atr", 0)
        )

        await self.send_message(
            "risk_check_response",
            {
                "allowed": result.allowed,
                "reason": result.reason,
                "risk_level": result.risk_level,
                "stop_loss": result.stop_loss
            },
            target=data.get("requester")
        )

    # ==================== 飞书命令 ====================

    async def _cmd_position(self, args: str, user_id: str, chat_id: str) -> str:
        """仓位计算命令"""
        parts = args.split()

        if len(parts) < 3:
            return """用法: 仓位 品种 账户资金 当前价格 [ATR]

示例:
  仓位 AU 100000 750
  仓位 AU 100000 750 15
"""

        symbol = parts[0].upper()
        account_value = float(parts[1])
        price = float(parts[2])
        atr = float(parts[3]) if len(parts) > 3 else price * 0.015

        # 使用多种方法计算
        results = []
        for method in ["fixed_risk", "kelly", "fixed_fraction"]:
            result = self.calculate_position(symbol, account_value, price, atr, method=method)
            results.append(result)

        config = self.CONTRACT_CONFIGS.get(symbol, {})

        lines = [
            f"## 📊 {symbol} 仓位计算",
            "",
            f"**账户资金**: {account_value:,.0f} 元",
            f"**当前价格**: {price} 元",
            f"**ATR**: {atr:.2f}",
            "",
            "### 建议仓位",
        ]

        method_names = {
            "fixed_risk": "固定风险法",
            "kelly": "凯利公式",
            "fixed_fraction": "固定比例法"
        }

        for result in results:
            lines.append(f"**{method_names.get(result.method, result.method)}**:")
            lines.append(f"  建议手数: {result.suggested_lots} 手")
            lines.append(f"  最大手数: {result.max_lots} 手")
            lines.append(f"  单手风险: {result.risk_per_lot:,.0f} 元")
            lines.append(f"  总风险: {result.total_risk:,.0f} 元")
            lines.append("")

        lines.append(f"*保证金率约: {config.get('margin_rate', 0.1)*100:.0f}%*")

        return "\n".join(lines)

    async def _cmd_stop_loss(self, args: str, user_id: str, chat_id: str) -> str:
        """止损计算命令"""
        parts = args.split()

        if len(parts) < 2:
            return """用法: 止损 品种 入场价 [方向] [ATR]

示例:
  止损 AU 750
  止损 AU 750 long 15
"""

        symbol = parts[0].upper()
        entry_price = float(parts[1])
        direction = parts[2] if len(parts) > 2 else "long"
        atr = float(parts[3]) if len(parts) > 3 else entry_price * 0.015

        result = self.calculate_stop_loss(symbol, entry_price, direction, atr)

        lines = [
            f"## 🛡️ {symbol} 止损计算",
            "",
            f"**入场价格**: {entry_price}",
            f"**方向**: {'做多 📈' if direction == 'long' else '做空 📉'}",
            f"**ATR**: {atr:.2f}",
            "",
            f"**建议止损位**: {result['stop_loss']:.2f}",
            f"**止损距离**: {result['risk_amount']:.2f} ({result['risk_percent']:.2f}%)",
            "",
            f"*基于 ATR × {self.default_stop_loss_atr} 计算*"
        ]

        return "\n".join(lines)

    async def _cmd_risk_check(self, args: str, user_id: str, chat_id: str) -> str:
        """风险检查命令"""
        # 简化版，显示当前风控参数
        lines = [
            "## ⚠️ 风控参数设置",
            "",
            f"**最大仓位比例**: {self.max_position_pct*100:.0f}%",
            f"**单笔最大亏损**: {self.max_single_loss_pct*100:.2f}%",
            f"**日最大亏损**: {self.max_daily_loss_pct*100:.2f}%",
            f"**默认止损ATR倍数**: {self.default_stop_loss_atr}",
            "",
            "使用 **仓位** 或 **止损** 命令计算具体参数"
        ]
        return "\n".join(lines)

    async def _cmd_kelly(self, args: str, user_id: str, chat_id: str) -> str:
        """凯利公式命令"""
        parts = args.split()

        if len(parts) < 2:
            return """用法: 凯利 胜率 盈亏比

示例:
  凯利 0.55 2.0
"""

        win_rate = float(parts[0])
        payoff_ratio = float(parts[1])

        kelly = self._kelly_formula(win_rate, payoff_ratio)
        full_kelly = (win_rate * payoff_ratio - (1 - win_rate)) / payoff_ratio if payoff_ratio > 0 else 0

        lines = [
            "## 🎯 凯利公式计算",
            "",
            f"**胜率**: {win_rate*100:.1f}%",
            f"**盈亏比**: {payoff_ratio}:1",
            "",
            f"**全凯利仓位**: {full_kelly*100:.2f}%",
            f"**半凯利仓位**: {kelly*100:.2f}% (推荐)",
            "",
            "⚠️ 凯利公式基于历史统计，实际使用时建议采用半凯利或更保守的比例"
        ]
        return "\n".join(lines)

    # ==================== Agent生命周期 ====================

    async def initialize(self):
        """初始化"""
        await super().initialize()
        self.logger.info("风险管理技能初始化完成")


# 兼容旧代码
RiskManagementAgent = RiskSkill
