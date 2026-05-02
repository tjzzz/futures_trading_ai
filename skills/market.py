#!/usr/bin/env python3
"""
市场行情分析技能
整合自:
- futures_trading_skills/market-analysis-skill/scripts/analyze.py
- futures_trading_system/agents/market_analysis_agent.py
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd
import logging

from core import SkillAgent, Message
from shared import DataClient, Config
from shared.indicators import calculate_all_indicators, generate_signals, analyze_trend


class MarketSkill(SkillAgent):
    """
    市场分析技能
    功能:
    1. 获取实时行情数据
    2. 计算技术指标
    3. 生成交易信号
    4. 飞书机器人交互
    """

    # 品种信息配置
    COMMODITIES = {
        "AU": {"name": "黄金", "unit": "元/克", "exchange": "上期所", "multiplier": 1000},
        "AG": {"name": "白银", "unit": "元/千克", "exchange": "上期所", "multiplier": 15},
        "CU": {"name": "铜", "unit": "元/吨", "exchange": "上期所", "multiplier": 5},
        "AL": {"name": "铝", "unit": "元/吨", "exchange": "上期所", "multiplier": 5},
        "ZN": {"name": "锌", "unit": "元/吨", "exchange": "上期所", "multiplier": 5},
        "RB": {"name": "螺纹钢", "unit": "元/吨", "exchange": "上期所", "multiplier": 10},
        "HC": {"name": "热卷", "unit": "元/吨", "exchange": "上期所", "multiplier": 10},
        "SC": {"name": "原油", "unit": "元/桶", "exchange": "能源中心", "multiplier": 1000},
        "M": {"name": "豆粕", "unit": "元/吨", "exchange": "大商所", "multiplier": 10},
        "Y": {"name": "豆油", "unit": "元/吨", "exchange": "大商所", "multiplier": 10},
        "I": {"name": "铁矿石", "unit": "元/吨", "exchange": "大商所", "multiplier": 100},
        "SR": {"name": "白糖", "unit": "元/吨", "exchange": "郑商所", "multiplier": 10},
        "CF": {"name": "棉花", "unit": "元/吨", "exchange": "郑商所", "multiplier": 5},
        "TA": {"name": "PTA", "unit": "元/吨", "exchange": "郑商所", "multiplier": 5},
        "MA": {"name": "甲醇", "unit": "元/吨", "exchange": "郑商所", "multiplier": 10},
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("market_analysis", config)

        # 数据缓存
        self._price_data: Dict[str, pd.DataFrame] = {}
        self._analysis_results: Dict[str, Dict[str, Any]] = {}
        self._max_cache_size = self.config.get("max_cache_size", 1000)

        # 初始化数据客户端
        data_source = self.config.get("data_source", "akshare")
        self._data_client = DataClient(source=data_source)
        self.set_data_client(self._data_client)

        # 注册飞书命令
        self._register_commands()

        # 注册消息处理器
        self.register_handler("market_data", self._on_market_data)
        self.register_handler("analysis_request", self._on_analysis_request)

    def _register_commands(self):
        """注册飞书命令"""
        self.register_command("行情", self._cmd_quote, "获取品种行情，如: 行情 AU")
        self.register_command("分析", self._cmd_analyze, "分析品种，如: 分析 AU")
        self.register_command("信号", self._cmd_signals, "查看交易信号，如: 信号")
        self.register_command("list", self._cmd_list, "列出支持的品种")

    # ==================== 数据获取 ====================

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情"""
        symbol = symbol.upper()
        quote = self._data_client.get_quote(symbol)

        if quote:
            # 添加品种信息
            commodity = self.COMMODITIES.get(symbol, {})
            quote["name"] = commodity.get("name", symbol)
            quote["unit"] = commodity.get("unit", "")
            quote["exchange"] = commodity.get("exchange", "")

        return quote

    async def analyze(self, symbol: str) -> Optional[Dict[str, Any]]:
        """执行分析"""
        symbol = symbol.upper()

        # 获取行情
        quote = await self.get_quote(symbol)
        if not quote:
            return None

        price = quote.get("price", 0)

        # 获取历史数据计算指标
        from datetime import timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)

        bars = self._data_client.get_bars(
            symbol,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )

        indicators = {}
        signals = []
        trend = {"direction": "neutral", "strength": 50, "risk_level": "medium"}

        if bars and len(bars) >= 60:
            df = pd.DataFrame(bars)
            df = df.sort_values("date")

            # 计算指标
            try:
                indicators = calculate_all_indicators(df)
                signals = generate_signals(indicators, price)
                trend = analyze_trend(indicators, price)
            except Exception as e:
                self.logger.error(f"计算指标失败: {e}")

        # 构建分析结果
        result = {
            "symbol": symbol,
            "name": quote.get("name", symbol),
            "unit": quote.get("unit", ""),
            "exchange": quote.get("exchange", ""),
            "timestamp": datetime.now().isoformat(),
            "price": {
                "current": price,
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "change_pct": quote.get("change_pct", 0),
            },
            "indicators": indicators,
            "signals": signals,
            "trend": trend,
            "recommendation": self._generate_recommendation(trend, signals),
        }

        # 保存结果
        self._analysis_results[symbol] = result

        return result

    def _generate_recommendation(self, trend: Dict, signals: List) -> str:
        """生成建议"""
        direction = trend.get("direction", "neutral")
        strength = trend.get("strength", 50)

        if "strong_bullish" in direction:
            return "强烈做多信号，可考虑在支撑位附近入场"
        elif "bullish" in direction:
            return "偏多信号，可轻仓尝试"
        elif "strong_bearish" in direction:
            return "强烈做空信号，可考虑在阻力位附近入场"
        elif "bearish" in direction:
            return "偏空信号，可轻仓尝试"
        else:
            return "震荡行情，建议观望"

    # ==================== 消息处理器 ====================

    async def _on_market_data(self, data: Dict):
        """处理市场数据消息"""
        symbol = data.get("symbol")
        if symbol:
            await self.analyze(symbol)

    async def _on_analysis_request(self, data: Dict):
        """处理分析请求消息"""
        symbol = data.get("symbol")
        requester = data.get("requester")

        if symbol:
            result = await self.analyze(symbol)
            if result and requester:
                await self.send_message(
                    "analysis_response",
                    {"symbol": symbol, "result": result},
                    target=requester
                )

    # ==================== 飞书命令处理器 ====================

    async def _cmd_quote(self, args: str, user_id: str, chat_id: str) -> str:
        """行情命令"""
        symbol = args.strip().upper() if args else "AU"

        quote = await self.get_quote(symbol)
        if not quote:
            return f"❌ 无法获取 {symbol} 的行情数据"

        lines = [
            f"## 📊 {quote.get('name', symbol)}({symbol}) 行情",
            "",
            f"**当前价格**: {quote.get('price')} {quote.get('unit')}",
        ]

        if quote.get('change_pct') is not None:
            change = quote.get('change_pct', 0)
            emoji = "📈" if change > 0 else "📉"
            lines.append(f"**涨跌幅**: {emoji} {change:+.2f}%")

        if quote.get('open'):
            lines.extend([
                f"**开盘**: {quote.get('open')}",
                f"**最高**: {quote.get('high')}",
                f"**最低**: {quote.get('low')}",
            ])

        lines.extend([
            "",
            f"*数据来源: {quote.get('source', 'unknown')}*",
        ])

        return "\n".join(lines)

    async def _cmd_analyze(self, args: str, user_id: str, chat_id: str) -> str:
        """分析命令"""
        symbol = args.strip().upper() if args else "AU"

        result = await self.analyze(symbol)
        if not result:
            return f"❌ 无法分析 {symbol}"

        lines = [
            f"## 📈 {result['name']}({symbol}) 技术分析",
            "",
            f"**当前价格**: {result['price']['current']} {result['unit']}",
            "",
            f"**趋势判断**: {self._format_trend(result['trend'])}"
        ]

        # 技术指标
        indicators = result.get('indicators', {})
        if indicators:
            lines.extend([
                "",
                "**技术指标**:",
                f"  RSI: {indicators.get('rsi', 0):.1f}",
                f"  MACD: {indicators.get('macd', 0):.3f}",
                f"  ATR: {indicators.get('atr', 0):.2f}",
            ])

        # 交易信号
        signals = result.get('signals', [])
        if signals:
            lines.extend(["", "**交易信号**:"])
            for sig in signals[:3]:
                emoji = "✅" if sig.get('direction') == 'long' else "⚠️"
                lines.append(f"  {emoji} {sig.get('description')} (强度: {sig.get('strength', 0):.0f})")

        lines.extend([
            "",
            f"**建议**: {result.get('recommendation', '观望')}",
        ])

        return "\n".join(lines)

    async def _cmd_signals(self, args: str, user_id: str, chat_id: str) -> str:
        """信号命令"""
        lines = ["## 📡 当前交易信号", ""]

        if not self._analysis_results:
            return "暂无分析结果，请先使用「分析 品种代码」获取数据"

        for symbol, result in list(self._analysis_results.items())[:5]:
            signals = result.get('signals', [])
            trend = result.get('trend', {})

            if signals:
                lines.append(f"**{result.get('name', symbol)}** ({symbol}):")
                for sig in signals[:2]:
                    emoji = "🟢" if sig.get('direction') == 'long' else "🔴"
                    lines.append(f"  {emoji} {sig.get('description')}")
                lines.append("")

        return "\n".join(lines) if len(lines) > 2 else "暂无交易信号"

    async def _cmd_list(self, args: str, user_id: str, chat_id: str) -> str:
        """列出品种"""
        lines = ["## 📋 支持的品种列表", ""]

        # 按交易所分组
        by_exchange = {}
        for code, info in self.COMMODITIES.items():
            exchange = info.get('exchange', '其他')
            if exchange not in by_exchange:
                by_exchange[exchange] = []
            by_exchange[exchange].append((code, info.get('name', code)))

        for exchange, items in by_exchange.items():
            lines.append(f"**{exchange}**:")
            for code, name in items:
                lines.append(f"  {code} - {name}")
            lines.append("")

        return "\n".join(lines)

    def _format_trend(self, trend: Dict) -> str:
        """格式化趋势"""
        direction = trend.get('direction', 'neutral')
        strength = trend.get('strength', 50)

        mapping = {
            'strong_bullish': '📈 强烈看多',
            'bullish': '↗️ 偏多',
            'neutral': '➡️ 中性',
            'bearish': '↘️ 偏空',
            'strong_bearish': '📉 强烈看空',
        }

        return f"{mapping.get(direction, direction)} (强度: {strength})"

    # ==================== Agent生命周期 ====================

    async def initialize(self):
        """初始化"""
        await super().initialize()
        self.logger.info("市场分析技能初始化完成")

    async def _handle_default(self, text: str, user_id: str, chat_id: str) -> str:
        """默认处理 - 尝试识别品种代码"""
        text = text.strip().upper()

        # 如果是品种代码，获取行情
        if text in self.COMMODITIES or len(text) <= 4:
            return await self._cmd_analyze(text, user_id, chat_id)

        return await super()._handle_default(text, user_id, chat_id)


# 兼容旧代码的导入
MarketAnalysisAgent = MarketSkill
