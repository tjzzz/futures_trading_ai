"""
因子配置管理 — 加载和管理因子配置
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class FactorDirection(str, Enum):
    """因子方向枚举"""
    POSITIVE = "positive"  # 因子上涨 → 目标上涨
    NEGATIVE = "negative"  # 因子上涨 → 目标下跌


class FactorType(str, Enum):
    """因子类型枚举"""
    CONTINUOUS = "continuous"  # 连续变量
    DISCRETE = "discrete"      # 离散事件
    COMPOSITE = "composite"    # 复合指标


@dataclass
class FactorConfig:
    """单个因子配置"""
    id: str
    name: str
    direction: FactorDirection
    data_source: Optional[str] = None
    data_field: Optional[str] = None
    type: FactorType = FactorType.CONTINUOUS
    weight: float = 1.0
    note: str = ""


@dataclass
class TimeframeConfig:
    """时间粒度配置"""
    window: str
    data_grain: str  # "daily" | "minutely"
    label: str


@dataclass
class FactorSet:
    """因子集配置"""
    target: str  # "gold" | "silver"
    name: str
    timeframes: Dict[str, TimeframeConfig]
    factors: List[FactorConfig]


class FactorConfigManager:
    """因子配置管理器"""
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            # 默认路径：当前模块下的factors目录
            self.config_dir = Path(__file__).parent / "factors"
        else:
            self.config_dir = Path(config_dir)
        
        self._configs: Dict[str, FactorSet] = {}
        self._load_configs()
    
    def _load_configs(self):
        """加载所有因子配置文件"""
        for config_file in self.config_dir.glob("*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 解析时间粒度配置
                timeframes = {}
                for timeframe_key, timeframe_data in data.get("timeframes", {}).items():
                    timeframes[timeframe_key] = TimeframeConfig(
                        window=timeframe_data.get("window", ""),
                        data_grain=timeframe_data.get("data_grain", "daily"),
                        label=timeframe_data.get("label", "")
                    )
                
                # 解析因子配置
                factors = []
                for factor_data in data.get("factors", []):
                    factor = FactorConfig(
                        id=factor_data.get("id"),
                        name=factor_data.get("name"),
                        direction=FactorDirection(factor_data.get("direction", "positive")),
                        data_source=factor_data.get("data_source"),
                        data_field=factor_data.get("data_field"),
                        type=FactorType(factor_data.get("type", "continuous")),
                        weight=float(factor_data.get("weight", 1.0)),
                        note=factor_data.get("note", "")
                    )
                    factors.append(factor)
                
                factor_set = FactorSet(
                    target=data.get("target"),
                    name=data.get("name"),
                    timeframes=timeframes,
                    factors=factors
                )
                
                self._configs[factor_set.target] = factor_set
                print(f"✅ 已加载因子配置: {factor_set.name} ({factor_set.target})")
                
            except Exception as e:
                print(f"❌ 加载配置文件 {config_file} 失败: {e}")
    
    def get_factor_set(self, target: str) -> Optional[FactorSet]:
        """获取指定品种的因子集"""
        return self._configs.get(target)
    
    def get_factor(self, target: str, factor_id: str) -> Optional[FactorConfig]:
        """获取指定品种的特定因子配置"""
        factor_set = self.get_factor_set(target)
        if not factor_set:
            return None
        
        for factor in factor_set.factors:
            if factor.id == factor_id:
                return factor
        return None
    
    def get_timeframe_config(self, target: str, timeframe: str) -> Optional[TimeframeConfig]:
        """获取指定品种和时间粒度的配置"""
        factor_set = self.get_factor_set(target)
        if not factor_set:
            return None
        return factor_set.timeframes.get(timeframe)
    
    def list_targets(self) -> List[str]:
        """列出所有支持的品种"""
        return list(self._configs.keys())
    
    def get_all_factors(self, target: str) -> List[FactorConfig]:
        """获取指定品种的所有因子"""
        factor_set = self.get_factor_set(target)
        return factor_set.factors if factor_set else []


# 全局配置管理器实例
_config_manager: Optional[FactorConfigManager] = None


def get_config_manager() -> FactorConfigManager:
    """获取全局配置管理器实例（单例模式）"""
    global _config_manager
    if _config_manager is None:
        _config_manager = FactorConfigManager()
    return _config_manager


def load_factor_set(target: str) -> FactorSet:
    """加载指定品种的因子集"""
    manager = get_config_manager()
    factor_set = manager.get_factor_set(target)
    if not factor_set:
        raise ValueError(f"未找到品种 '{target}' 的因子配置")
    return factor_set


def get_factor(target: str, factor_id: str) -> FactorConfig:
    """获取指定品种的特定因子配置"""
    manager = get_config_manager()
    factor = manager.get_factor(target, factor_id)
    if not factor:
        raise ValueError(f"未找到品种 '{target}' 的因子 '{factor_id}'")
    return factor


def get_timeframe_config(target: str, timeframe: str) -> TimeframeConfig:
    """获取指定品种和时间粒度的配置"""
    manager = get_config_manager()
    config = manager.get_timeframe_config(target, timeframe)
    if not config:
        raise ValueError(f"未找到品种 '{target}' 的时间粒度配置 '{timeframe}'")
    return config


if __name__ == "__main__":
    # 测试代码
    manager = FactorConfigManager()
    print("支持的品种:", manager.list_targets())
    
    gold_factors = manager.get_all_factors("gold")
    print(f"\n黄金因子 ({len(gold_factors)}个):")
    for factor in gold_factors:
        print(f"  - {factor.name} ({factor.id}): {factor.direction.value}")