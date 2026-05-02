#!/usr/bin/env python3
"""
回测技能
整合自:
- futures_trading_skills/backtest-skill/scripts/backtest.py
- futures_trading_system/agents/backtest_agent.py
"""
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

from core import SkillAgent, Message
from shared import DataClient


@dataclass
class Trade:
    """交易记录"""
    entry_time: str
    exit_time: str = ""
    symbol: str = ""
    direction: str = ""  # long/short
    entry_price: float = 0
    exit_price: float = 0
    volume: int = 0
    pnl: float = 0
    commission: float = 0
    status: str = "open"  # open/closed


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)


class BacktestSkill(SkillAgent):
    """
    回测技能
    功能:
    1. 策略回测
    2. 绩效分析
    3. 策略优化
    4. 飞书报告
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("backtest", config)

        # 配置
        self.initial_capital = config.get("initial_capital", 1000000)
        self.commission_rate = config.get("commission_rate", 0.0001)
        self.slippage = config.get("slippage", 0.001)

        # 策略注册
        self._strategies: Dict[str, Callable] = {}

        # 回测状态
        self._current_capital = self.initial_capital
        self._positions: Dict[str, Dict] = {}
        self._trades: List[Trade] = []
        self._equity_curve: List[Dict] = []

        # 注册命令
        self._register_commands()

        # 注册消息处理器
        self.register_handler("backtest_request", self._on_backtest_request)

    def _register_commands(self):
        """注册命令"""
        self.register_command("回测", self._cmd_backtest, "执行回测，如: 回测 AU 2024-01-01 2024-03-01")
        self.register_command("策略", self._cmd_strategies, "列出可用策略")
        self.register_command("绩效", self._cmd_performance, "查看回测绩效")

    # ==================== 策略管理 ====================

    def register_strategy(self, name: str, strategy_func: Callable):
        """注册策略"""
        self._strategies[name] = strategy_func
        self.logger.info(f"注册策略: {name}")

    def get_strategies(self) -> List[str]:
        """获取策略列表"""
        return list(self._strategies.keys())

    # ==================== 回测引擎 ====================

    def run_backtest(
        self,
        strategy_name: str,
        symbol: str,
        start_date: str,
        end_date: str,
        initial_capital: Optional[float] = None
    ) -> Optional[BacktestResult]:
        """
        运行回测

        Args:
            strategy_name: 策略名称
            symbol: 品种代码
            start_date: 开始日期
            end_date: 结束日期
            initial_capital: 初始资金
        """
        strategy = self._strategies.get(strategy_name)
        if not strategy:
            self.logger.error(f"策略不存在: {strategy_name}")
            return None

        # 重置状态
        capital = initial_capital or self.initial_capital
        self._current_capital = capital
        self._positions = {}
        self._trades = []
        self._equity_curve = []

        # 获取历史数据
        data_client = DataClient(source="akshare")
        bars = data_client.get_bars(symbol, start_date, end_date)

        if not bars or len(bars) < 20:
            self.logger.warning(f"数据不足: {symbol}")
            return self._create_empty_result(strategy_name, start_date, end_date, capital)

        # 执行回测
        for i, bar in enumerate(bars):
            # 记录权益
            self._equity_curve.append({
                "date": bar.get("date"),
                "equity": self._current_capital,
                "price": bar.get("close")
            })

            # 调用策略
            signal = strategy(bar, bars[:i+1] if i > 0 else [bar])

            if signal:
                self._process_signal(symbol, signal, bar)

        # 平仓所有持仓
        if bars:
            self._close_all_positions(bars[-1])

        # 计算绩效
        return self._calculate_performance(
            strategy_name, start_date, end_date, capital
        )

    def _process_signal(self, symbol: str, signal: Dict, bar: Dict):
        """处理交易信号"""
        action = signal.get("action")  # buy/sell/close
        direction = signal.get("direction", "long")
        volume = signal.get("volume", 1)
        price = bar.get("close", 0)

        if action == "buy" and "long" in direction:
            self._open_position(symbol, "long", volume, price, bar.get("date"))
        elif action == "sell" and "short" in direction:
            self._open_position(symbol, "short", volume, price, bar.get("date"))
        elif action == "close":
            self._close_position(symbol, price, bar.get("date"))

    def _open_position(self, symbol: str, direction: str, volume: int, price: float, date: str):
        """开仓"""
        if symbol in self._positions:
            return

        trade = Trade(
            entry_time=date,
            symbol=symbol,
            direction=direction,
            entry_price=price,
            volume=volume,
            status="open"
        )

        self._positions[symbol] = trade
        self._trades.append(trade)

    def _close_position(self, symbol: str, price: float, date: str):
        """平仓"""
        position = self._positions.get(symbol)
        if not position:
            return

        # 计算盈亏
        if position.direction == "long":
            pnl = (price - position.entry_price) * position.volume * 10  # 假设乘数10
        else:
            pnl = (position.entry_price - price) * position.volume * 10

        # 扣除手续费
        commission = (price + position.entry_price) * position.volume * self.commission_rate
        pnl -= commission

        position.exit_price = price
        position.exit_time = date
        position.pnl = pnl
        position.commission = commission
        position.status = "closed"

        self._current_capital += pnl
        del self._positions[symbol]

    def _close_all_positions(self, last_bar: Dict):
        """平掉所有持仓"""
        symbols = list(self._positions.keys())
        for symbol in symbols:
            self._close_position(symbol, last_bar.get("close", 0), last_bar.get("date", ""))

    def _calculate_performance(
        self,
        strategy_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float
    ) -> BacktestResult:
        """计算回测绩效"""
        closed_trades = [t for t in self._trades if t.status == "closed"]

        if not closed_trades:
            return self._create_empty_result(strategy_name, start_date, end_date, initial_capital)

        # 基础统计
        total_trades = len(closed_trades)
        winning_trades = len([t for t in closed_trades if t.pnl > 0])
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

        # 盈亏统计
        total_pnl = sum(t.pnl for t in closed_trades)
        gross_profit = sum(t.pnl for t in closed_trades if t.pnl > 0)
        gross_loss = sum(t.pnl for t in closed_trades if t.pnl <= 0)
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else 0

        # 最大回撤
        max_drawdown = 0
        max_drawdown_pct = 0
        peak = initial_capital

        for point in self._equity_curve:
            equity = point["equity"]
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            drawdown_pct = (drawdown / peak) * 100 if peak > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct

        # 夏普比率（简化计算）
        returns = []
        for i in range(1, len(self._equity_curve)):
            prev = self._equity_curve[i-1]["equity"]
            curr = self._equity_curve[i]["equity"]
            if prev > 0:
                returns.append((curr - prev) / prev)

        sharpe = 0
        if returns:
            import statistics
            avg_return = sum(returns) / len(returns)
            std = statistics.stdev(returns) if len(returns) > 1 else 0.001
            sharpe = (avg_return * 252) / (std * (252 ** 0.5)) if std > 0 else 0

        return BacktestResult(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_capital=self._current_capital,
            total_return=(self._current_capital - initial_capital) / initial_capital * 100,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe,
            trades=closed_trades,
            equity_curve=self._equity_curve
        )

    def _create_empty_result(
        self,
        strategy_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float
    ) -> BacktestResult:
        """创建空结果"""
        return BacktestResult(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            profit_factor=0,
            max_drawdown=0,
            max_drawdown_pct=0,
            sharpe_ratio=0
        )

    # ==================== 消息处理器 ====================

    async def _on_backtest_request(self, data: Dict):
        """处理回测请求"""
        result = self.run_backtest(
            strategy_name=data.get("strategy", "ma_crossover"),
            symbol=data.get("symbol", "AU"),
            start_date=data.get("start_date", "2024-01-01"),
            end_date=data.get("end_date", "2024-03-01"),
            initial_capital=data.get("initial_capital", 1000000)
        )

        if result and data.get("requester"):
            await self.send_message(
                "backtest_response",
                {
                    "strategy": result.strategy_name,
                    "total_return": result.total_return,
                    "win_rate": result.win_rate,
                    "max_drawdown_pct": result.max_drawdown_pct
                },
                target=data.get("requester")
            )

    # ==================== 飞书命令 ====================

    async def _cmd_backtest(self, args: str, user_id: str, chat_id: str) -> str:
        """回测命令"""
        parts = args.split()

        if len(parts) < 3:
            return """用法: 回测 品种 开始日期 结束日期 [策略名]

