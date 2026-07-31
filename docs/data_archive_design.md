# 数据层按日归档设计方案

> 当前问题：新闻/事件数据每次刷新覆盖，无法回溯历史
> 目标：每条新闻/事件按日期存储，复用缓存减少重复采集

---

## 1. 数据结构

### 目录结构

```
data/events/
├── news/                    # 新闻按日归档（新增）
│   ├── 2026-06-08.json
│   ├── 2026-06-09.json
│   ├── 2026-06-10.json     # 每天的新闻存一份
│   └── latest.json          # symlink 或副本 -> 最新一天，方便快速读取
├── calendar/                # 日历按日归档（新增）
│   ├── 2026-06-08.json
│   ├── 2026-06-09.json
│   └── latest.json
├── tracker/                 # 事件跟踪按日快照（新增）
│   ├── 2026-06-08.json
│   ├── 2026-06-09.json
│   └── latest.json
│
├── latest_feed.json         # 保留（用于快速读取最新，但采集时先归档再覆写）
├── calendar_cache.json      # 保留
├── event_tracker.json       # 保留
└── monitor_state.json       # 保留
```

### 新闻归档逻辑

```
每次采集新闻时:
  1. 检查 data/events/news/{today}.json 是否存在
  2. 如果存在 → 跳过新闻采集（复用缓存）
  3. 如果不存在 → 采集 → 写入 data/events/news/{today}.json → 更新 latest.json
```

### 日历归档逻辑

```
每次采集日历后:
  1. 读取新日历中的事件
  2. 检查哪些事件 date 已过
  3. 将这些事件归档到 data/events/calendar/{date}.json
  4. 保留未发生的事件在 calendar_cache.json
```

### 事件跟踪归档逻辑

```
每次采集事件跟踪后:
  1. 将当前事件跟踪状态快照写入 data/events/tracker/{today}.json
  2. 保留 event_tracker.json 作为活跃事件
```

---

## 2. data_query.py 新增命令

```
python data_query.py news --date 2026-06-10    # 查某天的新闻
python data_query.py news --latest              # 查最新新闻

python data_query.py events --date 2026-06-10   # 查某天的日历
```

**新鲜度判断更新**：
```
检查 news/{today}.json 是否存在且完整
   存在 → 复用（不再触发采集）
   不存在 → 采集 → 归档
```

---

## 3. 采集器改动点

### collectors/run.py

```python
def collect_news():
    today = datetime.now().strftime("%Y-%m-%d")
    archive_path = DATA_EVENTS / "news" / f"{today}.json"
    
    if archive_path.exists():
        logger.info(f"今日新闻已归档，跳过采集: {today}")
        return read_json(archive_path)
    
    # 正常采集
    news = do_actual_collect()
    
    # 写入归档
    with open(archive_path, "w") as f:
        json.dump(news, f)
    
    # 更新 latest symlink/copy
    shutil.copy(archive_path, DATA_EVENTS / "news" / "latest.json")
    return news
```

---

## 4. 注意事项

| 注意点 | 处理方式 |
|--------|---------|
| 跨日期分析 | data_query 自动检查归档目录，跨日期时读取对应日期的缓存 |
| 缓存过期 | 当天数据保留当天，次日自动视为过期（触发新采集） |
| 数据一致性 | latest.json 始终指向最新一天，兼容现有代码逻辑 |
| 存储成本 | 每天约50-100条新闻 (JSON ~50KB)，一年约18MB |
| 回填历史 | 首次迁移时，将 latest_feed.json 的59条按pubDate分拣到对应日期的归档文件 |