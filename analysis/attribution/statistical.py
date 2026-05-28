"""
L1: 统计归因模块

核心算法：pearson r × beta × Δ
在指定时间窗口内，量化各因子对价格变动的贡献度
"""

import json
import logging
import math
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta
import statistics

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.csv_loader import load_csv_data, CSVLoaderError
from utils.date_parser import parse_date
from .factor_config import load_factor_set, FactorConfig, FactorDirection


logger = logging.getLogger(__name__)


class DataLoader:
    """数据加载器：从CSV文件加载历史数据"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
    
    def load_price_series(self, target: str, start: str, end: str, grain: str = "daily") -> List[Dict[str, Any]]:
        """
        加载价格序列

        Args:
            target: 品种 "gold" | "silver"
            start: 开始日期 "YYYY-MM-DD"
            end: 结束日期 "YYYY-MM-DD"
            grain: 数据粒度 "daily" | "minutely"

        Returns:
            价格序列列表，每个元素包含 {date, value}
        """
        # 确定数据文件
        if grain == "daily":
            csv_file = "gold_silver_daily.csv"
            data_path = self.data_dir / "history" / "daily" / csv_file
        else:  # minutely
            csv_file = "gold_silver_minutely.csv"
            data_path = self.data_dir / "history" / "minutely" / csv_file

        if not data_path.exists():
            logger.warning(f"价格数据文件不存在: {data_path}")
            return []

        # 确定价格字段
        price_field = "gold_close" if target == "gold" else "silver_close"

        # 解析日期
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")

        try:
            # 使用共享CSV加载器，计算所需天数
            days = (end_date - start_date).days + 1

            # 加载原始数据
            raw_data = load_csv_data(
                data_path,
                days=days,
                max_points=10000,  # 归因分析需要更多数据点
            )

            # 筛选并转换数据
            series = []
            for item in raw_data:
                row_date_str = item.get("date", "")
                row_date = parse_date(row_date_str)
                if row_date is None:
                    continue

                # 检查是否在时间窗口内
                if start_date <= row_date <= end_date:
                    # 从原始行数据中获取价格字段
                    # load_csv_data 返回 {date, value}，但归因需要特定字段
                    # 这里需要重新读取原始CSV获取特定字段
                    pass

            # 由于load_csv_data返回的是通用格式，我们需要直接读取CSV获取特定字段
            # 使用改进后的加载方式
            series = self._load_series_with_field(data_path, price_field, start_date, end_date, grain)

            logger.info(f"加载价格序列: {target} {len(series)} 个数据点 ({start}~{end})")
            return series

        except CSVLoaderError as e:
            logger.error(f"加载价格序列失败: {e}")
            return []
        except Exception as e:
            logger.error(f"加载价格序列失败: {e}")
            return []

    def _load_series_with_field(self, data_path: Path, value_field: str,
                                 start_date: datetime, end_date: datetime,
                                 grain: str) -> List[Dict[str, Any]]:
        """加载特定字段的序列数据"""
        import csv

        series = []
        date_format = "%Y-%m-%d" if grain == "daily" else "%Y-%m-%d %H:%M:%S"

        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_date_str = row.get("date", "")
                    row_date = parse_date(row_date_str)
                    if row_date is None:
                        continue

                    if start_date <= row_date <= end_date:
                        value_str = row.get(value_field, "")
                        if value_str:
                            try:
                                value = float(value_str)
                                series.append({
                                    "date": row_date.strftime(date_format),
                                    "value": value,
                                    "timestamp": row_date
                                })
                            except (ValueError, TypeError):
                                continue

            series.sort(key=lambda x: x["timestamp"])
            return series

        except Exception as e:
            logger.error(f"加载序列数据失败: {e}")
            return []
    
    def load_factor_series(self, factor: FactorConfig, start: str, end: str,
                          grain: str = "daily") -> List[Dict[str, Any]]:
        """
        加载因子序列

        Args:
            factor: 因子配置
            start: 开始日期
            end: 结束日期
            grain: 数据粒度

        Returns:
            因子序列列表，每个元素包含 {date, value}
        """
        # 事件因子特殊处理
        if factor.type == "discrete":
            return []  # 事件因子在L2中处理

        if not factor.data_source:
            logger.warning(f"因子 {factor.id} 没有数据源配置")
            return []

        # 确定数据文件
        data_path = self.data_dir / "history" / grain / factor.data_source
        if not data_path.exists():
            logger.warning(f"因子数据文件不存在: {data_path}")
            return []

        # 解析日期
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        date_format = "%Y-%m-%d" if grain == "daily" else "%Y-%m-%d %H:%M:%S"

        try:
            # 使用共享方法加载特定字段
            series = self._load_series_with_field(
                data_path, factor.data_field, start_date, end_date, grain
            )

            logger.info(f"加载因子序列: {factor.id} {len(series)} 个数据点")
            return series

        except CSVLoaderError as e:
            logger.error(f"加载因子序列 {factor.id} 失败: {e}")
            return []
        except Exception as e:
            logger.error(f"加载因子序列 {factor.id} 失败: {e}")
            return []


class StatisticalAnalyzer:
    """统计分析器：计算相关性、贡献度等指标"""
    
    @staticmethod
    def align_series(price_series: List[Dict], factor_series: List[Dict]) -> Tuple[List[float], List[float]]:
        """
        对齐价格序列和因子序列（按时间戳匹配）
        
        Returns:
            (aligned_prices, aligned_factors)
        """
        aligned_prices = []
        aligned_factors = []
        
        # 创建价格序列的时间戳映射
        price_dict = {item["date"]: item["value"] for item in price_series}
        
        for factor_item in factor_series:
            date = factor_item["date"]
            if date in price_dict:
                aligned_prices.append(price_dict[date])
                aligned_factors.append(factor_item["value"])
        
        if len(aligned_prices) < 2:
            logger.warning(f"对齐后的数据点不足: {len(aligned_prices)} 个")
        
        return aligned_prices, aligned_factors
    
    @staticmethod
    def calculate_pearson_correlation(x: List[float], y: List[float]) -> float:
        """
        计算Pearson相关系数
        
        Args:
            x: 变量X序列
            y: 变量Y序列
            
        Returns:
            Pearson相关系数r，范围[-1, 1]
        """
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        try:
            n = len(x)
            
            # 计算均值
            mean_x = sum(x) / n
            mean_y = sum(y) / n
            
            # 计算协方差和标准差
            covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
            std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
            std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
            
            # 避免除零
            if std_x == 0 or std_y == 0:
                return 0.0
            
            # 计算相关系数
            r = covariance / (std_x * std_y)
            
            # 限制在[-1, 1]范围内
            return max(-1.0, min(1.0, r))
            
        except Exception as e:
            logger.error(f"计算Pearson相关系数失败: {e}")
            return 0.0
    
    @staticmethod
    def calculate_factor_delta(factor_series: List[Dict]) -> float:
        """
        计算因子变动幅度（标准化）
        
        Args:
            factor_series: 因子序列
            
        Returns:
            标准化变动幅度 ΔF
        """
        if len(factor_series) < 2:
            return 0.0
        
        values = [item["value"] for item in factor_series]
        
        try:
            # 计算变动幅度
            start_value = values[0]
            end_value = values[-1]
            absolute_change = end_value - start_value
            
            # 计算标准差用于标准化
            if len(values) >= 2:
                std_dev = statistics.stdev(values) if len(values) > 1 else abs(values[0])
                if std_dev == 0:
                    std_dev = 1.0  # 避免除零
            else:
                std_dev = 1.0
            
            # 标准化变动幅度
            delta = absolute_change / std_dev
            
            return delta
            
        except Exception as e:
            logger.error(f"计算因子变动幅度失败: {e}")
            return 0.0
    
    @staticmethod
    def calculate_contribution(r: float, delta: float, direction: FactorDirection) -> float:
        """
        计算因子贡献度
        
        公式：贡献度 = |r| × |ΔF| × sign(r × direction_sign)
        
        Args:
            r: Pearson相关系数
            delta: 因子变动幅度
            direction: 因子方向
            
        Returns:
            贡献度分数
        """
        # 方向符号：positive=1, negative=-1
        direction_sign = 1 if direction == FactorDirection.POSITIVE else -1
        
        # 计算贡献度
        contribution = abs(r) * abs(delta) * (1 if r * direction_sign > 0 else -1)
        
        return contribution
    
    @staticmethod
    def normalize_contributions(contributions: Dict[str, float]) -> Dict[str, float]:
        """
        归一化贡献度（转换为百分比）
        
        Args:
            contributions: 原始贡献度字典 {factor_id: contribution}
            
        Returns:
            归一化后的贡献度百分比字典 {factor_id: percentage}
        """
        if not contributions:
            return {}
        
        # 找到最大绝对贡献度
        max_abs = max(abs(c) for c in contributions.values())
        if max_abs == 0:
            return {k: 0.0 for k in contributions.keys()}
        
        # 归一化到百分比
        normalized = {}
        for factor_id, contribution in contributions.items():
            percentage = (contribution / max_abs) * 100
            normalized[factor_id] = round(percentage, 1)
        
        return normalized


def statistical_attribution(target: str, start: str, end: str, 
                           grain: str = "daily", data_dir: str = "data") -> Dict[str, Any]:
    """
    执行统计归因分析
    
    Args:
        target: 品种 "gold" | "silver"
        start: 开始日期 "YYYY-MM-DD"
        end: 结束日期 "YYYY-MM-DD"
        grain: 数据粒度 "daily" | "minutely"
        data_dir: 数据目录路径
        
    Returns:
        统计归因结果
    """
    logger.info(f"开始统计归因: {target} {start}~{end} ({grain})")
    
    # 加载因子配置
    factor_set = load_factor_set(target)
    
    # 初始化数据加载器
    loader = DataLoader(data_dir)
    analyzer = StatisticalAnalyzer()
    
    # 1. 加载价格序列
    price_series = loader.load_price_series(target, start, end, grain)
    if not price_series:
        raise ValueError(f"无法加载 {target} 的价格序列")
    
    # 计算价格变动
    price_values = [item["value"] for item in price_series]
    price_start = price_values[0] if price_values else 0
    price_end = price_values[-1] if price_values else 0
    price_change = price_end - price_start
    price_change_pct = (price_change / price_start * 100) if price_start != 0 else 0
    
    # 2. 分析每个因子
    driver_ranking = []
    contributions = {}
    
    for factor in factor_set.factors:
        # 跳过事件因子（在L2中处理）
        if factor.type == "discrete":
            continue
        
        # 加载因子序列
        factor_series = loader.load_factor_series(factor, start, end, grain)
        if not factor_series:
            logger.warning(f"因子 {factor.id} 无有效数据")
            continue
        
        # 对齐序列
        aligned_prices, aligned_factors = analyzer.align_series(price_series, factor_series)
        if len(aligned_prices) < 2:
            logger.warning(f"因子 {factor.id} 对齐后数据点不足: {len(aligned_prices)}")
            continue
        
        # 计算指标
        r = analyzer.calculate_pearson_correlation(aligned_prices, aligned_factors)
        delta = analyzer.calculate_factor_delta(factor_series)
        contribution = analyzer.calculate_contribution(r, delta, factor.direction)
        
        # 记录贡献度
        contributions[factor.id] = contribution
        
        # 构建因子详情
        factor_detail = {
            "factor": factor.id,
            "name": factor.name,
            "contribution_raw": round(contribution, 3),
            "r": round(r, 3),
            "delta": round(delta, 3),
            "direction": factor.direction.value,
            "data_points": len(aligned_prices),
            "factor_start": factor_series[0]["value"] if factor_series else None,
            "factor_end": factor_series[-1]["value"] if factor_series else None,
            "factor_change": factor_series[-1]["value"] - factor_series[0]["value"] if len(factor_series) >= 2 else 0
        }
        
        driver_ranking.append(factor_detail)
    
    # 3. 归一化贡献度
    normalized = analyzer.normalize_contributions(contributions)
    
    # 更新driver_ranking中的贡献度百分比
    for item in driver_ranking:
        factor_id = item["factor"]
        if factor_id in normalized:
            item["contribution_pct"] = normalized[factor_id]
    
    # 4. 按贡献度排序
    driver_ranking.sort(key=lambda x: abs(x.get("contribution_pct", 0)), reverse=True)
    
    # 5. 生成详细描述
    for item in driver_ranking:
        factor_id = item["factor"]
        factor_name = item["name"]
        contribution_pct = item.get("contribution_pct", 0)
        r = item["r"]
        delta = item["delta"]
        factor_start = item.get("factor_start")
        factor_end = item.get("factor_end")
        
        # 生成描述文本
        detail = f"{factor_name}"
        if factor_start is not None and factor_end is not None:
            change = factor_end - factor_start
            change_pct = (change / factor_start * 100) if factor_start != 0 else 0
            direction = "涨" if change > 0 else "跌"
            detail += f" 从 {factor_start:.2f} {direction}至 {factor_end:.2f} ({change_pct:+.1f}%)"
        
        if abs(r) > 0.3:
            correlation_type = "正相关" if r > 0 else "负相关"
            detail += f"，与价格{correlation_type}较强 (r={r:.2f})"
        
        item["detail"] = detail
    
# 6. 构建结果（确保可序列化）
        # 清理价格序列中的datetime对象
        serializable_price_series = []
        for item in price_series:
            serializable_item = {
                "date": item["date"],
                "value": item["value"]
            }
            serializable_price_series.append(serializable_item)
        
        result = {
            "target": target,
            "target_name": factor_set.name,
            "period": {
                "start": start,
                "end": end,
                "grain": grain
            },
            "price_change": {
                "from": round(price_start, 2),
                "to": round(price_end, 2),
                "absolute": round(price_change, 2),
                "pct": round(price_change_pct, 2)
            },
            "driver_ranking": driver_ranking,
            "price_series": serializable_price_series,  # 用于L2事件匹配
            "statistics": {
                "total_factors_analyzed": len(driver_ranking),
                "effective_factors": len([d for d in driver_ranking if abs(d.get("r", 0)) > 0.3]),
                "dominant_factor": driver_ranking[0]["factor"] if driver_ranking else None,
                "dominant_contribution": driver_ranking[0].get("contribution_pct", 0) if driver_ranking else 0
            }
        }
    
    logger.info(f"统计归因完成: {len(driver_ranking)} 个因子分析完成")
    return result


if __name__ == "__main__":
    # 测试代码
    import sys
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("测试统计归因模块...")
    
    try:
        result = statistical_attribution(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            grain="daily",
            data_dir="data"
        )
        
        print(f"\n归因结果:")
        print(f"品种: {result['target_name']}")
        print(f"区间: {result['period']['start']} ~ {result['period']['end']}")
        print(f"价格变动: {result['price_change']['from']} → {result['price_change']['to']} ({result['price_change']['pct']}%)")
        
        print(f"\n驱动因子排名:")
        for i, driver in enumerate(result['driver_ranking']):
            print(f"{i+1}. {driver['name']}: 贡献 {driver.get('contribution_pct', 0)}%, r={driver['r']}, Δ={driver['delta']}")
        
    except ValueError as e:
        print(f"数据错误: {e}")
    except CSVLoaderError as e:
        print(f"CSV加载错误: {e}")
    except Exception as e:
        print(f"测试失败: {e}")