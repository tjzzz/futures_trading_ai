#!/usr/bin/env python3
"""
基本面分析技能
整合自:
- futures_trading_skills/fundamental-skill/scripts/fundamental.py
- futures_trading_system/agents/fundamental_agent.py
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import logging

from core import SkillAgent
from shared import DataClient


@dataclass
class FundamentalConfig:
    """基本面配置"""
    # 供需权重
    supply_demand_weight: float = 0.30
    # 库存权重
    inventory_weight: float = 0.25
    # 宏观权重
    macro_weight: float = 0.20
    # 基差权重
    basis_weight: float = 0.15
    # 季节性权重
    seasonal_weight: float = 0.10


@dataclass
class FundamentalData:
    """基本面数据"""
    symbol: str
    date: str

    # 供需数据
    supply_demand_score: float = 50  # 0-100
    supply_demand_notes: str = ""

    # 库存数据
    inventory_score: float = 50
    inventory_level: str = "normal"  # low, normal, high
    inventory_notes: str = ""

    # 宏观数据
    macro_score: float = 50
    macro_drivers: List[Dict] = field(default_factory=list)

    # 基差数据
    basis_score: float = 50
    spot_price: float = 0
    futures_price: float = 0
    basis: float = 0  # 基差 = 现货 - 期货

    # 季节性数据
    seasonal_score: float = 50
    seasonal_pattern: str = ""
    seasonal_notes: str = ""

    # 综合评分
    overall_score: float = 50
    bias: str = "neutral"  # bullish, neutral, bearish


class FundamentalSkill(SkillAgent):
    """
    基本面分析技能
    分析期货品种的基本面因素，给出多空偏向
    """

    # 品种基本面配置
    COMMODITY_CONFIGS = {
        "AU": {  # 黄金
            "name": "黄金",
            "category": "precious_metal",
            "factors": ["美元指数", "实际利率", "地缘政治", "央行购金", "通胀预期"],
            "inventory_sensitive": False,
            "macro_sensitive": True,
        },
        "AG": {  # 白银
            "name": "白银",
            "category": "precious_metal",
            "factors": ["黄金价格", "工业需求", "美元指数", "金银比"],
            "inventory_sensitive": False,
            "macro_sensitive": True,
        },
        "SC": {  # 原油
            "name": "原油",
            "category": "energy",
            "factors": ["OPEC产量", "美国库存", "全球需求", "地缘政治", "美元汇率"],
            "inventory_sensitive": True,
            "macro_sensitive": True,
        },
        "CU": {  # 铜
            "name": "铜",
            "category": "industrial_metal",
            "factors": ["全球库存", "中国需求", "美元汇率", "矿山供应", "新能源需求"],
            "inventory_sensitive": True,
            "macro_sensitive": True,
        },
        "RB": {  # 螺纹钢
            "name": "螺纹钢",
            "category": "steel",
            "factors": ["钢厂库存", "房地产需求", "基建投资", "铁矿石成本", "环保政策"],
            "inventory_sensitive": True,
            "macro_sensitive": False,
        },
        "I": {  # 铁矿石
            "name": "铁矿石",
            "category": "steel_raw",
            "factors": ["港口库存", "钢厂需求", "发运量", "汇率", "巴西澳洲天气"],
            "inventory_sensitive": True,
            "macro_sensitive": False,
        },
        "M": {  # 豆粕
            "name": "豆粕",
            "category": "agriculture",
            "factors": ["美豆产量", "进口大豆", "养殖需求", "库存", "美豆出口"],
            "inventory_sensitive": True,
            "macro_sensitive": False,
        },
        "SR": {  # 白糖
            "name": "白糖",
            "category": "agriculture",
            "factors": ["产量", "进口", "库存", "消费", "政策"],
            "inventory_sensitive": True,
            "macro_sensitive": False,
        },
        "CF": {  # 棉花
            "name": "棉花",
            "category": "agriculture",
            "factors": ["产量", "库存", "纺织需求", "进口", "储备"],
            "inventory_sensitive": True,
            "macro_sensitive": False,
        },
    }

    # 季节性规律
    SEASONAL_PATTERNS = {
        "AU": {  # 黄金
            1: "年初避险需求，偏强",
            2: "中国春节需求，偏多",
            3: "加息预期压制，偏空",
            8: "印度节庆需求，偏多",
            9: "央行购金季，偏多",
            12: "年末避险，偏强",
        },
        "SC": {  # 原油
            1: "冬季取暖需求，偏多",
            5: "夏季驾驶季，偏多",
            6: "飓风季开始，波动加大",
            9: "炼厂检修，需求转弱",
            10: "秋季检修，偏空",
        },
        "RB": {  # 螺纹钢
            3: "金三银四开工季，偏多",
            4: "旺季延续，偏多",
            7: "高温雨季，需求转弱",
            8: "淡季持续，偏空",
            9: "金九银十，需求回升",
            10: "旺季延续，偏多",
            12: "冬储博弈，观望",
        },
        "M": {  # 豆粕
            4: "南美上市压力，偏空",
            5: "到港增加，压力大",
            6: "美豆种植期，天气炒作",
            7: "美豆关键生长期",
            8: "美豆定产，单产确定",
            9: "南美种植开始",
        },
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("fundamental", config)

        self.fundamental_config = FundamentalConfig()
        self._analysis_cache: Dict[str, FundamentalData] = {}
        self._data_client = DataClient(source="akshare")

        # 注册命令
        self._register_commands()

    def _register_commands(self):
        """注册命令"""
        self.register_command("基本面", self._cmd_analysis, "分析品种基本面，如: 基本面 AU")
        self.register_command("宏观", self._cmd_macro, "查看宏观驱动因素")
        self.register_command("库存", self._cmd_inventory, "查看库存数据")
        self.register_command("基差", self._cmd_basis, "查看基差分析")
        self.register_command("季节性", self._cmd_seasonal, "查看季节性规律")

    async def analyze(self, symbol: str) -> Optional[FundamentalData]:
        """分析品种基本面"""
        symbol = symbol.upper()
        config = self.COMMODITY_CONFIGS.get(symbol)

        if not config:
            return self._create_default_analysis(symbol)

        now = datetime.now()

        # 计算各维度评分
        supply_demand = self._analyze_supply_demand(symbol, config)
        inventory = self._analyze_inventory(symbol, config)
        macro = self._analyze_macro(symbol, config)
        basis = self._analyze_basis(symbol)
        seasonal = self._analyze_seasonal(symbol, now.month)

        # 加权计算综合评分
        overall_score = (
            supply_demand["score"] * self.fundamental_config.supply_demand_weight +
            inventory["score"] * self.fundamental_config.inventory_weight +
            macro["score"] * self.fundamental_config.macro_weight +
            basis["score"] * self.fundamental_config.basis_weight +
            seasonal["score"] * self.fundamental_config.seasonal_weight
        )

        # 确定偏向
        if overall_score >= 60:
            bias = "bullish"
        elif overall_score <= 40:
            bias = "bearish"
        else:
            bias = "neutral"

        analysis = FundamentalData(
            symbol=symbol,
            date=now.strftime("%Y-%m-%d"),
            supply_demand_score=supply_demand["score"],
            supply_demand_notes=supply_demand["notes"],
            inventory_score=inventory["score"],
            inventory_level=inventory["level"],
            inventory_notes=inventory["notes"],
            macro_score=macro["score"],
            macro_drivers=macro["drivers"],
            basis_score=basis["score"],
            spot_price=basis["spot"],
            futures_price=basis["futures"],
            basis=basis["basis"],
            seasonal_score=seasonal["score"],
            seasonal_pattern=seasonal["pattern"],
            seasonal_notes=seasonal["notes"],
            overall_score=overall_score,
            bias=bias
        )

        self._analysis_cache[symbol] = analysis
        return analysis

    def _create_default_analysis(self, symbol: str) -> FundamentalData:
        """创建默认分析"""
        return FundamentalData(
            symbol=symbol,
            date=datetime.now().strftime("%Y-%m-%d"),
            overall_score=50,
            bias="neutral",
            supply_demand_notes="暂无该品种详细数据",
        )

    def _analyze_supply_demand(self, symbol: str, config: Dict) -> Dict:
        """分析供需"""
        # 这里应该从数据库或API获取真实数据
        # 现在使用模拟数据
        score = 50
        notes = "供需基本平衡"

        if symbol == "AU":
            score = 65
            notes = "央行购金需求旺盛，供应相对稳定"
        elif symbol == "SC":
            score = 55
            notes = "OPEC+减产支撑，需求担忧仍存"
        elif symbol == "CU":
            score = 60
            notes = "新能源需求强劲，矿山供应受限"
        elif symbol == "RB":
            score = 45
            notes = "房地产需求偏弱，库存去化缓慢"
        elif symbol == "M":
            score = 55
            notes = "南美大豆丰产，国内需求稳定"

        return {"score": score, "notes": notes}

    def _analyze_inventory(self, symbol: str, config: Dict) -> Dict:
        """分析库存"""
        score = 50
        level = "normal"
        notes = "库存处于正常水平"

        if config.get("inventory_sensitive"):
            # 库存敏感品种
            if symbol in ["CU", "RB", "I"]:
                score = 55
                level = "low"
                notes = "库存偏低，对价格有支撑"
            elif symbol in ["M"]:
                score = 45
                level = "high"
                notes = "库存较高，压制价格"

        return {"score": score, "level": level, "notes": notes}

    def _analyze_macro(self, symbol: str, config: Dict) -> Dict:
        """分析宏观因素"""
        score = 50
        drivers = []

        if config.get("macro_sensitive"):
            drivers = [
                {"factor": "美元指数", "impact": "利空", "description": "美元走强，压制大宗商品"},
                {"factor": "美联储政策", "impact": "中性", "description": "加息接近尾声"},
                {"factor": "中国经济", "impact": "利多", "description": "刺激政策陆续出台"},
            ]
            score = 55
        else:
            drivers = [
                {"factor": "国内政策", "impact": "中性", "description": "政策维持稳定"},
            ]

        return {"score": score, "drivers": drivers}

    def _analyze_basis(self, symbol: str) -> Dict:
        """分析基差"""
        # 获取行情数据计算基差
        quote = self._data_client.get_quote(symbol)
        futures_price = quote.get("price", 0) if quote else 0

        # 模拟现货价格（实际应从数据源获取）
        spot_price = futures_price * 1.02 if futures_price else 0
        basis = spot_price - futures_price

        # 基差判断
        if basis > futures_price * 0.01:  # 升水1%以上
            score = 60
        elif basis < -futures_price * 0.01:  # 贴水1%以上
            score = 40
        else:
            score = 50

        return {
            "score": score,
            "spot": round(spot_price, 2),
            "futures": round(futures_price, 2),
            "basis": round(basis, 2)
        }

    def _analyze_seasonal(self, symbol: str, month: int) -> Dict:
        """分析季节性"""
        patterns = self.SEASONAL_PATTERNS.get(symbol, {})
        pattern = patterns.get(month, "")

        if "多" in pattern or "强" in pattern:
            score = 60
        elif "空" in pattern or "弱" in pattern:
            score = 40
        else:
            score = 50

        return {
            "score": score,
            "pattern": pattern,
            "notes": pattern if pattern else "该月无明显季节性规律"
        }

    # ==================== 飞书命令 ====================

    async def _cmd_analysis(self, args: str, user_id: str, chat_id: str) -> str:
        """基本面分析命令"""
        symbol = args.strip().upper() if args else "AU"

        analysis = await self.analyze(symbol)
        if not analysis:
            return f"❌ 无法分析 {symbol}"

        config = self.COMMODITY_CONFIGS.get(symbol, {})
        name = config.get("name", symbol)

        bias_emoji = {
            "bullish": "📈",
            "neutral": "➡️",
            "bearish": "📉"
        }.get(analysis.bias, "➡️")

        lines = [
            f"## {bias_emoji} {name}({symbol}) 基本面分析",
            "",
            f"**综合评分**: {analysis.overall_score:.0f}/100",
            f"**多空偏向**: {self._format_bias(analysis.bias)}",
            "",
            "### 分项评分",
            f"  供需面: {analysis.supply_demand_score:.0f} - {analysis.supply_demand_notes}",
            f"  库存面: {analysis.inventory_score:.0f} - {analysis.inventory_notes}",
            f"  宏观面: {analysis.macro_score:.0f}",
            f"  基差: {analysis.basis_score:.0f} (基差: {analysis.basis:+.2f})",
            f"  季节性: {analysis.seasonal_score:.0f} - {analysis.seasonal_notes}",
        ]

        if analysis.macro_drivers:
            lines.extend(["", "### 宏观驱动因素"])
            for driver in analysis.macro_drivers[:3]:
                impact_emoji = "🟢" if driver.get("impact") == "利多" else "🔴" if driver.get("impact") == "利空" else "⚪"
                lines.append(f"  {impact_emoji} {driver['factor']}: {driver['description']}")

        return "\n".join(lines)

    async def _cmd_macro(self, args: str, user_id: str, chat_id: str) -> str:
        """宏观因素命令"""
        lines = [
            "## 🌍 宏观驱动因素概览",
            "",
            "**美元指数**: 近期走强，对大宗商品形成压力",
            "**美联储**: 加息周期接近尾声，关注降息预期",
            "**中国经济**: 稳增长政策陆续出台，需求端有望改善",
            "**地缘政治**: 中东局势紧张，能源供应风险溢价",
        ]
        return "\n".join(lines)

    async def _cmd_inventory(self, args: str, user_id: str, chat_id: str) -> str:
        """库存数据命令"""
        symbol = args.strip().upper() if args else ""

        if not symbol:
            return "请指定品种代码，如: 库存 AU"

        config = self.COMMODITY_CONFIGS.get(symbol)
        if not config:
            return f"暂无 {symbol} 的库存数据"

        return f"## 📦 {config['name']}({symbol}) 库存数据\n\n(数据接口开发中...)"

    async def _cmd_basis(self, args: str, user_id: str, chat_id: str) -> str:
        """基差分析命令"""
        symbol = args.strip().upper() if args else "AU"

        analysis = await self.analyze(symbol)
        if not analysis:
            return f"❌ 无法分析 {symbol}"

        lines = [
            f"## 📊 {symbol} 基差分析",
            "",
            f"**现货价格**: {analysis.spot_price}",
            f"**期货价格**: {analysis.futures_price}",
            f"**基差**: {analysis.basis:+.2f}",
            "",
            "**基差解读**:",
        ]

        if analysis.basis > 0:
            lines.append("基差为正，现货升水，通常反映现货供应紧张或需求旺盛")
        elif analysis.basis < 0:
            lines.append("基差为负，期货升水，通常反映供应充足或预期未来供应增加")
        else:
            lines.append("基差接近零，期现价格基本一致")

        return "\n".join(lines)

    async def _cmd_seasonal(self, args: str, user_id: str, chat_id: str) -> str:
        """季节性命令"""
        symbol = args.strip().upper() if args else "AU"

        patterns = self.SEASONAL_PATTERNS.get(symbol, {})
        config = self.COMMODITY_CONFIGS.get(symbol, {})
        name = config.get("name", symbol)

        lines = [f"## 📅 {name}({symbol}) 季节性规律", ""]

        if not patterns:
            lines.append("暂无该品种的季节性数据")
        else:
            for month, pattern in sorted(patterns.items()):
                lines.append(f"**{month}月**: {pattern}")

        lines.extend([
            "",
            "⚠️ 季节性规律仅供参考，实际走势受多种因素影响"
        ])

        return "\n".join(lines)

    def _format_bias(self, bias: str) -> str:
        """格式化偏向"""
        mapping = {
            "bullish": "偏多 📈",
            "neutral": "中性 ➡️",
            "bearish": "偏空 📉"
        }
        return mapping.get(bias, bias)

    # ==================== Agent生命周期 ====================

    async def initialize(self):
        """初始化"""
        await super().initialize()
        self.logger.info("基本面分析技能初始化完成")

    async def _handle_default(self, text: str, user_id: str, chat_id: str) -> str:
        """默认处理"""
        text = text.strip().upper()

        if text in self.COMMODITY_CONFIGS or len(text) <= 4:
            return await self._cmd_analysis(text, user_id, chat_id)

        return await super()._handle_default(text, user_id, chat_id)


# 兼容旧代码
FundamentalAgent = FundamentalSkill
