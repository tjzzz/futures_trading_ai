"""
共享模块 - 数据、配置、工具
整合自 skills 的 shared/
"""
from .data_client import DataClient, DataSource, AKShareDataSource, MockDataSource
from .data_platform import DataStorage, DataCollector, DataService
from .feishu_bot import FeishuBot, FeishuMessage, FeishuWebhookServer
from .config import Config

__all__ = [
    # 数据客户端
    "DataClient", "DataSource", "AKShareDataSource", "MockDataSource",
    # 数据中台
    "DataStorage", "DataCollector", "DataService",
    # 飞书机器人
    "FeishuBot", "FeishuMessage", "FeishuWebhookServer",
    # 配置
    "Config"
]
