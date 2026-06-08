"""
已废弃（V2）。

所有配置已迁移到根目录 config.py。
此文件仅保留 ImportError 存根，防止旧代码直接 import 时出现 ModuleNotFoundError。
"""

import warnings

warnings.warn(
    "shared/config.py 已废弃，请使用根目录 config.py",
    DeprecationWarning,
    stacklevel=2,
)

Config = None
FEISHU_CONFIG = None
DEFAULT_CONFIG = None


def get_config(*args, **kwargs):
    raise ImportError("shared/config.py 已废弃，请使用根目录 config.py")


def init_config(*args, **kwargs):
    raise ImportError("shared/config.py 已废弃，请使用根目录 config.py")
