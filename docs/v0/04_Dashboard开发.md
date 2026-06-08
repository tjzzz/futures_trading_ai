# Dashboard 开发 SOP

## 目录结构

```
dashboard/
├── app.py                         # Flask 后端 (路由/API)
├── templates/
│   ├── base.html                  # 基础模板 (侧边栏/顶栏/布局)
│   ├── index.html                 # SPA 入口 (extends base.html)
│   └── pages/                     # 各页面面板 (由 index.html include)
│       ├── overview.html
│       ├── macro.html
│       ├── attribution.html
│       ├── events.html
│       ├── config.html
│       ├── commodities.html
│       ├── simtrade.html
│       └── data_mgmt.html
├── static/
│   ├── css/style.css              # 全局样式 (暗色主题/CSS变量)
│   └── js/app.js                  # 全局 JS (导航/API/渲染)
```

---

## 新增页面速查

| 页面 | 文件 | API 端点 | 状态 |
|:---|:---|:---|:---|
| 总览页 | `pages/overview.html` | `/api/data`, `/api/macro`, `/api/prediction/summary` | ✅ 已完成 |
| 宏观页 | `pages/macro.html` | `/api/macro` | ✅ 已完成 |
| 归因页 | `pages/attribution.html` | `/api/attribution` | ✅ 已完成 |
| 事件页 | `pages/events.html` | `/api/events` | ✅ 已完成 |
| 配置页 | `pages/config.html` | `/api/config` | ✅ 已完成 |
| 实时探查 | `pages/realtime.html` | `/api/realtime/*` | ✅ 已完成 |
| **研究报告** | `pages/research.html` | `/api/research/*` | 📋 设计中 |

---

## 一、页面体系

### 1.1 SPA 架构

整个仪表盘是**单页应用(SPA)**：所有页面面板拆分在 `pages/*.html` 中，由 `index.html` 统一 include。

```
index.html ({% block content %})
├── {% include 'pages/overview.html' %}        ← 默认首页
├── {% include 'pages/macro.html' %}
├── {% include 'pages/attribution.html' %}
├── {% include 'pages/events.html' %}
├── {% include 'pages/config.html' %}
├── {% include 'pages/commodities.html' }      ← "模块开发中"
├── {% include 'pages/simtrade.html' }         ← "模块开发中"
└── {% include 'pages/data_mgmt.html' }
```

### 1.2 每页面=三个注册点

新增一个页面需要**修改3个文件**：

| # | 文件 | 操作 |
|---|------|------|
| 1 | `base.html` | 侧边栏加导航项 |
| 2 | `pages/xxx.html` | 新建页面面板文件 |
| 3 | `index.html` | 加入 `{% include 'pages/xxx.html' %}` |
| 4 | `app.js` | `pageMeta` 加标题/副标题 |

---

## 二、新增页面步骤

### Step 1: 侧边栏导航 (`base.html`)

在 `<nav class="sidebar-nav">` 内添加导航项：

```html
<!-- Section: XXX -->
<div class="nav-section">
  <div class="nav-section-divider"></div>
  <a href="/xxx" class="nav-item" data-page="xxx" style="text-decoration: none; color: inherit;">
    <span class="icon">📊</span> XXX
  </a>
</div>
```

**规则：**
- 有独立子页面的模块用 `<div class="nav-section">` 包裹
- 有路由的用 `<a href="/xxx" data-page="xxx">`（URL 会反映在地址栏）
- 未开发完的仍用 `<div class="nav-item" data-page="xxx">`（无 href）
- `data-page` 的值 = 面板 ID，全局唯一
- 图标用 emoji，保持简洁

如需子导航项：

```html
<a href="/parent" class="nav-item" data-page="parent" style="text-decoration: none; color: inherit;">
  <span class="icon">🥇</span> 父级
</a>
<a href="/child1" class="nav-subitem" data-page="child1" style="text-decoration: none; color: inherit;">
  <span class="icon">🔍</span> 子项1
</a>
```

### Step 2: Flask 路由 (`app.py`)

SPA 子页面共享 `index.html`，用堆叠装饰器注册：

