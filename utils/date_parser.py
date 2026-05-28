"""日期解析工具模块

提供统一的日期解析功能，支持多种日期格式。
"""

from datetime import datetime
from typing import Optional

# 支持的日期格式列表
DATE_FORMATS = [
    "%Y-%m-%d",      # 2026-01-15
    "%Y-%m-%d %H:%M:%S",  # 2026-01-15 14:30:00
    "%Y-%m-%d %H:%M",     # 2026-01-15 14:30
    "%m/%d/%Y",      # 01/15/2026 (Treasury 格式)
    "%m/%d/%Y %H:%M:%S",  # 01/15/2026 14:30:00
    "%Y/%m/%d",      # 2026/01/15
]


def parse_date(date_str: str) -> Optional[datetime]:
    """解析日期字符串，支持多种格式

    Args:
        date_str: 日期字符串

    Returns:
        datetime 对象或 None（解析失败时）
    """
    if not date_str or not isinstance(date_str, str):
        return None

    # 清理字符串
    s = date_str.strip()
    if not s:
        return None

    # 尝试每种格式
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s[:len(fmt) + 10], fmt)
        except ValueError:
            continue

    # 特殊处理：纯日期部分（去掉时间）
    date_part = s.split()[0] if " " in s else s
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(date_part, fmt)
        except ValueError:
            continue

    return None


def format_date(dt: datetime, fmt: str = "%Y-%m-%d") -> str:
    """格式化日期为字符串

    Args:
        dt: datetime 对象
        fmt: 输出格式

    Returns:
        格式化后的日期字符串
    """
    if not dt:
        return ""
    return dt.strftime(fmt)


def get_date_column(fieldnames: list) -> Optional[str]:
    """从字段名列表中识别日期列

    Args:
        fieldnames: CSV 字段名列表

    Returns:
        日期列名或 None
    """
    if not fieldnames:
        return None

    date_candidates = ["date", "timestamp", "Date", "Timestamp", "DATE", "TIMESTAMP"]
    for candidate in date_candidates:
        if candidate in fieldnames:
            return candidate
    return None
