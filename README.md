# 期货 AI 交易系统 V1

基于金银七因子归因模型的宏观分析系统。数据采集 → 因子对齐 → AI Agent 分析 + 记忆闭环。

---

## 系统架构

```
                    ┌──────────────────────┐
                    │        用户            │
                    └──────────┬───────────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
       ┌───────▼──────┐ ┌─────▼──────┐       │
       │  飞书机器人    │ │  Web 应用   │       │
       │ (即时/推送)   │ │ (深度分析)  │       │
       └───────┬──────┘ └─────┬──────┘       │
               │               │              │
               └───────┬───────┘              │
                       │                      │
              ┌────────▼────────┐   ┌─────────┴──────────┐
              │  后端 AI 引擎    │   │    交易档案          │
              │ (trade-macro)   │   │ (trading_archive/)   │
              │                 │   │ user_profile         │
              │  工具链:         │   │ positions            │
              │  data_query     │   │ trade_history        │
              │  compute_factors│   │ macro_memo           │
              │  analyze_macro  │   │ decisions            │
              └────────┬────────┘   └─────────────────────┘
                       │
              ┌────────▼────────┐
              │   数据基础层      │
              │  (采集器→因子)   │
              └─────────────────┘
```

---

## 数据采集（按数据源组织）

| 采集器 | 数据源 | 指标 | 频率 |
|--------|--------|------|:----:|
| `gold_api.py` | gold-api.com | 金银现货 | 5min |
| `yfinance_batch.py` | Yahoo Finance | DXY/US10Y/VIX/金银期货/原油/GLD/SLV/Fed Funds | 5min |
| `treasuries.py` | U.S. Treasury | 美债收益率 2Y/10Y/30Y | 每日 |
| `fred.py` | FRED | TIPS / CPI / Core PCE / HY Credit Spread | 每日 |
| `cboe_vix.py` | CBOE | VIX 日频历史 | 每日 |
| `fallback.py` | FRED + ExchangeRate-API | WTI原油/布伦特原油/铜/USD/CNY | 每日 |
| `china_futures.py` | AKShare/新浪 | 沪金/沪银 OHLC + 持仓量 | 每日 |
| `news_rss.py` | CNBC + MarketWatch | 新闻（七因子归类） | 30min |

```bash
# 一键运行所有采集器
python -m collectors.run

# 仅实时数据
python -m collectors.run realtime

# 仅日频数据
python -m collectors.run daily
```

---

## 因子对齐数据

数据通过 `compute_factors.py` 按七因子模型组织为结构化 JSON：

| 因子 | 指示指标 |
|------|---------|
| 机会成本 | TIPS / 名义利率 / FedWatch概率 |
| 货币 | DXY / USD/CNY |
| 避险需求 | VIX / 信用利差 / S&P 500 |
| 通胀预期 | 盈亏平衡通胀率 / CPI / PCE / 原油 / 铜 |
| 持仓动量 | COMEX OI / 沪金银 OI / GLD |
| 结构性需求 | 央行购金（手动） |
| 银价专用 | 金银比 / 白银库存 |

```bash
python tools/compute_factors.py          # 全量计算
python tools/compute_factors.py --pretty # 格式化输出到 stdout
python tools/data_query.py factors       # 通过查询 CLI 查看
```

---

## 分析工具

```bash
# 宏观信号合成（加权投票制）
python tools/analyze_macro.py
python tools/analyze_macro.py --json

# 品种归因
python tools/analyze_position.py --symbol all
```

---

## AI Agent 分析框架

| 文档 | 用途 |
|------|------|
| `Projects/交易Agent系统/1_宏观三维七因子归因框架.md` | 分析框架（七因子归因模型，位于 vault） |
| `docs/v1-Agent分析SOP.md` | 分析标准操作流程 |
| `docs/v1-数据中台设计.md` | 数据架构规范 |

交易档案位于 `wiki_trade/trading_archive/`（Obsidian vault 内），包含：
- `user_profile.md` — 用户画像
- `positions.md` — 当前持仓
- `macro_memo.md` — 宏观备忘录（每次分析更新）
- `trade_history.md` — 交易历史
- `decisions.md` — 决策复盘记录

---

## 项目结构

```
futures_trading_ai/
├── collectors/              # V1 采集器（按数据源命名）
│   ├── base.py
│   ├── gold_api.py / yfinance_batch.py / treasuries.py
│   ├── fred.py / cboe_vix.py / fallback.py
│   ├── china_futures.py / news_rss.py
│   └── run.py               # 统一采集总管
├── tools/                   # 分析工具
│   ├── data_query.py         # 统一数据查询 CLI
│   ├── compute_factors.py    # 因子对齐计算
│   ├── analyze_macro.py      # 宏观信号合成
│   └── analyze_position.py   # 品种归因
├── config/
│   ├── constants.py           # 项目常量
│   └── indicator_source.json # 指标注册表
├── data/                     # 数据中台
│   ├── current/              # dashboard 快照
│   ├── history/daily/        # 日频 CSV
│   ├── history/minutely/     # 分钟级 CSV
│   ├── events/               # 新闻/事件
│   └── factors/              # 因子对齐 JSON
└── docs/
    ├── v0/                   # V0 历史文档（归档）
    ├── 【MOC】FuturesTradingAI方案.md
    ├── v1-数据中台设计.md
    ├── v1-后端引擎设计.md
    ├── v1-Agent分析SOP.md
    └── （框架文档已迁移至 vault: Projects/交易Agent系统/1_宏观三维七因子归因框架.md）
```