```python
@app.route("/xxx")
def spa_page():
    return render_template("index.html")
```

已有 `spa_page()` 可继续堆叠：

```python
@app.route("/macro")
@app.route("/attribution")
@app.route("/events")
@app.route("/config")
@app.route("/data-management")
@app.route("/xxx")          # 新增
def spa_page():
    return render_template("index.html")
```

> API 端点按 `GET /api/xxx` / `POST /api/xxx` 命名。

### Step 3: 面板 HTML (`pages/xxx.html`)

在 `templates/pages/` 下新建文件：

```html
<!-- ===== PAGE: XXX ===== -->
<div class="page" id="page-xxx">
  <div class="page-header">
    <h3>XXX</h3>
    <div class="page-desc">XXX 的描述</div>
  </div>
  <!-- 页面内容 -->
</div>
```

然后 `index.html` 的 `{% block content %}` 中加入：

```html
  {% include 'pages/xxx.html' %}
```

**一致性规则：**
- `id="page-xxx"` 必须匹配 `data-page="xxx"`
- `.page-header` 是标准页头组件（h3 + desc）
- 卡片用 `.config-section`（已有样式）
- 表格用 `.data-mgmt-table`（已有样式）
- 空状态用 `.empty-state`（已有样式）

### Step 4: pageMeta 注册 (`app.js`)

在 `pageMeta` 对象中添加标题映射：

```javascript
const pageMeta = {
  // ... 已有项
  xxx: { title: 'XXX', sub: 'XXX 的描述' },
};
```

这控制页面切换时顶栏的标题和副标题。

### Step 5: URL 路径映射 (可选)

如果加了新路由，以下 **3 处**需要同步：

**1. `base.html` 的 `pageIdFromPath()`：**

```javascript
function pageIdFromPath() {
  const map = {
    '/': 'overview',
    '/macro': 'macro',
    '/attribution': 'attribution',
    '/events': 'events',
    '/config': 'config',
    '/data-management': 'data-mgmt',
    '/xxx': 'xxx',    // ← 新增
  };
  return map[window.location.pathname] || 'overview';
}
```

**2. `app.js` 的 `initDashboard()` 内 `pathToId` 映射（控制刷新时懒加载）：**

```javascript
const pathToId = {
  '/': 'overview',
  '/macro': 'macro',
  // ...
  '/xxx': 'xxx',    // ← 新增
};
```
```

---

## 三、样式系统

### 3.1 CSS 变量 (暗色主题)

定义在 `style.css :root` 中，所有页面统一使用：

| 变量 | 用途 | 值 |
|------|------|-----|
| `--bg` | 最底层背景 | `#0f1117` |
| `--bg2` | 卡片背景 | `#161b27` |
| `--bg3` | 表头/悬停 | `#1e2535` |
| `--bg4` | 高亮 | `#252d3d` |
| `--text` | 主文字 | `#e8eaf0` |
| `--text2` | 次要文字 | `#8b92a8` |
| `--text3` | 辅助文字 | `#5a6278` |
| `--border` | 边框 | `rgba(255,255,255,0.08)` |
| `--blue` | 蓝色强调 | `#4a9eff` |
| `--teal` | 绿色/涨 | `#2dd4a0` |
| `--amber` | 黄色/警告 | `#f5a623` |
| `--coral` | 红色/跌 | `#ff6b6b` |
| `--purple` | 紫色 | `#a78bfa` |
| `--radius` | 大圆角 | `12px` |
| `--radius-sm` | 小圆角 | `8px` |

### 3.2 常用组件 CSS 类

| 类名 | 用途 |
|------|------|
| `.config-section` | 卡片式区块容器 |
| `.config-row` | 行式布局（标签+值+开关） |
| `.data-mgmt-table` | 数据表格（暗色表头+悬停行） |
| `.empty-state` | 空状态/开发中占位 |
| `.coverage-wrap / .coverage-track / .coverage-fill` | 进度条 |
| `.dm-status` | 状态徽章（active/backup/pending） |
| `.card-badge` | 标签（bullish/bearish/neutral） |
| `.tag` | 顶栏标签 |
| `.toggle-switch` | 开关组件 |
| `page-header` | 页面标准头部 |
| `loading-row` | 表格加载态 |
| `.loading-pulse` | 脉冲加载动画 |
| `.up / .down / .flat` | 涨跌颜色 |

