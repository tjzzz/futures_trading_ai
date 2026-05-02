"""
统一配置管理
整合两个项目的配置
"""
import os
import json
from typing import Dict, Any, Optional
from pathlib import Path


class Config:
    """统一配置类"""

    # 默认配置
    DEFAULTS = {
        # 系统配置
        "system": {
            "log_level": "INFO",
            "log_file": "logs/trading_system.log",
            "data_dir": "data",
            "mode": "local",  # local 或 redis
        },

        # 市场分析配置
        "market_analysis": {
            "ma_periods": [5, 10, 20, 60],
            "ema_periods": [12, 26],
            "rsi_period": 14,
            "macd_params": [12, 26, 9],
            "bollinger_period": 20,
            "bollinger_std": 2.0,
            "atr_period": 14,
            "max_cache_size": 1000,
        },

        # 风控配置
        "risk_management": {
            "max_position_pct": 0.3,  # 最大仓位比例
            "max_single_loss_pct": 0.02,  # 单笔最大亏损
            "default_stop_loss_atr": 2.0,  # 默认止损ATR倍数
            "max_daily_loss_pct": 0.05,  # 日最大亏损
        },

        # 交易执行配置
        "trade_execution": {
            "default_strategy": "twap",
            "twap_interval": 60,  # 秒
            "vwap_buckets": 10,
        },

        # 回测配置
        "backtest": {
            "initial_capital": 1000000,
            "commission_rate": 0.0001,
            "slippage": 0.001,
        },

        # 数据源配置
        "data_source": {
            "primary": "akshare",  # akshare, tushare, mock
            "tushare_token": "",
        },

        # 飞书配置
        "feishu": {
            "app_id": "",
            "app_secret": "",
            "webhook_port": 8080,
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config_file()
        self._config = self._load_config()

    def _find_config_file(self) -> Optional[str]:
        """查找配置文件"""
        possible_paths = [
            "config.json",
            "config/config.json",
            os.path.expanduser("~/.futures_trading/config.json"),
        ]
        for path in possible_paths:
            if Path(path).exists():
                return path
        return None

    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        config = self.DEFAULTS.copy()

        # 从文件加载
        if self.config_path and Path(self.config_path).exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                self._deep_update(config, user_config)

        # 从环境变量加载
        self._load_from_env(config)

        return config

    def _load_from_env(self, config: Dict[str, Any]):
        """从环境变量加载配置"""
        env_mappings = {
            "TUSHARE_TOKEN": ("data_source", "tushare_token"),
            "FEISHU_APP_ID": ("feishu", "app_id"),
            "FEISHU_APP_SECRET": ("feishu", "app_secret"),
            "LOG_LEVEL": ("system", "log_level"),
        }

        for env_key, (section, key) in env_mappings.items():
            value = os.getenv(env_key)
            if value:
                if section not in config:
                    config[section] = {}
                config[section][key] = value

    def _deep_update(self, base: Dict, update: Dict):
        """深度更新字典"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号分隔"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取配置节"""
        return self._config.get(section, {})

    def save(self, path: Optional[str] = None):
        """保存配置到文件"""
        save_path = path or self.config_path or "config.json"
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return self._config.copy()


# 全局配置实例
_config_instance: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """获取全局配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(config_path)
    return _config_instance


def init_config(config_path: Optional[str] = None) -> Config:
    """初始化配置"""
    global _config_instance
    _config_instance = Config(config_path)
    return _config_instance
