---
name: macro-analysis
description: "宏观分析/归因/事件预案 — 金银七因子归因 SOP + 短线异动归因 + 事件洞察。可移植内核在 scripts/（compute_factors/verify_predictions/query_shfe，纯 Python 仅标准库）。详细 SOP 全文见 SOP_reference.md 与 event-insight_reference.md。"
metadata:
  version: 2.0.0
  tags: trading, gold, silver, macro, sop, futures
  source: "合并自 trade-analysis-sop + trade-event-insight（v1 → v2-agent-team）"
---

# 宏观分析 / 归因 / 事件预案

> v2-agent-team 4 大块 skill 之一（宏观分析）。
> **可移植内核**（`scripts/`，纯 Python 仅标准库，给别人可直抽）：`compute_factors.py` / `verify_predictions.py` / `query_shfe.py`
> **依赖 collectors 的部分**：`tools/data_query.py`（保留在仓库 tools/，因动态 import collectors，akshare/fred 依赖）
> 详细 SOP 全文：`SOP_reference.md`（七因子标准分析 + 异动归因）、`event-insight_reference.md`（事件洞察）

## 工具路径约定
- cwd = 仓库根 `/Users/zhenzhenzheng/zzz/work@AI/futures_trading_ai`
- 可移植内核：`python skills/macro-analysis/scripts/<脚本>.py`
- data_query（依赖 collectors）：`python tools/data_query.py <子命令>`

## 场景路由

| 场景 | 执行 |
|:--|:--|
| 日常分析 / 主动问行情 | 标准分析流程（六步） |
| 异动归因（急涨急跌） | 短线异动归因流程 |
| 重大事件专题 | 事件洞察流程（见 event-insight_reference.md） |

## 一、标准分析流程（六步骨架）

> 完整规则（数据新鲜度判断、推理标注 `(数据)/(推断)/(经验)/(猜测)🚫`、输出格式模板、记忆更新）见 `SOP_reference.md`。

1. **宏观体检** — `data_query.py snapshot` + `macro` → 一句话概括当前状态，与 macro_memo 上次判断对比
2. **因子深度分析** — `scripts/compute_factors.py` → 七因子（机会成本/货币/避险/通胀预期/持仓动量/结构性需求/银价专用）方向 + 强度 + 关键证据
3. **技术面验证** — `data_query.py technical` + `history <品种> 30` → 趋势/动量/关键位，与因子信号双层对照
4. **场景分类** — `compute_factors.py` 看 short/mid/long 信号 → 趋势驱动 / 情绪事件驱动 / 震荡噪音 / 回调 / 转折
5. **信息增量** — `data_query.py events` + `news_by_factor <主导因子>` + WebSearch（知识库不足时）
6. **场景推演 & 输出** — 基准/偏多/偏空三情景（概率+触发+影响）+ 持仓建议 + 风险提示

**记忆更新**：每次分析后覆写 macro_memo 当前判断 + 追加历史记录 + `verify_predictions.py add_prediction_entry` 记预判。

## 二、短线异动归因（日内 >1% 金 / >2% 银）

六步：确认异动参数 → 事件排查（`data_query.py events/news` + 交易时段判断）→ 因子快速排查（TIPS/DXY/VIX/OI 四层）→ 预期评估（ATR 区间）→ 持仓影响 → 输出。

> 详细输出格式、交易时段表、升级条件见 `SOP_reference.md` 短线异动归因流程。

## 三、事件洞察（重大事件专题）

触发：地缘 / 宏观 / FOMC / 重大数据。流程：SHFE 实时行情（`scripts/query_shfe.py`）+ COMEX 兜底（gold-api）+ CNBC 新闻采集 + 持仓盈亏分析 + 归因 + 报告生成。

> 完整 SOP 见 `event-insight_reference.md`。

## 工具调用速查

| 用途 | 命令（cwd=仓库根） | 可移植 |
|:--|:--|:--:|
| 七因子计算 | `python skills/macro-analysis/scripts/compute_factors.py [--factor X] [--pretty]` | ✅ |
| 预判验证 / 命中率统计 | `python skills/macro-analysis/scripts/verify_predictions.py [--stats-only] [--json]` | ✅ |
| SHFE 沪金沪银实时 | `python skills/macro-analysis/scripts/query_shfe.py [silver\|gold\|AG2612]` | ✅ |
| 数据快照/宏观/因子/技术/事件/新闻 | `python tools/data_query.py <子命令>` | ❌ 依赖 collectors |

## 可移植内核说明（给别人交付）

`scripts/` 下三脚本是纯 Python（仅标准库 / 零外部依赖），给别人时直接抽 + CLI 壳即可，不需 WorkBuddy。`data_query.py` 因依赖 collectors（akshare/fred），留在仓库 `tools/`，给别人时需带 collectors + 装 requirements。

## ⏳ 待办（本期遗留）
- [ ] `data_query.py` 裁剪：剥离 collectors 动态 import，抽出纯查询部分进 scripts/（或保留 tools/ 但文档化依赖）
- [ ] 脚本内 data 路径：当前部分脚本用相对路径写 `data/`，需改为相对仓库根或可配置，保证从 scripts/ 跑也能正确读写 data/
- [ ] symlink 到 ~/.workbuddy/skills/macro-analysis 后，下次会话验证 WorkBuddy 能否加载 + agent 能否按本 SKILL.md 调起
