# v2-agent-team 架构骨架

> 状态：骨架（结构 + 要点 + 空位），待镇哥补 / 改
> 来源：2026-07-31 详议（coach-talks/2026-07-28 §4.5 + 本日讨论）
> 基线：从 v1 @0ea641c 拉出 v2-agent-team 分支（v1 已封存）

## 0. TL;DR / 大原则

- **拆分**：工程化平台模式 → agent 工作流模式
- **不重建平台**：提取 v1 最值钱的引擎，其余封存
- **两条线分离**（对应 MOC）：个人验证线（自用）/ 产品化线（给别人）
- 本周复盘证明真缺口是**执行装置 + 引擎**，不是网页

## 1. 场景定位（与 TradingAgents 的差异）

| 维度 | TradingAgents（参考） | 本项目 |
|:--|:--|:--|
| agent 数量 | 多 agent（分析师/研究员/交易员/风控）辩论 | **单 agent + 多 skill**（AGENT_WORK 路由） |
| 编排框架 | LangGraph | 不引入（线性路由，LangGraph 是过度工程） |
| 实盘 | 只到模拟交易所 | 决策 + 条件单清单；实盘只自用 |

→ 本项目是"单 agent + 多 skill 线性流程"，没有多 agent 辩论回路，**不引入 LangGraph**。给别人那面用轻量 CLI 编排即可。若未来扩展到"多 agent 辩论"再考虑。

## 2. 三层架构

### 2.1 引擎层（portable Python，无 UI 依赖）
> 两线共用，只写一次。

| 模块 | 来源 v1 | 作用 |
|:--|:--|:--|
| compute_factors（三周期七因子） | tools/compute_factors.py | 周度因子快照 |
| verify_predictions | tools/verify_predictions.py | 预判命中率追踪 |
| data_query | tools/data_query.py | 数据查询 |
| collectors | collectors/ | 数据采集（akshare 国内 / fred 美债·TIPS） |
| **条件单清单生成器** 🆕 | 待建 | 事件前生成待挂触发单 + 止损单清单（执行装置） |

空位：
- [ ] 各模块输入/输出契约
- [ ] 数据源依赖清单（akshare 可替国内，fred 留美债/TIPS）
- [ ] 条件单清单的输出格式（文本/JSON）

### 2.2 编排层

| 面 | 形态 | 状态 |
|:--|:--|:--|
| 自用 | WorkBuddy skill 包（trade-factor-3d / 执行装置 / verify-predictions）+ AGENT_WORK 路由 | 已在跑，零迁移 |
| 给别人 | 轻量 CLI 编排（Python，按 AGENT_WORK 路由跑引擎模块） | 待建 |

空位：
- [ ] CLI 命令设计（子命令结构）
- [ ] 给别人是否带 LLM 步骤（决策需 LLM，引擎不需要）——影响交付是否含模型/key
- [ ] 配置项（品种 / 数据源 / 可选 LLM key）

### 2.3 展示层（静态 dashboard）

- 形态：**生成式静态网页**（dashboard.html 风格），非 SaaS、无交易交互
- tab：机会发现 / 信源 / 当前持仓 / agent 自学习进度
- 数据源：引擎输出的 JSON/md 快照
- 刷新：周节奏（守护后刷新）
- 纯展示

空位：
- [ ] 各 tab 具体字段
- [ ] 由谁/何时生成（守护末步？）
- [ ] 自用与给别人是否同一份

## 3. 交付物边界

| 项 | 自用 | 给别人 |
|:--|:--|:--|
| 因子快照 | ✅ | ✅ |
| 决策（带价位 / 止损 / 赔率） | ✅ | ✅ |
| 待挂条件单清单 | ✅ | ✅ |
| 实盘自动下单 | ✅（自己用） | ❌ 不交付 |
| 静态 dashboard | ✅ | ✅（只读） |

## 4. 分阶段

- **Phase 1（轻）**：trade-factor-3d skill + 执行装置（条件单清单）→ 验收 = 连续 2 周有快照且影响机会分级
- **Phase 2**：verify_predictions 进周五复盘（命中率追踪）
- **Phase 3**：vectorbt 最小回测（落 05 目录）
- 展示层 dashboard 随 Phase 1 产出逐步搭 tab

空位：
- [ ] Phase 1 时间盒
- [ ] dashboard 第一个 tab 优先级

## 5. 暂缓 / 重议条件

- 展现层 SaaS 化（多用户 / 实时交互）：暂缓
- 重议触发（满足任一）：① 账户连续 2 月正收益且回撤可控 ② 闭环跑满 8 周 ③ 出现第二个真实使用者且不会用 CLI
- LangGraph：若从"单 agent"扩展到"多 agent 辩论"再引入

## 6. 待镇哥拍板 / 补

- [ ] 本骨架认可？
- [ ] 给别人那面是否含 LLM 步骤（决定交付是否带模型/key）
- [ ] dashboard tab 优先级与字段
- [ ] Phase 1 时间盒
