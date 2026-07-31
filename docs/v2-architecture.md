# v2-agent-team 架构

> 仓库：github `tjzzz/FuturesTradingAI`（更名中，原名 futures_trading_ai）；v2-agent-team 分支，v1 封存 @0ea641c
> 大原则：拆分（工程化 → agent 工作流）；单 agent + 多 skill，不上 LangGraph

## skills 层（5 块）

| 大类 | scripts/ 内核 | 状态 |
|:--|:--|:--|
| trade-data 数据中台 | collectors + data_query（akshare/fred，需装依赖） | ⏳ |
| 行情概览 | collectors 取数 → 行情快照 | ⏳ |
| 机会探查 | 条件单清单生成器（+ 决策/归因 agent 规则） | ⏳ |
| 宏观分析/归因/事件预案 | compute_factors + verify_predictions + query_shfe（纯Python仅标准库） | ✅ Phase1 |
| 复盘归因 | verify_predictions 命中率统计 | ⏳ |

- 每 skill = `SKILL.md`（agent 规则）+ `scripts/`（可移植内核，不依赖 WorkBuddy）
- **trade-data 是底层公共取数层**，其余 4 块业务 skill 调它
- 决策 + 条件单清单（执行装置）并入"机会探查"
- 自用加载：`skills/<skill>` symlink → `~/.workbuddy/skills/<skill>`

## web 展示层
- 静态 dashboard，4 tab（行情/机会/宏观/复盘），从各 skill 输出快照生成，周节奏刷新
- v1 `dashboard/`（Flask）→ 重写为静态生成

## 自用 vs 给别人
| 项 | 自用 | 给别人 |
|:--|:--|:--|
| skills | symlink + WorkBuddy agent | 抽 `scripts/` 内核 + CLI 壳 |
| LLM | agent 全程 | 仅"机会探查"决策步 |
| 实盘下单 | 自用 | 不交付 |
| trading 回测 | 自用验证 | 不交付 |

## 分阶段
- Phase 1 ✅ 骨架 + 宏观分析块 + symlink + 文档
- Phase 2 搬其余 4 块（trade-data / 行情 / 机会 / 复盘），collectors 迁入 trade-data
- Phase 3 web 静态 dashboard（4 tab）
- Phase 4 给别人 CLI 壳（远期 / 重议触发）

## 待办
- 下次会话验证 macro-analysis symlink 加载；不通则回退 install 脚本
- collectors / data_query 迁入 `skills/trade-data/scripts/`（Phase 2）
- 脚本内 data 相对路径改造
- github 仓库改名后更新本地 remote URL
