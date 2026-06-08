# 事件与新闻系统设计回顾

> 合并自：event-driven-macro-system.md / news-collection-system.md
> 原始作者：宏观分析师（AI助手）| 整合日期：2026-05-21

---

## 一、新闻采集现状

当前由 `rss_news.py` 实现，每 30 分钟采集 4 个 RSS 源：

| 源 | URL | 状态 |
|:--:|-----|:----:|
| MarketWatch | `feeds.content.dowjones.io/.../mw_topstories` | ✅ 稳定 |
| CNBC Politics | `www.cnbc.com/id/10000113/device/rss/rss.html` | ✅ 稳定 |
| CNBC Markets | `search.cnbc.com/.../id=10000664` | ✅ 稳定 |
| CNBC Economy | `search.cnbc.com/.../id=10000115` | ✅ 稳定 |

采集流程：拉取 → 关键词匹配归因（四象限）→ 强度评级（S/A/B/C）→ 写入 `latest_feed.json` + 更新 dashboard 事件摘要。

---

## 二、四象限事件映射规则

每则新闻通过关键词匹配归入一个或多个象限：

| 象限 | 事件类型 | 影响方向 |
|:----:|---------|:--------:|
| 🟢 货币锚 | 美债收益率突破/央行购金/DXY 波动/信用评级调整 | 美债信用↓→黄金↑ |
| 🔵 流动性 | Fed 利率决议/资产负债表变化/FRA-OIS 利差/财政政策 | 降息/扩表→金银↑ |
| 🟠 风险偏好 | 地缘冲突/美股暴跌/VIX 飙升/停火协议 | 避险↑→金银↑ |
| 🔴 供需博弈 | COMEX 交割/ETF 持仓/矿企停产/工业需求 | 供给↓→金银↑ |

详见 `rss_news.py` 中的 `QUADRANT_RULES` 和 `LEVEL_KEYWORDS_S`/`LEVEL_KEYWORDS_A`。

---

## 三、事件强度评级（S/A/B/C）

| 等级 | 定义 | 触发动作 | 示例 |
|:----:|------|---------|------|
| **S** | 颠覆性事件，改变宏观叙事 | 推送 + Dashboard 闪红 | 美债违约/美联储紧急降息 |
| **A** | 重大事件，显著影响因子 | 推送 + Dashboard 标记 | 30Y 破 5%/非农大幅不及预期 |
| **B** | 重要事件，确认/强化趋势 | 次晨汇总 | Fed 官员讲话/ETF 数据 |
| **C** | 常规事件，背景噪音 | 仅入库不推送 | 日常经济数据微幅波动 |

---

## 四、事件追踪库（手动维护）

`data/events/event_tracker.json` 结构：

| 字段 | 说明 | 维护方式 |
|------|------|---------|
| `active_events[]` | S/A 级事件详情 | 人工维护 |
| `events_to_watch[]` | 待观察升级事件 | 人工维护 |
| `quadrant_summary{}` | 各象限事件分布 | 自动统计 |

每个活跃事件含：`title` / `level` / `quadrant` / `status`（ongoing/resolved）/ `timeline[]` / `summary`。

---

## 五、待增强点（尚未实施）

| 功能 | 描述 | 优先级 |
|------|------|:------:|
| 情感打分 | RSS 事件做正/负面情感分析 | 中 |
| 经济日历匹配 | CPI/FOMC/NFP 发布时间自动识别 | 中 |
| S 级事件自动推送 | 通过飞书 @镇哥 | 低（需飞书增强） |
| 事件时间轴自动更新 | 同一事件跨多次采集合并追踪 | 低 |
| 中文财经源 | 财新/华尔街见闻 RSS | 低 |

---

*原始文档：archive/event-driven-macro-system.md / archive/news-collection-system.md*
