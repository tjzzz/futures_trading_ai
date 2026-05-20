"""
事件监控器 — 阈值检测 + 推送

核心逻辑：
  1. 采集器写文件后可选的 HTTP POST 通知 event_monitor
  2. event_monitor 收到通知后对比阈值
  3. S 级 → 飞书 @所有人（或日志告警）
  4. A 级 → 飞书私信（或日志告警）
  5. 同指标同方向 24h 内不重复推送（除非升级）

依赖：
  - data/current/dashboard_data.json（最新快照）
  - event_monitor/thresholds.py（阈值定义）

配置：
  在 config.py 或环境变量中设置：
    EVENT_MONITOR_ENABLED=true|false（默认 true）
    EVENT_MONITOR_INTERVAL=3600（检查间隔，秒）
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone

from config import PROJECT_ROOT, DATA_DIR
from event_monitor.thresholds import THRESHOLDS
from collectors.base_collector import acquire_exclusive_lock, release_exclusive_lock


logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=8))

# ─── 状态文件 ──────────────────────────────────────────────
STATE_FILE = PROJECT_ROOT / "data" / "events" / "monitor_state.json"
LOCK_FILE = PROJECT_ROOT / "data" / "events" / "monitor_state.lock"


# ─── 文件锁（跨平台，兼容 iCloud/网络文件系统） ────────────

def _acquire_lock(timeout: float = 5.0) -> bool:
    """尝试获取排他文件锁（委托 base_collector 的 os.open O_EXCL 实现）"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    return acquire_exclusive_lock(LOCK_FILE, timeout=timeout, stale_after=10.0)


def _release_lock():
    """释放文件锁"""
    release_exclusive_lock(LOCK_FILE)


# ─── 工具函数 ──────────────────────────────────────────────

def _safe_float_get(data: Dict, path: str) -> Optional[float]:
    """
    按点号路径从嵌套 dict 中安全读取 float 值
    示例: "treasury.10yr" → data["treasury"]["10yr"]
           "dxy.value"    → data["dxy"]["value"]
           "__spread__"   → 特殊计算标记
           "__change__"   → 特殊计算标记
    """
    if path == "__spread__":
        # 计算 2Y-10Y 利差
        t10 = _safe_float_get(data, "treasury.10yr")
        t2 = _safe_float_get(data, "treasury.2yr")
        if t10 is not None and t2 is not None:
            return round(t10 - t2, 2)
        return None
    if path == "__change__":
        # 黄金日内波动 — 由于只有 daily CSV，暂不实现实时日内波动计算
        # 留作扩展
        logger.warning("__change__ 未实现，跳过黄金日内波动检测")
        return None

    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    # 自动解包 {"value": X}
    if isinstance(current, dict) and "value" in current:
        current = current["value"]
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def _event_fingerprint(threshold_key: str, direction: str) -> str:
    """生成事件指纹（用于去重）"""
    raw = f"{threshold_key}|{direction}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _load_state() -> Dict[str, Any]:
    """加载监控状态"""
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "version": "1",
            "last_check": None,
            "fired_events": {},  # fingerprint → {level, first_fired, last_fired, count}
        }


