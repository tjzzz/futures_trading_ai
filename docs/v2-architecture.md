# v2-agent-team 架构

> 状态：Phase 1 进行中（骨架 + 宏观分析块已落地）
> 基线：从 v1 @0ea641c 拉出 v2-agent-team 分支（v1 已封存）
> 大原则：拆分（工程化平台 → agent 工作流模式）；单 agent + 多 skill，不引入 LangGraph

## 0. 总览

两层 + 其他：
- **skills 层**：4 大块 skill，每块 = `SKILL.md`（agent 规则）+ `scripts/`（可移植纯 Python 内核，不依赖 WorkBuddy）
- **web 展示层**：静态 dashboard，4 tab 对应 4 个 skill 流程
- **其他**：trading 模拟交易 / collectors 数据采集 / dashboard 生成器 / 实盘下单（自用）/ CLI 壳（给别人）

## 1. skills 层 4 大块

| 大类 | 归并来源（原 ~/.workbuddy/skills/） | scripts/ 可移植内核 | 状态 |
|:--|:--|:--|:--|
| 行情概览 | trade-info-intake + trade-macro-morning-briefing | collectors 取数 → 行情快照 | ⏳ Phase 2 |
| 机会探查 | commodity-scan + commodity-research + options-volatility + 🆕决策/条件单清单 | 条件单清单生成器 | ⏳ Phase 2 |
| 宏观分析/归因/事件预案 | trade-analysis-sop + trade-event-insight | compute_factors + verify_predictions + query_shfe（纯Python仅标准库） | ✅ Phase 1 |
| 复盘归因 | trade-weekly-review | verify_predictions（命中率统计） | ⏳ Phase 2 |

> 决策建议 + 条件单清单（执行装置）并入"机会探查"（机会→决策→条件单一条链）。

### 加载方式（自用）
symlink：仓库 `skills/<skill>` → `~/.workbuddy/skills/<skill>`。仓库里开发，软链回家目录加载，改一处即生效。

### 内核 / agent 分界
- **纯计算/取数**（compute_factors / verify_predictions / query_shfe / collectors）→ `scripts/` 可移植内核
- **需 agent 判断**（决策 / 归因 / 事件解读 / 复盘）→ `SKILL.md` 规则，agent 按 SKILL.md 调 scripts/

## 2. web 展示层

- 形态：**生成式静态网页**（dashboard.html 风格），非 SaaS、无交易交互
- 4 tab：行情 / 机会 / 宏观 / 复盘（与 skills 层一一对应）
- 数据源：各 skill 输出的 JSON/md 快照
- 刷新：周节奏（守护后刷新）
- 改造：v1 `dashboard/` 是 Flask 动态 → 重写为静态生成

## 3. 其他

| 模块 | 说明 | 本期 |
|:--|:--|:--|
| `collectors/` | 数据采集层（akshare/fred/yfinance），被 skills 调用 | 保留 |
| `trading/` | 模拟交易/回测引擎（v1 已有正收益） | 保留不动 |
| dashboard 生成器 | 聚合各 skill 输出 → 静态 html | ⏳ Phase 3 |
| 实盘下单 | 只自用，不进给别人交付 | 远期 |
| `cli/` | 给别人的 CLI 壳 + requirements | ⏳ Phase 4（重议触发） |

## 4. 仓库目录结构

```
futures_trading_ai/
├── skills/                # 4 大块 skill 源码（symlink 出去自用）
│   ├── market-overview/   # 行情概览        (SKILL.md + scripts/)
│   ├── opportunity/       # 机会探查（含决策+条件单清单）
│   ├── macro-analysis/    # 宏观分析/归因/事件预案  ✅ Phase1
│   └── review/            # 复盘归因
├── collectors/            # 数据采集层（akshare/fred）
├── tools/                 # 现有引擎脚本，逐步迁入对应 skill 的 scripts/
├── dashboard/             # web 展现层（Flask → 静态生成）
├── trading/               # 模拟交易/回测引擎
├── docs/                  # 本文档
├── data/                  # 数据（runtime log/state 已 gitignore）
└── cli/                   # 给别人的 CLI 壳（远期）
```

## 5. 自用 vs 给别人

| 项 | 自用 | 给别人 |
|:--|:--|:--|
| 4 块 skills | symlink + WorkBuddy agent 调 | 抽 `scripts/` 内核 + CLI 壳 |
| LLM 步骤 | agent 全程 | 仅"机会探查"决策步带 LLM，取数/计算不带 |
| dashboard | 自用看 | 只读给 |
| 实盘下单 | 自用 | 不交付 |
| trading 回测 | 自用验证 | 不交付（远期） |

## 6. 分阶段

- **Phase 1**（进行中）：骨架 + 宏观分析块（✅ scripts 验证可独立跑 + SKILL.md + symlink）+ 本文档重写
- **Phase 2**：搬其余 3 块（行情概览 / 机会探查 / 复盘归因），每块 symlink + 验证
- **Phase 3**：web 展现层（dashboard 静态生成，4 tab）
- **Phase 4**（远期/重议触发）：给别人 CLI 壳

## 7. 风险 / 待办
- **symlink 是否被 WorkBuddy 跟随**：下次会话验证 agent 能否调起 macro-analysis；不支持则回退 install 脚本同步
- **data_query.py 裁剪**（依赖 collectors 动态 import）：TODO，暂留 tools/
- **脚本内 data 相对路径**：部分脚本用相对路径写 `data/`，需改为相对仓库根或可配置，保证从 scripts/ 跑也正确读写
- 现有 skills 全无 scripts/，Phase 2 搬时要新增 scripts/ 并迁引擎
- v1 dashboard Flask → 静态生成：Phase 3 重写
