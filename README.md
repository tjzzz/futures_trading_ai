# 期货 AI 交易系统 V2

以黄金（XAU）为核心的宏观基本面分析系统，数据驱动的四象限分析引擎 + 事件监控 + Web 仪表盘。

---

## 架构概览

```
采集层（cron 调度） → 数据中台（data/） → 分析引擎 → 飞书 / 仪表盘
```

**设计原则**：

- **数据中台唯一** — 所有模块只从 `data/` 目录读文件，模块间不解耦，不传消息
- **采集器独立** — cron 调度，只做 `fetch → parse → 写文件`，不参与分析逻辑
- **分析可选择** — 规则引擎 / LLM 双模式，默认规则模式，运行时动态切换
- **飞书是前端入口之一** — 与仪表盘并列，不承载核心调度逻辑
- **不引入 Agent 通信框架** — 全通过文件解耦，无消息总线

## 数据流

```
cron → 采集器 → fetch() → parse()
                └──→ data/current/dashboard_data.json（快照）
                     └── data/history/ 下对应 CSV（历史）
                     └── data/events/（新闻+事件）

用户 → 飞书命令 → feishu/handlers.py → analysis 引擎 → 格式化回复
浏览器 → dashboard/app.py → REST API → analysis 引擎 → JSON
```

## 项目结构

```
futures_trading_ai/
├── collectors/              # 采集器（cron 调度，只写文件）
│   ├── base_collector.py    # 采集器基类
│   ├── gold_silver.py       # 金银行情（5分钟）
│   ├── daily.py             # 每日 Treasury/FRED/VIX
│   ├── rss_news.py          # RSS 新闻（30分钟）
│   ├── aggregate_daily.py   # 每日数据聚合
│   ├── backfill_2026.py     # 历史数据回填（一次性）
│   └── cleanup.py           # 历史数据清理
│
├── analysis/                # 宏观分析引擎
│   ├── __init__.py
│   ├── engine.py            # 统一入口（rules/llm 分发）
│   ├── rules/
│   │   └── macro.py         # 四象限规则分析
│   └── llm/
│       └── macro.py         # 四象限 LLM 分析
│
├── event_monitor/           # 事件监控（阈值检测）
│   ├── __init__.py
│   ├── monitor.py           # 检测 + 推送逻辑
│   └── thresholds.py        # 预设阈值定义
│
├── dashboard/               # Web 仪表盘（Flask）
│   ├── app.py               # Flask 后端（REST API）
│   ├── chart_builder.py     # 图表生成
│   └── templates/index.html # 单页 HTML（深色主题）
│
├── feishu/                  # 飞书集成
│   ├── __init__.py
│   └── handlers.py          # 命令解析与分发
│
├── shared/                  # 共享模块（旧组件，保留兼容）
│   ├── __init__.py
│   ├── config.py            # ⚠️ 已废弃，统一用根目录 config.py
│   ├── data_client.py       # 数据客户端
│   ├── feishu_bot.py        # 飞书机器人基类
│   └── indicators.py        # 技术指标计算
│
├── data/                    # 数据中台（唯一数据源）
│   ├── current/
│   │   └── dashboard_data.json  # 当前快照
│   ├── history/
│   │   ├── daily/           # 日频 CSV
│   │   └── minutely/        # 分钟级 CSV（7天滚动）
│   └── events/
│       ├── latest_feed.json     # RSS 新闻缓存（最近 100 条）
│       └── event_tracker.json   # 事件追踪数据
│
├── config.py                # 全局配置（ANALYSIS_MODE 等）
├── server.py                # 飞书 Webhook 服务器
├── start.py                 # 启动入口
├── requirements.txt
└── README.md
```

## 模块说明

### 1. 采集器（collectors/）

| 采集器 | 来源 | 频次 | 产出 |
|--------|------|------|------|
| `gold_silver.py` | gold-api.com | 5 分钟 | 金银实时行情 → 快照 + CSV |
| `daily.py` | Treasury.gov / FRED | 每日 7:30 | Treasury 收益率、VIX、DXY → 快照 + CSV |
| `rss_news.py` | CNBC / MarketWatch RSS | 30 分钟 | 新闻抓取 + 关键词分类 → 事件追踪 |
| `aggregate_daily.py` | 各 CSV | 每日 | 日频数据合并去重 |
| `backfill_2026.py` | 各数据源 | 一次性 | 回填 2026 年缺失的历史数据 |
| `cleanup.py` | — | 按需 | 清理过期历史数据 |

### 2. 分析引擎（analysis/）

统一入口 `analysis/engine.py`，通过 `config.py` 中的 `ANALYSIS_MODE` 配置分发：

```python
ANALYSIS_MODE = "rules"  # "rules"（默认）| "llm"
```

**规则模式**（`analysis/rules/macro.py`）：
基于四象限框架的硬编码规则判定：

