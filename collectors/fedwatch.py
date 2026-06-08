#!/usr/bin/env python3
"""
CME FedWatch 利率概率采集器 — 日频

从 CME Group 官方页面采集联邦基金利率期货隐含的加息/降息概率。
输出到 dashboard_data.json 的 fedwatch_prob 字段。

用法:
    python -m collectors.fedwatch              # 采集并写入
    python -m collectors.fedwatch --pretty     # 带 stdout 输出

数据来源: CME Group FedWatch Tool (https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html)
频率: 日频 (建议每天运行1次)
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from collectors.base_collector import BaseCollector

logger = logging.getLogger("fedwatch")
CST = timezone(timedelta(hours=8))

# ====================================================================
#  CME FedWatch API / 页面 URL
# ====================================================================

# CME FedWatch Tool 主页面
FEDWATCH_PAGE_URL = (
    "https://www.cmegroup.com/markets/interest-rates/"
    "cme-fedwatch-tool.html"
)

# CME 提供 JSON 数据的内部 API 端点
FEDWATCH_API_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/QuietZone/v1/"
    "fedWatch/probability"
)

# 请求头（模拟浏览器）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
}


class FedWatchCollector(BaseCollector):
    """
    CME FedWatch 利率概率采集器。

    采集方式:
    1. 优先尝试 CME 内部 JSON API
    2. 回退到 HTML 页面解析（正则提取 JSON 数据）

    输出字段:
    - fedwatch_prob: dict，格式如 {"cut_25bp": 0.65, "hold": 0.30, "hike_25bp": 0.05}
    """

    def __init__(self):
        super().__init__("fedwatch")

    def _fetch_from_api(self) -> Optional[dict]:
        """尝试从 CME JSON API 获取概率数据"""
        try:
            logger.info("尝试从 CME API 获取 FedWatch 数据...")
            r = requests.get(
                FEDWATCH_API_URL,
                headers=HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                logger.info("CME API 返回成功")
                return data
            else:
                logger.warning(f"CME API 返回状态码: {r.status_code}")
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"CME API 请求失败: {e}")
        return None

    def _fetch_from_page(self) -> Optional[dict]:
        """回退方法：从 CME FedWatch HTML 页面中提取 JSON 数据"""
        try:
            logger.info("尝试从 CME 页面解析 FedWatch 数据...")
            r = requests.get(FEDWATCH_PAGE_URL, headers=HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text

            # 尝试从页面提取 JSON 数据
            # CME 页面通常将数据嵌入 <script> 标签中的 JavaScript 变量
            # 或 data-* 属性中

            # 方法1：查找 window.__INITIAL_STATE__ 或类似全局变量
            patterns = [
                r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                r'window\.__DATA__\s*=\s*({.*?});',
                r'CME\.FedWatch\s*=\s*({.*?});',
                r'fedWatchData\s*=\s*({.*?});',
                r'dataLayer\s*=\s*\[({.*?})\];',
                r'"fedWatch":\s*({.*?}),\s*"',
            ]

            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        if data:
                            logger.info("从页面 JS 变量解析成功")
                            return data
                    except (json.JSONDecodeError, KeyError):
                        continue

            # 方法2：查找包含概率数据的 JSON-LD 或 JSON 块
            json_pattern = r'<script[^>]*type="application/json"[^>]*>({.*?})</script>'
            for match in re.finditer(json_pattern, html, re.DOTALL):
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, dict) and (
                        "probability" in str(data).lower()
                        or "fedwatch" in str(data).lower()
                        or "cut" in str(data).lower()
                    ):
                        logger.info("从 JSON-LD 块解析成功")
                        return data
                except (json.JSONDecodeError, KeyError):
                    continue

            logger.warning("无法从页面中提取结构化数据")

        except (requests.RequestException, OSError) as e:
            logger.warning(f"页面请求失败: {e}")

        return None

    def fetch(self) -> Dict[str, Any]:
        """从 CME 获取 FedWatch 原始数据

        优先尝试 API，失败则回退到页面解析。

        Returns:
            包含概率数据的字典
        """
        # 尝试 API
        data = self._fetch_from_api()
        if data:
            return {"source": "api", "data": data}

        # 回退页面
        page_data = self._fetch_from_page()
        if page_data:
            return {"source": "page", "data": page_data}

        # 两者都失败
        raise RuntimeError("无法获取 FedWatch 数据：API 和页面解析均失败")

    def parse(self, raw_data: dict) -> dict:
        """
        解析 FedWatch 原始数据为结构化概率字典。

        Args:
            raw_data: {"source": "...", "data": {...}}

        Returns:
            {
                "snapshot_key": "fedwatch_prob",
                "snapshot_value": {
                    "next_meeting": "2026-06-17",
                    "cut_25bp": 0.65,
                    "hold": 0.30,
                    "hike_25bp": 0.05,
                    ...
                },
                "history_row": {...},
                "grain": "daily"
            }
        """
        source = raw_data.get("source", "unknown")
        data = raw_data.get("data", {})

        now = self._now()

        # 尝试从 API 返回或页面数据中提取概率
        probabilities = self._extract_probabilities(data)

        # 提取下次会议日期
        next_meeting = self._extract_next_meeting(data)

        snapshot_value = {
            "next_meeting": next_meeting,
            "source": f"cme_fedwatch ({source})",
            "updated_at": now,
        }
        snapshot_value.update(probabilities)

        return {
            "snapshot_key": "fedwatch_prob",
            "snapshot_value": snapshot_value,
            "history_row": {
                "date": now[:10],
                **{k: v for k, v in probabilities.items() if isinstance(v, (int, float))},
            },
            "grain": "daily",
        }

    def _extract_probabilities(self, data: dict) -> Dict[str, Any]:
        """
        从 API 响应或页面数据中提取利率概率。

        处理多种可能的 JSON 结构。
        """
        probs: Dict[str, Any] = {}

        if not data:
            return probs

        # 处理不同的数据结构
        # CME API 通常返回的结构: {"data": [{"meetingDate": "...", "probabilities": [...]}]}
        # 或扁平结构: {"meetings": [...], "productId": "FEDWATCH"}

        raw_str = json.dumps(data, ensure_ascii=False)

        # 从可能包含概率的字段中提取
        for meeting_key in ["meetings", "data", "results", "probabilityData", "items"]:
            meetings = data.get(meeting_key, [])
            if isinstance(meetings, list) and meetings:
                # 获取最近一次会议
                meeting = meetings[0]
                if isinstance(meeting, dict):
                    # 尝试不同字段名
                    probs_raw = (
                        meeting.get("probabilities")
                        or meeting.get("probability")
                        or meeting.get("rates")
                        or meeting.get("contracts")
                        or []
                    )
                    if isinstance(probs_raw, list):
                        for item in probs_raw:
                            if isinstance(item, dict):
                                key = (
                                    item.get("rate")
                                    or item.get("targetRate")
                                    or item.get("action")
                                    or item.get("name")
                                    or item.get("label")
                                    or ""
                                )
                                value = (
                                    item.get("probability")
                                    or item.get("prob")
                                    or item.get("value")
                                    or item.get("pct")
                                )
                                if value is not None:
                                    probs[str(key)] = round(float(value), 4)
                            elif isinstance(item, (int, float)):
                                probs[f"option_{len(probs)}"] = item

                    # 提取会议日期
                    meeting_date = (
                        meeting.get("meetingDate")
                        or meeting.get("date")
                        or meeting.get("meeting_date")
                        or meeting.get("expirationDate")
                    )
                    if meeting_date:
                        probs["next_meeting_date"] = str(meeting_date)[:10]

                    break

        # 如果未从嵌套结构提取到数据，尝试扁平键
        if not probs:
            flat_keys = [
                "cut_50bp", "cut_25bp", "hold", "hike_25bp", "hike_50bp",
                "cut_75bp", "hike_75bp",
            ]
            for key in flat_keys:
                val = data.get(key)
                if val is None:
                    # 尝试带下划线的变体
                    for alt_key in [key.replace("_", ""), key.upper(), key.lower()]:
                        val = data.get(alt_key)
                        if val is not None:
                            break
                if val is not None:
                    probs[key] = round(float(val), 4)

        # 如果仍未提取到，回退到正则搜索
        if not probs:
            probs = self._regex_fallback(raw_str)

        return probs

    def _extract_next_meeting(self, data: dict) -> Optional[str]:
        """从数据中提取下次 FOMC 会议日期"""
        if not data:
            return None

        for key in ["nextMeeting", "next_meeting", "meetingDate", "nextMeetingDate"]:
            val = data.get(key)
            if val:
                return str(val)[:10]

        # 从嵌套结构中查找
        for meeting_key in ["meetings", "data", "results"]:
            meetings = data.get(meeting_key, [])
            if isinstance(meetings, list) and meetings:
                meeting = meetings[0] if isinstance(meetings[0], dict) else {}
                for date_key in ["meetingDate", "date", "meeting_date"]:
                    val = meeting.get(date_key)
                    if val:
                        return str(val)[:10]

        return None

    def _regex_fallback(self, text: str) -> Dict[str, float]:
        """
        终极回退：通过正则从文本中提取概率模式。

        查找类似 "cut_25bp": 0.65 或 "Hike 25": 12.3% 的文本。
        """
        probs: Dict[str, float] = {}

        # 常见概率标签
        patterns = {
            "cut_50bp": [r'cut[_-]?50', r'[_-]50\s*(?:bp|bps)', r'50\s*(?:bp|bps)\s*cut'],
            "cut_25bp": [r'cut[_-]?25', r'[_-]25\s*(?:bp|bps)', r'25\s*(?:bp|bps)\s*cut'],
            "hold": [r'\bhold\b', r'no\s*change', r'unchanged'],
            "hike_25bp": [r'hike[_-]?25', r'[_-]25\s*(?:bp|bps)\s*hike', r'25\s*(?:bp|bps)\s*hike'],
            "hike_50bp": [r'hike[_-]?50', r'[_-]50\s*(?:bp|bps)\s*hike', r'50\s*(?:bp|bps)\s*hike'],
        }

        for label, regexes in patterns.items():
            for pattern in regexes:
                # 查找 key 附近的数字值
                matches = re.finditer(
                    pattern + r'[^0-9]*?["\':\s]*(\d+\.?\d*)',
                    text,
                    re.IGNORECASE,
                )
                for m in matches:
                    try:
                        val = float(m.group(1))
                        # 判断是百分比还是小数
                        if val > 1:
                            val = val / 100
                        if 0 < val <= 1:
                            probs[label] = round(val, 4)
                            break
                    except (ValueError, IndexError):
                        continue
                if label in probs:
                    break

        return probs


def main():
    parser = argparse.ArgumentParser(description="CME FedWatch 利率概率采集器")
    parser.add_argument("--pretty", action="store_true", help="输出格式化结果到 stdout")
    args = parser.parse_args()

    collector = FedWatchCollector()
    success = collector.run()

    # 如果请求了 pretty 输出，读取并打印
    if success and args.pretty:
        from pathlib import Path as _Path
        snap_file = _Path(__file__).resolve().parent.parent / "data/current/dashboard_data.json"
        if snap_file.exists():
            data = json.loads(snap_file.read_text(encoding="utf-8"))
            fw = data.get("fedwatch_prob", {})
            print(json.dumps({"fedwatch_prob": fw}, ensure_ascii=False, indent=2))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
