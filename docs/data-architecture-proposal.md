# 数据中台架构设计 v0.2
> **作者：宏观分析师（AI助手）**

> 统一管理所有数据源的采集、存储与消费
> 支撑宏观看板 + 其他数据消费场景

---

## 一、核心问题

### 痛点
1. **多数据源**：gold-api（实时）、FRED（日频）、Treasury（日频）、CBOE（日频）、未来还会有AKShare/Tushare（国内宏观/股票）
2. **不同时间粒度**：实时价格（每分钟级别）、日频指标（每天更新）、月频指标（社融/M2/PMI）、季度数据（GDP/央行购金）
3. **不同延迟**：Treasury T+1、FRED T+2、CPI/GDP发布有固定日程
4. **多消费场景**：Web看板要最新快照、后续可能要历史趋势图、可能要导出分析

### 一个JSON文件的限制
现在的 `dashboard_data.json` 只存当前快照，没有历史，扩展性不够。但全量上数据库又太重。

---

## 二、推荐方案：分层数据存储

```
┌──────────────────────────────────────────────────┐
│              数据消费层 (Consumer)                  │
│  Dashboard Web │ 快照文件 │ 日/周报 │ 交易决策     │
└──────────────────────┬───────────────────────────┘
                       │ 读取
┌──────────────────────▼───────────────────────────┐
│             快照层 (Snapshot)                       │
│  📄 dashboard_data.json                          │
│  → 只存当前最新值，前端直接消费                      │
│  → 每次采集都覆盖更新                               │
│  → 格式固定，面向展示                               │
└──────────────────────┬───────────────────────────┘
                       │ 写入最新值
┌──────────────────────▼───────────────────────────┐
│             历史层 (History)                        │
│  📁 data/history/                                 │
│  ├── minutely/         ← 分钟级，仅保留近7天         │
│  │   └── gold_silver_minutely.csv                 │
│  ├── daily/            ← 天级，持续保留              │
│  │   ├── gold_silver_daily.csv                    │
│  │   ├── treasury.csv                             │
│  │   ├── vix.csv                                  │
│  │   ├── dxy.csv                                   │
│  │   ├── tips.csv                                  │
│  │   └── sp500.csv                                 │
│  ├── monthly/          ← 月度级，持续保留            │
│  │   ├── china_cpi.csv                            │
│  │   ├── china_pmi.csv                            │
│  │   ├── us_cpi.csv                               │
│  │   └── us_nonfarm.csv                           │
│  └── quarterly/        ← 季度级，持续保留            │
│      ├── central_bank_gold.csv                    │
│      └── china_gdp.csv                            │
│  → CSV格式，便于追加和分析                           │
│  → 按时间粒度分层，不同保留策略                       │
└──────────────────────┬───────────────────────────┘
                       │ 写入原始/处理后数据
┌──────────────────────▼───────────────────────────┐
│             采集层 (Collector)                      │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │ 实时采集器  │ │ 日频采集器  │ │ 月度采集器    │  │
│  │ realtime.py│ │ daily.py   │ │ monthly.py   │  │
│  │ cron: */5  │ │ cron: 7:30 │ │ cron: 发布日  │  │
│  └────────────┘ └────────────┘ └──────────────┘  │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│             数据源层 (Sources)                      │
│  gold-api │ Treasury │ FRED │ CBOE │ AKShare ...  │
└───────────────────────────────────────────────────┘
```

---

## 三、各层级数据结构

### 快照层 (dashboard_data.json) — 面向展示

只存"当前最新值"，前端不需要了解数据来源的复杂性。

