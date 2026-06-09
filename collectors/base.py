#!/usr/bin/env python3
"""
采集器基类 — V1 简化版

改动 vs V0:
  - 去掉文件锁（不再需要并发写 dashboard_data.json）
  - 采集器只负责 fetch + parse，不直接写文件
  - run() 返回结构化 dict，由 run.py 统一合并写入
  - 保持与旧代码的最小兼容

每个采集器实现:
  def collect(self) -> dict | None:
      ...
      return {"snapshot": {key: value_dict, ...}, "history": [{"file": ..., "row": ...}]}
"""

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
CST = timezone(timedelta(hours=8))


def setup_logger(name: str) -> logging.Logger:
    """配置统一日志"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fh = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)
    return logger


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def today_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


class BaseCollector:
    """采集器基类 — V1 简化版"""

    def __init__(self, name: str):
        self.name = name
        self.logger = setup_logger(name)

    def collect(self) -> dict | None:
        """
        采集主入口 — 子类必须实现。

        Returns:
            dict: {
                "snapshot": {snapshot_key: value_dict, ...},  # 合并到 dashboard_data.json
                "history": [                                    # 可选，追加到 CSV
                    {"file": "relative/path.csv", "row": {...}, "grain": "minutely|daily"}
                ]
            }
            None: 采集失败
        """
        raise NotImplementedError

    def _now(self) -> str:
        return now_cst()

    def _today(self) -> str:
        return today_cst()
