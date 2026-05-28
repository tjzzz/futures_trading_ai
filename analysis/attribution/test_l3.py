"""
测试L3报告生成功能
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from attribution.report import generate_report, ReportGenerator


def create_mock_data():
    """创建模拟的L1和L2数据用于测试"""
    
    # 模拟L1统计归因结果
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
            },
            {
                "factor": "gold_futures",
                "name": "黄金期货",
                "contribution_pct": 5.2,
                "r": 0.92,
                "delta": 1.5,
                "detail": "黄金期货同步上涨，强化趋势"
            },
            {
                "factor": "silver_futures",
                "name": "白银期货",
                "contribution_pct": 3.8,
                "r": 0.85,
                "delta": 1.2,
                "detail": "白银跟随黄金上涨，但幅度较小"
            }
        ],
        "price_series": [
            {"date": "2026-05-01", "value": 4420.5},
            {"date": "2026-05-05", "value": 4435.2},
            {"date": "2026-05-10", "value": 4450.8},
            {"date": "2026-05-15", "value": 4475.6},
            {"date": "2026-05-20", "value": 4495.3}
        ]
    }
    
    # 模拟L2事件匹配结果
    mock_l2_result = {
        "matched_events": [
            {
                "anomaly_date": "2026-05-15",
                "event_title": "30Y 美债收益率突破 5%",
                "event_level": "S",
                "event_quadrant": "货币锚",
                "price_impact": {"change": -60, "before": 4480, "after": 4420},
                "direction": "下跌",
                "match_confidence": 0.85,
                "time_diff_hours": 2.5
            },
            {
                "anomaly_date": "2026-05-18",
                "event_title": "美伊和谈破裂",
                "event_level": "A",
                "event_quadrant": "风险偏好",
                "price_impact": {"change": 45, "before": 4450, "after": 4495},
                "direction": "上涨",
                "match_confidence": 0.72,
                "time_diff_hours": 4.2
            },
            {
                "anomaly_date": "2026-05-19",
                "event_title": "美联储官员暗示可能暂停加息",
                "event_level": "A",
                "event_quadrant": "货币锚",
                "price_impact": {"change": 25, "before": 4470, "after": 4495},
                "direction": "上涨",
                "match_confidence": 0.68,
                "time_diff_hours": 3.1
            }
        ],
        "impact_analysis": {
            "total_matched": 3,
            "by_level": {"S": 1, "A": 2},
            "by_quadrant": {"货币锚": 2, "风险偏好": 1},
            "avg_confidence": 0.75,
            "total_price_impact": 130
        }
    }
    
    return mock_l1_result, mock_l2_result


def test_report_generator():
    """测试报告生成器"""
    print("=" * 60)
    print("测试L3报告生成功能")
    print("=" * 60)
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    try:
        # 创建模拟数据
        print("\n步骤1: 创建模拟数据...")
        mock_l1, mock_l2 = create_mock_data()
        print(f"   L1数据: {len(mock_l1['driver_ranking'])} 个驱动因子")
        print(f"   L2数据: {len(mock_l2['matched_events'])} 个匹配事件")
        
        # 测试1: 初始化报告生成器
        print("\n步骤2: 初始化报告生成器...")
        generator = ReportGenerator()
        print(f"   模板目录: {generator.templates_dir}")
        
        # 检查模板文件
        template_files = list(generator.templates_dir.glob("*.j2"))
        print(f"   模板文件: {len(template_files)} 个")
        for tf in template_files:
            print(f"     - {tf.name}")
        
        # 测试2: 生成规则模板报告
        print("\n步骤3: 生成规则模板报告...")
        report_result = generator.generate_rule_based_report(
            l1_result=mock_l1,
            l2_result=mock_l2,
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily"
        )
        
        print(f"✅ 规则模板报告生成成功")
        print(f"   报告类型: {report_result.get('report_type')}")
        print(f"   生成时间: {report_result.get('generated_at')}")
        print(f"   目标品种: {report_result.get('target')}")
        print(f"   报告摘要: {report_result.get('summary', '无')[:100]}...")
        
        # 检查报告内容
        if "html_report" in report_result:
            html_len = len(report_result["html_report"])
            print(f"   HTML报告长度: {html_len} 字符")
        
        if "text_report" in report_result:
            text_len = len(report_result["text_report"])
            print(f"   文本报告长度: {text_len} 字符")
        
        # 测试3: 使用generate_report函数
        print("\n步骤4: 使用generate_report函数...")
        
        # 创建输出目录
        output_dir = Path("analysis/reports")
        output_dir.mkdir(exist_ok=True)
        
        full_report = generate_report(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            l1_result=mock_l1,
            l2_result=mock_l2,
            mode="rule_based",
            output_dir=str(output_dir)
        )
        
        print(f"✅ 完整报告生成成功")
        print(f"   HTML文件: {full_report.get('html_file', '未生成')}")
        print(f"   文本文件: {full_report.get('text_file', '未生成')}")
        print(f"   JSON文件: {full_report.get('json_file', '未生成')}")
        
        # 检查生成的文件
        print("\n步骤5: 检查生成的文件...")
        generated_files = list(output_dir.glob("attribution_report_*.html"))
        if generated_files:
            print(f"   找到 {len(generated_files)} 个HTML报告文件")
            for i, file in enumerate(generated_files[:3]):
                print(f"   {i+1}. {file.name}")
                
                # 检查文件大小
                file_size = file.stat().st_size
                print(f"      大小: {file_size:,} 字节")
                
                # 预览文件内容
                if i == 0:
                    with open(file, 'r', encoding='utf-8') as f:
                        content = f.read(500)
                        print(f"      前500字符: {content[:100]}...")
        
        # 测试4: 测试结论生成
        print("\n步骤6: 测试结论生成...")
        conclusion = full_report.get("conclusion", "")
        print(f"   生成结论: {conclusion[:150]}...")
        
        # 测试5: 测试没有L2数据的情况
        print("\n步骤7: 测试没有L2数据的情况...")
        report_no_l2 = generator.generate_rule_based_report(
            l1_result=mock_l1,
            l2_result=None,
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily"
        )
        
        print(f"✅ 无L2数据报告生成成功")
        print(f"   结论包含'事件': {'事件' in report_no_l2.get('conclusion', '')}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_real_data_integration():
    """测试真实数据集成"""
    print("\n" + "=" * 60)
    print("测试真实数据集成")
    print("=" * 60)
    
    try:
        from attribution.statistical import statistical_attribution
        from attribution.event_matcher import match_events
        
        print("步骤1: 运行L1获取真实数据...")
        l1_real = statistical_attribution(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            data_dir="data"
        )
        
        print(f"   L1完成: {len(l1_real.get('driver_ranking', []))} 个驱动因子")
        
        print("\n步骤2: 运行L2获取真实事件匹配...")
        price_series = l1_real.get("price_series", [])
        l2_real = match_events(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            price_series=price_series,
            data_dir="data"
        )
        
        print(f"   L2完成: {l2_real['impact_analysis']['total_matched']} 个匹配事件")
        
        print("\n步骤3: 生成真实数据报告...")
        real_report = generate_report(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            l1_result=l1_real,
            l2_result=l2_real,
            mode="rule_based",
            output_dir="analysis/reports"
        )
        
        print(f"✅ 真实数据报告生成成功")
        print(f"   报告文件: {real_report.get('json_file', '未生成')}")
        
        # 读取并显示报告摘要
        if real_report.get('json_file'):
            with open(real_report['json_file'], 'r', encoding='utf-8') as f:
                report_data = json.load(f)
                print(f"   报告摘要: {report_data.get('summary', '无')}")
        
        return True
        
    except Exception as e:
        print(f"⚠️  真实数据测试失败 (可能数据不足): {e}")
        return False


if __name__ == "__main__":
    print("归因模块L3功能测试")
    print("=" * 60)
    
    # 运行测试
    success1 = test_report_generator()
    success2 = test_real_data_integration()
    
    print("\n" + "=" * 60)
    if success1:
        print("✅ L3报告生成功能测试通过")
    else:
        print("❌ L3报告生成功能测试失败")
    print("=" * 60)