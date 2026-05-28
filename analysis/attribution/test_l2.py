"""
测试L2事件匹配功能
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from attribution.event_matcher import match_events, EventMatcher


def test_event_matcher():
    """测试事件匹配功能"""
    print("=" * 60)
    print("测试L2事件匹配功能")
    print("=" * 60)
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    try:
        # 创建模拟价格序列（基于实际数据）
        print("\n测试1: 创建模拟价格序列...")
        
        # 从实际数据中读取价格序列
        from attribution.statistical import DataLoader
        loader = DataLoader("data")
        price_series = loader.load_price_series("gold", "2026-05-01", "2026-05-20", "daily")
        
        if not price_series:
            print("⚠️  无法加载实际价格序列，使用模拟数据")
            # 创建模拟价格序列
            base_date = datetime(2026, 5, 1)
            base_price = 4400
            
            price_series = []
            for i in range(20):
                date = base_date + timedelta(days=i)
                # 模拟一些波动
                if i == 5:  # 第5天异常上涨
                    price = base_price + 100
                elif i == 12:  # 第12天异常下跌
                    price = base_price - 80
                else:
                    price = base_price + (i * 2)  # 缓慢上涨
                
                price_series.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "value": price,
                    "timestamp": date
                })
        
        print(f"   价格序列: {len(price_series)} 个数据点")
        
        # 测试2: 初始化事件匹配器
        print("\n测试2: 初始化事件匹配器...")
        matcher = EventMatcher("data")
        
        # 加载事件数据
        events = matcher.load_events()
        print(f"   加载事件: {len(events)} 个")
        
        if events:
            print(f"   事件示例:")
            for i, event in enumerate(events[:3]):
                print(f"   {i+1}. {event.get('title', '无标题')}")
                print(f"      日期: {event.get('pubDate', '无日期')}")
                print(f"      等级: {event.get('level', '未知')}")
                print(f"      象限: {event.get('quadrant', '未知')}")
        
        # 测试3: 检测异常波动日
        print("\n测试3: 检测异常波动日...")
        anomaly_days = matcher.detect_anomaly_days(price_series)
        print(f"   检测到异常日: {len(anomaly_days)} 个")
        
        if anomaly_days:
            print(f"   异常日详情:")
            for i, anomaly in enumerate(anomaly_days[:3]):
                direction = "上涨" if anomaly["price_change"] > 0 else "下跌"
                print(f"   {i+1}. {anomaly['date']}: {direction} {abs(anomaly['price_change_pct']):.1f}%")
                print(f"      异常分数: {anomaly['anomaly_score']}, 阈值: ±{anomaly['threshold']:.2f}%")
        
        # 测试4: 匹配事件
        print("\n测试4: 匹配事件...")
        matched_events = matcher.match_events_with_anomalies(anomaly_days, events)
        print(f"   匹配事件: {len(matched_events)} 个")
        
        if matched_events:
            print(f"   匹配事件详情:")
            for i, match in enumerate(matched_events[:3]):
                print(f"   {i+1}. {match['event_title']} ({match['event_level']}级)")
                print(f"      异常日期: {match['anomaly_date']}")
                print(f"      事件日期: {match['event_date']}")
                print(f"      时间差: {match['time_diff_hours']} 小时")
                print(f"      价格影响: {match['direction']} {abs(match['price_impact']['change'])} 点")
                print(f"      置信度: {match['match_confidence']}")
        
        # 测试5: 分析事件影响
        print("\n测试5: 分析事件影响...")
        impact_stats = matcher.analyze_event_impact(matched_events)
        print(f"   事件影响统计:")
        print(f"   总匹配数: {impact_stats['total_matched']}")
        print(f"   按等级: {impact_stats.get('by_level', {})}")
        print(f"   按象限: {impact_stats.get('by_quadrant', {})}")
        print(f"   平均置信度: {impact_stats.get('avg_confidence', 0)}")
        print(f"   总价格影响: {impact_stats.get('total_price_impact', 0)}")
        
        # 测试6: 完整的事件匹配函数
        print("\n测试6: 完整的事件匹配函数...")
        result = match_events(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            price_series=price_series,
            data_dir="data"
        )
        
        print(f"✅ 事件匹配执行成功")
        print(f"   目标: {result['target']}")
        print(f"   区间: {result['period']['start']} ~ {result['period']['end']}")
        print(f"   异常日: {result['anomaly_detection']['anomaly_days']} 个")
        print(f"   匹配事件: {result['impact_analysis']['total_matched']} 个")
        print(f"   摘要: {result['summary']}")
        
        # 保存结果
        output_file = Path("analysis/results/event_matches.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 结果已保存到: {output_file}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integration_with_l1():
    """测试与L1的集成"""
    print("\n" + "=" * 60)
    print("测试L1+L2集成")
    print("=" * 60)
    
    try:
        # 先运行L1获取价格序列
        from attribution.statistical import statistical_attribution
        from attribution.engine import AttributionEngine
        
        print("步骤1: 运行L1统计归因...")
        l1_result = statistical_attribution(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            data_dir="data"
        )
        
        price_series = l1_result.get("price_series", [])
        print(f"   获取价格序列: {len(price_series)} 个数据点")
        
        print("\n步骤2: 运行L2事件匹配...")
        l2_result = match_events(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            price_series=price_series,
            data_dir="data"
        )
        
        print(f"✅ L1+L2集成测试成功")
        print(f"   L1驱动因子: {len(l1_result.get('driver_ranking', []))} 个")
        print(f"   L2匹配事件: {l2_result['impact_analysis']['total_matched']} 个")
        
        return True
        
    except Exception as e:
        print(f"❌ 集成测试失败: {e}")
        return False


if __name__ == "__main__":
    print("归因模块L2功能测试")
    print("=" * 60)
    
    # 运行测试
    success1 = test_event_matcher()
    success2 = test_integration_with_l1()
    
    print("\n" + "=" * 60)
    if success1 and success2:
        print("✅ L2事件匹配功能测试通过")
    else:
        print("❌ L2事件匹配功能测试失败")
    print("=" * 60)