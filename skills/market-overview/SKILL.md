---
name: market-overview
description: "行情概览 — 每日/每周行情快照生成。取数（沪金/沪银/沪锌 + 现货金银比 + DXY/VIX）→ 一屏 Markdown 快照，供看板「一、行情概览与信息资讯」写回与周二深度定锚的基础素材。可移植内核 scripts/market_snapshot.py（akshare + 标准库）。"
metadata:
  version: 1.0.0
  tags: trading, overview, snapshot, gold, silver
  source: "v2-agent-team M3 里程碑（2026-08-05 建）"
---

# 行情概览（M3）

> v2-agent-team 5 大块 skill 之一（行情概览）。
> 定位：**取数 → 行情快照**，是周二深度定锚 / 每日基础守护的素材层，不是分析层（分析归 macro-analysis）。

## 工具
- 行情快照生成器：`python skills/market-overview/scripts/market_snapshot.py [--json|--markdown|--out <path>]`
  - 默认落盘 `data/snapshots/market_YYYYMMDD_HHMM.md`
  - `--json` 输出结构化 JSON（供其他脚本/看板解析）
- cwd = 仓库根 `/Users/zhenzhenzheng/zzz/work@AI/futures_trading_ai`

## 执行流程（基础守护内）
1. 跑 `market_snapshot.py --markdown` → 拿到一屏快照
2. 与看板「一」上次快照对比：金银锌价格、涨跌幅、金银比、DXY 变动
3. 标注关键变动（>1% 或突破关键位）→ 需要时转 macro-analysis 归因
4. 快照写回看板「一」最新事实；原始 md 留 `data/snapshots/`

## 输出格式（快照模板）
```markdown
## 行情快照 · YYYY-MM-DD HH:MM
- 沪银 白银连续：xxxxx（+x.xx%） 高 x / 低 x / 持仓 x 手 / HH:MM
- 沪金 黄金连续：xxxxx（+x.xx%） 高 x / 低 x / 持仓 x 手 / HH:MM
- 沪锌 沪锌连续：xxxxx（+x.xx%） 高 x / 低 x / 持仓 x 手 / HH:MM
- 现货：金 x / 银 x / 金银比 x
- 宏观：DXY x / VIX x
```

## 边界
- 快照只记录事实，不做归因判断（归因 = macro-analysis）
- 数据源失败时输出「暂无数据」，不脑补
- 行情速读是静默核对：只有触发红灯/通知才打扰镇哥

## ⏳ 待办
- [ ] 接入 trade-data 统一取数层（当前直连 akshare，M2 完成后切换）
- [ ] 与 macro-analysis 的 data_query.py snapshot 去重评估
- [ ] symlink 到 ~/.workbuddy/skills/market-overview 并验证 WorkBuddy 加载
