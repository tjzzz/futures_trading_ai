#!/usr/bin/env python3
"""
期货交易系统 V2 — 启动脚本

使用 V2 架构启动 HTTP 服务器（飞书 Webhook + 健康检查）。
飞书入口自动处理以下命令：
  - 宏观           → 四象限综合分析（调用 analysis 引擎）
  - 归因 <指标> ...  → 指标区间归因
  - 趋势 <指标> ...  → 趋势分析
  - 事件            → 活跃事件列表（调用 event_monitor）
  - 监控 status     → 当前阈值状态

用法:
    python start.py              # 默认端口 8080
    python start.py --port 8080  # 指定端口
    python start.py -p 8080      # 简写
"""

import sys
import argparse
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from server import start_server
from config import validate_config


def main():
    parser = argparse.ArgumentParser(
        description="期货交易系统 V2 — 启动脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python start.py                # 默认端口 8080
  python start.py -p 8080        # 指定端口
        """,
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8080,
        help="HTTP 服务端口（默认: 8080）",
    )
    args = parser.parse_args()

    # 配置日志（独立启动时控制台输出）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 启动时验证配置
    issues = validate_config()
    if issues:
        print("⚠️  配置检查发现以下问题:")
        for issue in issues:
            print(f"    - {issue}")
        print()

    print("=" * 70)
    print("  期货交易系统 V2  —  飞书 Webhook 服务器")
    print("=" * 70)
    print(f"  端口: {args.port}")
    print(f"  模式: 飞书 Webhook + V2 分析路由")
    print(f"  命令: 宏观 / 归因 / 趋势 / 事件 / 监控")
    print("=" * 70)
    print()

    start_server(port=args.port)


if __name__ == "__main__":
    main()
