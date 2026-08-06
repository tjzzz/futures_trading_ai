---
name: trade-data
description: "数据中台 — 4 业务块共用的取数层。data_query.py（realtime 直连主路径）+ collectors（akshare/fred/yfinance，v1 搬迁归档）。依赖 akshare/fred，给别人要装 requirements。"
metadata:
  version: 2.1.0
  tags: trading, data, akshare, fred
  source: "归集自 v1 collectors/ + tools/data_query.py（M2 2026-08-06 迁入）"
---

# trade-data 数据中台

> 4 业务块（行情概览 / 机会探查 / 宏观分析 / 复盘归因）共用的取数层。
> **依赖**：akshare / fred / yfinance（非标准库，先 `pip install -r skills/trade-data/requirements.txt`）。
> **可移植性**：脚本可抽，但需装依赖（区别于宏观分析块的纯标准库内核）。

## 运行入口（一条命令）

```bash
# 实时数据直查（主路径，不落盘）— ✅ 已实测
python skills/trade-data/scripts/data_query.py realtime all
#   gold/silver  → gold-api.com 金银现货 + akshare COMEX
#   macro        → fred/yfinance 宏观（DXY/VIX/GLD/SLV）
# 沪期货主力行情（直连 akshare）
python skills/market-overview/scripts/market_snapshot.py --markdown
```

## 子命令（data_query.py）

| 子命令 | 说明 | v2 状态 |
|:--|:--|:--|
| `realtime <源>` | 实时直查（gold/silver/comex/macro/all），主路径 | ✅ 实测通（8/6） |
| `snapshot` | 当前行情快照（读 v1 落盘 data/current） | ⚠️ 依赖 v1 数据，v2 由 market_snapshot 替代 |
| `macro` | 宏观摘要（读 v1 落盘） | ⚠️ 同上 |
| `technical` | 技术指标（读 v1 current_factors） | ⚠️ 同上 |
| `history` | 历史行情（读 v1 data/history） | ⚠️ 同上 |
| `analysis` | v1 四象限引擎 | ❌ 已废弃，由 macro-analysis compute_factors 替代 |
| `events/news/factors` | 读 v1 data/events 落盘 | ⚠️ 保留归档，无 v1 数据则空 |

## 路径约定
- cwd = 仓库根；脚本相对路径已改造（`parents[3]/parents[4]` 定位仓库根，不依赖运行目录）
- collectors 在 `skills/trade-data/scripts/collectors/`（v1 搬迁归档，部分接口与最新 akshare 未逐一验证；实际取数以 market_snapshot.py / compute_factors.py 直连写法为准）

## 依赖
- 见 `skills/trade-data/requirements.txt`

## ✅ 待办更新（M2 2026-08-06）
- [x] collectors + data_query.py 迁入 `skills/trade-data/scripts/`（相对路径改造）
- [x] realtime 主路径实测通过（金/银/COMEX/金银比，akshare 直连）
- [x] requirements.txt 依赖清单
- [ ] 各 collector 与最新 akshare 接口逐一适配（用到再改，随业务 skill 走）
