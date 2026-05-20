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
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# 异步事件循环池（每个线程一个事件循环）
_loop_cache = {}
_loop_lock = threading.Lock()

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from shared import FeishuWebhookServer
from feishu.handlers import extract_user_message, is_v2_command, handle_v2_command

class RequestHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def __init__(self, webhook_server: FeishuWebhookServer, *args, **kwargs):
        self.webhook_server = webhook_server
        super().__init__(*args, **kwargs)

    def _run_async(self, coro):
        """在线程池中安全运行异步代码，避免每次创建新事件循环"""
        thread_id = threading.get_ident()
        
        # 线程安全获取/创建事件循环
        with _loop_lock:
            if thread_id not in _loop_cache:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _loop_cache[thread_id] = loop
            else:
                loop = _loop_cache[thread_id]
        
        return loop.run_until_complete(coro)

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
                # —— V2 分析命令路由 ——
                # 步骤 1: 从 Feishu webhook 数据中提取用户文本
                text = extract_user_message(data)

                # 步骤 2: 判断是否为 V2 命令（归因/趋势/宏观）
                if is_v2_command(text):
                    logger.info(f"V2 命令: {text}")
                    return await handle_v2_command(text)

                # 步骤 3: 旧命令 → 走原有 UnifiedBot 路由
                return await self.webhook_server.handle_request(path, data)

            # 使用线程池执行异步函数，避免每次创建新事件循环
            response_text = self._run_async(process())

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


def start_server(port: int = 8080):
    """
    启动飞书服务器 — V2 架构

    仅处理 V2 命令路由（宏观 / 归因 / 趋势 / 事件 / 监控），
    V1 Agent 路由（market/fundamental/risk 等）已移除。
    如需 V1 兼容，请通过 FeishuWebhookServer 手动注册 bot。

    Args:
        port: 端口号
    """
    logger = logging.getLogger("FeishuServer")

    # 创建 Webhook 服务器（V2 命令直接由 do_POST 中的 handle_v2_command 处理，
    # webhook_server 仅用于飞书 challenge 验证和可选的 bot 注册扩展）
    webhook_server = FeishuWebhookServer(port=port)

    def handler_factory(*args, **kwargs):
        return RequestHandler(webhook_server, *args, **kwargs)

    server = HTTPServer(('127.0.0.1', port), handler_factory)

    logger.info(f"=" * 70)
    logger.info(f"期货交易系统 V2 - 分析服务器")
    logger.info(f"=" * 70)
    logger.info(f"监听端口: {port}")
    logger.info(f"")
    logger.info(f"端点地址:")
    logger.info(f"  V2 路由: http://localhost:{port} -> 宏观/归因/趋势/事件/监控")
    logger.info(f"  健康检查: http://localhost:{port}/")
    logger.info(f"")
    logger.info(f"V2 命令格式:")
    logger.info(f"  宏观                   — 四象限综合判断")
    logger.info(f"  归因 <指标> <开始> <结束> — 指标区间归因")
    logger.info(f"  趋势 <指标> [天数]       — 趋势分析")
    logger.info(f"  事件 [S/A]              — 活跃事件列表")
    logger.info(f"  监控 status/check       — 阈值状态/检测")
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
