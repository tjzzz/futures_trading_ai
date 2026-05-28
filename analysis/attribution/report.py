"""
L3: 报告生成模块

核心功能：整合L1和L2的结果，生成归因报告
支持两种模式：规则模板（固定格式）、LLM增强（可配置）
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import jinja2

from .factor_config import load_factor_set


logger = logging.getLogger(__name__)


class ReportGenerator:
    """报告生成器：整合L1和L2结果，生成归因报告"""
    
    def __init__(self, templates_dir: str = None):
        """
        初始化报告生成器
        
        Args:
            templates_dir: 模板目录路径，如果为None则使用默认模板
        """
        if templates_dir:
            self.templates_dir = Path(templates_dir)
        else:
            # 默认模板目录：当前模块目录下的templates
            self.templates_dir = Path(__file__).parent / "templates"
        
        # 创建模板目录（如果不存在）
        self.templates_dir.mkdir(exist_ok=True)
        
        # 初始化Jinja2环境
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.templates_dir)),
            autoescape=jinja2.select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # 创建默认模板（如果不存在）
        self._create_default_templates()
    
    def _create_default_templates(self):
        """创建默认报告模板"""
        # HTML报告模板
        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ report_title }}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 {
            margin: 0;
            font-size: 2.5em;
        }
        .header .meta {
            margin-top: 15px;
            opacity: 0.9;
            font-size: 0.9em;
        }
        .section {
            background: white;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 25px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .section h2 {
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
            margin-top: 0;
        }
        .price-change {
            font-size: 1.5em;
            font-weight: bold;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
            margin: 20px 0;
        }
        .price-up { color: #27ae60; }
        .price-down { color: #e74c3c; }
        .driver-ranking {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .driver-card {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            transition: transform 0.2s;
        }
        .driver-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .driver-card.top-3 {
            border-left: 5px solid #3498db;
        }
        .contribution-bar {
            height: 10px;
            background: #ecf0f1;
            border-radius: 5px;
            margin: 10px 0;
            overflow: hidden;
        }
        .contribution-fill {
            height: 100%;
            background: linear-gradient(90deg, #3498db, #2ecc71);
            border-radius: 5px;
        }
        .event-list {
            list-style: none;
            padding: 0;
        }
        .event-item {
            padding: 15px;
            margin-bottom: 10px;
            border-left: 4px solid;
            background: #f8f9fa;
            border-radius: 4px;
        }
        .event-item.s-level { border-color: #e74c3c; }
        .event-item.a-level { border-color: #f39c12; }
        .event-item.b-level { border-color: #3498db; }
        .event-item.c-level { border-color: #95a5a6; }
        .conclusion {
            background: #fffde7;
            border-left: 5px solid #f1c40f;
            padding: 20px;
            border-radius: 5px;
            font-size: 1.1em;
        }
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .stat-item {
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #2c3e50;
        }
        .stat-label {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-top: 5px;
        }
        .footer {
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #7f8c8d;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ report_title }}</h1>
        <div class="meta">
            生成时间: {{ generation_time }} | 分析引擎: {{ engine_name }} | 模式: {{ mode }}
        </div>
    </div>
    
    <div class="section">
        <h2>📊 概览</h2>
        <div class="price-change {% if price_change.pct > 0 %}price-up{% else %}price-down{% endif %}">
            {{ target_name }}: {{ price_change.from }} → {{ price_change.to }} 
            ({{ price_change.pct|abs }}% {% if price_change.pct > 0 %}上涨{% else %}下跌{% endif %})
        </div>
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-value">{{ period.days }}天</div>
                <div class="stat-label">分析周期</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{{ driver_count }}个</div>
                <div class="stat-label">分析因子</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{{ event_count }}个</div>
                <div class="stat-label">匹配事件</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{{ dominant_contribution }}%</div>
                <div class="stat-label">主导因子贡献</div>
            </div>
        </div>
    </div>
    
    <div class="section">
        <h2>🏆 驱动因子排名</h2>
        <div class="driver-ranking">
            {% for driver in driver_ranking %}
            <div class="driver-card {% if loop.index <= 3 %}top-3{% endif %}">
                <h3>{{ loop.index }}. {{ driver.name }}</h3>
                <div class="contribution-bar">
                    <div class="contribution-fill" style="width: {{ driver.contribution_pct|abs }}%;"></div>
                </div>
                <p>贡献度: <strong>{{ driver.contribution_pct }}%</strong></p>
                <p>相关性: r = {{ driver.r }} ({{ "正相关" if driver.r > 0 else "负相关" }})</p>
                <p>变动幅度: Δ = {{ driver.delta }}</p>
                <p class="detail">{{ driver.detail }}</p>
            </div>
            {% endfor %}
        </div>
    </div>
    
    {% if matched_events %}
    <div class="section">
        <h2>📰 事件匹配</h2>
        <ul class="event-list">
            {% for event in matched_events %}
            <li class="event-item {{ event.event_level|lower }}-level">
                <strong>{{ event.event_title }}</strong> ({{ event.event_level }}级)
                <br>
                <small>日期: {{ event.anomaly_date }} | 时间差: {{ event.time_diff_hours }}小时</small>
                <br>
                价格影响: {{ event.direction }} {{ event.price_impact.change|abs }}点
                <br>
                置信度: {{ event.match_confidence }} | 象限: {{ event.event_quadrant }}
            </li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}
    
    <div class="section">
        <h2>💡 综合结论</h2>
        <div class="conclusion">
            {{ conclusion }}
        </div>
    </div>
    
    <div class="footer">
        期货AI交易系统 V2 - 归因分析报告 | 生成于 {{ generation_date }}
    </div>
</body>
</html>"""
        
        # 文本报告模板
        text_template = """# {{ report_title }}
生成时间: {{ generation_time }}
分析引擎: {{ engine_name }}
模式: {{ mode }}

## 📊 概览
{{ target_name }} {{ period.start }} ~ {{ period.end }} ({{ period.days }}天)
价格: {{ price_change.from }} → {{ price_change.to }} ({{ price_change.pct|abs }}% {% if price_change.pct > 0 %}上涨{% else %}下跌{% endif %})

## 🏆 驱动因子排名
{% for driver in driver_ranking %}
{{ loop.index }}. {{ driver.name }}
  贡献度: {{ driver.contribution_pct }}%
  相关性: r = {{ driver.r }} ({{ "正相关" if driver.r > 0 else "负相关" }})
  变动幅度: Δ = {{ driver.delta }}
  详情: {{ driver.detail }}
{% endfor %}

## 📰 事件匹配
{% if matched_events %}
{% for event in matched_events %}
- {{ event.event_title }} ({{ event.event_level }}级)
  日期: {{ event.anomaly_date }} | 时间差: {{ event.time_diff_hours }}小时
  价格影响: {{ event.direction }} {{ event.price_impact.change|abs }}点
  置信度: {{ event.match_confidence }} | 象限: {{ event.event_quadrant }}
{% endfor %}
{% else %}
未检测到显著的事件驱动波动
{% endif %}

## 💡 综合结论
{{ conclusion }}
"""
        
        # 保存模板文件
        html_template_path = self.templates_dir / "report.html.j2"
        text_template_path = self.templates_dir / "report.txt.j2"
        
        if not html_template_path.exists():
            html_template_path.write_text(html_template, encoding='utf-8')
            logger.info(f"创建HTML模板: {html_template_path}")
        
        if not text_template_path.exists():
            text_template_path.write_text(text_template, encoding='utf-8')
            logger.info(f"创建文本模板: {text_template_path}")
    
    def generate_rule_based_report(self, l1_result: Dict[str, Any], 
                                  l2_result: Optional[Dict[str, Any]] = None,
                                  target: str = None, start: str = None, end: str = None,
                                  grain: str = "daily") -> Dict[str, Any]:
        """
        生成规则模板报告
        
        Args:
            l1_result: L1统计归因结果
            l2_result: L2事件匹配结果（可选）
            target: 品种（如果l1_result中未提供）
            start: 开始日期（如果l1_result中未提供）
            end: 结束日期（如果l1_result中未提供）
            grain: 数据粒度
            
        Returns:
            报告结果
        """
        logger.info("生成规则模板报告")
        
        # 提取数据
        target = target or l1_result.get("target", "unknown")
        target_name = l1_result.get("target_name", target)
        start = start or l1_result.get("period", {}).get("start", "unknown")
        end = end or l1_result.get("period", {}).get("end", "unknown")
        
        # 计算周期天数
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
            period_days = (end_date - start_date).days + 1
        except:
            period_days = 0
        
        # 价格变动
        price_change = l1_result.get("price_change", {})
        
        # 驱动因子排名
        driver_ranking = l1_result.get("driver_ranking", [])
        
        # 事件匹配
        matched_events = []
        if l2_result:
            matched_events = l2_result.get("matched_events", [])
        
        # 生成结论
        conclusion = self._generate_conclusion(driver_ranking, matched_events, price_change)
        
        # 准备模板数据
        template_data = {
            "report_title": f"{target_name} 归因分析报告",
            "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "generation_date": datetime.now().strftime("%Y-%m-%d"),
            "engine_name": "期货AI交易系统 V2",
            "mode": "规则模板",
            "target": target,
            "target_name": target_name,
            "period": {
                "start": start,
                "end": end,
                "days": period_days
            },
            "price_change": price_change,
            "driver_ranking": driver_ranking,
            "driver_count": len(driver_ranking),
            "matched_events": matched_events,
            "event_count": len(matched_events),
            "dominant_contribution": driver_ranking[0].get("contribution_pct", 0) if driver_ranking else 0,
            "conclusion": conclusion
        }
        
        # 渲染报告
        try:
            html_template = self.jinja_env.get_template("report.html.j2")
            html_report = html_template.render(**template_data)
            
            text_template = self.jinja_env.get_template("report.txt.j2")
            text_report = text_template.render(**template_data)
            
            logger.info("规则模板报告生成成功")
            
            return {
                "report_type": "rule_based",
                "generated_at": template_data["generation_time"],
                "target": target,
                "period": template_data["period"],
                "html_report": html_report,
                "text_report": text_report,
                "conclusion": conclusion,
                "summary": self._generate_summary(template_data)
            }
            
        except Exception as e:
            logger.error(f"渲染报告模板失败: {e}")
            raise
    
    def _generate_conclusion(self, driver_ranking: List[Dict[str, Any]], 
                           matched_events: List[Dict[str, Any]],
                           price_change: Dict[str, Any]) -> str:
        """生成综合结论"""
        if not driver_ranking:
            return "数据不足，无法生成有效结论"
        
        # 提取主要驱动因子
        top_drivers = driver_ranking[:3]
        
        # 价格变动方向
        price_pct = price_change.get("pct", 0)
        direction = "上涨" if price_pct > 0 else "下跌"
        
        # 构建结论
        conclusion_parts = []
        
        # 1. 价格变动描述
        conclusion_parts.append(f"在分析周期内，价格{direction}了{abs(price_pct):.1f}%。")
        
        # 2. 主要驱动因子
        if top_drivers:
            main_driver = top_drivers[0]
            conclusion_parts.append(f"主要驱动因素是{main_driver['name']}，贡献度{main_driver.get('contribution_pct', 0)}%。")
            
            if len(top_drivers) > 1:
                other_drivers = [d for d in top_drivers[1:] if abs(d.get('contribution_pct', 0)) > 10]
                if other_drivers:
                    other_names = "、".join([d['name'] for d in other_drivers])
                    conclusion_parts.append(f"次要因素包括{other_names}。")
        
        # 3. 事件影响
        if matched_events:
            sa_events = [e for e in matched_events if e.get('event_level') in ['S', 'A']]
            if sa_events:
                conclusion_parts.append(f"检测到{len(sa_events)}个S/A级重要事件，对价格波动产生显著影响。")
        
        # 4. 综合判断
        if price_pct > 2.0:
            conclusion_parts.append("整体来看，市场呈现较强的趋势性行情。")
        elif abs(price_pct) < 0.5:
            conclusion_parts.append("市场整体波动较小，处于盘整状态。")
        else:
            conclusion_parts.append("市场呈现温和波动，需关注后续催化剂。")
        
        return " ".join(conclusion_parts)
    
    def _generate_summary(self, template_data: Dict[str, Any]) -> str:
        """生成报告摘要"""
        target_name = template_data["target_name"]
        price_change = template_data["price_change"]
        driver_count = template_data["driver_count"]
        event_count = template_data["event_count"]
        
        return f"{target_name} {template_data['period']['start']}~{template_data['period']['end']}，" \
               f"价格{price_change.get('pct', 0):+.1f}%，" \
               f"分析{driver_count}个因子，匹配{event_count}个事件。" \
               f"主要驱动: {template_data['driver_ranking'][0]['name'] if template_data['driver_ranking'] else '无'}。"
    
    def generate_llm_report(self, l1_result: Dict[str, Any], 
                           l2_result: Optional[Dict[str, Any]] = None,
                           llm_provider: str = "openai",
                           model: str = "gpt-4") -> Dict[str, Any]:
        """
        生成LLM增强报告（待实现）
        
        Args:
            l1_result: L1统计归因结果
            l2_result: L2事件匹配结果
            llm_provider: LLM提供商
            model: 模型名称
            
        Returns:
            LLM增强报告
        """
        logger.info(f"生成LLM增强报告（{llm_provider}/{model}）")
        
        # TODO: 实现LLM集成
        # 1. 构建prompt
        # 2. 调用LLM API
        # 3. 解析响应
        
        # 临时返回规则模板报告
        return self.generate_rule_based_report(l1_result, l2_result)


