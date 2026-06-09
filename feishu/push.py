"""
feishu/push.py — 飞书主动推送

通过飞书自定义机器人 Webhook 向群聊发送消息。
零外部依赖（只用标准库）。

用法：
    python -m feishu.push              # 测试推送
"""

import json
import time
import hmac
import hashlib
import base64
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import WEBHOOK_URL, SECRET, DATA_DIR

logger = logging.getLogger("feishu.push")
TZ = timezone(timedelta(hours=8))


# ════════════════════════════════════════════════════════════════
#  底层发送
# ════════════════════════════════════════════════════════════════

def _sign(timestamp: int, secret: str) -> str:
    """HMAC-SHA256 签名"""
    string_to_sign = f"{timestamp}\n{secret}"
    return base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()


def send_message(payload: dict, msg_type: str = "interactive",
                 webhook_url: str = "", secret: str = "") -> bool:
    """
    发送消息到飞书群聊。

    Args:
        payload: 消息内容
        msg_type: "interactive" | "post" | "text"
        webhook_url: 覆盖默认 URL
        secret: 覆盖默认 secret

    Returns:
        True 成功，False 失败
    """
    url = webhook_url or WEBHOOK_URL
    sec = secret or SECRET

    if not url:
        logger.warning("WEBHOOK_URL 未配置，跳过推送")
        return False

    body = {"msg_type": msg_type, "content": payload}
    if sec:
        ts = int(time.time())
        body["timestamp"] = str(ts)
        body["sign"] = _sign(ts, sec)

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 0:
            logger.info("推送成功: %s", msg_type)
            return True
        else:
            logger.error("推送失败: %s — %s", result.get("code"), result.get("msg"))
            return False
    except Exception as e:
        logger.error("推送异常: %s", e)
        return False


# ════════════════════════════════════════════════════════════════
#  数据读取
# ════════════════════════════════════════════════════════════════

def _read_json(*parts) -> dict:
    path = DATA_DIR.joinpath(*parts)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ════════════════════════════════════════════════════════════════
#  推送内容构造
# ════════════════════════════════════════════════════════════════

def _val(d, key, fallback="--"):
    v = d.get(key, {})
    if isinstance(v, dict):
        return v.get("value", fallback)
    return v if v is not None else fallback


# ════════════════════════════════════════════════════════════════
#  场景 1：早报卡片
# ════════════════════════════════════════════════════════════════

def push_morning_brief() -> bool:
    """早报卡片 — 每日开盘前推送"""
    snapshot = _read_json("current", "dashboard_data.json")
    factors = _read_json("factors", "current_factors.json")

    now = datetime.now(TZ).strftime("%m/%d %H:%M")

    gold = _val(snapshot, "gold_price")
    silver = _val(snapshot, "silver_price")
    ratio = _val(snapshot, "gold_silver_ratio")
    tips = _val(snapshot.get("tips_10y", {}), "value", "--")
    dxy = _val(snapshot.get("dxy", {}), "value", "--")
    vix = _val(snapshot.get("vix", {}), "value", "--")
    us10y = _val(snapshot.get("treasury_10y", {}), "value", "--")

    # 事件摘要
    event_data = snapshot.get("events", {})
    active_s = event_data.get("active_s", []) if isinstance(event_data, dict) else []
    event_lines = "\n".join(f"🔴 {e}" for e in active_s[:3]) if active_s else "今日无重大事件"

    # 综合方向（从因子信号估算）
    direction = "—"
    if factors:
        f = factors.get("factors", {})
        bullish = sum(
            v.get("data", {}).get("signals", {}).get("mid", {}).get("strength", 0)
            for v in f.values()
            if v.get("data", {}).get("signals", {}).get("mid", {}).get("direction") == "bullish"
        )
        bearish = sum(
            v.get("data", {}).get("signals", {}).get("mid", {}).get("strength", 0)
            for v in f.values()
            if v.get("data", {}).get("signals", {}).get("mid", {}).get("direction") == "bearish"
        )
        if bullish > bearish * 1.5:
            direction = "偏多 ↑"
        elif bearish > bullish * 1.5:
            direction = "偏空 ↓"
        else:
            direction = "中性 —"

    content = (
        f"**贵金属早报 | {now}**\n\n"
        f"**行情速览**\n"
        f"🥇 黄金: {gold}  |  🥈 白银: {silver}  |  金银比: {ratio}\n\n"
        f"**核心指标**\n"
        f"TIPS: {tips}  |  DXY: {dxy}  |  VIX: {vix}  |  US10Y: {us10y}\n\n"
        f"**宏观判断**: {direction}\n\n"
        f"**今日关注**\n{event_lines}"
    )

    payload = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🌅 贵金属早报 {datetime.now(TZ).strftime('%m/%d')}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": content},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "数据: gold-api / FRED / Yahoo / 金十  |  FuturesAI"}]},
        ],
    }

    return send_message(payload)


