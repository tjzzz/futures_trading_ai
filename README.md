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
| `docs/1_金银价格驱动因子体系.md` | 分析框架（七因子归因模型） |
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
    └── 1_金银价格驱动因子体系.md
```

---

## 开发状态

### ✅ 已完成（V1）

- V1 采集器 8 个（按数据源命名），统一 `python -m collectors.run` 运行
- V2 AKShare 主源重构：akshare_futures（COMEX 金银实时）、akshare_global（全球指数）、akshare_bond（美债收益率）、akshare_news（金十新闻+宏观日历）
- run.py 后端感知频控（13 个后端独立 min_interval，按后端自动等待）
- 因子对齐数据管道（7 因子 → `current_factors.json`，含三周期信号计算）
- 统一直询 CLI `data_query.py`（snapshot/macro/factors/technical/history/events/news）
- 宏观信号合成 `analyze_macro.py`
- AI Agent 分析 SOP（含输出模板、数据新鲜度规则、推理标注规则、异动归因流程）
- SOP 标准分析流程首次端到端测试通过（2026-06-08）
- 交易档案系统（`wiki_trade/trading_archive/`）
- 数据采集全链路跑通（15/15 采集器通过，20/25 dashboard 字段实时）

### ⏳ 待完善

#### 🔴 数据源问题

- [ ] 东方财富代理屏蔽 — `push2.eastmoney.com` 被系统代理（Clash X/Surge TUN模式）拦截，所有 akshare_global（DXY/SP500/VIX）和 akshare_bond（美债）请求失败。需在代理客户端将 `eastmoney.com` 加入直连/白名单
- [ ] yfinance 429 限流 — 12-ticker 批量请求频繁触发 Yahoo 限流，仅 1-2/12 成功。DXY、SP500、VIX 数据停滞 18 天。方案：降低 yfinance 调用频率至 30s+，或减少 batch ticker 数量
- [ ] investing.com API 变更 — `futures_foreign_hist` 已废弃，无法获取 COMEX 金银日频历史。替代方案：新浪期货日频或 FRED
- [ ] CBOE VIX SSL 偶发错误 — 日频采集偶发 SSL 连接失败，重试一般可恢复
- [ ] 华尔街见闻频控限制 — 单日调用次数有限，`macro_info_ws()` 频繁调用可能封 IP。建议每日固定在 8:30 和 20:30 调用

#### 📡 数据覆盖缺口

- [ ] GLD/SLV ETF、FedWatch 概率 — 依赖 yfinance，当前不可用。AKShare 是否有替代 source 待调研
- [ ] SGE 黄金现货 — `spot_hist_sge("Au99.99")` AKShare 可用但未接入 dashboard
- [ ] COT 持仓数据 — `macro_usa_cftc_c_holding` AKShare 可用但未集成到 factor 模型
- [ ] COMEX 金银实时 OI — akshare_futures 返回的 OI 为 0，需排查数据字段映射
- [ ] compute_factors.py 结构性需求因子 — `structural_demand` 数据块为空，央行购金数据需手动录入或接入新闻自动归类
- [ ] 白银历史数据不连续 — 3/27 ~ 5/18 数据缺失，需回填
- [ ] data_query.py news 为空 — `news` 和 `news_by_factor` 返回空结果，latest_feed.json 格式可能不匹配查询解析逻辑
- [ ] data_query.py technical spot_silver — 数据截至 5/20，不反映当前价格，需排查数据源更新

#### 🔧 工程缺失

- [ ] generate_brief.py — 晨报/复盘自动生成工具尚未创建
- [ ] 分钟级历史记录 — COMEX 实时数据（akshare_futures）未写入 minutely CSV 历史
- [ ] monitor_state.json 采集状态监控 — run.py 当前不写入各采集器运行状态和最后成功时间
- [ ] compute_factors.py — fedwatch_prob 字段为 null，待数据源恢复后接入
- [ ] analyze_macro.py — 宏观信号合成脚本未实际验证输出质量
- [ ] data_query.py news_by_factor — 查询结果为空，大概率是管道格式不匹配

#### 🤖 Agent 分析闭环

- [ ] macro_memo.md 自动更新 — SOP 分析完成后未写入记忆系统，需在 `step_memory` 阶段调用写入
- [ ] decisions.md 复盘写入 — 判断错误检测后未自动记录到决策档案
- [ ] WebSearch 信息入库 — 搜索发现的新概念/知识未沉淀到 wiki 知识库
- [ ] 无持仓时的建议优化 — 当前持仓评估无数据时，建议应基于资金管理原则给出参考

#### 🚀 第三波计划

- [ ] 飞书推送 — 异动预警推送到飞书 webhook
- [ ] Web 因子看板 — 七因子仪表盘实时展示
- [ ] 定时晨报 — 每日开盘前自动生成并推送

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
