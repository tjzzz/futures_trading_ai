# 数据基础设施设计回顾

> 合并自：data-architecture-proposal.md / data-pipeline-proposal.md / data-procurement-report.md
> 原始作者：宏观分析师（AI助手）| 整合日期：2026-05-21

---

## 一、架构决策记录

### 为何选 JSON + CSV 分层，不选数据库

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|:----:|
| JSON 快照 + CSV 历史 | 零依赖、前端直接读、易备份 | 不支持复杂查询 | ✅ 当前方案 |
| SQLite | 支持查询 | 多进程写入冲突、依赖库 | ❌ 否决 |
| MySQL/PostgreSQL | 完整 DB 能力 | 太重、依赖安装运维 | ❌ 否决 |

### 为何锁文件放 /tmp

iCloud Drive 的 O_EXCL 语义有 bug（0 字节锁文件残留），所以 SNAPSHOT_LOCK 移到 `/tmp/futures_trading_dashboard.json.lock`。高频采集器（yahoo_finance）进一步绕过锁，直接批量读写。

### 为何不引入消息队列

当前只有 5 个采集器、数据量极小，cron + 文件锁足够。如果未来采集器 > 20 个，才需要考虑 Redis/MQ。

---

## 二、数据源调研结论

详见 [data-master-map.md](../data-master-map.md) 一~三节，关键结论：

- **所有核心指标均可零成本获取**（gold-api + Yahoo Finance + FRED + Treasury + CBOE）
- CNBC 页面抓取做兜底已被 Yahoo Finance API 替代（更稳定）
- COMEX 白银库存因 CME 网络不可达，暂无免费自动化方案
- 国内指标（沪金溢价、社融、PMI）待 AKShare 接入

### 已验证不可用的源

| 原计划源 | 原因 | 替代方案 |
|---------|:----:|----------|
| CNBC 美债页面 | 403 反爬 | Yahoo Finance API |
| Investing.com | 403 反爬 | FRED CSV |
| CME 官网 | 网络不可达 | AllTick（待注册） |
| 新浪财经接口 | 接口失效 | AKShare（待安装） |

---

## 三、错误处理策略

| 场景 | 处理方式 |
|------|----------|
| 单一数据源超时/挂掉 | 跳过该字段，保留旧值，日志告警 |
| Treasury CSV 当天未更新 | 使用前一日数据，标记"昨日数据" |
| 所有外部源全挂 | 前端显示"待更新"，不白屏 |
| 部分采集器失败 | 不影响其他采集器写入 |

对应代码实现：`base_collector.py` 的 `run()` 方法（`self.logger.warning` + 保留旧值）。

---

## 四、数据生命周期

```
每5分钟采集
    ↓
写入 dashboard_data.json（覆盖当前值）
写入 minutely/xxx.csv（追加一行）
    ↓
每天凌晨 cleanup.py 执行
    ├── 从 minutely CSV 中删除 > 7天 的行
    └── 聚合当日数据到 daily/xxx.csv
```

> daily/monthly/quarterly 数据永久保留。

---

## 五、待扩展方向（尚未实施）

| 方向 | 前置条件 | 优先级 |
|------|---------|:------:|
| AKShare 接入（国内宏观/期货） | 安装 akshare 库 | 低 |
| AllTick 实时 WebSocket 行情 | 注册 API Key | 中 |
| monthly/ 目录开启（CPI/非农/PMI） | 接入月频数据源 | 低 |
| quarterly/ 目录开启（央行购金/GDP） | 手动录入或爬取 | 低 |
| 分钟级数据自动清理 | cleanup.py 已就绪，需配 cron | 低 |
| 多采集器并发冲突监控 | 当前锁机制已够用 | 低 |

---

*原始文档：archive/data-architecture-proposal.md / data-pipeline-proposal.md / data-procurement-report.md*
