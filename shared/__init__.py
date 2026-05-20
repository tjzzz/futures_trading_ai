"""
共享模块 - 数据客户端

注意: 配置管理统一使用根目录 config.py，shared/config.py 已废弃。
      FeishuBot 相关保留 import 但不在 V2 活跃模块中使用。
"""
from .data_client import DataClient, DataSource, AKShareDataSource, MockDataSource

# 飞书机器人（V2 已废弃，保留引用避免潜在 import 错误）
from .feishu_bot import FeishuBot, FeishuMessage, FeishuWebhookServer

__all__ = [
    "DataClient", "DataSource", "AKShareDataSource", "MockDataSource",
]
