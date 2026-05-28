"""
归因引擎统一入口 — 期货交易系统 V2

整合统计归因(L1)、事件匹配(L2)和报告生成(L3)
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .statistical import statistical_attribution
from .event_matcher import match_events
from .report import generate_report
from .factor_config import load_factor_set


logger = logging.getLogger(__name__)


class AttributionEngine:
    """
    归因引擎统一入口
    
    接口：
        run() - 执行完整归因分析
        run_l1() - 仅执行统计归因
        run_l2() - 仅执行事件匹配
        run_l3() - 仅生成报告
    """
    
    def __init__(self, data_dir: str = "data"):
        """
        初始化归因引擎
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
    
    def run(self, target: str, start: str, end: str, 
            grain: str = "daily", mode: str = "full") -> Dict[str, Any]:
        """
        执行完整归因分析
        
        Args:
            target: 品种 "gold" | "silver"
            start: 开始日期 "YYYY-MM-DD"
            end: 结束日期 "YYYY-MM-DD"
            grain: 数据粒度 "daily" | "minutely"
            mode: 运行模式 "full" | "l1_only" | "l2_only" | "l3_only"
            
        Returns:
            归因分析结果
        """
        logger.info(f"开始归因分析: {target} {start}~{end} ({grain})")
        
        # 验证参数
        self._validate_params(target, start, end, grain)
        
        # 加载因子配置
        factor_set = load_factor_set(target)
        
        # L1: 统计归因
        l1_result = None
        if mode in ["full", "l1_only"]:
            try:
                l1_result = statistical_attribution(
                    target=target,
                    start=start,
                    end=end,
                    grain=grain,
                    data_dir=self.data_dir
                )
                logger.info(f"L1 统计归因完成: {len(l1_result.get('driver_ranking', []))} 个因子")
            except Exception as e:
                logger.error(f"L1 统计归因失败: {e}")
                if mode == "l1_only":
                    raise
        
        # L2: 事件匹配
        l2_result = None
        if mode in ["full", "l2_only"] and l1_result:
            try:
                # 从L1结果中获取价格序列
                price_series = l1_result.get("price_series", [])
                l2_result = match_events(
                    target=target,
                    start=start,
                    end=end,
                    price_series=price_series,
                    data_dir=self.data_dir
                )
                logger.info(f"L2 事件匹配完成: {len(l2_result.get('matched_events', []))} 个事件")
            except Exception as e:
                logger.error(f"L2 事件匹配失败: {e}")
                if mode == "l2_only":
                    raise
        
        # L3: 报告生成
        l3_result = None
        if mode in ["full", "l3_only"]:
            try:
                l3_result = generate_report(
                    target=target,
                    start=start,
                    end=end,
                    grain=grain,
                    l1_result=l1_result,
                    l2_result=l2_result,
                    mode="rule_based"  # 默认规则模板模式
                )
                logger.info("L3 报告生成完成")
            except Exception as e:
                logger.error(f"L3 报告生成失败: {e}")
                if mode == "l3_only":
                    raise
        
        # 整合结果
        result = {
            "engine": "attribution_v2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target": target,
            "target_name": factor_set.name,
            "period": {
                "start": start,
                "end": end,
                "grain": grain
            },
            "mode": mode,
            "l1_statistical": l1_result,
            "l2_event_matches": l2_result,
            "l3_report": l3_result,
            "status": "completed"
        }
        
        logger.info(f"归因分析完成: {target} {start}~{end}")
        return result
    
    def run_l1(self, target: str, start: str, end: str, grain: str = "daily") -> Dict[str, Any]:
        """仅执行统计归因"""
        return self.run(target, start, end, grain, mode="l1_only")
    
    def run_l2(self, target: str, start: str, end: str, grain: str = "daily") -> Dict[str, Any]:
        """仅执行事件匹配（需要先有L1结果）"""
        # 先运行L1获取价格序列
        l1_result = self.run_l1(target, start, end, grain)
        return self.run(target, start, end, grain, mode="l2_only")
    
    def run_l3(self, target: str, start: str, end: str, grain: str = "daily") -> Dict[str, Any]:
        """生成报告（需要先有L1和L2结果）"""
        return self.run(target, start, end, grain, mode="full")
    
    def _validate_params(self, target: str, start: str, end: str, grain: str):
        """验证参数"""
        # 验证品种
        valid_targets = ["gold", "silver"]
        if target not in valid_targets:
            raise ValueError(f"无效的品种: {target}，支持的品种: {valid_targets}")
        
        # 验证日期格式
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
            if start_date > end_date:
                raise ValueError(f"开始日期 {start} 不能晚于结束日期 {end}")
        except ValueError as e:
            raise ValueError(f"日期格式错误: {e}，请使用 YYYY-MM-DD 格式")
        
        # 验证粒度
        valid_grains = ["daily", "minutely"]
        if grain not in valid_grains:
            raise ValueError(f"无效的粒度: {grain}，支持的粒度: {valid_grains}")


# 工具函数：简化调用
def run_attribution(target: str, start: str, end: str, grain: str = "daily") -> Dict[str, Any]:
    """
    简化调用函数：执行完整归因分析
    
    Args:
        target: 品种 "gold" | "silver"
        start: 开始日期 "YYYY-MM-DD"
        end: 结束日期 "YYYY-MM-DD"
        grain: 数据粒度 "daily" | "minutely"
        
    Returns:
        归因分析结果
    """
    engine = AttributionEngine()
    return engine.run(target, start, end, grain)


if __name__ == "__main__":
    # 测试代码
    import json
    
    engine = AttributionEngine()
    
    # 测试L1统计归因
    print("测试L1统计归因...")
    try:
        result = engine.run_l1("gold", "2026-05-01", "2026-05-20", "daily")
        print(f"L1结果结构: {list(result.keys())}")
        if "l1_statistical" in result:
            l1 = result["l1_statistical"]
            print(f"价格变动: {l1.get('price_change', {}).get('pct', 'N/A')}")
            print(f"驱动因子: {len(l1.get('driver_ranking', []))}个")
    except Exception as e:
        print(f"测试失败: {e}")