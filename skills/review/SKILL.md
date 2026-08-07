---
name: review
description: "复盘归因 — 可验证假设命中率统计 + 交易复盘。记录 H1-H3 类可验证假设（方向+区间+验证窗口）→ 到期后自动验证命中/偏离 → 输出命中率统计与偏差归因，喂周六周报与因子权重反思。可移植内核 scripts/prediction_stats.py（纯 Python 标准库 + akshare 可选）。"
metadata:
  version: 1.0.0
  tags: trading, review, hypothesis, hit-rate, attribution
  source: "v2-agent-team M5 里程碑（2026-08-07 建）"
---

# 复盘归因（M5）

> v2-agent-team 5 大块 skill 之一（复盘归因）。
> 定位：**假设命中率闭环**——把每次分析/预案里的可验证假设（H1/H2/H3…）结构化记录，到验证窗口自动结算，让"判断准不准"用数据说话（替代 v1 verify_predictions.py 的落盘依赖）。

## 工具
- 假设命中率统计：`python skills/review/scripts/prediction_stats.py [--verify|--stats|--add ...]`
  - 数据文件：`data/predictions.json`（假设记录）
  - `--verify`：对已过窗口未验证的假设，用 akshare 实时价结算方向/区间命中
  - `--stats`：输出命中率统计（方向/区间/按标签分桶）
  - `--add`：追加一条假设（方向 区间 窗口 标签）
  - 纯标准库可跑（`--prices` 手传价格时），akshare 不可用则跳过验证只出统计
- cwd = 仓库根 `/Users/zhenzhenzheng/zzz/work@AI/futures_trading_ai`

## 假设记录格式（data/predictions.json）
```json
{
  "hypotheses": [
    {
      "id": "W32-H2",
      "created_at": "2026-08-06",
      "label": "定价重心切就业",
      "direction": "bullish",          // bullish/bearish/neutral（对金银）
      "target_symbol": "silver",        // silver/gold
      "price_at_analysis": 62.51,
      "range_low": 60.0,
      "range_high": 65.0,
      "verify_by": "2026-08-08",        // 验证窗口截止
      "verified": false,
      "result": null
    }
  ]
}
```

## 执行流程（周六复盘 / 周二定锚后）
1. 每次定锚/预案更新后，把可验证假设用 `--add` 记入（H1-H3 对应看板"一"）
2. 周六复盘：`--verify` 结算已过窗口假设 → 看命中率
3. `--stats` 出统计 → 写周报"预判命中率"节 + 看板"三"
4. 连续 miss 的假设 → 反思归因（判断错/时机错/数据源错），调整后续假设粒度

## 输出格式
```markdown
预判命中率（W32）：
- 已验证 N 条，方向命中 X 条（X%），区间命中 Y 条（Y%）
- 按标签：地缘/就业/突破 …
- 未命中明细：H-x 预期 bullish → 实际 bearish（归因：…）
看板写回：三、交易管理与复盘
长期沉淀：03_交易管理/交易&复盘.md
```

## 边界
- 假设验证只对"已过窗口"的结算，窗口未到不提前判定
- 价格缺失时输出「暂无数据」不脑补；akshare 失败可手传 `--prices`
- 命中率是复盘输入，不是行情预测；不因单次 miss 否定假设体系

## ⏳ 待办
- [ ] 与 macro-analysis 的 compute_factors 假设自动衔接（定锚后自动 add）
- [ ] 命中率异常（<50%）自动触发归因模板
- [ ] symlink 到 ~/.workbuddy/skills/review 并验证 WorkBuddy 加载