```json
{
  "gold_price": {
    "value": 4549.30,
    "unit": "USD/oz",
    "updated_at": "2026-05-18 16:00:00"
  },
  "silver_price": {
    "value": 76.19,
    "unit": "USD/oz",
    "updated_at": "2026-05-18 16:00:00"
  },
  "gold_silver_ratio": {
    "value": 59.72,
    "updated_at": "2026-05-18 16:00:00"
  },
  "treasury_10y": {
    "value": 4.59,
    "unit": "%",
    "source": "ustreasury",
    "as_of_date": "2026-05-15",
    "updated_at": "2026-05-18 07:30:00",
    "freshness": "昨日数据"
  },
  "treasury_30y": {
    "value": 5.12,
    "unit": "%",
    "source": "ustreasury",
    "as_of_date": "2026-05-15",
    "updated_at": "2026-05-18 07:30:00",
    "freshness": "昨日数据"
  },
  "tips_10y": {
    "value": 2.00,
    "unit": "%",
    "source": "fred",
    "as_of_date": "2026-05-14",
    "updated_at": "2026-05-18 07:30:00",
    "freshness": "延迟2天"
  },
  "dxy": {
    "value": 118.04,
    "unit": "",
    "source": "fred",
    "as_of_date": "2026-05-08",
    "updated_at": "2026-05-18 07:30:00",
    "freshness": "延迟5天"
  },
  "vix": {
    "value": 24.5,
    "unit": "",
    "source": "cboe",
    "as_of_date": "2026-05-16",
    "updated_at": "2026-05-18 07:30:00",
    "freshness": "周末无数据"
  },
  "sp500": {
    "value": 7408.50,
    "unit": "",
    "source": "fred",
    "as_of_date": "2026-05-15",
    "updated_at": "2026-05-18 07:30:00",
    "freshness": "昨日数据"
  },
  "global_updated_at": "2026-05-18 16:00:00",
  "global_freshness": "部分数据延迟"
}
```

每个指标自带 `source`（数据来源）、`as_of_date`（数据归属日期）、`freshness`（数据新鲜度标签），前端可以直接根据这个判断是否可信。

### 历史层 — 按时间粒度分层，不同保留策略

---

#### minutely/（分钟级，仅保留近7天）

这类数据密度最高，保留太久价值不大，7天后自动清理。

**data/history/minutely/gold_silver_minutely.csv**
```csv
timestamp,gold_usd,silver_usd,ratio
2026-05-18 09:00:00,4520.15,75.50,59.87
2026-05-18 09:05:00,4522.30,75.55,59.85
```

> 每日凌晨清理7天前的记录

---

#### daily/（天级，持续保留）

每天聚合后的数据，历史价值高，永久保留。
日频指标（美债/VIX/DXY）直接在daily/下存原始行。

**data/history/daily/gold_silver_daily.csv**（日收盘聚合）
```csv
date,gold_close,silver_close,ratio_close,gold_high,gold_low
2026-05-18,4549.30,76.19,59.72,4560.00,4520.15
```

**data/history/daily/treasury.csv**
```csv
date,10yr,30yr,2yr
2026-05-15,4.59,5.12,4.09
2026-05-14,4.47,5.02,4.00
```

**data/history/daily/vix.csv**
```csv
date,close
2026-05-16,24.50
```

**data/history/daily/dxy.csv**
```csv
date,value
2026-05-08,118.04
```

**data/history/daily/tips.csv**
```csv
date,value
2026-05-14,2.00
```

**data/history/daily/sp500.csv**
```csv
date,value
2026-05-15,7408.50
```

---

#### monthly/（月度级，持续保留）

**data/history/monthly/china_cpi.csv**
```csv
date,value,yoy
2026-01,0.5,0.5
2026-02,0.3,0.3
```

---

#### quarterly/（季度级，持续保留）

**data/history/quarterly/central_bank_gold.csv**
```csv
date,total_tons,quarterly_change
2026Q1,35000,+180
```

---

## 四、数据生命周期（以金银价格为例）

```
每5分钟采集
     ↓
写入快照 dashboard_data.json（覆盖当前值）
写入 minutely/gold_silver_minutely.csv（追加一行）
     ↓
每天 23:50 定时清理
     ↓
  ├── 聚合当日金银数据到 daily/gold_silver_daily.csv（日收盘价+最高最低）
  ├── 从 minutely CSV 中删除 > 7天 的行
     ↓
minutely文件维持近7天数据 ≈ 2000行
daily文件持续累积 ≈ 365行/年
```

---

## 五、数据源注册表

每个新接入的数据源都在这里登记一次，统一管理：

### data/sources/source_registry.json