| 象限 | 名称 | 核心指标 | 典型规则 |
|------|------|---------|---------|
| 🟢 货币锚 | Currency Anchor | 10Y/30Y Treasury, TIPS, DXY | 10Y > 4.5% → 利多黄金 |
| 🔵 宏观流动性 | Macro Liquidity | 2Y-10Y Spread, Fed Policy | 曲线倒挂 → 衰退信号 |
| 🟠 风险偏好 | Risk Appetite | VIX, S&P 500 | VIX > 25 → 恐慌利多 |
| 🔴 供需博弈 | Supply-Demand | 金银比, COMEX | 金银比 > 75 → 白银低估 |

**LLM 模式**（`analysis/llm/macro.py`）：
将快照数据 + 历史 CSV + 新闻组装为 prompt，调用 OpenAI API 输出结构化分析结果（格式与规则模式对齐）。

**接口**：

```python
engine = Analysis()
engine.analyze()           # → 四象限综合判断
engine.query_indicator("10Y", "2026-04-01", "2026-05-19")  # → 归因报告
engine.get_trend("金银比", 90)  # → 趋势数据
engine.handle_command("归因 10Y 2026-04-01 2026-05-19")    # → 飞书命令
```

### 3. 事件监控（event_monitor/）

阈值检测模块，从快照对比预设阈值生成 S/A 级事件。

| 指标 | warn 阈值 | crisis 阈值 |
|------|----------|------------|
| 10Y Treasury | > 4.5% | > 5.0% |
| VIX | > 25 | > 35 |
| 金银比 | > 75 | > 85 |
| XAU 日内波动 | > 3% | > 5% |

特性：24h 防重复推送、同方向升级检测、状态持久化（`monitor_state.json`）。

### 4. 仪表盘（dashboard/）

Flask Web App（端口 8082），深色主题单页应用，Chart.js 图表渲染，无额外前端框架。

**页面布局**：

```
┌─ 左侧导航栏 (240px) ─────────────────────────────────┐
│  期货 AI 交易体系                                       │
│  ├ 总览                                                │
│  ├ 四象限宏观                                          │
│  ├ 指标归因                                            │
│  ├ 事件中心                                            │
│  └ 配置                                                │
├─ 主内容区 ──────────────────────────────────────────────┤
│  顶部栏：页面标题 + 副标题 + 标签（分析模式/品种）        │
│  内容区：                                                │
│  ├ 概览页 → 四象限卡片 2×2 + 综合场景标签                │
│  ├ 宏观页 → 四象限详情 + mini 趋势图                    │
│  ├ 归因页 → 指标选择 + 日期区间 + 归因报告               │
│  ├ 事件页 → 活跃事件列表 + 历史事件                      │
│  └ 配置页 → 分析模式切换 + 阈值设置                      │
└─────────────────────────────────────────────────────────┘
```

**API 端点**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 仪表盘主页面 |
| `/api/data` | GET | 当前数据快照 |
| `/api/macro` | GET | 四象限综合分析 |
| `/api/history?indicator=X&days=Y` | GET | 指定指标历史趋势 |
| `/api/attribution` | POST | 指标归因查询 |
| `/api/events` | GET | 活跃事件列表 |
| `/api/config` | GET / POST | 配置读取/更新 |
| `/api/health` | GET | 健康检查 |

### 5. 飞书集成（feishu/）

飞书 Webhook 服务器（端口 8080），支持以下命令：

| 命令 | 说明 | 示例 |
|------|------|------|
| `宏观` | 四象限综合分析 | `宏观` |
| `归因 <指标> <开始> <结束>` | 指标区间归因 | `归因 10Y 2026-04-01 2026-05-19` |
| `趋势 <指标> [天数]` | 趋势分析 | `趋势 金银比 90` |
| `事件 [S/A]` | 活跃事件列表 | `事件 S` |
| `监控 status` | 阈值状态 | `监控 status` |
| `监控 check` | 执行一次检测 | `监控 check` |

**消息执行链路**（以用户发「黄金为什么大跌」为例）：

```
用户 @飞书机器人 "黄金为什么大跌"
  ↓
① server.py 收到飞书 POST /webhook
   └→ RequestHandler.do_POST() 解析 JSON body
  ↓
② feishu/handlers.py 命令分发
   └→ 提取文本，匹配命令前缀
   └→ 匹配 "归因"、"趋势"、"宏观" → 走 analysis 引擎
   └→ 无匹配 → 走原有 UnifiedBot 路由（兼容旧命令）
  ↓
③ analysis/engine.py 分析入口
   └→ 读取 data/current/dashboard_data.json（最新快照）
   └→ 读取 data/history/ 下相关 CSV（历史趋势）
   └→ 读取 data/events/latest_feed.json（最近新闻）
  ↓
④ 分析模式分发
   └→ 规则模式：rules/macro.py 四象限规则判定
   └→ LLM 模式：组装 prompt → HTTP POST 调用 LLM API
  ↓
⑤ 结果返回 → 格式化 → 飞书私信回复用户
```

**关键设计**：`analysis/engine.py` 是纯函数模块，不持有飞书连接，不做 `send_message`。LLM 模式仅通过 HTTP API 调用，不经过 Agent 或消息总线。整条链路只发 1 次消息。

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.py`（或通过环境变量覆盖）：

```bash
# 分析模式
ANALYSIS_MODE="rules"     # "rules" | "llm"

