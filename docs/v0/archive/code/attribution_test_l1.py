"""
测试L1统计归因功能
"""

import json
import logging
import sys
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from attribution.statistical import statistical_attribution
from attribution.engine import AttributionEngine


def test_statistical_attribution():
    """测试统计归因功能"""
    print("=" * 60)
    print("测试L1统计归因功能")
    print("=" * 60)
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    try:
        # 测试1: 直接调用statistical_attribution
        print("\n测试1: 直接调用statistical_attribution...")
        result = statistical_attribution(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            data_dir="data"
        )
        
        print(f"✅ 统计归因执行成功")
        print(f"   品种: {result['target_name']}")
        print(f"   区间: {result['period']['start']} ~ {result['period']['end']}")
        print(f"   价格变动: {result['price_change']['from']} → {result['price_change']['to']} ({result['price_change']['pct']}%)")
        print(f"   分析因子: {len(result['driver_ranking'])} 个")
        
        if result['driver_ranking']:
            print(f"\n   驱动因子排名 (前3):")
            for i, driver in enumerate(result['driver_ranking'][:3]):
                print(f"   {i+1}. {driver['name']}: 贡献 {driver.get('contribution_pct', 0)}%, r={driver['r']}")
        
        # 保存结果
        output_file = Path("analysis/results/statistical_attribution.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 结果已保存到: {output_file}")
        
        # 测试2: 通过引擎调用
        print("\n测试2: 通过AttributionEngine调用...")
        engine = AttributionEngine(data_dir="data")
        engine_result = engine.run_l1("gold", "2026-05-01", "2026-05-20", "daily")
        
        print(f"✅ 引擎调用成功")
        print(f"   状态: {engine_result.get('status', 'unknown')}")
        print(f"   目标: {engine_result.get('target', 'unknown')}")
        
        if 'l1_statistical' in engine_result:
            l1 = engine_result['l1_statistical']
            print(f"   价格变动: {l1.get('price_change', {}).get('pct', 'N/A')}%")
            print(f"   驱动因子: {len(l1.get('driver_ranking', []))} 个")
        
        # 测试3: 测试白银
        print("\n测试3: 测试白银归因...")
        try:
            silver_result = statistical_attribution(
                target="silver",
                start="2026-05-01",
                end="2026-05-20",
                grain="daily",
                data_dir="data"
            )
            print(f"✅ 白银归因执行成功")
            print(f"   品种: {silver_result['target_name']}")
            print(f"   分析因子: {len(silver_result['driver_ranking'])} 个")
        except Exception as e:
            print(f"⚠️  白银归因测试失败 (可能缺少数据): {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_data_files():
    """检查数据文件是否存在"""
    print("\n" + "=" * 60)
    print("检查数据文件")
    print("=" * 60)
    
    data_dir = Path("data")
    required_files = [
        data_dir / "history" / "daily" / "gold_silver_daily.csv",
        data_dir / "history" / "daily" / "dxy.csv",
        data_dir / "history" / "daily" / "treasury.csv",
        data_dir / "history" / "daily" / "tips.csv",
        data_dir / "history" / "daily" / "vix.csv",
    ]
    
    all_exist = True
    for file_path in required_files:
        if file_path.exists():
            print(f"✅ {file_path.relative_to(data_dir.parent)}")
        else:
            print(f"❌ {file_path.relative_to(data_dir.parent)} (不存在)")
            all_exist = False
    
    return all_exist


if __name__ == "__main__":
    print("归因模块L1功能测试")
    print("=" * 60)
    
    # 检查数据文件
    if not check_data_files():
        print("\n⚠️  警告: 部分数据文件缺失，测试可能失败")
        print("请确保数据采集器已运行并生成了所需的数据文件")
    
    # 运行测试
    success = test_statistical_attribution()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ L1统计归因功能测试通过")
    else:
        print("❌ L1统计归因功能测试失败")
    print("=" * 60)