### 3.3 添加新样式

- 页面特有样式写在 `style.css` 文件末尾（在 `Animations` 之前）
- 类名加前缀避免冲突（如 `.xxx-table`、`.xxx-card`）
- 颜色只用 CSS 变量，不用硬编码色值

---

## 四、懒加载机制

页面采用**按需加载 (Lazy Loading)**，只有总览页在初始化时加载，其他页面首次访问时才拉取数据。

### 4.1 加载策略

```
初始化 (initDashboard)
  ├── GET /api/data        ← 总览数据
  ├── GET /api/macro       ← 宏观分析 (缓存供宏观页使用)
  └── 只渲染总览页 + 更新顶栏

首次访问某页面 (ensurePageLoaded)
  ├── macro     → renderMacro(_cachedMacro)          ← 用缓存，不额外请求
  ├── events    → GET /api/events                    ← 首次请求
  ├── config    → GET /api/config                    ← 首次请求
  ├── data-mgmt → GET /api/sources                   ← 首次请求
  └── attribution → setupAttribution()                ← 只绑点击事件
```

### 4.2 核心代码位置

| 职责 | 位置 |
|------|------|
| 状态跟踪 | `app.js` — `const _pageLoaded = {}` |
| 宏观缓存 | `app.js` — `let _cachedMacro = null` |
| 按需加载函数 | `app.js` — `ensurePageLoaded(pageId)` |
| 导航触发点 | 导航 `click` 事件 + `popstate` 事件 |

### 4.3 新增页面的懒加载注册

新增页面如果有 API 请求，要在 `ensurePageLoaded` 中添加 case：

```javascript
case 'xxx':
  await renderXxx();  // 内部调用 API.get()
  break;
```

如果页面没有 API 请求，则无需注册。

---

## 六、数据流

```
数据采集层 (collectors/) 
    → data/current/dashboard_data.json 
    → Flask REST API (/api/data, /api/macro, /api/history, etc.)
    → app.js (API.get() 获取)
    → render 函数填充面板
```

- API 请求用 `API.get(url)` / `API.post(url, body)`（已封装在 app.js 顶部）
- API 响应失败时显示 fallback 静态数据，不白屏
- `initDashboard()` 在页面加载时自动调用
- 新增 API 端点按 Flask RESTful 风格命名

---

## 七、基础模板 (`base.html`) 的块

| 块名 | 用途 | 是否必需 |
|------|------|----------|
| `title` | 浏览器标签标题 | 可选 |
| `extra_css` | 页面级 CSS 注入 | 可选 |
| `sidebar` | 侧边栏（一般不改） | 不重写 |
| `header_title` | 顶栏标题 | 可选 |
| `header_subtitle` | 顶栏副标题 | 可选 |
| `content` | 页面主体 HTML | **是** |
| `extra_js` | 页面级 JS | 可选 |

一般只用 `content` 块，其他通过 JS 动态更新。

---

## 八、导航机制

点击侧边栏 `<a>` 的执行链路：

```
click → e.preventDefault()
      → 切换 .active 类 (显隐页面)
      → history.pushState() (更新 URL)
      → 顶栏标题/副标题更新 (pageMeta)
      → ensurePageLoaded(pageId)  ← 首次访问才拉取 API 数据
```

浏览器前进/后退：

```
popstate → pageIdFromPath() → switchPage() → 激活对应页面
                               → ensurePageLoaded(pid) → 按需加载数据
```

刷新页面（非总览页）：

```
initDashboard() 加载总览数据
    → 检查当前 URL → 若指向其他页面 → ensurePageLoaded(initialPage)
    → 数据填充对应页面
```

**关键原则：** `data-page="xxx"` / `id="page-xxx"` / `pageMeta.xxx` 三者命名一致。

---

## 十、总览页预测卡片设计

