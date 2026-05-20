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

    def query_indicator(self, indicator: str, start: str, end: str) -> Dict[str, Any]:
        """
        指定指标在日期区间的走势归因
        """
        return self._rules_analyzer.query_indicator(indicator, start, end)

    def get_trend(self, indicator: str, days: int = 90) -> List[Dict[str, Any]]:
        """
        返回趋势数据
        """
        return self._rules_analyzer.get_trend(indicator, days)

    # ─── 飞书命令处理 ──────────────────────────────────────

    def handle_command(self, text: str) -> str:
        """
        处理飞书命令文本，返回格式化回复

        V2 命令格式：
            宏观                   → 四象限综合判断
            归因 <指标> <开始> <结束> → 指标区间归因报告
            趋势 <指标> <天数>        → 趋势分析
        """
        text = text.strip()

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
