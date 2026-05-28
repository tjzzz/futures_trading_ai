"""
分析引擎统一入口 — 期货交易系统 V2

根据 ANALYSIS_MODE 配置分发到规则引擎或 LLM 模式。
纯函数模块，不持有飞书连接，不做 send_message。
"""

import logging
from typing import Dict, Any, List

import config
from config import DATA_DIR
from .rules import MacroRulesAnalyzer
from .llm import MacroLLMAnalyzer
from .prediction.engine import PredictionEngine


logger = logging.getLogger(__name__)


class Analysis:
    """
    统一分析入口

    接口：
        analyze()             → 四象限综合分析
        query_indicator()     → 指标区间归因
        get_trend()           → 趋势数据
        handle_command()      → 飞书命令入口
    """

    def __init__(self):
        self.data_dir = str(DATA_DIR)
        self._rules_analyzer = MacroRulesAnalyzer(data_dir=self.data_dir)
        self._llm_analyzer = MacroLLMAnalyzer(data_dir=self.data_dir)
        self._predictor = PredictionEngine(data_dir=self.data_dir)
        logger.info(f"Analysis 引擎初始化完成，模式: {config.ANALYSIS_MODE}")
        if config.ANALYSIS_MODE == "llm":
            logger.info(f"  LLM 分析器: {'已配置' if self._llm_analyzer._configured else '未配置 API Key'}")


    def analyze(self) -> Dict[str, Any]:
        """
        四象限综合分析
        返回结构化分析结果
        """
        if config.ANALYSIS_MODE == "llm":
            return self._analyze_llm()
        return self._analyze_rules()

    def _analyze_rules(self) -> Dict[str, Any]:
        """规则引擎模式分析"""
        result = self._rules_analyzer.analyze()

        # 格式化为 dict（用于 JSON 序列化）
        return {
            "mode": "rules",
            "timestamp": result.timestamp,
            "overall_signal": result.overall_signal,
            "overall_confidence": result.overall_confidence,
            "summary": result.summary,
            "scenario_label": result.scenario_label,
            "quadrants": [
                {
                    "name": q.name,
                    "emoji": q.emoji,
                    "signal": q.signal,
                    "confidence": q.confidence,
                    "explanation": q.explanation,
                    "indicators": q.indicators,
                }
                for q in result.quadrants
            ],
            "key_levels": result.key_levels,
        }

    def _analyze_llm(self) -> Dict[str, Any]:
        """LLM 模式分析 — 调用 LLM API 进行综合分析"""
        logger.info("LLM 模式分析 — 调用 LLM 分析器")
        return self._llm_analyzer.analyze()

    def query_indicator(self, indicator: str, start: str, end: str, grain: str = "daily") -> Dict[str, Any]:
        """
        指定指标在日期区间的走势归因
        
        支持两种模式：
        1. 归因模式：对于gold/silver等品种，使用新的归因模块
        2. 传统模式：对于其他指标，使用原有的CSV查询
        """
        # 检查是否为归因支持的品种
        attribution_targets = ["gold", "silver", "金银比", "XAU", "XAG"]
        
        if indicator.lower() in [t.lower() for t in attribution_targets]:
            try:
                # 导入归因模块（延迟导入，避免循环依赖）
                from .attribution.engine import run_attribution
                
                # 映射指标到归因目标
                target_map = {
                    "gold": "gold",
                    "silver": "silver",
                    "金银比": "gold",  # 金银比暂时用黄金归因
                    "XAU": "gold",
                    "XAG": "silver"
                }
                
                target = target_map.get(indicator.lower(), indicator.lower())
                
                # 运行归因分析
                attribution_result = run_attribution(
                    target=target,
                    start=start,
                    end=end,
                    grain=grain
                )
                
                # 转换为兼容格式
                return self._format_attribution_result(attribution_result, indicator, start, end)
                
            except ImportError as e:
                logger.warning(f"归因模块导入失败，回退到传统模式: {e}")
                return self._rules_analyzer.query_indicator(indicator, start, end)
            except Exception as e:
                logger.error(f"归因分析失败: {e}")
                # 失败时回退到传统模式
                return self._rules_analyzer.query_indicator(indicator, start, end)
        else:
            # 传统指标，使用原有逻辑
            return self._rules_analyzer.query_indicator(indicator, start, end)
    
    def _format_attribution_result(self, attribution_result: Dict[str, Any], 
                                  indicator: str, start: str, end: str) -> Dict[str, Any]:
        """
        将归因结果格式化为兼容的查询结果格式
        
        Args:
            attribution_result: 归因模块的完整结果
            indicator: 原始指标名称
            start: 开始日期
            end: 结束日期
            
        Returns:
            兼容的查询结果
        """
        l1_result = attribution_result.get("l1_statistical")
        if not l1_result:
            return {
                "indicator": indicator,
                "period": f"{start} ~ {end}",
                "data_points": 0,
                "error": "归因模块未返回有效结果"
            }
        
        price_change = l1_result.get("price_change", {})
        driver_ranking = l1_result.get("driver_ranking", [])
        
        # 构建兼容结果
        result = {
            "indicator": indicator,
            "period": f"{start} ~ {end}",
            "data_points": len(l1_result.get("price_series", [])),
            "start_value": price_change.get("from"),
            "end_value": price_change.get("to"),
            "change": price_change.get("absolute"),
            "high": None,  # 需要从价格序列计算
            "low": None,   # 需要从价格序列计算
            "mode": "attribution_v2",  # 标记为归因模式
            "price_change_pct": price_change.get("pct"),
            "driver_count": len(driver_ranking),
            "dominant_driver": driver_ranking[0] if driver_ranking else None,
            "attribution_summary": self._generate_attribution_summary(l1_result)
        }
        
        # 计算最高/最低价
        price_series = l1_result.get("price_series", [])
        if price_series:
            values = [item["value"] for item in price_series]
            result["high"] = max(values) if values else None
            result["low"] = min(values) if values else None
        
        return result
    
    def _generate_attribution_summary(self, l1_result: Dict[str, Any]) -> str:
        """生成归因摘要"""
        price_change = l1_result.get("price_change", {})
        driver_ranking = l1_result.get("driver_ranking", [])
        
        if not driver_ranking:
            return "无有效归因结果"
        
        price_from = price_change.get("from", 0)
        price_to = price_change.get("to", 0)
        price_pct = price_change.get("pct", 0)
        
        direction = "上涨" if price_pct > 0 else "下跌"
        summary = f"价格从 {price_from} {direction}至 {price_to} ({abs(price_pct):.1f}%)。"
        
        if driver_ranking:
            top_driver = driver_ranking[0]
            summary += f" 主要驱动: {top_driver.get('name', '未知')} (贡献 {top_driver.get('contribution_pct', 0):.1f}%)。"
        
        return summary

    def get_trend(self, indicator: str, days: int = 90) -> List[Dict[str, Any]]:
        """
        返回趋势数据
        """
        return self._rules_analyzer.get_trend(indicator, days)

    # ─── 预测模块 ──────────────────────────────────────────

    def predict(self, symbol: str = "gold", horizon: str = "all"):
        """
        价格预测

        参数:
            symbol: gold / silver
            horizon: short / mid / long / all（融合）
        """
        return self._predictor.predict(symbol=symbol, horizon=horizon)

    def _format_prediction_report(self) -> str:
        """格式化为飞书友好的预测报告"""
        result = self._predictor.predict(symbol="gold", horizon="all")

        if "error" in result:
            return f"❌ 预测失败: {result['error']}"

        from datetime import datetime

        lines = [
            f"## 🔮 黄金多周期预测",
            f"",
            f"**综合方向**: {result.get('direction_label', 'N/A')} (置信度: {result.get('confidence', 0):.0%})",
            f"**综合评分**: {result.get('final_score', 0):+.2f}",
            f"**时间**: {result.get('timestamp', datetime.now().isoformat())}",
            f"",
        ]

        for model in result.get("models", []):
            name = model["label"]
            direction = model.get("direction_label", "")
            conf = model.get("confidence", 0)
            signals = model.get("signals", [])
            weight = model.get("weight", 0)
            error = model.get("error")

            icon = {"看多": "📈", "略偏多": "↗️", "震荡": "➖", "略偏空": "↘️", "看空": "📉"}.get(direction, "➖")
            lines.append(f"### {name} {icon}")
            lines.append(f"**方向**: {direction} | **置信度**: {conf:.0%} | **权重**: {weight:.0%}")
            if signals:
                for s in signals[:3]:
                    lines.append(f"  • {s}")
            if error:
                lines.append(f"  ⚠️ {error}")
            lines.append("")

        scenarios = result.get("scenarios", [])
        if not scenarios:
            try:
                long_r = self._predictor.predict_long()
                scenarios = long_r.get("scenarios", [])
            except Exception:
                pass

        if scenarios:
            lines.append("### 📊 长期情景分析")
            for s in scenarios:
                lines.append(f"• **{s['name']}** ({s.get('probability', 0):.0%}): "
                           f"目标 {s.get('target_price', 'N/A')} "
                           f"[{s.get('range', ['', ''])[0]} ~ {s.get('range', ['', ''])[1]}]")
            lines.append("")

        return "\n".join(lines)

    # ─── 飞书命令处理 ──────────────────────────────────────

    def handle_command(self, text: str) -> str:
        """
        处理飞书命令文本，返回格式化回复

        V2 命令格式：
            宏观                   → 四象限综合判断
            归因 <指标> <开始> <结束> → 指标区间归因报告
            趋势 <指标> <天数>        → 趋势分析
            预测 [短/中/长/融合]     → 价格预测
        """
        text = text.strip()

        if text.startswith("预测"):
            return self._format_prediction_report()

        if text.startswith("宏观"):
            return self._format_macro_report()

        if text.startswith("归因"):
            return self._format_attribution(text)

        if text.startswith("趋势"):
            return self._format_trend(text)

        return "无法识别的 V2 命令。支持: 宏观、归因、趋势"

    def _format_macro_report(self) -> str:
        """格式化为飞书友好的宏观报告"""
        result = self.analyze()
        mode_label = "📐 规则分析" if result["mode"] == "rules" else "🧠 AI 分析"

        lines = [
            f"## 📊 四象限宏观分析",
            f"",
            f"**{result['scenario_label']}**",
            f"**综合信号**: {result['overall_signal'].upper()} (置信度: {result['overall_confidence']})",
            f"**总结**: {result['summary']}",
            f"**模式**: {mode_label}",
            f"**时间**: {result['timestamp']}",
            f"",
        ]

        # 各象限
        for q in result["quadrants"]:
            signal_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➖",
                           "mixed": "🔄", "bullish_silver": "🥈"}.get(q["signal"], "➖")
            lines.append(f"### {q['emoji']} {q['name']} {signal_icon}")
            lines.append(f"{q['explanation']}")
            for k, v in q["indicators"].items():
                lines.append(f"  • {k}: {v}")
            lines.append("")

        # 关键价位
        if result.get("key_levels"):
            lines.append("### 🎯 关键价位")
            for k, v in result["key_levels"].items():
                lines.append(f"  • {k}: {v}")
            lines.append("")

        return "\n".join(lines)

    def _format_attribution(self, text: str) -> str:
        """格式化为归因报告"""
        # 解析: "归因 10Y 2026-04-01 2026-05-19"
        parts = text.split()
        if len(parts) < 4:
            return (
                "格式: `归因 <指标> <开始日期> <结束日期>`\n"
                "示例: `归因 10Y 2026-04-01 2026-05-19`"
            )

        indicator = parts[1]
        start = parts[2]
        end = parts[3]

        result = self.query_indicator(indicator, start, end)

        if "error" in result:
            return f"❌ 查询失败: {result['error']}"

        lines = [
            f"## 📈 指标归因: {indicator}",
            f"**区间**: {result.get('period', f'{start} ~ {end}')}",
            f"**数据点**: {result.get('data_points', 0)} 个",
            f"",
        ]

        # 检查是否为归因模式
        if result.get("mode") == "attribution_v2":
            # 归因模式：显示详细归因结果
            lines.append(f"**分析模式**: 🆕 归因分析 V2")
            lines.append(f"**价格变动**: {result.get('price_change_pct', 0):+.2f}%")
            
            if result.get("attribution_summary"):
                lines.append(f"**归因摘要**: {result['attribution_summary']}")
            
            dominant_driver = result.get("dominant_driver")
            if dominant_driver:
                lines.append(f"**主导因子**: {dominant_driver.get('name', '未知')}")
                lines.append(f"**贡献度**: {dominant_driver.get('contribution_pct', 0):.1f}%")
                lines.append(f"**相关性**: r = {dominant_driver.get('r', 0):.2f}")
            
            lines.append(f"**分析因子**: {result.get('driver_count', 0)} 个")
            
            # 添加详细驱动因子（最多显示3个）
            if "driver_ranking" in result:
                lines.append(f"\n**驱动因子排名**:")
                drivers = result.get("driver_ranking", [])[:3]
                for i, driver in enumerate(drivers):
                    icon = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
                    lines.append(f"{icon} **{driver.get('name', '未知')}**: "
                               f"贡献 {driver.get('contribution_pct', 0):.1f}%, "
                               f"r={driver.get('r', 0):.2f}, "
                               f"Δ={driver.get('delta', 0):.2f}")
        else:
            # 传统模式：显示基本统计
            if result.get("start_value") is not None:
                change = result.get("change")
                change_str = f"{change:+.2f}" if change is not None else "N/A"
                direction = "📈 上涨" if change and change > 0 else "📉 下跌" if change and change < 0 else "➖ 持平"
                lines.extend([
                    f"**起始值**: {result['start_value']}",
                    f"**结束值**: {result['end_value']}",
                    f"**变动**: {change_str} {direction}",
                    f"",
                    f"**区间内最高**: {result.get('high')}",
                    f"**区间内最低**: {result.get('low')}",
                ])

        return "\n".join(lines)

    def _format_trend(self, text: str) -> str:
        """格式化为趋势分析"""
        # 解析: "趋势 金银比 90"
        parts = text.split()
        if len(parts) < 2:
            return "格式: `趋势 <指标> [天数]`\n示例: `趋势 金银比 90`"

        indicator = parts[1]
        days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 90

        data = self.get_trend(indicator, days)

        if not data:
            return f"未找到指标 **{indicator}** 的趋势数据"

        values = [d["value"] for d in data if "value" in d]
        if not values:
            return f"指标 **{indicator}** 趋势数据为空"

        lines = [
            f"## 📉 趋势分析: {indicator}",
            f"**周期**: 最近 {days} 天",
            f"**数据点**: {len(data)} 个",
            f"",
            f"**当前值**: {values[-1]}",
            f"**区间最高**: {max(values)}",
            f"**区间最低**: {min(values)}",
            f"**均值**: {sum(values) / len(values):.2f}",
        ]

        if len(values) >= 2:
            lines.append(f"**变动幅度**: {(values[-1] - values[0]):+.2f}")

        return "\n".join(lines)
