---
name: 事件洞察
description: "对重要市场事件(地缘/宏观/FOMC/数据)进行驱动分析，结合实时行情、新闻采集、技术指标，输出结构化专题报告到wiki_trade/专题分析/。包含事件归因、持仓盈亏评估和策略建议。"
metadata:
  version: 1.0.0
  tags: trading, event, macro, analysis, report
---

# 事件洞察 SOP

> **工具链**:
> - `tools/query_shfe.py` — SHFE实时价格（东财API，零依赖）
> - `tools/data_query.py` — COMEX/宏观数据（需数据管道正常）
> - `gold-api.com` — COMEX金银现货（兜底方案）
> - CNBC RSS — 新闻采集
> - `wiki_trade/专题分析/` — 报告归档

---

## 场景路由

| 触发 | 执行流程 |
|:----|:---------|
| "帮我分析下持仓" / "看下当前盈亏" | **持仓盈亏分析** |
| "为什么最近涨/跌" / "发生了什么" | **归因分析** |
| "整理一份分析报告" | **生成报告** |
| "更新下新闻数据" | **新闻采集** |

---

## 一、数据采集

### 1.1 SHFE实时行情（必做）

```bash
PROJECT=/Users/zhenzhenzheng/zzz/work@AI/futures_trading_ai
/usr/local/bin/python3.11 $PROJECT/tools/query_shfe.py         # 沪银+沪金
/usr/local/bin/python3.11 $PROJECT/tools/query_shfe.py silver  # 仅沪银

# 或指定某个合约
/usr/local/bin/python3.11 $PROJECT/tools/query_shfe.py AG2612
```

**输出字段**: price(最新价), change_pct(涨跌幅%), prev_close(昨收), open(今开), high/low(日内), volume(成交量), open_interest(持仓量)

### 1.2 COMEX金银现货（兜底）

```bash
/usr/local/bin/python3.11 -c "
import urllib.request, json
req = urllib.request.Request('https://api.gold-api.com/price/XAU', headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=10)
print(json.loads(resp.read()))
"
# 同上 XAG → 白银
```

### 1.3 CNBC新闻采集

```bash
# 国际/地缘新闻
curl -sL 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362' \
  -H 'User-Agent: Mozilla/5.0' | grep -E '<title>' | head -15

# 金融/市场新闻
curl -sL 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664' \
  -H 'User-Agent: Mozilla/5.0' | grep -E '<title>' | head -15
```

> 采集后保存到 `data/events/news/{日期}.json`

### 1.4 历史行情（技术指标）

```bash
# 读取已缓存的日线数据
cat $PROJECT/data/history/daily/gold_silver_daily.csv | tail -30
```

计算指标：MA20/MA60、30日高/低、涨幅百分比。

---

## 二、持仓盈亏分析

### 2.1 读取持仓

从 `wiki_trade/trading_archive/positions.md` 读取用户持仓（YAML frontmatter + Markdown表格）。

**必读字段**：品种、合约、方向、手数、开仓均价。

### 2.2 计算盈亏

```
多头盈亏 = (当前价 - 开仓价) × 手数 × 合约乘数
空头盈亏 = (开仓价 - 当前价) × 手数 × 合约乘数

沪银合约乘数 = 15(元/点)
沪金合约乘数 = 1000(元/点)
```

> ⚠️ **禁止估算价格**：必须用 `query_shfe.py` 获取实时价后计算

### 2.3 结构分析

- 计算净敞口（多 - 空）
- 计算多空均价差
- 识别最大风险头寸（最大浮亏）
- 评估对冲有效性

---

## 三、技术面分析

从历史日线数据计算：

| 指标 | 计算方法 | 解读 |
|:----|:---------|:-----|
| MA20 | 近20日收盘均值 | 中期趋势 |
| MA60 | 近60日收盘均值 | 长期趋势 |
| 30日高/低 | 近30日极值 | 支撑/阻力 |
| 距高/低% | (当前-低)/(高-低) | 位置判断 |
| 金银比 | 金价/银价 | 银价弹性指标 |

---

## 四、归因分析

### 因子排查（按优先级）

```
第一层: 
  TIPS急变 → 机会成本
  DXY急变(且TIPS没动) → 货币
  VIX跳升 → 避险

第二层:
  金银同向 → 支持宏观驱动
  金跌银不跌 → 白银工业对冲
  金银比急变 → 白银独立行情

第三层:
  OI骤降 → 踩踏
  OI骤增 → 新开仓
```

### 新闻归因（对照事件时间线）

```
1. 检查新闻中是否有重大事件（地缘/数据/央行讲话）
2. 对照价格变动时间确认因果关系
3. 标注推理等级: (数据) / (推断) / (搜索) / (猜测)🚫
```

---

## 五、报告生成

### 输出格式

在 `wiki_trade/专题分析/` 下创建 `{日期}_{主题}.md`

**报告结构**:
```markdown
# {日期} {主题} — 标题

## 一、事件回顾
按时间线列出核心事件

## 二、价格传导分析
事件→价格的逻辑链条

## 三、技术面分析
表格展示关键指标

## 四、当前持仓分析
真实盈亏 + 结构特征 + 风险点

## 五、观点/策略
情景推演 + 操作建议

## 六、风险提示
```

### 更新MOC

同时更新 `wiki_trade/专题分析.md` 添加新报告索引。

---

## 六、数据沉淀

### 新闻归档

将采集的新闻按日期保存到 `data/events/news/{日期}.json`：

```json
{
  "fetched_at": "YYYY-MM-DD HH:mm CST",
  "total": N,
  "events": [
    {
      "source": "cnbc_world",
      "title": "...",
      "description": "...",
      "link": "...",
      "pubDate": "..."
    }
  ]
}
```

### 专题报告归档

报告 → `wiki_trade/专题分析/{日期}_{主题}.md`
同时更新 `wiki_trade/专题分析.md`（MOC文件）。

---

## 七、常用命令速查

| 操作 | 命令 |
|:----|:------|
| SHFE实时行情 | `python tools/query_shfe.py` |
| COMEX黄金 | `gold-api.com/price/XAU` |
| COMEX白银 | `gold-api.com/price/XAG` |
| CNBC国际新闻 | `curl cnbc_rss_id_100727362` |
| CNBC金融新闻 | `curl cnbc_rss_id_10000664` |
| 黄金日线数据 | `cat data/history/daily/gold_silver_daily.csv` |
| 新闻归档路径 | `data/events/news/{日期}.json` |
| 报告归档路径 | `wiki_trade/专题分析/{日期}_{主题}.md` |
| 持仓文件 | `wiki_trade/trading_archive/positions.md` |

---

## 八、注意事项

1. ⚠️ **禁止用估算价格分析持仓**——必须实时查询
2. ⚠️ **标注推理等级**: (数据)/(推断)/(搜索)/(猜测)🚫
3. ⚠️ **禁止用价格反推原因**: "因为跌了→所以数据不好"是循环论证
4. 新闻采集使用CNBC RSS免费接口，无需API Key
5. 如果数据管道(`data_query.py`)故障，使用gold-api + query_shfe双兜底