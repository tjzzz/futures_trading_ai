"""
飞书命令解析与分发 — V2 架构

从飞书 Webhook JSON 中提取用户消息文本，
匹配 V2 命令前缀并分发到 analysis 引擎。
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone

from config import V2_COMMANDS
from analysis import Analysis
from event_monitor import EventMonitor


TZ = timezone(timedelta(hours=8))


logger = logging.getLogger(__name__)


# 分析引擎缓存（避免每次命令重新创建）
_analysis_engine: Optional[Analysis] = None

def _get_analysis_engine() -> Analysis:
    global _analysis_engine
    if _analysis_engine is None:
        _analysis_engine = Analysis()
    return _analysis_engine


# ─── 命令定义 ──────────────────────────────────────────────
# 与 config.py 保持同步，此处单独引用方便模块内使用
V2_PREFIXES: List[str] = V2_COMMANDS  # ["归因", "趋势", "宏观"]


def extract_user_message(data: Dict[str, Any]) -> str:
    """
    从飞书 Webhook JSON 中提取用户消息纯文本。

    支持两种格式：
    1. 飞书标准事件格式（event.message.content 中的 text）
    2. 简化测试格式（直接传 text 字段）

    Args:
        data: 飞书 webhook body (dict)

    Returns:
        提取到的纯文本，不含 @ 提及部分
    """
    # 格式 1: 标准 Feishu 事件
    event = data.get("event", {})
    message = event.get("message", {})

    if message:
        content = message.get("content", "")
        if isinstance(content, str):
            try:
                content_obj = json.loads(content)
                text = content_obj.get("text", "")
            except (json.JSONDecodeError, TypeError):
                text = content
        elif isinstance(content, dict):
            text = content.get("text", "")
        else:
            text = str(content) if content else ""
    else:
        # 格式 2: 简化格式
        text = data.get("text", data.get("content", ""))

    # 去除 @ 提及
    text = _strip_mentions(text, data)

    return text.strip()


def _strip_mentions(text: str, data: Dict[str, Any]) -> str:
    """
    去除文本中的 @机器人 提及

    飞书群聊中 @ 机器人的格式为:
    - @机器人名称
    - @用户ID (由 mentions 中的 key 字段给出)
    """
    # 从事件中获取 mentions 列表
    mentions = (
        data.get("event", {})
        .get("message", {})
        .get("mentions", [])
    )

    for mention in mentions:
        key = mention.get("key", "")
        name = mention.get("name", "")
        if key:
            text = text.replace(key, "")
        if name:
            text = text.replace(f"@{name}", "")

    return text.strip()


def is_v2_command(text: str) -> bool:
    """
    判断文本是否以 V2 命令前缀开头

    Args:
        text: 用户消息纯文本

    Returns:
        True 如果是 V2 命令
    """
    if not text:
        return False

    text = text.strip()
    # 改为 .startswith 匹配（支持前缀完全匹配）
    return any(text.startswith(prefix) for prefix in V2_COMMANDS)


async def handle_v2_command(text: str) -> Optional[str]:
    """
    处理 V2 命令，返回回复文本

    根据命令前缀分发到 analysis 引擎或 event_monitor 的对应方法。

    Args:
        text: 完整的用户消息文本

    Returns:
        回复文本（Markdown 格式）
    """
    text_stripped = text.strip()

    # 事件相关命令 → event_monitor
    if text_stripped.startswith("事件"):
        return _handle_event_command(text_stripped)

    if text_stripped.startswith("监控"):
        return _handle_monitor_command(text_stripped)

    # 分析相关命令 → analysis 引擎
    engine = _get_analysis_engine()
    return engine.handle_command(text)


def _handle_event_command(text: str) -> str:
    """
    处理事件相关命令

    格式:
        事件        → 查看活跃事件列表
        事件 S      → 仅 S 级事件
        事件 A      → 仅 A 级事件
    """
    from collectors.rss_news import load_events
    import json

    events_data = load_events()
    active = events_data.get("active_events", [])

    # 过滤级别
    parts = text.split()
    level_filter = parts[1].upper() if len(parts) > 1 else None
    if level_filter and level_filter not in ("S", "A"):
        return f"不支持的事件级别: {level_filter}。支持: S, A"

    filtered = []
    if level_filter:
        filtered = [e for e in active if e.get("level") == level_filter]
    else:
        filtered = active

    if not filtered:
        return "当前无活跃事件 ✅" if not level_filter else f"当前无 {level_filter} 级活跃事件"

    lines = [f"## 📋 活跃事件", f"**总数**: {len(filtered)} (S: {len([e for e in active if e['level']=='S'])} / A: {len([e for e in active if e['level']=='A'])})", f""]

    for e in filtered:
        icon = "🔴" if e.get("level") == "S" else "🟡"
        lines.append(f"{icon} **{e.get('level', '?')} | {e.get('title', '')}**")
        summary = e.get("summary", e.get("description", ""))
        if summary:
            lines.append(f"  {summary[:150]}")
        quadrants = e.get("quadrant", [])
        if quadrants:
            lines.append(f"  象限: {', '.join(quadrants)}")
        lines.append("")

    return "\n".join(lines)


def _handle_monitor_command(text: str) -> str:
    """
    处理监控相关命令

    格式:
        监控 status → 查看当前阈值状态
        监控 check  → 执行一次检测
    """
    parts = text.split()
    subcmd = parts[1].lower() if len(parts) > 1 else "status"

    monitor = EventMonitor()

    if subcmd == "check":
        events = monitor.check()
        monitor.push(events)

        if not events:
            return "✅ 阈值检测完成，所有指标正常"

        s_count = sum(1 for e in events if e["level"] == "crisis")
        a_count = len(events) - s_count
        lines = [f"## 📊 事件监控报告",
                 f"**检查时间**: {events[0]['timestamp'] if events else 'N/A'}",
                 f"**触发事件**: {len(events)} (S: {s_count}, A: {a_count})",
                 f""]
        for e in events:
            icon = "🔴" if e["level"] == "crisis" else "🟡"
            lines.append(f"{icon} **{e['name']}**: {e['current_value']}{e.get('unit', '')} (阈值: {e['threshold']}{e.get('unit', '')})")
        return "\n".join(lines)

    elif subcmd == "status":
        thresholds = monitor.get_active_thresholds()
        lines = [f"## 📊 阈值状态总览", f"**检查时间**: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M CST')}", f""]

        triggered = [t for t in thresholds if t.get("triggered")]
        safe = [t for t in thresholds if not t.get("triggered")]

        if triggered:
            lines.append(f"### ⚠️ 已触发 ({len(triggered)})")
            for t in triggered:
                icon = "🔴" if t.get("trigger_level") == "crisis" else "🟡"
                lines.append(f"  {icon} {t['name']}: {t['current_value']}")
            lines.append("")

        lines.append(f"### ✅ 正常 ({len(safe)})")
        for t in safe:
            lines.append(f"  ✅ {t['name']}: {t['current_value']}")
        lines.append("")

        return "\n".join(lines)

    return "监控子命令: status（状态）, check（检测）"
