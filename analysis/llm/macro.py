"""
四象限宏观 LLM 分析 — llm 模式

将采集数据组装成结构化 prompt，调用 LLM API 进行综合分析。
输出格式与 rules 模式完全兼容，前端/飞书无缝切换。

需要环境变量（在 config.py 中配置）：
    LLM_API_KEY    — API 密钥
    LLM_API_URL    — OpenAI 兼容 API 地址（默认 https://api.openai.com/v1/chat/completions）
    LLM_MODEL      — 模型名称（默认 gpt-4o）
"""

import json
import logging
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

import requests

from config import LLM_API_KEY, LLM_API_URL, LLM_MODEL


logger = logging.getLogger(__name__)

# ─── Prompt 模板 ──────────────────────────────────────────────

SYSTEM_PROMPT = """你是一位贵金属市场宏观分析师，专注于黄金 (XAU/USD) 和白银 (XAG/USD) 市场分析。

请基于提供的市场数据，按照四象限框架进行综合分析：

## 四象限框架
1. 🟢 货币锚 — 实际利率与美元信用
   - 指标: 10Y/30Y 国债收益率、TIPS 实际利率、DXY 美元指数
   - 高利率 → 压制黄金（持有成本上升）| 美元强势 → 压制黄金

2. 🔵 宏观流动性 — 收益率曲线形态
   - 指标: 2Y-10Y 利差
   - 倒挂 → 衰退预期 → 利多黄金（避险）| 陡峭化 → 宽松预期 → 利多

3. 🟠 风险偏好 — 避险情绪
   - 指标: VIX 恐慌指数、S&P 500、地缘新闻
   - VIX > 25 → 恐慌 → 利多黄金 | VIX < 15 → 风险偏好 → 利空黄金

4. 🔴 供需博弈 — 金银相对价值
   - 指标: 金银比 (Gold/Silver Ratio)
   - 金银比 > 80 → 白银严重低估 → bullish_silver
   - 金银比 < 65 → 白银相对高估 → bearish_silver

## 输出格式
必须返回一个 JSON 对象，不要包含任何其他文本或 markdown 包裹：

```json
{
  "overall_signal": "bullish|bearish|neutral",
  "overall_confidence": "high|medium|low",
  "scenario_label": "场景中文标签",
  "summary": "一句话综合判断（中文）",
  "quadrants": [
    {
      "name": "货币锚",
      "emoji": "🟢",
      "signal": "bullish|bearish|neutral",
      "confidence": "high|medium|low",
      "explanation": "简短中文说明",
      "indicators": {
        "10Y Treasury": "4.59% (偏高)",
        "DXY": "119.28"
      }
    }
  ],
  "key_levels": {
    "gold_current": 4495.0,
    "gold_support": 4405.1,
    "gold_resistance": 4584.9,
    "silver_current": 74.22
  }
}
```

信号规则：
- overall_signal: bullish（看多）| bearish（看空）| neutral（中性）
- 象限信号可额外使用: mixed（矛盾）、bullish_silver（白银低估看多）、bearish_silver（白银高估看空）
- scenario_label 识别市场核心叙事，简明有力（如 "🛡️ 避险模式 — 市场恐慌涌入黄金"）
- summary 限 50 字以内，中文
- explanation 限 80 字以内，中文
"""