```json
{
  "sources": [
    {
      "id": "gold-api",
      "name": "Gold API",
      "type": "api",
      "url": "https://api.gold-api.com/price/{symbol}",
      "frequency": "minutely",
      "collect_interval": 5,
      "collect_interval_unit": "minute",
      "delay": "real_time",
      "fields": ["XAU", "XAG"],
      "status": "active",
      "since": "2026-05-18"
    },
    {
      "id": "ustreasury",
      "name": "U.S. Treasury Yield Curve",
      "type": "csv",
      "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all",
      "frequency": "daily",
      "collect_interval": 1,
      "collect_interval_unit": "day",
      "collect_time": "07:30",
      "delay": "T+1",
      "fields": ["10yr", "30yr", "2yr"],
      "status": "active",
      "since": "2026-05-18"
    },
    {
      "id": "fred-DFII10",
      "name": "FRED 10-Year TIPS",
      "type": "csv",
      "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10",
      "frequency": "daily",
      "collect_interval": 1,
      "collect_interval_unit": "day",
      "delay": "T+2",
      "status": "active",
      "since": "2026-05-18"
    },
    {
      "id": "fred-DTWEXBGS",
      "name": "FRED Trade Weighted USD Index",
      "type": "csv",
      "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS",
      "frequency": "daily",
      "delay": "T+1~5",
      "status": "active",
      "since": "2026-05-18"
    },
    {
      "id": "fred-SP500",
      "name": "FRED S&P 500",
      "type": "csv",
      "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500",
      "frequency": "daily",
      "delay": "T+1",
      "status": "active",
      "since": "2026-05-18"
    },
    {
      "id": "cboe-vix",
      "name": "CBOE VIX Index",
      "type": "csv",
      "url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
      "frequency": "daily",
      "delay": "real_time",
      "status": "active",
      "since": "2026-05-18"
    },
    {
      "id": "akshare",
      "name": "AKShare (国内宏观/期货)",
      "type": "python_lib",
      "frequency": "on_demand",
      "status": "pending",
      "notes": "待安装akshare库"
    }
  ]
}
```

这样的好处：
- 接入新数据源只需在这里加一条 + 写对应的采集函数
- 随时能查看中台接入了哪些数据
- 采集器可以根据 `frequency` / `collect_interval` 决定何时触发

---

## 六、目录结构

```
macro/
├── data/                           ← 数据中台目录
│   ├── current/                    ← 快照层
│   │   └── dashboard_data.json
│   ├── history/                    ← 历史层（按时间粒度分层）
│   │   ├── minutely/               ← 分钟级，仅保留近7天
│   │   │   └── gold_silver_minutely.csv
│   │   ├── daily/                  ← 天级，持续保留
│   │   │   ├── gold_silver_daily.csv
│   │   │   ├── treasury.csv
│   │   │   ├── vix.csv
│   │   │   ├── dxy.csv
│   │   │   ├── tips.csv
│   │   │   └── sp500.csv
│   │   ├── monthly/                ← 月度级，持续保留
│   │   └── quarterly/              ← 季度级，持续保留
│   └── sources/
│       └── source_registry.json    ← 数据源注册表
│
├── collectors/                     ← 采集脚本
│   ├── base_collector.py           ← 基类（共用方法）
│   ├── realtime_collector.py       ← 金银价格
│   ├── daily_collector.py          ← 美债/VIX/DXY/SP500/TIPS
│   └── monthly_collector.py        ← 国内宏观
│
├── framework/                      ← 分析框架
│   ├── gold-silver-dashboard-framework.md
│   ├── data-pipeline-proposal.md
│   ├── data-procurement-report.md
│   └── data-architecture-proposal.md
│
├── dashboard/                      ← Web看板
│   ├── app.py
│   ├── dashboard_data.json         ← 软链到 data/current/dashboard_data.json
│   └── templates/
│
└── logs/                           ← 采集日志
    ├── collector_realtime.log
    ├── collector_daily.log
    └── collector_monthly.log
```

---

## 七、采集器设计思路

### 基类结构