# LLM 模式需配置（可选）
LLM_API_KEY="sk-xxx"
LLM_API_URL="https://api.openai.com/v1/chat/completions"
LLM_MODEL="gpt-4o"

# 飞书配置（可选）
FEISHU_APP_ID="cli_xxx"
FEISHU_APP_SECRET="xxx"
```

### 3. 启动服务

```bash
# 启动飞书 Webhook 服务器（端口 8080）
python start.py

# 启动仪表盘服务器（端口 8082，另开终端）
python -m dashboard.app --port 8082
```

### 4. 手动运行采集器（可选）

```bash
python -m collectors.gold_silver    # 金银行情
python -m collectors.daily          # 每日数据
python -m collectors.rss_news       # RSS 新闻
```

### 5. 配置 cron 调度（生产环境）

```bash
# 金银行情 — 每 5 分钟
*/5 * * * * cd /path/to/project && python -m collectors.gold_silver

# 每日 Treasury/FRED/VIX — 每天 7:30
30 7 * * * cd /path/to/project && python -m collectors.daily

# RSS 新闻 — 每 30 分钟
*/30 * * * * cd /path/to/project && python -m collectors.rss_news
```

### 6. 事件监控测试

```bash
python -m event_monitor.monitor     # 检查当前阈值状态
```

## 配置

全局配置（`config.py`）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ANALYSIS_MODE` | `"rules"` | 分析模式：rules / llm |
| `LLM_API_KEY` | `""` | LLM API Key |
| `LLM_API_URL` | OpenAI 端点 | LLM API 地址 |
| `LLM_MODEL` | `"gpt-4o"` | LLM 模型 |
| `FEISHU_APP_ID` | `""` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | `""` | 飞书应用 Secret |
| `FEISHU_WEBHOOK_PORT` | `8080` | 飞书 Webhook 端口 |

所有配置项支持环境变量覆盖。

## 实现路线图

| Phase | 内容 | 产出 |
|-------|------|------|
| 1 | 移植采集器（base_collector → gold_silver/daily/rss_news） | 数据正常收集到文件 |
| 2 | 实现 analysis rules 模式 + engine.py 开关架构 | 飞书可查宏观/归因/趋势 |
| 3 | 前端仪表盘（深色主题 + 四象限卡片） | 浏览器可看宏观仪表盘 |
| 4 | analysis llm 模式接入 + event_monitor | 可切换 LLM 分析 + 事件推送 |

> 当前状态：Phase 1-3 已完成，Phase 4（LLM 模式 + 事件监控）持续推进中。

## 变更说明

### V1 → V2 主要变化

1. **架构重构**：去掉 Agent 通信框架，改为纯数据流驱动
2. **模块简化**：`core/`、`skills/` 等旧模块废弃，现有 `collectors/` + `analysis/` + `dashboard/` + `event_monitor/`
3. **配置统一**：所有配置收敛到根目录 `config.py`，`shared/config.py` 已废弃
4. **飞书精简**：V2 命令（宏观/归因/趋势/事件/监控）直接路由到 analysis 引擎，V1 Agent 路由已移除
5. **数据中台**：`data/` 目录作为唯一数据源，所有模块只从文件读
6. **双模式分析**：规则引擎（默认）和 LLM 分析两种模式，运行时动态切换

---

## 代码质量修复记录

### 2026-05 批量修复（代码审查）

| 问题 | 严重度 | 文件 | 修复内容 |
|------|--------|------|----------|
| 非排他文件锁 | 🔴 | `collectors/rss_news.py` | `tmp.replace()` 替换为 `os.open(O_CREAT\|O_EXCL)` 真正排他锁，与 `base_collector` 共享同一锁文件 |
| 写入竞争 | 🔴 | `collectors/rss_news.py` | 锁实现与 `base_collector.write_snapshot` 统一，避免并发脏写 `dashboard_data.json` |
| Mock 静默降级 | 🟡 | `shared/data_client.py` | TuShare/AKShare 降级到 Mock 时记录 `logger.warning()`，附带降级原因 |
| print() 代替 logging | 🟡 | `collectors/rss_news.py`、`collectors/daily.py` | 全部 `print()` 替换为 `logger.info/warning/error` |
| Linux 硬编码字体 | 🟡 | `dashboard/chart_builder.py` | `_FONT_CANDIDATES` 新增 macOS 路径（PingFang、STHeiti、Homebrew wqy） |
| 空字符串拼接 | 🟡 | `analysis/engine.py` | `_format_trend` 中条件 `"变动幅度" if len>=2 else ""` 改为条件 `append`，避免无效空行 |
| 废弃代码导出 | 🟡 | `shared/config.py`、`shared/__init__.py` | config.py 加运行时 `DeprecationWarning`；`__init__` `__all__` 移除飞书导出 |
| 数据新鲜度日志 | 🟡 | `collectors/daily.py` | `run_all_daily()` 改用 logger 输出，不再直接 print