### 10.1 功能定位

预测卡片位于总览页场景横幅和四象限分析之间，展示短/中/长期趋势预判：

- **定位**：参考性质，明确标注"仅供参考 · 每日更新"
- **数据源**：`analysis/prediction/fusion.py` 融合预测引擎
- **展示内容**：三周期方向 + 区间 + 一句话原因

### 10.2 数据结构

API 端点：`GET /api/prediction/summary`

```json
{
  "summary": {
    "direction": "slightly_bearish",
    "direction_label": "略偏空",
    "confidence": 0.48,
    "final_score": -0.35,
    "advice": "偏空思路，关注支撑测试"
  },
  "predictions": [
    {
      "name": "short_term",
      "label": "看空",
      "direction": "bearish",
      "horizon": "1周内",
      "interval": "$3300-3500",
      "reason": "MACD死叉，短均线跌破中均线",
      "confidence": 0.50
    }
  ],
  "updated_at": "2026-05-21 23:08:48"
}
```

### 10.3 UI 结构

```html
<div class="prediction-card" id="prediction-card">
  <div class="prediction-header">
    <div class="prediction-title">
      <span class="icon">🎯</span> 趋势预判
      <span class="prediction-subtitle">仅供参考 · 每日更新</span>
    </div>
    <div class="prediction-summary">
      <span class="prediction-badge" id="prediction-badge">略偏空</span>
      <span class="prediction-confidence">置信度 48%</span>
    </div>
  </div>
  <div class="prediction-body" id="prediction-body">
    <!-- 三周期列表 -->
    <div class="prediction-item">
      <div class="prediction-item-label">短期</div>
      <div class="prediction-item-direction bearish">看空</div>
      <div class="prediction-item-interval">1周内</div>
      <div class="prediction-item-reason" title="MACD死叉...">MACD死叉...</div>
    </div>
  </div>
  <div class="prediction-footer">
    <span class="prediction-hint">💡 偏空思路，关注支撑测试</span>
  </div>
</div>
```

### 10.4 样式类

| 类名 | 用途 |
|:---|:---|
| `.prediction-card` | 卡片容器 |
| `.prediction-header` | 头部区域（标题+综合判断） |
| `.prediction-badge` | 综合方向徽章（支持 bullish/bearish/neutral） |
| `.prediction-body` | 三周期列表容器 |
| `.prediction-item` | 单行周期项 |
| `.prediction-item-label` | 周期标签（短期/中期/长期） |
| `.prediction-item-direction` | 方向（看多/看空/中性） |
| `.prediction-item-interval` | 时间区间标签 |
| `.prediction-item-reason` | 一句话原因 |

### 10.5 JavaScript 渲染

```javascript
function renderPrediction(prediction) {
  const card = document.getElementById('prediction-card');
  if (!card) return;

  // 处理错误/空数据
  if (!prediction || prediction.error) {
    // 显示 fallback 状态
    return;
  }

  // 更新综合徽章
  const badge = document.getElementById('prediction-badge');
  badge.className = `prediction-badge ${prediction.summary.direction}`;
  badge.textContent = prediction.summary.direction_label;

  // 渲染三周期列表
  const body = document.getElementById('prediction-body');
  body.innerHTML = prediction.predictions.map(p => `
    <div class="prediction-item">
      <div class="prediction-item-label">${horizonLabels[p.name]}</div>
      <div class="prediction-item-direction ${p.direction}">${p.label}</div>
      <div class="prediction-item-interval">${p.horizon}</div>
      <div class="prediction-item-reason" title="${p.reason}">${p.reason}</div>
    </div>
  `).join('');
}
```

---

## 十一、检查清单

新增页面后检查：

- [ ] 侧边栏导航 `data-page` 与面板 `id` 一致
- [ ] Flask 路由已注册（指向 `index.html`）
- [ ] `pageIdFromPath()` 已添加 URL 映射
- [ ] `pageMeta` 已添加标题
- [ ] 颜色只用 CSS 变量
- [ ] API 调用失败时有 fallback
- [ ] 页面内容在 `.page` 容器内
