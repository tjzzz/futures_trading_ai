# 新闻事件收集与宏观归因系统
> **作者：宏观分析师（AI助手）**

> 基于RSS/Feed的数据采集 + 事件归因到四象限框架
> 2026.5.18 | v1.0

---

## 一、数据源架构

### RSS/Feed 主源（已验证可用 ✅）

| 来源 | URL | 内容特点 | 可用性 |
|:----:|------|---------|:------:|
| **MarketWatch** | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | 金融市场头条，含美债/油价/地缘 | ✅ 今天实测有美债+伊战+Ebola |
| **CNBC Politics** | `https://www.cnbc.com/id/10000113/device/rss/rss.html` | 政治与政策，地缘冲突 | ✅ 今天实测有伊朗+美债+川普 |
| CNBC Markets | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664` | 金融市场 | 待验证 |
| CNBC Economy | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115` | 经济数据/央行 | 待验证 |

### Rerg 待验证扩展源

| 类别 | 来源 | URL |
|:----:|------|-----|
| **中国经济** | 财新/华尔街见闻 | 需确认RSS可用性 |
| **大宗商品** | Reuters Commodities | 可能被墙 |
| **央行/美联储** | Fed官网RSS/Speeches | 待验证 |
| **地缘政治** | BBC World | 待验证 |

---

## 二、采集与归因流程

```
每30分钟 cron 触发
        ↓
news_collector.py 运行
    ├── 拉取所有RSS源
    ├── 合并去重（按title+date）
    ├── 关键词匹配 → 归因到象限
    ├── 强度评级（S/A/B/C）
    └── 写入 news_events.json

同时，更新 dashboard_data.json 中的关联事件
        ↓
对我提示：有新S/A级事件 → 我主动给镇哥推送解读
无重大事件 → 按需等待镇哥提问
```

### 归因规则（关键词匹配）

```python
# 关键词 → 象限映射
QUADRANT_RULES = {
    "green": {  # 🟢 货币锚
        "keywords": ["Treasury yield", "bond yield", "10-year", "30-year",
                     "DXY", "dollar index", "central bank gold", "Fed rate",
                     "credit rating", "debt ceiling", "T-bill"],
        "weight": 1.0
    },
    "blue": {   # 🔵 宏观流动性
        "keywords": ["Federal Reserve", "Fed", "interest rate", "rate cut",
                     "rate hike", "balance sheet", "quantitative easing",
                     "liquidity", "FRA-OIS", "LIBOR", "SOFR"],
        "weight": 1.0
    },
    "orange": { # 🟠 风险偏好
        "keywords": ["Iran", "war", "geopolitical", "sanctions", "VIX",
                     "S&P 500", "stock market", "crash", "volatility",
                     "safe haven", "risk-on", "risk-off", "Ebola",
                     "military", "conflict", "ceasefire"],
        "weight": 1.0
    },
    "red": {    # 🔴 供需博弈
        "keywords": ["COMEX", "silver inventory", "gold ETF", "SLV", "GLD",
                     "mining", "supply", "shortage", "industrial demand",
                     "photovoltaic", "silver demand", "gold demand"],
        "weight": 1.0
    }
}

# 金银价格联动（不属于象限但需要关注）
PRICE_RELATED = [
    "gold price", "silver price", "gold rally", "silver rally",
    "precious metals", "commodities", "XAU", "XAG"
]
```

### 强度评级逻辑

```
S级: 美债收益率突破警戒线 / 美联储紧急行动 / 战争升级至关
      键转折 / 央行大规模意外行动
A级: 收益率逼近警戒线 / 重要Fed官员讲话 / 地缘重大进展/
      超预期的经济数据
B级: 常规经济数据发布 / 次级官员讲话 / 市场预期内的变化
C级: 市场噪音 / 重复信息 / 不相关的政治新闻
```

---

## 三、数据存储格式