---

## 开发状态

### ✅ 已完成（V1）

- V1 采集器统一命名（按数据源），统一 `python -m collectors.run` 运行
- run.py 后端感知频控（13 个后端独立 min_interval，按后端自动等待）
- 因子对齐数据管道（7 因子 → `current_factors.json`，含三周期信号计算）
- 统一直询 CLI `data_query.py`（snapshot/macro/factors/technical/history/events/news/realtime，含 `--refresh` 自动刷新）
- 宏观信号合成 `analyze_macro.py`（含 NFP 预期差修正、COT 替代判断）
- macro_memo.md 自动更新 — 分析完成后自动对比上次判断并写入记忆
- GLD/SLV ETF、FedWatch 概率 — yfinance 采集已实现
- COMEX 金银实时 OI — futures_sina.py 字段映射已修复
- 白银历史数据回填 — 数据连续至最新
- Dashboard — Flask + Jinja2 + Lightweight Charts 单页看板
- 飞书推送 — feishu/push.py 异动预警/晨报/事件提醒已实现
- 预判验证闭环 — tools/verify_predictions.py（745 行）
- 交易引擎 — trading/ 全套实现（engine/strategy/risk/order/backtest）
- news_by_factor / events_by_factor — data_query.py 命令已实现
- 分钟级 CSV 历史 — V1 已废弃（不再使用 minutely 级落盘）

### ⏳ 待完善

#### 🔴 数据源问题

- [ ] yfinance 429 限流 — 12-ticker 批量请求频繁触发 Yahoo 限流。方案：降低调用频率至 30s+，或减少 batch ticker 数量
- [ ] CBOE VIX SSL 偶发错误 — 日频采集偶发 SSL 连接失败，重试一般可恢复
- [ ] 华尔街见闻频控限制 — 单日调用次数有限，建议每日固定在 8:30 和 20:30 调用

#### 📡 数据覆盖缺口

- [ ] SGE 黄金现货 — `spot_hist_sge("Au99.99")` AKShare 可用但未接入 dashboard 和 factor 模型
- [ ] COT 持仓数据 — `macro_usa_cftc_c_holding` AKShare 可用但未集成到 factor 模型
- [ ] compute_factors.py 结构性需求因子 — `structural_demand` 数据块为空，央行购金数据需手动录入或接入新闻自动归类
- [ ] data_query.py news 结果为空 — latest_feed.json 格式可能与查询解析逻辑不匹配

#### 🔧 工程缺失

- [ ] generate_brief.py — 晨报/复盘自动生成工具尚未创建
- [ ] monitor_state.json 采集状态监控 — run.py 当前不写入各采集器运行状态和最后成功时间
- [ ] analyze_macro.py — 宏观信号合成脚本未实际验证输出质量
- [ ] 交易引擎 (trading/) 未与主系统集成 — 当前是独立模块，未被 collectors/tools 引用
- [ ] 飞书推送未集成到采集/分析流程 — feishu/push.py 代码到位但未对接 run.py 或 analyze_macro.py
- [ ] 定时晨报调度 — feishu/push.py 有 push_morning_brief() 但无定时 cron 调度
- [ ] 统一启动入口 — server.py/start.py 已被清理，缺少新的启动脚本

#### 🤖 Agent 分析闭环

- [ ] decisions.md 复盘写入 — 判断错误检测后未自动记录到决策档案
- [ ] WebSearch 信息入库 — 搜索发现的新概念/知识未沉淀到 wiki 知识库
- [ ] 无持仓时的建议优化 — 当前持仓评估无数据时，建议应基于资金管理原则给出参考

#### 🧹 代码清理
- [ ] README 项目结构图过时 — 采集器列表(旧名)、目录与实际代码不符
- [ ] SOP 文档被清理后 — 新框架文档（三维因子分析框架设计.md + 新闻事件模块设计.md）是否完全覆盖旧 SOP 内容需确认

---

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 运行全部采集器
python -m collectors.run

# 计算因子数据
python tools/compute_factors.py
```

---

## 数据源

| 数据源 | 使用范围 | 费用 |
|--------|---------|:----:|
| gold-api.com | 金银现货 | 免费 |
| Yahoo Finance | DXY/US10Y/VIX/金银期货/原油/ETF | 免费（需注意限流） |
| U.S. Treasury | 美债收益率曲线 | 免费 |
| FRED | TIPS / CPI / PCE / 信用利差 / 原油 | 免费 |
| CBOE | VIX 日频历史 | 免费 |
| ExchangeRate-API | USD/CNY | 免费（无需 key） |
| AKShare/新浪 | 沪金/沪银 OHLC + 持仓量 | 免费 |
| CNBC + MarketWatch | RSS 新闻 | 免费 |
