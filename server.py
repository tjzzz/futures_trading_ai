#!/usr/bin/env python3
"""
飞书机器人 Webhook 服务器
整合后的统一入口
"""
import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, List
from http.server import HTTPServer, BaseHTTPRequestHandler

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from shared import FeishuWebhookServer
from core import SkillAgent


class UnifiedBot(SkillAgent):
    """
    统一机器人入口 - 根据关键词路由到不同 Skill
    整合所有技能的路由逻辑
    """

    def __init__(self, agents: Dict[str, SkillAgent]):
        super().__init__("unified")
        self.agents = agents
        self._routers = {
            "行情": "market",
            "分析": "market",
            "黄金": "market",
            "原油": "market",
            "铜": "market",
            "螺纹钢": "market",
            "基本面": "fundamental",
            "宏观": "fundamental",
            "库存": "fundamental",
            "基差": "fundamental",
            "风控": "risk",
            "风险": "risk",
            "仓位": "risk",
            "止损": "risk",
            "凯利": "risk",
            "执行": "execution",
            "下单": "execution",
            "平仓": "execution",
            "撤单": "execution",
            "持仓": "execution",
            "订单": "execution",
            "回测": "backtest",
            "测试": "backtest",
            "策略": "backtest",
            "绩效": "backtest",
            "日志": "journal",
            "记录": "journal",
            "复盘": "journal",
            "统计": "journal",
            "列表": "journal",
        }

    def get_bot_name(self) -> str:
        return "期货智能助手"

    def get_bot_description(self) -> str:
        return """期货交易智能助手，支持以下功能：
- 行情分析（行情/分析 + 品种）
- 基本面分析（基本面/宏观 + 品种）
- 风险管理（风控/仓位/止损）
- 交易执行（下单/持仓/订单）
- 策略回测（回测 + 参数）
- 交易日志（记录/复盘/统计）
输入「帮助」查看详细命令。"""

    async def handle_feishu_message(self, text: str, user_id: str = "", chat_id: str = "") -> str:
        """处理飞书消息并路由"""
        text = text.strip()

        # 帮助命令
        if text in ["帮助", "help", "?"]:
            return await self._show_help()

        # 根据关键词路由
        for keyword, agent_name in self._routers.items():
            if keyword in text:
                agent = self.agents.get(agent_name)
                if agent:
                    # 移除关键词前缀
                    remaining = text.replace(keyword, "").strip()
                    return await agent.handle_feishu_message(remaining or text, user_id, chat_id)

        # 默认使用市场分析
        agent = self.agents.get("market")
        if agent:
            return await agent.handle_feishu_message(text, user_id, chat_id)

        return "抱歉，我暂时无法理解您的指令。请输入「帮助」查看可用命令。"

    async def _show_help(self) -> str:
        """显示帮助"""
        lines = [
            f"## {self.get_bot_name()}",
            "",
            self.get_bot_description(),
            "",
            "### 各技能入口",
            "",
        ]

        help_info = {
            "📈 行情分析": ["行情 AU", "分析 RB", "信号"],
            "📊 基本面分析": ["基本面 AU", "宏观", "库存 AU", "基差 RB"],
            "🛡️ 风险管理": ["仓位 AU 100000 750", "止损 AU 750", "凯利 0.55 2.0"],
            "📋 交易执行": ["下单 AU 多 2 750", "持仓", "订单"],
            "📉 策略回测": ["回测 AU 2024-01-01 2024-03-01", "绩效"],
            "📝 交易日志": ["记录", "复盘", "统计 30", "列表"],
        }

        for category, examples in help_info.items():
            lines.append(f"**{category}**:")
            for ex in examples:
                lines.append(f"  • {ex}")
            lines.append("")

        return "\n".join(lines)


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def __init__(self, webhook_server: FeishuWebhookServer, *args, **kwargs):
        self.webhook_server = webhook_server
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """处理 GET 请求（健康检查）"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {"status": "ok", "message": "Futures Trading Server is running"}
        self.wfile.write(json.dumps(response).encode())

    def do_POST(self):
        """处理 POST 请求（飞书回调）"""
        try:
            path = self.path
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))

            logger = logging.getLogger("FeishuServer")
            logger.info(f"收到请求: {path}")

            # 处理飞书 challenge（首次配置验证）
            if "challenge" in data:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {"challenge": data["challenge"]}
                self.wfile.write(json.dumps(response).encode())
                logger.info("响应 challenge 验证")
                return

            # 处理消息
            async def process():
                return await self.webhook_server.handle_request(path, data)

            response_text = asyncio.run(process())

            # 返回响应
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            response = {
                "code": 0,
                "msg": "success",
                "data": {}
            }

            if response_text:
                response["data"]["text"] = response_text

            self.wfile.write(json.dumps(response).encode())

            logger.info(f"响应: {response_text[:100] if response_text else 'None'}...")

        except Exception as e:
            logger = logging.getLogger("FeishuServer")
            logger.error(f"处理请求失败: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"code": 500, "msg": str(e)}
            self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        """自定义日志"""
        logger = logging.getLogger("FeishuServer")
        logger.info(f"{self.address_string()} - {format % args}")


def start_server(port: int = 8080, agents: Dict = None):
    """
    启动飞书服务器

    Args:
        port: 端口号
        agents: Agent字典（用于统一路由）
    """
    logger = logging.getLogger("FeishuServer")

    # 创建 Webhook 服务器
    webhook_server = FeishuWebhookServer(port=port)

    # 注册各 Skill 机器人
    if agents:
        webhook_server.register_bot("/market", agents["market"])
        webhook_server.register_bot("/fundamental", agents["fundamental"])
        webhook_server.register_bot("/risk", agents["risk"])
        webhook_server.register_bot("/execution", agents["execution"])
        webhook_server.register_bot("/backtest", agents["backtest"])
        webhook_server.register_bot("/journal", agents["journal"])

        # 统一入口
        unified_bot = UnifiedBot(agents)
        webhook_server.register_bot("/webhook", unified_bot)

    def handler_factory(*args, **kwargs):
        return RequestHandler(webhook_server, *args, **kwargs)

    server = HTTPServer(('0.0.0.0', port), handler_factory)

    logger.info(f"=" * 70)
    logger.info(f"期货交易系统 - 飞书机器人服务器")
    logger.info(f"=" * 70)
    logger.info(f"监听端口: {port}")
    logger.info(f"")
    logger.info(f"端点地址:")
    logger.info(f"  统一入口: http://localhost:{port}/webhook")
    logger.info(f"  行情分析: http://localhost:{port}/market")
    logger.info(f"  基本面:   http://localhost:{port}/fundamental")
    logger.info(f"  风控:     http://localhost:{port}/risk")
    logger.info(f"  执行:     http://localhost:{port}/execution")
    logger.info(f"  回测:     http://localhost:{port}/backtest")
    logger.info(f"  交易日志: http://localhost:{port}/journal")
    logger.info(f"")
    logger.info(f"健康检查: http://localhost:{port}/")
    logger.info(f"=" * 70)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\n服务器停止")
        server.shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="飞书机器人服务器")
    parser.add_argument("--port", "-p", type=int, default=8080, help="端口号")
    args = parser.parse_args()

    start_server(args.port)
