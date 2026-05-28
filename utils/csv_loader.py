"""CSV 数据加载工具模块

提供统一的 CSV 文件读取、日期解析、数值提取功能。
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from .date_parser import parse_date, get_date_column

logger = logging.getLogger(__name__)

# 数值列候选名（按优先级排序）
VALUE_CANDIDATES = [
    "value", "close", "Close", "CLOSE",
    "gold_usd", "silver_usd", "ratio", "ratio_close",
    "10yr", "2yr", "30yr",  # Treasury
    "10 Yr", "2 Yr", "30 Yr",  # Treasury 原始列名
    "price", "Price", "PRICE",
]

# 默认最大返回数据点数
DEFAULT_MAX_POINTS = 200


class CSVLoaderError(Exception):
    """CSV 加载错误基类"""
    pass


class CSVFileNotFoundError(CSVLoaderError):
    """CSV 文件不存在错误"""
    pass


class CSVFormatError(CSVLoaderError):
    """CSV 格式错误"""
    pass


class CSVEmptyError(CSVLoaderError):
    """CSV 文件为空错误"""
    pass


def find_value_column(fieldnames: List[str], indicator: str = "") -> Optional[str]:
    """查找数值列名

    Args:
        fieldnames: CSV 字段名列表
        indicator: 指标名称（用于匹配特定列）

    Returns:
        数值列名或 None
    """
    if not fieldnames:
        return None

    # 创建候选列表（优先匹配 indicator）
    candidates = VALUE_CANDIDATES.copy()
    if indicator:
        candidates.insert(0, indicator.lower())
        candidates.insert(0, indicator)

    # 查找第一个匹配的列
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate

    # Fallback: 返回第一个非日期列
    for name in fieldnames:
        lower = name.lower()
        if lower not in ["date", "timestamp", "time", "datetime"]:
            return name

    return None


def extract_value(row: Dict[str, str], value_column: Optional[str] = None,
                  fieldnames: Optional[List[str]] = None) -> Optional[float]:
    """从行中提取数值

    Args:
        row: CSV 行数据
        value_column: 指定的数值列名
        fieldnames: 所有字段名（用于自动查找）

    Returns:
        浮点数值或 None
    """
    # 如果指定了列名，优先使用
    if value_column and value_column in row:
        try:
            return float(row[value_column])
        except (ValueError, TypeError):
            pass

    # 自动查找数值列
    if fieldnames:
        col = find_value_column(fieldnames)
        if col and col in row:
            try:
                return float(row[col])
            except (ValueError, TypeError):
                pass

    # Fallback: 尝试第一个非空数值列
    for k, v in row.items():
        if k.lower() in ["date", "timestamp", "time"]:
            continue
        try:
            return float(v)
        except (ValueError, TypeError):
            continue

    return None


def load_csv_data(
    csv_path: Path,
    days: int = 90,
    max_points: int = DEFAULT_MAX_POINTS,
    date_filter: Optional[Callable[[datetime], bool]] = None
) -> List[Dict[str, Any]]:
    """加载 CSV 数据

    Args:
        csv_path: CSV 文件路径
        days: 回溯天数（None 表示不限制）
        max_points: 最大返回点数
        date_filter: 额外的日期过滤函数

    Returns:
        数据点列表，每个点为 {"date": "YYYY-MM-DD", "value": float}

    Raises:
        CSVFileNotFoundError: 文件不存在
        CSVEmptyError: 文件为空或没有有效数据
        CSVFormatError: 格式错误
    """
    if not csv_path.exists():
        raise CSVFileNotFoundError(f"CSV 文件不存在: {csv_path}")

    results = []
    cutoff = datetime.now() - timedelta(days=days) if days else None

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames

            if not fieldnames:
                raise CSVEmptyError("CSV 文件没有字段名")

            date_col = get_date_column(fieldnames)
            value_col = find_value_column(fieldnames)

            for row in reader:
                # 解析日期
                date_str = row.get(date_col, "") if date_col else ""
                if not date_str:
                    continue

                dt = parse_date(date_str)
                if not dt:
                    continue

                # 日期过滤
                if cutoff and dt < cutoff:
                    continue
                if date_filter and not date_filter(dt):
                    continue

                # 提取数值
                val = extract_value(row, value_col, fieldnames)
                if val is None:
                    continue

                results.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "value": val,
                })

    except UnicodeDecodeError as e:
        raise CSVFormatError(f"文件编码错误: {e}")
    except csv.Error as e:
        raise CSVFormatError(f"CSV 解析错误: {e}")

    if not results:
        raise CSVEmptyError("没有找到有效数据")

    # 限制返回数量
    if len(results) > max_points:
        results = results[-max_points:]

    return results


def get_csv_time_range(csv_path: Path) -> Dict[str, Any]:
    """获取 CSV 文件的时间范围

    Args:
        csv_path: CSV 文件路径

    Returns:
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "count": int}
    """
    try:
        data = load_csv_data(csv_path, days=None, max_points=100000)
        dates = [d["date"] for d in data if d.get("date")]

        if not dates:
            return {"start": "无有效日期", "end": "无有效日期", "count": 0}

        dates.sort()
        return {
            "start": dates[0],
            "end": dates[-1],
            "count": len(dates)
        }

    except CSVLoaderError as e:
        logger.warning(f"读取 CSV 时间范围失败 {csv_path}: {e}")
        return {"start": "读取失败", "end": "读取失败", "count": 0}
    except Exception as e:
        logger.warning(f"读取 CSV 时间范围失败 {csv_path}: {e}")
        return {"start": "读取失败", "end": "读取失败", "count": 0}