```json
// news_events.json
{
  "last_updated": "2026-05-18 18:00 CST",
  "active_s_events": [
    {
      "id": "evt-S-001",
      "title": "30Y美债收益率突破5%，10Y突破4.5%",
      "quadrant": "green",
      "direction": "利多黄金",
      "level": "S",
      "status": "ongoing",
      "started_at": "2026-05-15",
      "timeline": [
        {"date": "2026-05-15", "event": "触发突破", "impact": "金银暴跌"},
        {"date": "2026-05-16", "event": "CNBC分析: 美债市场发出伊朗警告", "impact": "确认趋势"},
        {"date": "2026-05-18", "event": "Yardeni: 10Y可能触及5%", "impact": "持续施压"},
      ],
      "summary": "降息周期中长端利率逆势上涨，市场定价逻辑从货币政策切换到财政信用"
    }
  ],
  "active_a_events": [
    {
      "id": "evt-A-001",
      "title": "美伊战争陷入僵局",
      "quadrant": "orange",
      "direction": "利多黄金（避险）多空交织白银（战争消耗→通胀→加息预期）",
      "level": "A",
      "status": "ongoing",
      "started_at": "2026-02-28",
      "timeline": [
        {"date": "2026-02-28", "event": "战争爆发"},
        {"date": "2026-05-17", "event": "Trump警告伊朗'什么都不剩'", "impact": "升级威胁"},
        {"date": "2026-05-15", "event": "Trump称Xi愿协助调解", "impact": "外交信号"},
      ],
      "summary": "战争持续近3个月，油价上行，军事开支扩大加剧财政赤字→美债承压"
    },
    {
      "id": "evt-A-002",
      "title": "油价大涨叠加伊战，冲击消费与经济",
      "quadrant": "orange",
      "direction": "利多黄金（通胀+避险）",
      "level": "A",
      "status": "ongoing",
      "started_at": "2026-05-15",
      "timeline": [
        {"date": "2026-05-17", "event": "MarketWatch分析: 伊战可能带来3000亿美元冲击"},
        {"date": "2026-05-18", "event": "油价上涨，Walmart/Target将显示消费变化"},
      ]
    },
    {
      "id": "evt-A-003",
      "title": "Ebola在刚果/乌干达爆发（WHO宣布紧急状态）",
      "quadrant": "orange",
      "direction": "变量—不确定性增加→避险提升",
      "level": "A",
      "status": "ongoing",
      "started_at": "2026-05-17",
    }
  ],
  "event_queue": [
    // 待处理的B/C级事件，用于次晨汇总
  ],
  "raw_feed": [
    // 保留最近24小时的原始RSS条目
  ]
}
```

---

## 四、与Dashboard联动

Dashboard数据结构扩展：

```json
{
  "quadrant": { ... },
  "events": {
    "active_s": ["30Y美债突破5%", ...],
    "active_a": ["美伊战争僵局", "油价冲击", "Ebola"],
    "quadrant_events": {
      "green": {"count": 1, "s_level": 1, "direction": "利多"},
      "blue":  {"count": 0, "s_level": 0, "direction": "中性"},
      "orange": {"count": 3, "s_level": 0, "direction": "利多"},
      "red":   {"count": 0, "s_level": 0, "direction": "中性"}
    }
  }
}
```

Dashboard每个象限卡片底部会显示：

```
🟢 货币锚 ── 利多
   趋势: 🟢
   关联事件: 美债破5%【S级】⚠️

🟠 风险偏好 ── 利多
   趋势: 🟠
   关联事件: 美伊战争僵局【A级】| 油价冲击【A级】| Ebola【A级】
```

---

## 五、采集脚本结构

```python
# news_collector.py

import requests
import xml.etree.ElementTree as ET
import json
import hashlib
from datetime import datetime

RSS_FEEDS = {
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "cnbc_politics": "https://www.cnbc.com/id/10000113/device/rss/rss.html",
    "cnbc_markets": "...",
}

QUADRANT_KEYWORDS = { ... }

def fetch_rss(url):
    r = requests.get(url, timeout=15)
    root = ET.fromstring(r.content)
    items = []
    for item in root.findall('.//item'):
        items.append({
            "title": item.findtext('title', ''),
            "description": item.findtext('description', ''),
            "link": item.findtext('link', ''),
            "pubDate": item.findtext('pubDate', ''),
            "source": url
        })
    return items

def classify_event(item):
    """归因到象限 + 评级"""
    text = (item['title'] + ' ' + item['description']).lower()
    
    # 匹配象限
    quadrants = []
    for q, rules in QUADRANT_KEYWORDS.items():
        for kw in rules['keywords']:
            if kw.lower() in text:
                quadrants.append(q)
                break
    
    # 评级
    level = 'C'
    # S级关键词...
    # A级关键词...
    
    return {
        "quadrant": quadrants if quadrants else ["unclassified"],
        "level": level
    }

def update_events():
    all_events = []
    for name, url in RSS_FEEDS.items():
        items = fetch_rss(url)
        for item in items:
            classification = classify_event(item)
            event = {
                "id": hashlib.md5(item['title'].encode()).hexdigest()[:12],
                "source": name,
                "title": item['title'],
                "description": item['description'][:200],
                "link": item['link'],
                "pubDate": item['pubDate'],
                **classification
            }
            all_events.append(event)
    
    # 去重、合并到已有数据
    # 写入 news_events.json

if __name__ == "__main__":
    update_events()
```

---

## 六、与技术中台的协作

| 功能 | 数据中台 | 我 |
|:----:|:---------:|:--:|
| 原始数字指标 | 提供金价/美债/VIX等 | — |
| RSS新闻采集 | — | 定时采集+归因 |
| 事件评级 | — | 判断S/A/B/C |
| 时间轴管理 | — | 持续追踪 |
| 解读 | — | 推给镇哥 |
| Dashboard集成 | — | 整合事件到象限 |

---

## 七、cron设定

```bash
# 每30分钟抓取一次新闻
*/30 * * * * cd /home/admin/.openclaw/workspace-trade-ai && python3 news_collector.py >> news_collector.log 2>&1
```

---

## 八、推送策略

| 级别 | 动作 |
|:----:|:----:|
| **S级** | 我立即推送一句话+宏观解读给镇哥 |
| **A级** | 我推送简短摘要+影响方向 |
| **B级** | 下次对话时报汇总 |
| **C级** | 直接入库，不提 |


---
*作者：宏观分析师（AI助手）*
