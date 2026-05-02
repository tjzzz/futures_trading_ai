#!/usr/bin/env python3
"""
期货交易系统主程序
整合 futures_trading_system 和 futures_trading_skills
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from core import MessageBus, BaseAgent
from shared import Config, get_config, FeishuWebhookServer
from skills import (
    MarketSkill,
    FundamentalSkill,
    RiskSkill,
    ExecutionSkill,
    BacktestSkill,
    JournalSkill
)


class FuturesTradingSystem:
    """
    期货交易系统
    整合Agent消息总线和飞书机器人
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._setup_logging()

        # 消息总线（支持local/redis模式）
        mode = self.config.get("system.mode", "local")
        self.message_bus = MessageBus(mode=mode)

        # Agent/Skill实例
        self.agents: Dict[str, BaseAgent] = {}

        # 飞书服务器
        self.feishu_server: Optional[FeishuWebhookServer] = None

        self.logger = logging.getLogger("FuturesTradingSystem")

    def _setup_logging(self):
        """设置日志"""
        log_level = self.config.get("system.log_level", "INFO")
        log_file = self.config.get("system.log_file", "logs/trading_system.log")

        # 创建logs目录
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

    async def initialize(self):
        """初始化系统"""
        self.logger.info("=" * 60)
        self.logger.info("期货交易系统初始化中...")
        self.logger.info("=" * 60)

        # 创建所有Agent/Skill
        await self._create_agents()

        # 注册到消息总线
        await self._register_agents()

        # 初始化所有Agent
        for agent in self.agents.values():
            await agent.initialize()

        self.logger.info("系统初始化完成")

    async def _create_agents(self):
        """创建Agent实例"""
        # 市场行情技能
        self.agents["market"] = MarketSkill(
            config=self.config.get_section("market_analysis")
        )

        # 基本面分析技能
        self.agents["fundamental"] = FundamentalSkill(
            config=self.config.get_section("fundamental")
        )

        # 风险管理技能
        self.agents["risk"] = RiskSkill(
            config=self.config.get_section("risk_management")
        )

        # 交易执行技能
        self.agents["execution"] = ExecutionSkill(
            config=self.config.get_section("trade_execution")
        )

        # 回测技能
        self.agents["backtest"] = BacktestSkill(
            config=self.config.get_section("backtest")
        )

        # 交易日志技能
        self.agents["journal"] = JournalSkill(
            config=self.config.get_section("trade_journal")
        )

        self.logger.info(f"已创建 {len(self.agents)} 个技能")

    async def _register_agents(self):
        """注册Agent到消息总线"""
        for name, agent in self.agents.items():
            agent.set_message_bus(self.message_bus)
            self.message_bus.subscribe_agent(name, agent.receive_message)

        self.logger.info("所有Agent已注册到消息总线")

    def setup_feishu_server(self, port: int = 8080) -> FeishuWebhookServer:
        """
        设置飞书机器人服务器
        """
        self.feishu_server = FeishuWebhookServer(port=port)

        # 注册各Skill到飞书
        self.feishu_server.register_bot("/market", self.agents["market"])
        self.feishu_server.register_bot("/fundamental", self.agents["fundamental"])
        self.feishu_server.register_bot("/risk", self.agents["risk"])
        self.feishu_server.register_bot("/execution", self.agents["execution"])
        self.feishu_server.register_bot("/backtest", self.agents["backtest"])
        self.feishu_server.register_bot("/journal", self.agents["journal"])

        # 统一入口
        from server import UnifiedBot
        unified = UnifiedBot(self.agents)
        self.feishu_server.register_bot("/webhook", unified)

        self.logger.info(f"飞书服务器配置完成，端口: {port}")
        return self.feishu_server

    async def start_feishu(self, port: int = 8080):
        """启动飞书服务器"""
        if not self.feishu_server:
            self.setup_feishu_server(port)

        self.logger.info("启动飞书服务器...")
        # 这里应该启动HTTP服务器
        # 简化版本，实际应调用 feishu_server.start()

    async def start(self):
        """启动系统（Agent模式）"""
        self.logger.info("启动所有Agent...")

        # 启动所有Agent的消息循环
        tasks = [agent.start() for agent in self.agents.values()]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.logger.info("系统收到停止信号")
        except Exception as e:
            self.logger.error(f"系统运行异常: {e}")

    async def stop(self):
        """停止系统"""
        self.logger.info("停止所有Agent...")
        for agent in self.agents.values():
            await agent.stop()
        self.logger.info("系统已停止")

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """获取Agent"""
        return self.agents.get(name)

    # 快捷访问方法
    def get_market(self) -> MarketSkill:
        return self.agents.get("market")

    def get_fundamental(self) -> FundamentalSkill:
        return self.agents.get("fundamental")

    def get_risk(self) -> RiskSkill:
        return self.agents.get("risk")

    def get_execution(self) -> ExecutionSkill:
        return self.agents.get("execution")

    def get_backtest(self) -> BacktestSkill:
        return self.agents.get("backtest")

    def get_journal(self) -> JournalSkill:
        return self.agents.get("journal")


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="期货交易系统")
    parser.add_argument("--mode", "-m", choices=["agent", "feishu"], default="agent",
                       help="运行模式: agent(消息总线) 或 feishu(飞书机器人)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="飞书服务器端口")
    parser.add_argument("--config", "-c", help="配置文件路径")
    args = parser.parse_args()

    # 加载配置
    config = get_config(args.config)

    # 创建系统
    system = FuturesTradingSystem(config)

    try:
        # 初始化
        await system.initialize()

        if args.mode == "feishu":
            # 启动飞书服务器
            await system.start_feishu(args.port)
        else:
            # 启动Agent模式
            await system.start()

    except KeyboardInterrupt:
        print("\n收到中断信号，正在停止...")
        await system.stop()
    except Exception as e:
        print(f"系统异常: {e}")
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())
