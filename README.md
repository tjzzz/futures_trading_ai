# 期货交易系统（整合版）

整合 `futures_trading_system` 和 `futures_trading_skills` 两个项目的代码，减少冗余。

## 项目结构

```
futures_trading_integrated/
├── core/                    # 核心模块
│   ├── __init__.py
│   ├── base_agent.py       # Agent基类（整合）
│   ├── skill_agent.py      # SkillAgent基类（整合）
│   └── message_bus.py      # 统一消息总线（local/redis）
│
├── shared/                  # 共享模块
│   ├── __init__.py
│   ├── config.py           # 统一配置管理
│   ├── indicators.py       # 技术指标计算（整合）
│   ├── data_client.py      # 数据客户端
│   ├── data_platform.py    # 数据中台
│   └── feishu_bot.py       # 飞书机器人基类
│
├── skills/                  # 技能模块
│   ├── __init__.py
│   ├── market.py           # 行情分析（整合）
│   ├── fundamental.py      # 基本面分析（整合）
│   ├── risk.py             # 风险管理（整合）
│   ├── execution.py        # 交易执行（整合）
│   ├── backtest.py         # 回测（整合）
│   └── journal.py          # 交易日志（整合）
│
├── main.py                 # 主程序
├── server.py               # 飞书服务器
├── requirements.txt        # 依赖
└── README.md
```

## 整合说明

### 主要改进

1. **统一目录结构**
   - 移除重复的文件层级
   - 核心代码集中到 `core/` 和 `shared/`
   - 技能代码统一到 `skills/`

2. **统一消息总线**
   - 支持两种模式：`local`（async）和 `redis`（分布式）
   - 自动根据配置切换

3. **统一Agent架构**
   - `BaseAgent`: 基础Agent类，支持消息总线
   - `SkillAgent`: 扩展类，增加飞书命令支持
   - 技能类继承 `SkillAgent`，同时支持两种模式

4. **整合技术指标计算**
   - 统一到 `shared/indicators.py`
   - 支持所有常用指标：MA, EMA, MACD, RSI, Bollinger, ATR, KDJ

5. **删除冗余代码**
   - 重复的Message类定义
   - 重复的指标计算逻辑
   - 重复的配置管理

## 使用方法

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. Agent模式（消息总线）

```bash
python main.py --mode agent
```

### 3. 飞书机器人模式

```bash
python main.py --mode feishu --port 8080
```

或直接启动服务器：

```bash
python server.py --port 8080
```

### 4. 命令行使用示例

```python
import asyncio
from main import FuturesTradingSystem

async def test():
    system = FuturesTradingSystem()
    await system.initialize()

    # 获取市场行情
    market = system.get_market()
    quote = await market.get_quote("AU")
    print(quote)

    # 执行分析
    result = await market.analyze("AU")
    print(result)

asyncio.run(test())
```

## 飞书命令

### 行情分析
- `行情 AU` - 获取黄金行情
- `分析 AU` - 技术分析
- `信号` - 查看当前信号

### 基本面分析
- `基本面 AU` - 基本面分析
- `宏观` - 宏观因素
- `库存 AU` - 库存数据

### 风险管理
- `仓位 AU 100000 750` - 计算仓位
- `止损 AU 750` - 计算止损
- `凯利 0.55 2.0` - 凯利公式

### 交易执行
- `下单 AU 多 2 750` - 模拟下单
- `持仓` - 查看持仓
- `订单` - 查看订单

### 回测
- `回测 AU 2024-01-01 2024-03-01` - 执行回测
- `绩效` - 查看绩效

### 交易日志
- `记录` - 显示记录模板
- `复盘` - 生成复盘报告
- `统计 30` - 30天统计

## 配置

配置文件 `config.json`：

```json
{
  "system": {
    "log_level": "INFO",
    "mode": "local"
  },
  "market_analysis": {
    "ma_periods": [5, 10, 20, 60]
  },
  "risk_management": {
    "max_position_pct": 0.3
  },
  "feishu": {
    "app_id": "",
    "app_secret": ""
  }
}
```

## 与原项目的对比

| 项目 | 文件数 | 代码行数 | 特点 |
|------|--------|----------|------|
| futures_trading_system | ~20 | ~3000 | 完整的Agent架构，缺少飞书支持 |
| futures_trading_skills | ~25 | ~4000 | 飞书支持，代码分散 |
| **整合版** | ~15 | ~3500 | 统一架构，双重支持 |

## 后续计划

1. CTP实盘接口集成
2. 前端可视化界面
3. 策略优化模块
4. 机器学习信号
