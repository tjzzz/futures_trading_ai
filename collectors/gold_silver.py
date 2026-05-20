#!/usr/bin/env python3
"""
金银实时价格采集器 — V2 整合版
- 源：gold-api.com
- 粒度：5分钟
- 写入：dashboard_data.json + data/history/minutely/gold_silver_minutely.csv

源自 workspace-trade-ai/collectors/realtime_collector.py
V2 变更：导入路径适配 package 结构
"""

import requests
from collectors.base_collector import BaseCollector


class GoldSilverCollector(BaseCollector):
    def __init__(self):
        super().__init__("gold_silver")

    def fetch(self):
        """从 gold-api.com 获取金银价格，支持重试和详细异常处理"""
        import time
        
        max_retries = 3
        retry_delay = 2  # 秒
        
        last_error = None
        for attempt in range(max_retries):
            try:
                # 获取黄金价格
                resp_xau = requests.get(
                    "https://api.gold-api.com/price/XAU", 
                    timeout=10
                )
                resp_xau.raise_for_status()
                xau = resp_xau.json()
                
                # 获取白银价格
                resp_xag = requests.get(
                    "https://api.gold-api.com/price/XAG", 
                    timeout=10
                )
                resp_xag.raise_for_status()
                xag = resp_xag.json()
                
                return {"xau": xau, "xag": xag}
                
            except requests.exceptions.Timeout as e:
                last_error = f"API请求超时 (尝试 {attempt + 1}/{max_retries})"
                self.logger.warning(f"{last_error}: {e}")
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else "N/A"
                last_error = f"API返回HTTP错误 (尝试 {attempt + 1}/{max_retries})"
                self.logger.warning(f"{last_error}: 状态码 {status_code}, {e}")
            except requests.exceptions.RequestException as e:
                last_error = f"网络请求异常 (尝试 {attempt + 1}/{max_retries})"
                self.logger.warning(f"{last_error}: {e}")
            except ValueError as e:
                # JSON 解析失败
                last_error = f"API返回非JSON格式数据 (尝试 {attempt + 1}/{max_retries})"
                self.logger.warning(f"{last_error}: {e}")
            except Exception as e:
                last_error = f"未知错误 (尝试 {attempt + 1}/{max_retries})"
                self.logger.error(f"{last_error}: {e}")
            
            # 非最后一次尝试，等待后重试
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        
        # 所有重试都失败
        raise Exception(f"获取金银价格失败，已重试{max_retries}次: {last_error}")

    def parse(self, raw):
        xau = raw["xau"]
        xag = raw["xag"]
        gold_usd = float(xau.get("price", 0))
        silver_usd = float(xag.get("price", 0))
        ratio = round(gold_usd / silver_usd, 2) if silver_usd else 0

        now = self._now()

        return {
            "snapshot_key": "gold_price",
            "snapshot_value": {
                "value": round(gold_usd, 2),
                "unit": "USD/oz",
                "updated_at": now
            },
            "extra_snapshots": [
                ("silver_price", {
                    "value": round(silver_usd, 2),
                    "unit": "USD/oz",
                    "updated_at": now
                }),
                ("gold_silver_ratio", {
                    "value": ratio,
                    "updated_at": now
                }),
            ],
            "history_row": {
                "gold_usd": round(gold_usd, 2),
                "silver_usd": round(silver_usd, 2),
                "ratio": ratio,
            },
            "grain": "minutely",
        }

if __name__ == "__main__":
    collector = GoldSilverCollector()
    collector.run()
