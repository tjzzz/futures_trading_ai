---
name: trade-data
description: "数据中台 — 4 业务块共用的取数层。collectors（akshare/fred/yfinance）+ data_query 查询入口。依赖 akshare/fred，给别人要装 requirements。"
metadata:
  version: 2.0.0
  tags: trading, data, akshare, fred
  source: "归集自 v1 collectors/ + tools/data_query.py"
---

# trade-data 数据中台

> 4 业务块（行情概览 / 机会探查 / 宏观分析 / 复盘归因）共用的取数层。
> **依赖**：akshare / fred / yfinance（非标准库，给别人要装 requirements）。
> **可移植性**：脚本可抽，但需装依赖（区别于宏观分析块的纯标准库内核）。

## 取数能力（对应 collectors/）
- 期货行情：futures_shfe / futures_sina（akshare）
- COMEX / 外盘：yfinance / spot_gold / spot_daily
- 宏观：macro_index / macro_nfp / macro_tips / treasury（fred / akshare）
- 新闻：collectors/news/（CNBC RSS 等）
- 查询入口：data_query.py（snapshot / macro / factors / history / events / news / technical / realtime）

## 路径约定
- cwd = 仓库根
- collectors 暂在 `collectors/`、data_query 在 `tools/data_query.py`（后续迁入 `skills/trade-data/scripts/`）
- 调用：`python tools/data_query.py <子命令>` / `python collectors/run.py`

## ⏳ 待办
- [ ] collectors 迁入 `skills/trade-data/scripts/`（Phase 2）
- [ ] data_query.py 迁入（同上）
- [ ] 给别人 requirements 清单