def _save_state(state: Dict[str, Any]):
    """保存监控状态（带文件锁保护）"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _acquire_lock(timeout=3.0):
        logger.warning("无法获取文件锁，跳过状态写入")
        return
    try:
        # 原子写入：写临时文件 → 重命名替换
        tmp = STATE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp.replace(STATE_FILE)
    except Exception as e:
        logger.error(f"保存状态失败: {e}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    finally:
        _release_lock()


# ─── 检查逻辑 ──────────────────────────────────────────────

def _check_threshold(value: float, threshold_def: Dict) -> Optional[int]:
    """
    检查值是否触发阈值
    返回: None（未触发）| 0（warn 级别）| 1（crisis 级别）
    """
    warn = threshold_def["warn"]
    crisis = threshold_def["crisis"]
    direction = threshold_def["direction"]

    if direction == "above":
        if value >= crisis:
            return 1
        if value >= warn:
            return 0
    elif direction == "below":
        if value <= crisis:
            return 1
        if value <= warn:
            return 0

    return None


# ─── 消息格式化 ──────────────────────────────────────────────

def format_event_message(event: Dict[str, Any]) -> str:
    """格式化事件为可读文本"""
    level_icon = "🔴" if event["level"] == "crisis" else "🟡"
    lines = [
        f"{level_icon} **{event['name']}** ({'S' if event['level'] == 'crisis' else 'A'}级)",
        f"  当前值: {event['current_value']}",
        f"  阈值: {event['threshold']}",
        f"  说明: {event['description']}",
        f"  象限: {event['quadrant']}",
        f"  触发时间: {event['timestamp']}",
    ]
    return "\n".join(lines)


def format_digest(events: List[Dict[str, Any]]) -> str:
    """格式化事件摘要"""
    if not events:
        return "✅ 当前无阈值越界事件"

    lines = ["## 📊 事件监控摘要\n"]
    s_events = [e for e in events if e["level"] == "crisis"]
    a_events = [e for e in events if e["level"] == "warn"]

    if s_events:
        lines.append(f"### 🔴 S 级事件 ({len(s_events)})")
        for e in s_events:
            lines.append(format_event_message(e))
        lines.append("")

    if a_events:
        lines.append(f"### 🟡 A 级事件 ({len(a_events)})")
        for e in a_events:
            lines.append(format_event_message(e))
        lines.append("")

    return "\n".join(lines)


# ─── 主监控器 ──────────────────────────────────────────────

class EventMonitor:
    """
    事件监控器

    用法：
        monitor = EventMonitor()
        events = monitor.check()     # 执行检测
        monitor.push(events)         # 推送（当前为日志）
    """

    def __init__(self):
        self.state = _load_state()
        self._suppress_repeat = True  # 24h 防重复

    def check(self, snapshot: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        执行一次阈值检测

        Args:
            snapshot: 可选的数据快照（不传则自动读取）

        Returns:
            新触发的事件列表
        """
        if snapshot is None:
            snapshot = self._read_snapshot()

        if not snapshot:
            logger.warning("无数据快照，跳过检测")
            return []

        now = datetime.now(TZ)
        new_events = []

        for threshold_def in THRESHOLDS:
            value = _safe_float_get(snapshot, threshold_def["data_path"])
            if value is None:
                continue

            trigger_level = _check_threshold(value, threshold_def)
            if trigger_level is None:
                continue  # 未触发

            # 确定级别
            level = "crisis" if trigger_level == 1 else "warn"

            # 生成指纹
            direction = threshold_def["direction"]
            fp = _event_fingerprint(threshold_def["key"], direction)

            # 防重复检查
            if self._suppress_repeat and fp in self.state.get("fired_events", {}):
                fired = self.state["fired_events"][fp]
                last_fired = datetime.fromisoformat(fired["last_fired"])
                # 24h 内不重复（除非升级）
                if now - last_fired < timedelta(hours=24):
                    # 如果当前是 warn 但之前是 crisis，不用重复
                    # 如果当前是 crisis 但之前是 warn → 升级，允许
                    if level == fired.get("level") or (
                        level == "warn" and fired.get("level") == "crisis"
                    ):
                        logger.debug(f"跳过重复事件: {threshold_def['key']} ({fp})")
                        continue

            # 构建事件对象
            event = {
                "key": threshold_def["key"],
                "name": threshold_def["name"],
                "level": level,
                "current_value": value,
                "threshold": threshold_def["crisis"] if level == "crisis" else threshold_def["warn"],
                "unit": threshold_def.get("unit", ""),
                "direction": direction,
                "quadrant": threshold_def.get("quadrant", ""),
                "description": threshold_def["description"],
                "fingerprint": fp,
                "timestamp": now.strftime("%Y-%m-%d %H:%M CST"),
                "bullish_for": threshold_def.get("bullish_for"),
            }

            new_events.append(event)

            # 更新状态
            state_events = self.state.setdefault("fired_events", {})
            if fp in state_events:
                state_events[fp]["last_fired"] = now.isoformat()
                state_events[fp]["count"] += 1
                state_events[fp]["level"] = level
            else:
                state_events[fp] = {
                    "first_fired": now.isoformat(),
                    "last_fired": now.isoformat(),
                    "count": 1,
                    "level": level,
                    "event_name": threshold_def["name"],
                }

        # 更新最后检查时间
        self.state["last_check"] = now.isoformat()
        _save_state(self.state)

        if new_events:
            logger.info(f"检测到 {len(new_events)} 个新事件: "
                        f"{[e['name'] for e in new_events]}")

        return new_events

    def push(self, events: List[Dict[str, Any]]):
        """
        推送事件通知
        当前实现：输出到日志 + 打印到控制台
        飞书集成：TODO（需飞书 API 凭证）
        """
        if not events:
            logger.info("事件监控: 无新事件")
            return

        s_events = [e for e in events if e["level"] == "crisis"]
        a_events = [e for e in events if e["level"] == "warn"]

        # 日志输出
        if s_events:
            logger.warning(f"🔴 S 级事件 ({len(s_events)}): "
                           f"{', '.join(e['name'] for e in s_events)}")
            for e in s_events:
                logger.warning(f"  {e['name']}: {e['current_value']} "
                               f"(阈值: {e['threshold']}{e['unit']})")

        if a_events:
            logger.info(f"🟡 A 级事件 ({len(a_events)}): "
                        f"{', '.join(e['name'] for e in a_events)}")

        # 控制台输出（被 cron 调用时可见）
        print(format_digest(events))

    def get_active_thresholds(self) -> List[Dict[str, Any]]:
        """
        获取当前所有阈值状态
        返回每个阈值定义及其当前值（无需触发检测）
        """
        snapshot = self._read_snapshot()
        results = []
        for td in THRESHOLDS:
            value = _safe_float_get(snapshot, td["data_path"])
            trigger = _check_threshold(value, td) if value is not None else None
            results.append({
                "key": td["key"],
                "name": td["name"],
                "current_value": value,
                "warn": td["warn"],
                "crisis": td["crisis"],
                "direction": td["direction"],
                "triggered": trigger is not None,
                "trigger_level": "crisis" if trigger == 1 else "warn" if trigger == 0 else None,
                "quadrant": td["quadrant"],
            })
        return results

    # ─── 内部方法 ──────────────────────────────────────────

    @staticmethod
    def _read_snapshot() -> Dict[str, Any]:
        """读取当前数据快照"""
        path = DATA_DIR / "current" / "dashboard_data.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取数据快照失败: {e}")
            return {}


# ─── CLI 入口 ──────────────────────────────────────────────

def main():
    """CLI 入口：执行一次检查并推送"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    monitor = EventMonitor()
    events = monitor.check()
    monitor.push(events)

    # 输出摘要
    if not events:
        print("✅ 所有指标在正常范围内")
    else:
        s_count = sum(1 for e in events if e["level"] == "crisis")
        a_count = len(events) - s_count
        print(f"\n📊 触发 {len(events)} 个事件（S: {s_count}, A: {a_count}）")

    # 显示当前所有阈值状态
    print("\n--- 当前阈值状态 ---")
    for t in monitor.get_active_thresholds():
        icon = "🔴" if t["trigger_level"] == "crisis" else "🟡" if t["trigger_level"] == "warn" else "✅"
        print(f"  {icon} {t['name']}: {t['current_value']} "
              f"(warn: {t['warn']}, crisis: {t['crisis']})")


if __name__ == "__main__":
    main()
