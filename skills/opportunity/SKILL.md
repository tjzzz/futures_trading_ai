---
name: opportunity
description: "机会探查 — 新机会发现 + 决策 + 条件单清单（执行装置）。扫描候选分级（S/A/B/C + 三板斧）→ 决策规则 → 生成可挂单的条件单清单，解决'预案判断对但无预埋单踏空'的执行缺口（R4 补充条款）。可移植内核 scripts/order_list_gen.py（纯 Python 标准库）。"
metadata:
  version: 1.0.0
  tags: trading, opportunity, scan, order-list, execution
  source: "v2-agent-team M4 里程碑（2026-08-07 建）"
---

# 机会探查（M4）

> v2-agent-team 5 大块 skill 之一（机会探查）。
> 定位：**候选分级 → 决策 → 条件单清单**，输出可直接挂单的执行装置。
> 决策 + 条件单清单（执行装置）并入本块；纯数据扫描可参考 `trade-commodity-scan-sop`。

## 工具
- 条件单清单生成器：`python skills/opportunity/scripts/order_list_gen.py --plan <plan.json> [--out <out.md>]`
  - 输入：结构化预案 JSON（plan_name/symbol/contract/direction/hands/trigger_low/trigger_high/stop/target/risk_per_hand/valid_until…）
  - 输出：Markdown 条件单清单（触发单 + 止损单 + 目标单 + Elder 2% 风险校验 + 失效条件）
  - `--demo` 可看内置示例（非农 B 预案）；参数校验失败会报错退出
- cwd = 仓库根 `/Users/zhenzhenzheng/zzz/work@AI/futures_trading_ai`

## 候选分级（S/A/B/C）
- **S 级**：可进入交易计划——三板斧 3/3，具备明确入场区间、止损位、目标位、赔率、仓位建议、失效条件 → 生成条件单清单
- **A 级**：重点观察——逻辑清晰但缺价格触发 / 事件确认 / 赔率改善 → 看板"二"跟踪，不打扰镇哥
- **B 级**：只记录逻辑，暂不跟踪；数据强化后再升级
- **C 级**：剔除并记录原因（防重复研究伪机会）
- 入选 ≥3 个时全部列出；同产业链 / 同宏观因子候选须标注相关性风险（不能把高相关品种当分散）

## 执行流程（周二全量扫描 / 事件前触发）
1. 扫描（`trade-commodity-scan-sop` 或事件预案）→ 候选清单，分级 + 三板斧分值 + 核心驱动/风险
2. 对 S 级候选走决策规则：
   - 宏观因子定方向，技术面定时机（close/MA20 趋势 + 事件窗口）
   - 二元事件原则：赌"落地后的错误定价修正"，不赌方向本身
   - 每笔必须有硬止损 + 最大亏损测算，否则不给建议
3. **生成条件单清单**（本 skill 核心价值）：把 S 级计划参数化 → `order_list_gen.py` 输出触发单/止损单/目标单
4. 清单给镇哥授权后挂单（经纬不替挂）

## 输出格式
```markdown
候选清单：
品种 | 方向 | 等级 | 三板斧 | 走势标签 | 核心驱动 | 核心风险
S 级条件单清单（由 order_list_gen.py 生成）：
- 触发单 / 止损单 / 目标单 / 手数
- 风险校验（Elder 2%）/ 赔率三档 / 失效条件
看板写回：二、新机会发现
长期沉淀：02_机会池/
```

## 边界
- 只输出清单与建议，**不替镇哥挂单**（实盘需明确授权）
- 无数据时写「暂无数据」，不脑补
- 与 macro-analysis 分工：宏观归因/事件预案归 macro-analysis；本块承接"机会 → 决策 → 执行装置"

## ⏳ 待办
- [ ] 接入 trade-data 统一取数层（当前直接读预案 JSON）
- [ ] 与 trade-commodity-scan-sop 的扫描输出对接（自动生成候选 JSON → 批量生成清单）
- [ ] symlink 到 ~/.workbuddy/skills/opportunity 并验证 WorkBuddy 加载
- [ ] A 级 → S 级的自动升级提示（事件窗口临近时提醒重新评估）