示例:
  回测 AU 2024-01-01 2024-03-01
  回测 AU 2024-01-01 2024-03-01 ma_crossover
"""

        symbol = parts[0].upper()
        start_date = parts[1]
        end_date = parts[2]
        strategy = parts[3] if len(parts) > 3 else "ma_crossover"

        # 如果没有可用策略，显示提示
        if not self._strategies:
            return """## ⚠️ 暂无可用策略

请先在代码中注册策略:
```python
backtest_skill.register_strategy("策略名", 策略函数)
```

或直接使用 **绩效** 命令查看模拟结果。
"""

        result = self.run_backtest(strategy, symbol, start_date, end_date)

        if not result:
            return f"❌ 回测失败，请检查策略名称和日期"

        return self._format_backtest_report(result)

    def _format_backtest_report(self, result: BacktestResult) -> str:
        """格式化回测报告"""
        lines = [
            f"## 📊 {result.strategy_name} 回测报告",
            "",
            f"**回测周期**: {result.start_date} ~ {result.end_date}",
            "",
            "### 收益表现",
            f"  初始资金: {result.initial_capital:,.0f} 元",
            f"  最终资金: {result.final_capital:,.0f} 元",
            f"  总收益率: {result.total_return:+.2f}%",
            f"  夏普比率: {result.sharpe_ratio:.2f}",
            "",
            "### 交易统计",
            f"  总交易次数: {result.total_trades}",
            f"  盈利次数: {result.winning_trades}",
            f"  亏损次数: {result.losing_trades}",
            f"  胜率: {result.win_rate:.1f}%",
            f"  盈亏比: {result.profit_factor:.2f}",
            "",
            "### 风险控制",
            f"  最大回撤: {result.max_drawdown:,.0f} 元",
            f"  最大回撤率: {result.max_drawdown_pct:.2f}%",
        ]

        return "\n".join(lines)

    async def _cmd_strategies(self, args: str, user_id: str, chat_id: str) -> str:
        """策略列表命令"""
        strategies = self.get_strategies()

        if not strategies:
            return "暂无注册策略"

        lines = ["## 📋 可用策略", ""]
        for i, name in enumerate(strategies, 1):
            lines.append(f"{i}. {name}")

        return "\n".join(lines)

    async def _cmd_performance(self, args: str, user_id: str, chat_id: str) -> str:
        """绩效命令 - 模拟数据"""
        lines = [
            "## 📈 策略绩效（示例数据）",
            "",
            "**MA交叉策略**:",
            "  总收益率: +15.3%",
            "  胜率: 52.3%",
            "  最大回撤: 8.5%",
            "  夏普比率: 1.2",
            "",
            "**MACD策略**:",
            "  总收益率: +22.1%",
            "  胜率: 48.7%",
            "  最大回撤: 12.3%",
            "  夏普比率: 1.5",
            "",
            "💡 实际回测请使用 **回测** 命令"
        ]
        return "\n".join(lines)

    # ==================== Agent生命周期 ====================

    async def initialize(self):
        """初始化"""
        await super().initialize()

        # 注册示例策略
        self._register_default_strategies()
        self.logger.info("回测技能初始化完成")

    def _register_default_strategies(self):
        """注册默认策略"""
        def ma_crossover(bar: Dict, history: List[Dict]) -> Optional[Dict]:
            """MA交叉策略示例"""
            if len(history) < 20:
                return None

            # 简单实现：用收盘价判断
            closes = [b.get("close", 0) for b in history[-20:]]
            ma5 = sum(closes[-5:]) / 5
            ma20 = sum(closes[-20:]) / 20

            current = bar.get("close", 0)

            if ma5 > ma20 and current > ma5:
                return {"action": "buy", "direction": "long", "volume": 1}
            elif ma5 < ma20 and current < ma5:
                return {"action": "sell", "direction": "short", "volume": 1}

            return None

        self.register_strategy("ma_crossover", ma_crossover)


# 兼容旧代码
BacktestAgent = BacktestSkill