def generate_report(target: str, start: str, end: str, grain: str = "daily",
                   l1_result: Dict[str, Any] = None,
                   l2_result: Dict[str, Any] = None,
                   mode: str = "rule_based",
                   output_dir: str = "analysis/reports",
                   **kwargs) -> Dict[str, Any]:
    """
    生成归因报告
    
    Args:
        target: 品种
        start: 开始日期
        end: 结束日期
        grain: 数据粒度
        l1_result: L1统计归因结果（如果为None，将自动运行L1）
        l2_result: L2事件匹配结果（如果为None，将自动运行L2）
        mode: 报告模式 "rule_based" | "llm_enhanced"
        output_dir: 输出目录
        **kwargs: 其他参数（如LLM配置）
        
    Returns:
        报告结果
    """
    logger.info(f"生成归因报告: {target} {start}~{end} ({mode})")
    
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 初始化报告生成器
    generator = ReportGenerator()
    
    # 生成报告
    if mode == "rule_based":
        report_result = generator.generate_rule_based_report(
            l1_result=l1_result,
            l2_result=l2_result,
            target=target,
            start=start,
            end=end,
            grain=grain
        )
    elif mode == "llm_enhanced":
        report_result = generator.generate_llm_report(
            l1_result=l1_result,
            l2_result=l2_result,
            **kwargs
        )
    else:
        raise ValueError(f"不支持的报告模式: {mode}")
    
    # 保存报告文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_filename = f"attribution_report_{target}_{start}_{end}_{timestamp}"
    
    # 保存HTML报告
    html_file = output_path / f"{base_filename}.html"
    if "html_report" in report_result:
        html_file.write_text(report_result["html_report"], encoding="utf-8")
        report_result["html_file"] = str(html_file)
        logger.info(f"保存HTML报告: {html_file}")
    
    # 保存文本报告
    text_file = output_path / f"{base_filename}.txt"
    if "text_report" in report_result:
        text_file.write_text(report_result["text_report"], encoding="utf-8")
        report_result["text_file"] = str(text_file)
        logger.info(f"保存文本报告: {text_file}")
    
    # 保存JSON报告
    json_file = output_path / f"{base_filename}.json"
    json.dump(report_result, open(json_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    report_result["json_file"] = str(json_file)
    logger.info(f"保存JSON报告: {json_file}")
    
    return report_result


if __name__ == "__main__":
    # 测试代码
    import sys
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("测试报告生成模块...")
    
    # 创建模拟数据
    mock_l1_result = {
        "target": "gold",
        "target_name": "黄金 XAU/USD",
        "period": {
            "start": "2026-05-01",
            "end": "2026-05-20"
        },
        "price_change": {
            "from": 4420.5,
            "to": 4495.3,
            "absolute": 74.8,
            "pct": 1.69
        },
        "driver_ranking": [
            {
                "factor": "dxy",
                "name": "美元指数",
                "contribution_pct": 68.2,
                "r": -0.78,
                "delta": -2.3,
                "detail": "DXY 从 101.5 跌至 99.2，贡献主要涨幅"
            },
            {
                "factor": "vix",
                "name": "VIX 恐慌指数",
                "contribution_pct": 22.1,
                "r": 0.45,
                "delta": 4.0,
                "detail": "VIX 从 18 升至 22，避险情绪升温"
            },
            {
                "factor": "tips_10y",
                "name": "TIPS 实际利率",
                "contribution_pct": 9.7,
                "r": -0.65,
                "delta": 0.1,
                "detail": "实际利率变化不大，影响有限"
            }
        ]
    }
    
    mock_l2_result = {
        "matched_events": [
            {
                "anomaly_date": "2026-05-15",
                "event_title": "30Y 美债收益率突破 5%",
                "event_level": "S",
                "event_quadrant": "货币锚",
                "price_impact": {"change": -60},
                "direction": "下跌",
                "match_confidence": 0.85,
                "time_diff_hours": 2.5
            },
            {
                "anomaly_date": "2026-05-18",
                "event_title": "美伊和谈破裂",
                "event_level": "A",
                "event_quadrant": "风险偏好",
                "price_impact": {"change": 45},
                "direction": "上涨",
                "match_confidence": 0.72,
                "time_diff_hours": 4.2
            }
        ]
    }
    
    try:
        report_result = generate_report(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            l1_result=mock_l1_result,
            l2_result=mock_l2_result,
            mode="rule_based",
            output_dir="analysis/reports"
        )
        
        print(f"\n报告生成结果:")
        print(f"报告类型: {report_result.get('report_type')}")
        print(f"生成时间: {report_result.get('generated_at')}")
        print(f"HTML文件: {report_result.get('html_file', '未生成')}")
        print(f"文本文件: {report_result.get('text_file', '未生成')}")
        print(f"JSON文件: {report_result.get('json_file', '未生成')}")
        print(f"\n结论摘要: {report_result.get('summary', '无')}")
        
    except Exception as e:
        print(f"测试失败: {e}")