每个采集器继承同一个基类，统一处理：
- 错误重试（灵活动态配置）
- 超时控制
- 日志记录
- 时间戳
- 数据新鲜度标签

```python
class BaseCollector:
    def __init__(self, source_id):
        self.source_id = source_id
        self.logger = setup_logger(source_id)
    
    def fetch(self):
        raise NotImplementedError
    
    def parse(self, raw_data):
        raise NotImplementedError
    
    def write_snapshot(self, key, data):
        # 写入 data/current/dashboard_data.json
        pass
    
    def write_history(self, csv_line, grain="daily"):
        # 追加到 data/history/{grain}/xxx.csv
        pass
    
    def run(self):
        try:
            raw = self.fetch()
            parsed = self.parse(raw)
            self.write_snapshot(...)
            self.write_history(..., grain=...)
            self.logger.info("OK")
        except:
            self.logger.error("FAILED")
            # 保留旧值，不覆盖
```

---

## 八、不同时间粒度数据的管理

| 粒度 | 示例 | 存储方式 | 保留策略 | 采集策略 |
|:----:|------|:--------:|:--------:|:--------:|
| **分钟级** | 金银实时价格 | 快照 → minutely/gold_silver_minutely.csv（追加） → 凌晨清理7天前 → daily/gold_silver_daily.csv（日聚合） | minutely保留7天，daily永久 | 高频cron，交易时段5分钟 |
| **日频** | 美债/VIX/DXY/SP500/TIPS | 快照 → daily/下各自CSV追加（每天1行） | 永久 | 每天7:30一次 |
| **周频** | ETF持仓变化 | 快照 + monthly/下CSV | 永久 | 每周一 |
| **月频** | CPI/PMI/社融/非农 | monthly/下各自CSV | 永久 | 发布日 |
| **季度** | GDP/央行购金量 | quarterly/下各自CSV | 永久 | 发布日 |

**前端展示时**，每个指标自带 time_unit / frequency 字段，Dashboard根据频率判断展示什么：
- 实时指标：显示精确到分钟的时间戳
- 日频指标：显示"2026-05-15数据"
- 月频指标：显示"2026Q2数据"

---

## 九、数据清理机制

### 每天凌晨 23:50 执行 cleanup.py
1. 从 `minutely/gold_silver_minutely.csv` 中删除 `timestamp < now - 7天` 的行
2. 统计当日金银数据，聚合写入 `daily/gold_silver_daily.csv` 一行
3. 如果当天已有数据，跳过（防重复）

```python
def cleanup_minutely():
    cutoff = datetime.now() - timedelta(days=7)
    df = pd.read_csv("minutely/gold_silver_minutely.csv")
    df = df[df.timestamp >= cutoff.strftime("%Y-%m-%d")]
    df.to_csv("minutely/gold_silver_minutely.csv", index=False)
    # 聚合当日数据写入daily
    df_today = df[df.timestamp >= datetime.now().strftime("%Y-%m-%d")]
    if not df_today.empty:
        # 写入 gold_silver_daily.csv（追加）
```

---

## 十、后续扩展

### 新增数据源流程
1. 在 `source_registry.json` 注册
2. 写一个继承 `BaseCollector` 的采集器
3. 注册到cron
4. 数据自动进入快照和历史层

### 消费端扩展
- 现在：Web看板
- 未来：问"最近一个月金银比走势" → 从历史层取CSV数据
- 未来：日报自动生成 → 从历史层汇总
- 未来：Excel/CSV导出分析

### 下一步还能打开的
- AKShare（安装后接入国内宏观数据：社融、M2、PMI、CPI）
- 人民币汇率中间价
- 沪金/沪银主力合约价格
- 北向资金

---

## 十一、总结

> **快照层（JSON）** → 面向展示，只存当前最新值
>
> **历史层（CSV）** → 按时间粒度分层：
>   - **minutely**：仅保留近7天，自动清理
>   - **daily/monthly/quarterly**：持续保留，不设上限
>
> **注册表（JSON）** → 统一管理所有数据源配置

这套结构下，接入一个新数据源只需要：注册 → 写采集函数 → 配cron，三件事。

---
*作者：宏观分析师（AI助手）*