# ════════════════════════════════════════════════════════════════
#  场景 2：异动预警
# ════════════════════════════════════════════════════════════════

def push_anomaly_alert(title: str, indicator: str, current_value: str,
                       threshold: str, direction: str, detail: str = "") -> bool:
    """
    异动预警。

    Args:
        title: 预警标题
        indicator: 指标名
        current_value: 当前值
        threshold: 阈值
        direction: "up" / "down"
        detail: 补充说明
    """
    color = "red" if direction == "up" else "yellow"
    icon = "🚨" if direction == "up" else "⚠️"

    content = (
        f"**{title}**\n\n"
        f"指标: {indicator}\n"
        f"当前值: **{current_value}** ({'↑ 向上' if direction == 'up' else '↓ 向下'}突破 {threshold})\n\n"
        f"{detail}"
    )

    payload = {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"{icon} 异动预警"}, "template": color},
        "elements": [
            {"tag": "markdown", "content": content},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"触发: {datetime.now(TZ).strftime('%H:%M:%S')}  |  FuturesAI 监控"}]},
        ],
    }

    return send_message(payload)


# ════════════════════════════════════════════════════════════════
#  场景 3：事件提醒
# ════════════════════════════════════════════════════════════════

def push_event_reminder(event_name: str, event_time: str,
                        expected_impact: str, detail: str = "") -> bool:
    """事件提醒"""
    impact_color = "red" if expected_impact == "高" else "yellow"

    content = (
        f"**{event_name}**\n\n"
        f"⏰ 时间: {event_time}\n"
        f"⚡ 预期影响: **{expected_impact}**\n\n"
        f"{detail}"
    )

    payload = {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "📅 事件提醒"}, "template": impact_color},
        "elements": [
            {"tag": "markdown", "content": content},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"提醒: {datetime.now(TZ).strftime('%H:%M')}  |  FuturesAI"}]},
        ],
    }

    return send_message(payload)


# ════════════════════════════════════════════════════════════════
#  辅助：简易文本推送
# ════════════════════════════════════════════════════════════════

def push_text(text: str) -> bool:
    """纯文本消息"""
    return send_message({"text": text}, msg_type="text")


# ════════════════════════════════════════════════════════════════
#  测试入口
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if not WEBHOOK_URL:
        print("❌ 请先设置环境变量 FEISHU_BOT_WEBHOOK_URL")
        print("   在飞书群聊中添加自定义机器人后获取")
        exit(1)

    print("=" * 50)
    print("飞书推送测试")
    print("=" * 50)

    print("\n[1/3] 早报...")
    ok = push_morning_brief()
    print(f"  → {'✅' if ok else '❌'} 成功")

    print("\n[2/3] 异动预警...")
    ok = push_anomaly_alert(
        title="白银持仓量异动",
        indicator="沪银 OI",
        current_value="289,320 (+17.8%)",
        threshold="10% 日增幅",
        direction="up",
        detail="沪银持仓量日增幅 +17.8%，空头入场迹象明显。",
    )
    print(f"  → {'✅' if ok else '❌'} 成功")

    print("\n[3/3] 事件提醒...")
    ok = push_event_reminder(
        event_name="美国 5 月 CPI 数据发布",
        event_time="6/12 20:30",
        expected_impact="高",
        detail="预期 CPI 同比 +3.4%。若超预期可能利空金银。",
    )
    print(f"  → {'✅' if ok else '❌'} 成功")

    print("\n" + "=" * 50)
