#!/usr/bin/env python3
"""
数据采集器基类 — V2 整合版
所有采集器继承此类，统一处理：日志、重试、快照写入、历史CSV追加

V2 变更：
  - 路径从 config.py 动态解析，移除硬编码
  - 支持通过 -m collectors.xxx 直接运行
"""

import json
import csv
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 项目根目录（通过 config.py 解析，或通过文件位置回溯）
try:
    from config import PROJECT_ROOT
except ImportError:
    # fallback: 从所在目录向上回溯
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

SNAPSHOT_FILE = PROJECT_ROOT / "data/current/dashboard_data.json"
SNAPSHOT_LOCK = SNAPSHOT_FILE.with_suffix(".json.lock")
LOG_DIR = PROJECT_ROOT / "logs"
CST = timezone(timedelta(hours=8))


# ─── 真正的排他文件锁 ────────────────────────────────────
# 使用 os.open(O_CREAT | O_EXCL) 实现真正的互斥锁
# 所有写 dashboard_data.json 的地方必须使用 SNAPSHOT_LOCK

def acquire_exclusive_lock(lock_path: Path, timeout: float = 5.0,
                           stale_after: float = 10.0) -> bool:
    """
    获取真正排他的文件锁（os.open + O_CREAT | O_EXCL）

    Args:
        lock_path: 锁文件路径
        timeout: 等待超时（秒）
        stale_after: 锁文件存活超过此秒数视为死锁，自动打破

    Returns:
        是否成功获取锁
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # 死锁检测：如果锁文件存在且超过阈值，视为死锁
            if lock_path.exists():
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_after:
                    lock_path.unlink(missing_ok=True)
                    continue

            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL, mode=0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.1)
        except (OSError, PermissionError):
            time.sleep(0.1)
    return False


def release_exclusive_lock(lock_path: Path):
    """释放排他文件锁"""
    try:
        if lock_path.exists():
            lock_path.unlink(missing_ok=True)
    except (OSError, PermissionError):
        pass


# 快捷方式：为 snapshot（dashboard_data.json）提供锁操作
# 保持向后兼容，同时让 rss_news / monitor 也可用

def _acquire_snapshot_lock(timeout: float = 3.0) -> bool:
    """获取快照文件锁（兼容旧调用方）"""
    return acquire_exclusive_lock(SNAPSHOT_LOCK, timeout=timeout)


def _release_snapshot_lock():
    """释放快照文件锁（兼容旧调用方）"""
    release_exclusive_lock(SNAPSHOT_LOCK)


def setup_logger(name: str) -> logging.Logger:
    """配置统一日志（防重复添加）"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 防止重复添加处理器
    if logger.handlers:
        return logger

    # 文件日志
    fh = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    # 控制台日志
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    return logger


def now_cst() -> str:
    """当前时间 CST 格式"""
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def today_cst() -> str:
    """当天日期 CST"""
    return datetime.now(CST).strftime("%Y-%m-%d")


class BaseCollector:
    """采集器基类"""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.logger = setup_logger(source_id)
        self._snapshot_lock = False  # 简化防并发

    def _now(self) -> str:
        """当前时间 CST 格式，用于 updated_at 字段"""
        return now_cst()

    # ---- 子类必须实现 ----

    def fetch(self):
        """从数据源获取原始数据"""
        raise NotImplementedError

    def parse(self, raw_data):
        """解析原始数据为结构化dict
        必须返回: {"snapshot_key": value_dict, "history_row": {...}, "grain": "minutely|daily"}
        """
        raise NotImplementedError

    # ---- 通用写入方法 ----

    def write_snapshot(self, snapshot: dict):
        """更新快照文件中的字段（带文件锁，防并发脏写）"""

        if not _acquire_snapshot_lock(timeout=3.0):
            self.logger.warning("无法获取快照锁，跳过 snapshot 更新")
            return

        try:
            # 确保所有值都是可JSON序列化的
            safe = {}
            for k, v in snapshot.items():
                if isinstance(v, (str, int, float, bool, list, dict)):
                    safe[k] = v
                else:
                    safe[k] = str(v)

            # 读全文件（在锁保护下，不会被其它采集器干扰）
            if SNAPSHOT_FILE.exists():
                with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}

            data.update(safe)
            data["global_updated_at"] = now_cst()

            # 原子写入：临时文件 → 重命名替换
            tmp = SNAPSHOT_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(SNAPSHOT_FILE)

            self.logger.info(f"Snapshot updated: {list(safe.keys())}")
        except Exception as e:
            self.logger.error(f"write_snapshot failed: {e}")
            # 清理临时文件（如有）
            tmp = SNAPSHOT_FILE.with_suffix(".json.tmp")
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        finally:
            _release_snapshot_lock()

    def write_history_csv(self, csv_path: Path, row: dict):
        """追加一行到历史CSV文件（自动创建表头）"""
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        exists = csv_path.exists()
        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                if not exists:
                    writer.writeheader()
                writer.writerow(row)
            self.logger.info(f"History appended to {csv_path.name}")
        except Exception as e:
            self.logger.error(f"write_history_csv failed: {e}")

    # ---- 主入口 ----

    def run(self):
        """采集主流程"""
        self.logger.info(f"=== {self.source_id} start ===")
        failed = False
        raw = None

        try:
            raw = self.fetch()
        except Exception as e:
            self.logger.error(f"fetch failed: {e}")
            failed = True

        if raw is not None:
            try:
                result = self.parse(raw)
                if result:
                    snapshot_key = result.get("snapshot_key")
                    snapshot_value = result.get("snapshot_value", {})
                    history_row = result.get("history_row")
                    grain = result.get("grain", "daily")

                    # 写快照
                    if snapshot_key and snapshot_value:
                        self.write_snapshot({snapshot_key: snapshot_value})

                    # 写额外快照（如有多个字段要更新）
                    extra = result.get("extra_snapshots", [])
                    for key, val in extra:
                        self.write_snapshot({key: val})

                    # 写历史
                    if history_row:
                        if grain == "minutely":
                            csv_file = PROJECT_ROOT / "data/history/minutely" / f"{self.source_id}_minutely.csv"
                            ts = now_cst()
                            ordered = {"timestamp": ts}
                            ordered.update(history_row)
                            history_row = ordered
                        else:
                            csv_file = PROJECT_ROOT / "data/history/daily" / f"{self.source_id}.csv"
                            ordered = {"date": today_cst()}
                            ordered.update(history_row)
                            history_row = ordered

                        self.write_history_csv(csv_file, history_row)

                    self.logger.info(f"✅ {self.source_id} completed")
                    return True
            except Exception as e:
                self.logger.error(f"parse/write failed: {e}", exc_info=True)
                failed = True

        if failed:
            self.logger.warning(f"⚠️ {self.source_id} failed - snapshot not overwritten")
        return not failed