class MacroLLMAnalyzer:
    """
    四象限宏观 LLM 分析器
    使用 LLM 替代规则引擎进行市场分析
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.api_key = LLM_API_KEY
        self.api_url = LLM_API_URL
        self.model = LLM_MODEL
        self._configured = bool(self.api_key)

        if not self._configured:
            logger.warning("LLM 模式未配置 API key，将使用数据摘要替代")

    # ─── 公共入口 ──────────────────────────────────────────

    def analyze(self) -> Dict[str, Any]:
        """
        执行完整的四象限 LLM 分析
        返回与 rules 模式完全兼容的 dict 结构
        """
        # 1. 读取数据
        snapshot = self._read_snapshot()
        news = self._read_news()

        if not snapshot:
            return self._fallback_result("数据尚未采集，无法分析")

        # 2. 执行分析
        if self._configured:
            try:
                result = self._call_llm(snapshot, news)
                # 添加模式标记和时间戳
                result["mode"] = "llm"
                result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return result
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                return self._fallback_result(
                    f"LLM 分析失败 ({e})，无法返回结果",
                    overall_signal="neutral",
                    overall_confidence="low",
                )
        else:
            # 无 API key：用数据摘要替代
            return self._no_llm_summary(snapshot, news)

    def _no_llm_summary(self, snapshot: Dict, news: List) -> Dict[str, Any]:
        """
        无 LLM 时的数据摘要模式
        不运行完整规则引擎（避免与 rules 模式混淆），只返回数据概览
        """
        # 提取关键指标
        def safe_get(*keys) -> Optional[float]:
            current = snapshot
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    return None
            if isinstance(current, dict) and "value" in current:
                current = current["value"]
            try:
                return float(current)
            except (TypeError, ValueError):
                return None

        gold = safe_get("gold_price")
        silver = safe_get("silver_price")
        gs_ratio = safe_get("gold_silver_ratio")
        treasury_10y = safe_get("treasury", "10yr")
        dxy = safe_get("dxy")
        vix = safe_get("vix")
        sp500 = safe_get("sp500")

        # 构建每个象限的基础数据说明
        quadrants = []

        # 🟢 货币锚
        q_signals = []
        if treasury_10y:
            q_signals.append(f"10Y={treasury_10y}%")
        if dxy:
            q_signals.append(f"DXY={dxy}")
        quadrants.append({
            "name": "货币锚",
            "emoji": "🟢",
            "signal": "neutral",
            "confidence": "low",
            "explanation": "LLM 未配置，无深度分析",
            "indicators": {
                "10Y Treasury": f"{treasury_10y}%" if treasury_10y else "无数据",
                "DXY": f"{dxy}" if dxy else "无数据",
            }
        })

        # 🔵 宏观流动性
        treasury_2y = safe_get("treasury", "2yr")
        spread = (treasury_10y - treasury_2y) if (treasury_10y is not None and treasury_2y is not None) else None
        quadrants.append({
            "name": "宏观流动性",
            "emoji": "🔵",
            "signal": "neutral",
            "confidence": "low",
            "explanation": "LLM 未配置，无深度分析",
            "indicators": {
                "2Y Treasury": f"{treasury_2y}%" if treasury_2y else "无数据",
                "10Y Treasury": f"{treasury_10y}%" if treasury_10y else "无数据",
                "2-10 Spread": f"{spread:+.2f}%" if spread else "无数据",
            }
        })

        # 🟠 风险偏好
        quadrants.append({
            "name": "风险偏好",
            "emoji": "🟠",
            "signal": "neutral",
            "confidence": "low",
            "explanation": "LLM 未配置，无深度分析",
            "indicators": {
                "VIX": f"{vix}" if vix else "无数据",
                "S&P 500": f"{sp500}" if sp500 else "无数据",
                "新闻数量": f"{len(news)} 条",
            }
        })

        # 🔴 供需博弈
        quadrants.append({
            "name": "供需博弈",
            "emoji": "🔴",
            "signal": "neutral",
            "confidence": "low",
            "explanation": "LLM 未配置，无深度分析",
            "indicators": {
                "XAU/USD": f"${gold:.2f}" if gold else "无数据",
                "XAG/USD": f"${silver:.2f}" if silver else "无数据",
                "金银比": f"{gs_ratio:.1f}" if gs_ratio else "无数据",
            }
        })

        return {
            "mode": "llm",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_signal": "neutral",
            "overall_confidence": "low",
            "summary": "LLM 模式已启用但未配置 API Key，当前仅展示数据快照",
            "scenario_label": "⚠️ LLM 未配置",
            "note": (
                "请在环境变量或 config.py 中配置 LLM_API_KEY 以启用 AI 分析。"
                "当前仅展示原始数据快照，未进行深度分析。"
            ),
            "quadrants": quadrants,
            "key_levels": {
                "gold_current": round(gold, 2) if gold else None,
                "silver_current": round(silver, 2) if silver else None,
            } if gold else {},
        }

    def _fallback_result(self, message: str,
                         overall_signal: str = "neutral",
                         overall_confidence: str = "low") -> Dict[str, Any]:
        """返回备用结果（LLM 调用失败时）"""
        return {
            "mode": "llm",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_signal": overall_signal,
            "overall_confidence": overall_confidence,
            "summary": message,
            "scenario_label": "⚠️ 分析失败",
            "quadrants": [
                {
                    "name": name, "emoji": emoji,
                    "signal": "neutral", "confidence": "low",
                    "explanation": "LLM 分析不可用",
                    "indicators": {},
                }
                for name, emoji in [
                    ("货币锚", "🟢"), ("宏观流动性", "🔵"),
                    ("风险偏好", "🟠"), ("供需博弈", "🔴"),
                ]
            ],
            "key_levels": {},
        }

    # ─── LLM API 调用 ─────────────────────────────────────

    def _call_llm(self, snapshot: Dict, news: List) -> Dict[str, Any]:
        """
        调用 LLM API 进行综合分析
        使用 OpenAI 兼容的 Chat Completion API
        自动重试最多3次（指数退避）
        """
        # 组装用户 prompt
        user_prompt = self._build_prompt(snapshot, news)

        # 构建请求
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        max_retries = 3
        retry_delay = 2  # 初始重试间隔（秒）
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.info(f"调用 LLM: {self.model} @ {self.api_url} (尝试 {attempt + 1}/{max_retries})")
                resp = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()

                # 提取回复
                reply = data["choices"][0]["message"]["content"]
                logger.info(f"LLM 回复长度: {len(reply)} 字符")

                # 解析 JSON
                return self._parse_llm_response(reply)

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(f"LLM 请求超时 (尝试 {attempt + 1}/{max_retries}): {e}")
            except requests.exceptions.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response else "N/A"
                # 4xx 错误（除429限流）不重试
                if e.response and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    raise e
                logger.warning(f"LLM HTTP 错误 {status} (尝试 {attempt + 1}/{max_retries}): {e}")
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"LLM 网络异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            except KeyError as e:
                # choices[0] 不存在时直接失败，不重试
                raise ValueError(f"LLM 响应格式异常，缺少 choices 字段: {e}")

            # 指数退避：2s → 4s → 8s
            if attempt < max_retries - 1:
                wait = retry_delay * (2 ** attempt)
                logger.info(f"等待 {wait}s 后重试...")
                time.sleep(wait)

        # 所有重试失败
        raise RuntimeError(
            f"LLM 调用失败，已重试 {max_retries} 次: {last_error}"
        )

    def _parse_llm_response(self, text: str) -> Dict[str, Any]:
        """
        从 LLM 回复中提取 JSON 结果
        兼容带 markdown 代码块包裹和不带的情况
        """
        # 去掉可能的 markdown 代码块包裹
        text = text.strip()
        if text.startswith("```"):
            # 去掉开头的 ```json 或 ```
            lines = text.split("\n")
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # 尝试在文本中查找首个 { ... } 块
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    raise ValueError(f"无法解析 LLM 输出为 JSON:\n{text[:500]}")
            else:
                raise ValueError(f"LLM 输出中未找到 JSON:\n{text[:500]}")

        # 验证必要字段
        required = ["overall_signal", "overall_confidence", "summary", "quadrants"]
        for field in required:
            if field not in result:
                raise ValueError(f"LLM 输出缺少必要字段: {field}")

        # 验证象限
        if len(result.get("quadrants", [])) != 4:
            logger.warning(f"象限数量不为 4 (实际 {len(result.get('quadrants', []))})，尝试补全")
            # 补全缺失的象限
            expected = ["货币锚", "宏观流动性", "风险偏好", "供需博弈"]
            existing_names = {q.get("name") for q in result.get("quadrants", [])}
            for name in expected:
                if name not in existing_names:
                    result["quadrants"].append({
                        "name": name,
                        "emoji": {"货币锚": "🟢", "宏观流动性": "🔵",
                                  "风险偏好": "🟠", "供需博弈": "🔴"}.get(name, "➖"),
                        "signal": "neutral",
                        "confidence": "low",
                        "explanation": "LLM 未提供该象限分析",
                        "indicators": {},
                    })
            # 裁剪多余象限，仅保留标准 4 个并按预期顺序排列
            name_order = {n: i for i, n in enumerate(expected)}
            result["quadrants"] = sorted(
                [q for q in result["quadrants"] if q.get("name") in name_order],
                key=lambda q: name_order[q["name"]],
            )

        return result

    # ─── Prompt 构建 ───────────────────────────────────────

    def _build_prompt(self, snapshot: Dict, news: List) -> str:
        """构建用户消息 prompt"""
        parts = ["## 当前市场数据\n"]

        # 贵金属
        gold = snapshot.get("gold_price")
        silver = snapshot.get("silver_price")
        ratio = snapshot.get("gold_silver_ratio")
        parts.append("### 贵金属")
        parts.append(f"- XAU/USD: {gold}")
        parts.append(f"- XAG/USD: {silver}")
        parts.append(f"- 金银比: {ratio}")
        parts.append("")

        # 国债
        treasury = snapshot.get("treasury", {})
        parts.append("### 国债收益率")
        for k, v in treasury.items():
            if isinstance(v, dict) and "value" in v:
                parts.append(f"- {k}: {v['value']}")
            else:
                parts.append(f"- {k}: {v}")
        parts.append("")

        # 其他指标
        for key in ("dxy", "vix", "sp500", "tips_10y"):
            val = snapshot.get(key)
            if val is not None:
                parts.append(f"- {key}: {val}")
        parts.append("")

        # TIPS 实际利率
        tips = snapshot.get("tips")
        if isinstance(tips, dict):
            parts.append("### TIPS 实际利率")
            for k, v in tips.items():
                parts.append(f"- {k}: {v}")
            parts.append("")

        # 收益率曲线
        for key in ("yield_curve",):
            val = snapshot.get(key)
            if val:
                parts.append(f"### 收益率曲线")
                if isinstance(val, dict):
                    for k, v in val.items():
                        parts.append(f"- {k}: {v}")
                else:
                    parts.append(f"- {val}")
                parts.append("")

        # 事件摘要
        events = snapshot.get("events", {})
        if events:
            parts.append("### 活跃事件")
            s_events = events.get("active_s", [])
            a_events = events.get("active_a", [])
            if s_events:
                parts.append(f"- S 级事件 ({len(s_events)}): {', '.join(s_events[:3])}")
            if a_events:
                parts.append(f"- A 级事件 ({len(a_events)}): {', '.join(a_events[:5])}")
            parts.append("")

        # 新闻
        if news:
            parts.append("### 最近新闻")
            for i, article in enumerate(news[:10]):
                title = article.get("title", "")[:120]
                summary = (article.get("summary") or article.get("description", ""))[:80]
                parts.append(f"{i+1}. {title}")
                if summary:
                    parts.append(f"   {summary}")
            parts.append("")

        return "\n".join(parts)

    # ─── 数据读取 ──────────────────────────────────────────

    def _read_snapshot(self) -> Dict[str, Any]:
        """读取当前数据快照"""
        path = self.data_dir / "current" / "dashboard_data.json"
        if not path.exists():
            logger.warning(f"数据快照不存在: {path}")
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取数据快照失败: {e}")
            return {}

    def _read_news(self) -> List[Dict[str, Any]]:
        """读取最近新闻"""
        path = self.data_dir / "events" / "latest_feed.json"
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return data.get("events", [])
        except Exception as e:
            logger.warning(f"读取新闻失败: {e}")
            return []
