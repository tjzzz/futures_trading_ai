"""
四象限宏观规则分析 — rules 模式

根据采集器数据，对黄金/白银市场进行四象限规则判断。
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


# ─── 输出结构 ──────────────────────────────────────────────

@dataclass
class QuadrantResult:
    """单个象限分析结果"""
    name: str           # 象限名称
    emoji: str          # 图标
    signal: str         # 信号: bullish | bearish | neutral | mixed
    confidence: str     # 置信度: high | medium | low
    explanation: str    # 简短说明
    indicators: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MacroAnalysis:
    """宏观分析完整结果"""
    timestamp: str
    overall_signal: str                 # 综合信号
    overall_confidence: str             # 综合置信度
    summary: str                        # 一句话总结
    quadrants: List[QuadrantResult]     # 四个象限
    key_levels: Dict[str, float] = field(default_factory=dict)  # 关键价位
    scenario_label: str = ""            # 场景标签


# ─── 阈值常量 ──────────────────────────────────────────────

THRESHOLDS = {
    # 🟢 货币锚
    "treasury_10y_high": 4.5,       # 10Y > 4.5% → 利率压力
    "treasury_10y_low": 3.5,        # 10Y < 3.5% → 宽松
    "treasury_30y_high": 4.8,       # 30Y > 4.8% → 长端压力
    "dxy_strong": 105,              # DXY > 105 → 美元强势
    "dxy_weak": 100,                # DXY < 100 → 美元弱势

    # 🔵 宏观流动性
    "spread_inversion": -0.2,       # 2Y-10Y < -0.2% → 深度倒挂
    "spread_steep": 0.5,            # 2Y-10Y > 0.5% → 陡峭（衰退预期）

    # 🟠 风险偏好
    "vix_low": 15,                  # VIX < 15 → 市场平静
    "vix_high": 25,                 # VIX > 25 → 恐慌
    "vix_crisis": 35,               # VIX > 35 → 危机级别

    # 🔴 供需博弈
    "gs_ratio_high": 80,            # 金银比 > 80 → 白银低估
    "gs_ratio_low": 65,             # 金银比 < 65 → 白银高估
}


class MacroRulesAnalyzer:
    """
    四象限宏观规则分析器
    从 data/ 目录读取采集器数据，按规则引擎模式判断信号
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)

    # ─── 公共入口 ──────────────────────────────────────────

    def analyze(self) -> MacroAnalysis:
        """
        执行完整的四象限宏观分析
        返回结构化分析结果
        """
        # 1. 读取数据快照
        snapshot = self._read_snapshot()

        # 2. 读取新闻
        news = self._read_news()

        # 3. 逐象限分析
        quadrants = [
            self._analyze_currency_anchor(snapshot),
            self._analyze_macro_liquidity(snapshot),
            self._analyze_risk_appetite(snapshot, news),
            self._analyze_supply_demand(snapshot),
        ]

        # 4. 综合判断
        overall_signal, overall_confidence, summary = self._synthesize(quadrants)
        scenario_label = self._determine_scenario(quadrants, snapshot)
        key_levels = self._extract_key_levels(snapshot)

        return MacroAnalysis(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            overall_signal=overall_signal,
            overall_confidence=overall_confidence,
            summary=summary,
            quadrants=quadrants,
            key_levels=key_levels,
            scenario_label=scenario_label,
        )

    @staticmethod
    def _parse_csv_date(s: str) -> Optional[datetime]:
        """兼容 YYYY-MM-DD 和 MM/DD/YYYY"""
        s = s[:10].strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _get_csv_value(row: dict) -> Optional[float]:
        """从 CSV 行中提取数值，兼容 value / close 等列名"""
        for k in ("value", "close", "gold_usd", "silver_usd", "ratio", "ratio_close"):
            if k in row and row[k]:
                try:
                    return float(row[k])
                except (ValueError, TypeError):
                    continue
        # fallback: first numeric column
        for k, v in row.items():
            if k in ("date", "timestamp"):
                continue
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
        return None

    def query_indicator(self, indicator: str, start: str, end: str) -> Dict[str, Any]:
        """
        指定指标在日期区间的走势归因
        """
        # 从 history CSV 读取数据
        csv_path = self.data_dir / "history" / "daily" / f"{indicator}.csv"
        if not csv_path.exists():
            return {"error": f"未找到指标 {indicator} 的历史数据", "indicator": indicator}

        # 简化实现：读取 CSV 并返回基本信息
        try:
            import csv
            rows = []
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_date = row.get("date", "")
                    # 兼容两种日期格式做字符串比较之前先统一格式
                    d = self._parse_csv_date(row_date)
                    if d:
                        date_normalized = d.strftime("%Y-%m-%d")
                        if start <= date_normalized <= end:
                            rows.append(row)

            if not rows:
                return {
                    "indicator": indicator,
                    "period": f"{start} ~ {end}",
                    "data_points": 0,
                    "note": "该区间无数据",
                }

            values = [self._get_csv_value(r) for r in rows]
            values = [v for v in values if v is not None]
            return {
                "indicator": indicator,
                "period": f"{start} ~ {end}",
                "data_points": len(rows),
                "start_value": values[0] if values else None,
                "end_value": values[-1] if values else None,
                "change": round(values[-1] - values[0], 2) if len(values) >= 2 else None,
                "high": max(values) if values else None,
                "low": min(values) if values else None,
            }
        except Exception as e:
            logger.warning(f"读取 {csv_path} 失败: {e}")
            return {"error": str(e), "indicator": indicator}

    def get_trend(self, indicator: str, days: int = 90) -> List[Dict[str, Any]]:
        """
        返回趋势数据
        """
        csv_path = self.data_dir / "history" / "daily" / f"{indicator}.csv"
        if not csv_path.exists():
            return []

        try:
            import csv
            cutoff = datetime.now() - timedelta(days=days)
            results = []
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_date = row.get("date", "")
                    if row_date:
                        d = self._parse_csv_date(row_date)
                        if d and d >= cutoff:
                            val = self._get_csv_value(row)
                            results.append({
                                "date": d.strftime("%Y-%m-%d"),
                                "value": val,
                            })
            return results[-100:]  # 最多返回 100 个点
        except Exception as e:
            logger.warning(f"读取趋势数据失败: {e}")
            return []

    # ─── 数据读取 ──────────────────────────────────────────

    def _read_snapshot(self) -> Dict[str, Any]:
        """读取当前数据快照"""
        path = self.data_dir / "current" / "dashboard_data.json"
        if not path.exists():
            logger.warning(f"数据快照不存在: {path}")
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取数据快照失败: {e}")
            return {}

    def _read_news(self) -> List[Dict[str, Any]]:
        """读取最近新闻"""
        path = self.data_dir / "events" / "latest_feed.json"
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return data.get("events", [])
        except Exception as e:
            logger.warning(f"读取新闻失败: {e}")
            return []

    def _safe_float(self, data: Dict, *keys, default: Optional[float] = None) -> Optional[float]:
        """安全地从嵌套字典读取 float

        支持级联键（如 treasury,10yr → data['treasury']['10yr']）
        以及自动解包 {"value": X} 结构。
        """
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        # 自动解包 {"value": X}
        if isinstance(current, dict) and "value" in current:
            current = current["value"]
        try:
            return float(current)
        except (TypeError, ValueError):
            return default

    # ─── 四象限分析 ────────────────────────────────────────

    def _analyze_currency_anchor(self, data: Dict) -> QuadrantResult:
        """
        🟢 货币锚 — 实际利率与美元信用
        """
        treasury_10y = self._safe_float(data, "treasury", "10yr")
        treasury_30y = self._safe_float(data, "treasury", "30yr")
        dxy = self._safe_float(data, "dxy")
        tips_10y = self._safe_float(data, "tips_10y")

        signals = []
        bullish_count = 0
        bearish_count = 0

        # 10Y 国债收益率判断
        treasury_note = ""
        if treasury_10y is not None:
            if treasury_10y > THRESHOLDS["treasury_10y_high"]:
                signals.append("10Y 国债收益率偏高 (>4.5%)，利率压力大")
                bearish_count += 1
                treasury_note = f"{treasury_10y}% (偏高)"
            elif treasury_10y < THRESHOLDS["treasury_10y_low"]:
                signals.append("10Y 国债收益率较低 (<3.5%)，货币环境宽松")
                bullish_count += 1
                treasury_note = f"{treasury_10y}% (偏低)"
            else:
                signals.append(f"10Y 国债 {treasury_10y}%，中性")
                treasury_note = f"{treasury_10y}% (中性)"

        # DXY 美元指数
        dxy_note = ""
        if dxy is not None:
            if dxy > THRESHOLDS["dxy_strong"]:
                signals.append(f"DXY {dxy}，美元强势压制黄金")
                bearish_count += 1
                dxy_note = f"{dxy} (强势)"
            elif dxy < THRESHOLDS["dxy_weak"]:
                signals.append(f"DXY {dxy}，美元弱势支撑黄金")
                bullish_count += 1
                dxy_note = f"{dxy} (弱势)"
            else:
                dxy_note = f"{dxy} (中性)"

        # 综合判断
        if bullish_count > bearish_count:
            signal = "bullish"
            confidence = "medium"
            explanation = "货币环境宽松，美元偏弱，利多黄金"
        elif bearish_count > bullish_count:
            signal = "bearish"
            confidence = "medium"
            explanation = "利率偏高或美元走强，压制金价"
        else:
            signal = "neutral"
            confidence = "low"
            explanation = "货币锚信号中性，无明显偏向"

        return QuadrantResult(
            name="货币锚",
            emoji="🟢",
            signal=signal,
            confidence=confidence,
            explanation=explanation,
            indicators={
                "10Y Treasury": treasury_note or (f"{treasury_10y}%" if treasury_10y else "无数据"),
                "30Y Treasury": f"{treasury_30y}%" if treasury_30y else "无数据",
                "TIPS 实际利率": f"{tips_10y}%" if tips_10y else "无数据",
                "DXY": dxy_note or (f"{dxy}" if dxy else "无数据"),
            }
        )

    def _analyze_macro_liquidity(self, data: Dict) -> QuadrantResult:
        """
        🔵 宏观流动性 — 收益率曲线形态
        """
        treasury_2y = self._safe_float(data, "treasury", "2yr")
        treasury_10y = self._safe_float(data, "treasury", "10yr")

        if treasury_2y is not None and treasury_10y is not None:
            spread = treasury_10y - treasury_2y
            spread_str = f"{spread:+.2f}%"

            if spread < THRESHOLDS["spread_inversion"]:
                signal = "bullish"  # 深度倒挂 → 衰退预期 → 避险利多黄金
                confidence = "high"
                explanation = f"收益率曲线深度倒挂 ({spread_str})，衰退预期强，避险逻辑利多黄金"
            elif spread < 0:
                signal = "mixed"
                confidence = "medium"
                explanation = f"收益率曲线轻微倒挂 ({spread_str})，过渡信号"
            elif spread > THRESHOLDS["spread_steep"]:
                signal = "bullish"
                confidence = "medium"
                explanation = f"收益率曲线陡峭化 ({spread_str})，宽松预期支撑贵金属"
            else:
                signal = "neutral"
                confidence = "low"
                explanation = f"收益率曲线正常 ({spread_str})，流动性中性"

            return QuadrantResult(
                name="宏观流动性",
                emoji="🔵",
                signal=signal,
                confidence=confidence,
                explanation=explanation,
                indicators={
                    "2Y Treasury": f"{treasury_2y}%",
                    "10Y Treasury": f"{treasury_10y}%",
                    "2-10 Spread": spread_str,
                }
            )

        return QuadrantResult(
            name="宏观流动性",
            emoji="🔵",
            signal="neutral",
            confidence="low",
            explanation="缺少曲线数据，无法判断",
            indicators={"treasury_2y": "无数据", "treasury_10y": "无数据"}
        )

    def _analyze_risk_appetite(self, data: Dict, news: List[Dict]) -> QuadrantResult:
        """
        🟠 风险偏好 — VIX + 地缘政治
        """
        vix = self._safe_float(data, "vix")
        sp500 = self._safe_float(data, "sp500")

        signals = []
        signal = "neutral"
        confidence = "low"

        # VIX 恐慌指数
        vix_note = ""
        if vix is not None:
            if vix > THRESHOLDS["vix_crisis"]:
                vix_note = f"{vix} (危机级别)"
                signals.append(f"恐慌指数极高 ({vix})，强烈避险")
                signal = "bullish"
                confidence = "high"
            elif vix > THRESHOLDS["vix_high"]:
                vix_note = f"{vix} (恐慌)"
                signals.append(f"恐慌指数偏高 ({vix})，避险情绪升温")
                if signal == "neutral":
                    signal = "bullish"
                    confidence = "medium"
            elif vix < THRESHOLDS["vix_low"]:
                vix_note = f"{vix} (平静)"
                signals.append(f"恐慌指数极低 ({vix})，风险偏好高")
                if signal == "neutral":
                    signal = "neutral"
                    confidence = "low"
            else:
                vix_note = f"{vix} (正常)"
        else:
            vix_note = "无数据"

        # 地缘政治（从新闻中检测关键词）
        geo_risk_keywords = ["战争", "冲突", "制裁", "加息", "降息",
                             "war", "conflict", "sanction", "rate hike",
                             "geopolitical", "invasion", "tariff"]
        urgent_news = []
        for article in news[:20]:
            title = article.get("title", "") + " " + article.get("summary", "")
            for kw in geo_risk_keywords:
                if kw.lower() in title.lower():
                    urgent_news.append(article.get("title", ""))
                    break

        if urgent_news:
            signals.append(f"检测到 {len(urgent_news)} 条地缘/政策相关新闻")
            if confidence != "high":
                confidence = "medium"

        explanation = " | ".join(signals) if signals else "风险偏好中性，无显著恐慌信号"

        return QuadrantResult(
            name="风险偏好",
            emoji="🟠",
            signal=signal,
            confidence=confidence,
            explanation=explanation,
            indicators={
                "VIX": vix_note,
                "S&P 500": f"{sp500}" if sp500 else "无数据",
                "地缘新闻": str(len(urgent_news)) + " 条",
            }
        )

    def _analyze_supply_demand(self, data: Dict) -> QuadrantResult:
        """
        🔴 供需博弈 — 金银比
        """
        gold_price = self._safe_float(data, "gold_price")
        silver_price = self._safe_float(data, "silver_price")
        gs_ratio = self._safe_float(data, "gold_silver_ratio")

        # 计算金银比
        if gs_ratio is None and gold_price and silver_price and silver_price > 0:
            gs_ratio = gold_price / silver_price

        if gs_ratio is not None:
            if gs_ratio > THRESHOLDS["gs_ratio_high"]:
                signal = "bullish_silver"
                confidence = "high"
                explanation = f"金银比 {gs_ratio:.1f} > 80，白银严重低估，均值回归预期强"
            elif gs_ratio > THRESHOLDS["gs_ratio_low"]:
                signal = "neutral"
                confidence = "low"
                explanation = f"金银比 {gs_ratio:.1f}，在正常区间"
            else:
                signal = "bearish_silver"
                confidence = "medium"
                explanation = f"金银比 {gs_ratio:.1f} < 65，白银相对高估"
        else:
            signal = "neutral"
            confidence = "low"
            explanation = "缺少金银比数据"

        return QuadrantResult(
            name="供需博弈",
            emoji="🔴",
            signal=signal,
            confidence=confidence,
            explanation=explanation,
            indicators={
                "XAU/USD": f"${gold_price:.2f}" if gold_price else "无数据",
                "XAG/USD": f"${silver_price:.2f}" if silver_price else "无数据",
                "金银比": f"{gs_ratio:.1f}" if gs_ratio else "无数据",
            }
        )

    # ─── 综合 ──────────────────────────────────────────────

    def _synthesize(self, quadrants: List[QuadrantResult]) -> Tuple[str, str, str]:
        """
        综合四个象限信号
        返回 (overall_signal, overall_confidence, summary)
        """
        # 信号量化
        signal_map = {
            "bullish": 1, "bullish_silver": 1,
            "neutral": 0, "mixed": 0,
            "bearish": -1, "bearish_silver": -1,
        }
        confidence_weight = {"high": 3, "medium": 2, "low": 1}

        total_score = 0
        total_weight = 0

        for q in quadrants:
            s = signal_map.get(q.signal, 0)
            w = confidence_weight.get(q.confidence, 0)
            total_score += s * w
            total_weight += w

        if total_weight == 0:
            return "neutral", "low", "数据不足，无法综合判断"

        avg_score = total_score / total_weight

        if avg_score > 0.3:
            overall_signal = "bullish"
            confidence = "high" if avg_score > 0.6 else "medium"
            summary = "四象限综合看多黄金"
        elif avg_score < -0.3:
            overall_signal = "bearish"
            confidence = "high" if avg_score < -0.6 else "medium"
            summary = "四象限综合看空黄金"
        else:
            overall_signal = "neutral"
            confidence = "low"
            summary = "四象限信号分化或中性，等待方向确认"

        return overall_signal, confidence, summary

    def _determine_scenario(self, quadrants: List[QuadrantResult], data: Dict) -> str:
        """
        识别当前市场场景标签
        """
        bullish_count = sum(1 for q in quadrants if q.signal in ("bullish", "bullish_silver"))
        bearish_count = sum(1 for q in quadrants if q.signal in ("bearish", "bearish_silver"))

        # 检查关键指标
        vix = self._safe_float(data, "vix")
        treasury_10y = self._safe_float(data, "treasury", "10yr")
        dxy = self._safe_float(data, "dxy")

        if vix and vix > 25:
            return "🛡️ 避险模式 — 市场恐慌，避险资金流入"
        if treasury_10y and treasury_10y > 4.5:
            return "💰 利率压力 — 收益率高企，黄金承压"
        if dxy and dxy > 105:
            return "💵 美元强势 — 美元走强压制贵金属"
        if bullish_count >= 3:
            return "📈 全面看多 — 多象限共振看多"
        if bearish_count >= 3:
            return "📉 全面看空 — 多象限共振看空"
        if bullish_count >= 2 and bearish_count >= 1:
            return "⚡ 多空博弈 — 信号分化，观望为宜"

        return "⏳ 等待信号 — 无明显偏向"

    def _extract_key_levels(self, data: Dict) -> Dict[str, float]:
        """
        提取关键价位
        """
        levels = {}
        gold_price = self._safe_float(data, "gold_price")
        silver_price = self._safe_float(data, "silver_price")

        if gold_price:
            # 简单关键位：±2%
            levels["gold_current"] = round(gold_price, 2)
            levels["gold_support"] = round(gold_price * 0.98, 2)
            levels["gold_resistance"] = round(gold_price * 1.02, 2)

        if silver_price:
            levels["silver_current"] = round(silver_price, 2)

        return levels
