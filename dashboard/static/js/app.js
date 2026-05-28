// ==================== API Client ====================
const API = {
  get: (url) => fetch(url).then(r => r.json()).catch(e => { console.error(`GET ${url} failed:`, e); return null; }),
  post: (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json()).catch(e => { console.error(`POST ${url} failed:`, e); return null; }),
};

// ==================== Navigation ====================
const navItems = document.querySelectorAll('.nav-item, .nav-subitem');
const pages = document.querySelectorAll('.page');
const pageTitle = document.getElementById('pageTitle');
const pageSubtitle = document.getElementById('pageSubtitle');

const pageMeta = {
  overview: { title: '贵金属-总览', sub: '四象限宏观综合场景视图' },
  macro: { title: '四象限宏观', sub: '逐象限深度分析，含历史趋势与归因' },
  attribution: { title: '指标归因', sub: '选择指标与日期区间，查看走势归因分析' },
  events: { title: '事件中心', sub: '监控阈值触发事件与推送历史' },
  config: { title: '配置', sub: '分析模式切换与监控阈值自定义' },
  commodities: { title: '大宗商品', sub: '原油、铜、农产品等大宗商品行情与宏观分析' },
  simtrade: { title: '模拟交易', sub: '基于四象限信号的模拟交易回测与执行' },
  'data-mgmt': { title: '数据管理', sub: '数据源配置、采集日志、历史数据清理' },
  realtime: { title: '实时探查', sub: '分钟级监控 · 突变检测 · 因果分析' },
};

navItems.forEach(item => {
  item.addEventListener('click', (e) => {
    // 阻止 <a> 标签的页面跳转，用 pushState 无刷切换
    e.preventDefault();
    navItems.forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    const pageId = item.dataset.page;
    pages.forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`page-${pageId}`);
    if (target) target.classList.add('active');
    const meta = pageMeta[pageId];
    if (meta) { pageTitle.textContent = meta.title; pageSubtitle.textContent = meta.sub; }
    // 更新浏览器地址栏 URL
    const href = item.getAttribute('href');
    if (href) history.pushState({ page: pageId }, '', href);
    // Lazy load API data on first visit
    ensurePageLoaded(pageId);
  });
});

// ==================== Utility Helpers ====================
const SIGNAL_MAP = { bullish: 'bullish', bearish: 'bearish', neutral: 'neutral', mixed: 'neutral' };
const SIGNAL_LABELS = { bullish: '利多', bearish: '利空', neutral: '中性', mixed: '偏中性' };
const SIGNAL_ICONS = { bullish: '🟢', bearish: '🔴', neutral: '🟡', mixed: '🔄' };

function el(id) { return document.getElementById(id); }

function fmtNum(v, d) { return v != null ? Number(v).toFixed(d != null ? d : 2) : '--'; }

function fmtPct(v) { return v != null ? (v >= 0 ? `↑ +${v}%` : `↓ ${v}%`) : '--'; }

function trendClass(v) { return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'; }

function signalClass(s) { return SIGNAL_MAP[s] || 'neutral'; }

function signalLabel(s) { return SIGNAL_LABELS[s] || s || '--'; }

function signalBadgeHTML(s) {
  const cls = signalClass(s);
  const label = signalLabel(s);
  return `<span class="card-badge ${cls}">${label}</span>`;
}

// ==================== Lazy Loading State ====================
const _pageLoaded = {};
let _cachedMacro = null;

// ==================== Overview Page ====================
function renderOverview(data, macro) {
  const scenarioBanner = document.querySelector('.scenario-banner');
  if (!scenarioBanner) return;

  // Scenario signal
  const signal = (macro && macro.overall_signal) || 'neutral';
  const sCls = signalClass(signal);
  const sLabel = macro && macro.scenario_label ? macro.scenario_label : (signalLabel(signal) + ' — 等待数据');
  const confidence = macro && macro.overall_confidence != null ? macro.overall_confidence : '--';

  scenarioBanner.querySelector('.scenario-icon').className = `scenario-icon ${sCls}`;
  scenarioBanner.querySelector('.scenario-icon').textContent = SIGNAL_ICONS[signal] || '🟡';
  const valEl = scenarioBanner.querySelector('.value');
  valEl.textContent = sLabel;
  valEl.className = `value ${sCls}`;
  scenarioBanner.querySelector('.scenario-detail').innerHTML =
    `置信度: ${confidence}${typeof confidence === 'number' ? '%' : ''}<br>` +
    (macro && macro.summary ? `核心驱动: ${macro.summary.slice(0, 40)}...` : '数据加载中');

  // Quadrant cards
  const cards = document.querySelectorAll('.quadrant-card');
  if (!cards.length) return;

  const quadrantConfig = [
    { emoji: '🟢', name: '货币锚' },
    { emoji: '🔵', name: '宏观流动性' },
    { emoji: '🟠', name: '风险偏好' },
    { emoji: '🔴', name: '供需博弈' },
  ];

  const macroQuadrants = (macro && macro.quadrants) || [];
  const gPrice = data && data.gold_price ? data.gold_price.value : null;
  const sPrice = data && data.silver_price ? data.silver_price.value : null;
  const ratio = data && data.gold_silver_ratio ? data.gold_silver_ratio.value : null;
  const t10 = data && data.treasury ? data.treasury['10yr'] : null;
  const t30 = data && data.treasury ? data.treasury['30yr'] : null;
  const t2 = data && data.treasury ? data.treasury['2yr'] : null;
  const dxy = data && data.dxy ? data.dxy.value : null;
  const vixVal = data && data.vix ? data.vix.value : null;
  const sp500Val = data && data.sp500 ? data.sp500.value : null;

  cards.forEach((card, idx) => {
    const cfg = quadrantConfig[idx] || {};
    const mq = macroQuadrants[idx] || {};

    // Card title
    card.querySelector('.card-title').innerHTML = `<span class="emoji">${mq.emoji || cfg.emoji}</span> ${mq.name || cfg.name}`;
    // Badge
    const badge = card.querySelector('.card-badge');
    if (badge) {
      const sig = mq.signal || 'neutral';
      badge.className = `card-badge ${signalClass(sig)}`;
      badge.textContent = signalLabel(sig);
    }
    // Body metrics
    const metricsDiv = card.querySelector('.card-metrics');
    if (metricsDiv) {
      const indicators = mq.indicators || {};
      const indicatorPairs = Object.entries(indicators);
      if (indicatorPairs.length > 0) {
        metricsDiv.innerHTML = indicatorPairs.map(([k, v]) =>
          `<div class="metric">
            <div class="metric-label">${k}</div>
            <div class="metric-value">${v}</div>
          </div>`
        ).join('');
      } else {
        // Fallback: show raw data based on quadrant
        const fallbackMetrics = [];
        if (idx === 0) { // 货币锚
          if (t10) fallbackMetrics.push({ label: '10Y Treasury', value: fmtNum(t10, 2) + '%' });
          if (t30) fallbackMetrics.push({ label: '30Y Treasury', value: fmtNum(t30, 2) + '%' });
          if (dxy) fallbackMetrics.push({ label: 'DXY', value: fmtNum(dxy, 2) });
        } else if (idx === 1) { // 宏观流动性
          if (t2) fallbackMetrics.push({ label: '2Y Treasury', value: fmtNum(t2, 2) + '%' });
          if (t10 && t2) fallbackMetrics.push({ label: '2-10 Spread', value: fmtNum((t10 - t2) * 100, 2) + 'bp' });
        } else if (idx === 2) { // 风险偏好
          if (vixVal) fallbackMetrics.push({ label: 'VIX', value: fmtNum(vixVal, 1) });
          if (sp500Val) fallbackMetrics.push({ label: 'S&P 500', value: fmtNum(sp500Val, 0) });
        } else if (idx === 3) { // 供需博弈
          if (ratio) fallbackMetrics.push({ label: '金银比', value: fmtNum(ratio, 1) });
          if (gPrice) fallbackMetrics.push({ label: 'XAU/USD', value: '$' + fmtNum(gPrice, 0) });
          if (sPrice) fallbackMetrics.push({ label: 'XAG/USD', value: '$' + fmtNum(sPrice, 2) });
        }
        metricsDiv.innerHTML = fallbackMetrics.map(m =>
          `<div class="metric">
            <div class="metric-label">${m.label}</div>
            <div class="metric-value">${m.value}</div>
          </div>`
        ).join('');
      }
    }
    // Description
    const desc = card.querySelector('.card-desc');
    if (desc && mq.explanation) desc.textContent = mq.explanation;
  });
}

// ==================== Prediction Card ====================
function renderPrediction(prediction) {
  const card = document.getElementById('prediction-card');
  if (!card) return;

  const adviceEl = document.getElementById('prediction-advice');
  const badgeEl = document.getElementById('prediction-badge');
  const confEl = document.getElementById('prediction-confidence');
  const inlineEl = document.getElementById('prediction-inline');

  // 处理错误情况
  if (!prediction || prediction.error) {
    if (badgeEl) {
      badgeEl.textContent = '数据不足';
      badgeEl.className = 'prediction-badge neutral';
    }
    if (confEl) confEl.textContent = '';
    if (inlineEl) inlineEl.innerHTML = '<span class="prediction-loading">预测数据暂时不可用</span>';
    if (adviceEl) adviceEl.textContent = '请稍后重试';
    return;
  }

  const summary = prediction.summary || {};
  const predictions = prediction.predictions || [];

  // 更新徽章和置信度
  if (badgeEl) {
    const direction = summary.direction || 'neutral';
    const label = summary.direction_label || '中性';
    badgeEl.className = `prediction-badge ${direction}`;
    badgeEl.textContent = label;
  }

  if (confEl) {
    const conf = summary.confidence;
    confEl.textContent = typeof conf === 'number' ? `置信度 ${(conf * 100).toFixed(0)}%` : '';
  }

  // 箭头映射
  const arrowMap = {
    'bullish': '↑',
    'bearish': '↓',
    'neutral': '-',
    'mixed': '-',
    'slightly_bullish': '↑',
    'slightly_bearish': '↓'
  };

  // 周期名称映射
  const periodMap = {
    'short_term': '短期',
    'mid_term': '中期',
    'long_term': '长期'
  };

  // 生成单行紧凑内容
  if (inlineEl) {
    const periodsHTML = predictions.map((p, idx) => {
      const arrow = arrowMap[p.direction] || '-';
      const period = periodMap[p.name] || p.name;
      const interval = p.interval || '--';
      const reason = p.reason || '--';
      const separator = idx < predictions.length - 1 ? '<span class="prediction-separator">||</span>' : '';

      return `
        <span class="prediction-period">
          <span class="prediction-period-name">${period}</span>
          <span class="prediction-arrow ${p.direction || 'neutral'}">${arrow}</span>
          <span class="prediction-range">${interval}</span>
          <span class="prediction-reason">，${reason}</span>
        </span>${separator}
      `;
    }).join('');

    inlineEl.innerHTML = periodsHTML;
  }

  // 更新建议
  if (adviceEl) {
    adviceEl.textContent = summary.advice || '观望为主';
  }
}

// ==================== Macro Page ====================
async function renderMacro(macro) {
  const macroCards = document.querySelectorAll('.macro-card');
  if (!macroCards.length) return;

  const quadrants = (macro && macro.quadrants) || [];
  macroCards.forEach((card, idx) => {
    const q = quadrants[idx] || {};
    // Header
    const header = card.querySelector('.macro-card-header');
    if (header) {
      header.querySelector('.left').innerHTML = `<span>${q.emoji || '❓'}</span> ${q.name || '--'} — ${q.name_en || ''}`;
      const badge = header.querySelector('.card-badge');
      if (badge && q.signal) {
        badge.className = `card-badge ${signalClass(q.signal)}`;
        badge.textContent = signalLabel(q.signal);
      }
    }
    // Body: metrics
    const body = card.querySelector('.macro-card-body');
    if (!body) return;
    const metricsList = body.querySelector('.metrics-list');
    if (metricsList && q.indicators) {
      metricsList.innerHTML = Object.entries(q.indicators).map(([k, v]) =>
        `<div class="m-item"><span class="m-label">${k}</span><span class="m-value">${v}</span></div>`
      ).join('');
    }
    // Analysis text
    const analysisDiv = body.querySelector('.card-analysis');
    if (analysisDiv && q.explanation) {
      analysisDiv.innerHTML = `<strong>分析：</strong>${q.explanation}`;
    }
  });

  // Load mini chart history data
  await Promise.all([
    loadMiniChart('chartTenY', '#4a9eff', 'treasury', 60),
    loadMiniChart('chartSpread', '#a78bfa', 'treasury', 60),
    loadMiniChart('chartVix', '#2dd4a0', 'vix', 60),
    loadMiniChart('chartRatio', '#f5a623', 'gold_silver_daily', 60),
  ]);
}

async function loadMiniChart(canvasId, color, indicator, days) {
  const data = await API.get(`/api/history?indicator=${indicator}&days=${days}`);
  if (!data || !data.data || !data.data.length) {
    createMiniChart(canvasId, color, { values: [] });
    return;
  }
  const values = data.data.map(d => d.value).filter(v => v != null);
  const labels = data.data.map(d => {
    const parts = d.date ? d.date.split('-') : [];
    return parts.length >= 3 ? `${parseInt(parts[1])}/${parseInt(parts[2])}` : '';
  });
  createMiniChart(canvasId, color, { values, labels });
}

function createMiniChart(id, color, data) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  const values = (data && data.values && data.values.length) ? data.values : [0];
  const labels = (data && data.labels && data.labels.length) ? data.labels : values.map((_, i) => i + 1);
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels.slice(-30),
      datasets: [{
        data: values.slice(-30),
        borderColor: color,
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.3,
        fill: false,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { display: false }, y: { display: false, beginAtZero: false } },
      animation: { duration: 500 }
    }
  });
}

// ==================== Events Page ====================
async function renderEvents() {
  const evData = await API.get('/api/events');
  const eventList = document.querySelector('.event-list');
  const filterContainer = document.querySelector('.events-controls');
  if (!eventList) return;

  let events = [];
  let totalS = 0, totalA = 0;

  if (evData && (evData.active_s || evData.active_a)) {
    const sEvents = (evData.active_s || []).map(e => ({ ...e, level: 'S' }));
    const aEvents = (evData.active_a || []).map(e => ({ ...e, level: 'A' }));
    events = [...sEvents, ...aEvents];
    totalS = evData.total_s != null ? evData.total_s : sEvents.length;
    totalA = evData.total_a != null ? evData.total_a : aEvents.length;
  }

  // Update filter buttons
  if (filterContainer) {
    const total = totalS + totalA;
    filterContainer.innerHTML = `
      <div class="event-filter-btn active" data-filter="all">全部 (${total})</div>
      <div class="event-filter-btn" data-filter="S">S 级 (${totalS})</div>
      <div class="event-filter-btn" data-filter="A">A 级 (${totalA})</div>
    `;
    // Filter logic
    filterContainer.querySelectorAll('.event-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        filterContainer.querySelectorAll('.event-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const filter = btn.dataset.filter;
        renderEventItems(eventList, events, filter);
      });
    });
  }

  renderEventItems(eventList, events, 'all');
}

function renderEventItems(container, events, filter) {
  const filtered = filter === 'all' ? events : events.filter(e => e.level === filter);
  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state"><h3>暂无事件</h3><p>当前无活跃告警事件</p></div>';
    return;
  }
  container.innerHTML = filtered.map(e => `
    <div class="event-item">
      <div class="event-level ${e.level.toLowerCase()}">${e.level}</div>
      <div class="event-info">
        <div class="event-title">${e.title || '未知事件'}</div>
        <div class="event-desc">${e.description || ''}</div>
      </div>
    </div>
  `).join('');
}

// ==================== Config Page ====================
async function renderConfig() {
  const cfg = await API.get('/api/config');
  if (!cfg) return;

  // Analysis mode
  const modeLabel = document.querySelector('.config-row:first-child .config-label');
  const modeDesc = document.querySelector('.config-row:first-child .config-desc');
  if (modeLabel) {
    modeLabel.textContent = cfg.analysis_mode === 'llm' ? 'LLM 模式' : '规则模式';
  }
  if (modeDesc) {
    modeDesc.textContent = cfg.analysis_mode === 'llm'
      ? '启用 LLM（' + (cfg.llm_model || '--') + '）进行综合分析'
      : '规则模式 — 基于四象限规则引擎，快速响应数据变化';
  }

  // Toggle switch: rules mode checkbox
  const toggleCheckbox = document.querySelector('.config-section:first-child .toggle-switch input[type="checkbox"]');
  if (toggleCheckbox) {
    toggleCheckbox.checked = cfg.analysis_mode === 'llm';
    toggleCheckbox.disabled = !cfg.llm_configured;
    toggleCheckbox.addEventListener('change', async () => {
      const newMode = toggleCheckbox.checked ? 'llm' : 'rules';
      const result = await API.post('/api/config', { analysis_mode: newMode });
      if (result && result.status === 'ok') {
        // Reload macro analysis
        const macro = await API.get('/api/macro');
        renderOverview(null, macro);
        await renderMacro(macro);
      }
    });
  }

  // LLM mode status
  const llmRow = document.querySelectorAll('.config-row')[1];
  if (llmRow && !cfg.llm_configured) {
    const desc = llmRow.querySelector('.config-desc');
    if (desc) desc.textContent = 'LLM 尚未配置 API Key 和 URL';
  }

  // Update tags in header
  const modeTag = document.querySelector('.tag.active-tag');
  if (modeTag) {
    modeTag.innerHTML = `<span class="dot" style="background:var(--teal)"></span> ${cfg.analysis_mode === 'llm' ? 'LLM 模式' : '规则模式'}`;
  }
}

// ==================== Data Management Page ====================
const INDICATOR_META = {
  'gold-api': { icon: '🥇', name: '黄金 / 白银' },
  'ustreasury': { icon: '🏛️', name: '美债收益率' },
  'fred-DFII10': { icon: '📈', name: 'TIPS 实际收益率' },
  'fred-DTWEXBGS': { icon: '💵', name: '美元指数 DXY' },
  'fred-SP500': { icon: '📊', name: '标普 500' },
  'cboe-vix': { icon: '📉', name: 'VIX 波动率' },
  'cnbc-us10y': { icon: '🏛️', name: '10年美债 (备用)' },
  'cnbc-us30y': { icon: '🏛️', name: '30年美债 (备用)' },
};

function buildStatusBadge(status) {
  const labels = { active: '活跃', backup: '备用', pending: '待接入' };
  const cls = status || 'pending';
  return `<span class="dm-status ${cls}"><span class="dm-status-dot"></span>${labels[cls] || status}</span>`;
}

function buildCoverage(timeRange) {
  if (!timeRange || !timeRange.start || timeRange.start === '无数据') {
    return `<div class="coverage-wrap"><span style="color:var(--text3);font-size:12px">无数据</span></div>`;
  }

  const { start, end, count } = timeRange;
  const now = new Date();
  const endDate = new Date(end);
  const daysDiff = Math.floor((now - endDate) / (1000 * 60 * 60 * 24));

  let freshnessClass = 'fresh';
  if (daysDiff > 3) freshnessClass = 'stale';
  else if (daysDiff > 1) freshnessClass = 'aging';

  // Coverage: how many days we have data vs expected
  const startDate = new Date(start);
  const totalDays = Math.max(1, Math.ceil((now - startDate) / (1000 * 60 * 60 * 24)));
  const pct = Math.min(100, Math.round((count / Math.min(totalDays, 365)) * 100));

  return `
    <div class="coverage-wrap">
      <div class="coverage-track">
        <div class="coverage-fill ${freshnessClass}" style="width:${pct}%"></div>
      </div>
      <div class="coverage-info">
        <span class="ci-range">${start} ~ ${end}</span>
        <span class="ci-count">${count} 条</span>
      </div>
    </div>
  `;
}

function renderDmTable(tableId, countId, sources, mode) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  const countEl = document.getElementById(countId);

  if (!sources || !sources.length) {
    tbody.innerHTML = '<tr><td class="loading-row" colspan="4">暂无数据源</td></tr>';
    if (countEl) countEl.textContent = '0 个';
    return;
  }

  if (countEl) countEl.textContent = `${sources.length} 个`;

  tbody.innerHTML = sources.map(s => {
    const timeRange = mode === 'realtime' ? (s.time_range && s.time_range.minutely) : (s.time_range || null);
    const meta = INDICATOR_META[s.id] || { icon: '📡', name: s.name || s.id };

    const latest = timeRange ? timeRange.end : '--';
    const freq = mode === 'realtime' ? '实时/分钟' : s.frequency || '每日';
    const coverageHtml = buildCoverage(timeRange);
    const statusBadge = buildStatusBadge(s.status);

    return `<tr>
      <td>
        <div class="dm-indicator">
          <span class="dm-icon">${meta.icon}</span>
          <div>
            <div>${meta.name}</div>
            <div class="dm-source">${s.name || s.id} ${statusBadge}</div>
          </div>
        </div>
      </td>
      <td><span class="dm-freq">${freq}</span></td>
      <td><span class="dm-date">${latest}</span></td>
      <td>${coverageHtml}</td>
    </tr>`;
  }).join('');
}

async function renderDataMgmt(sourcesRes) {
  // Accept pre-fetched data from initDashboard; fallback to API call
  const res = sourcesRes || await API.get('/api/sources');
  if (!res || !res.sources) return;

  const realtime = [];
  const daily = [];

  for (const s of res.sources) {
    if (s.time_range && s.time_range.minutely) {
      realtime.push(s);
    } else {
      daily.push(s);
    }
  }

  renderDmTable('dm-table-realtime', 'dm-count-realtime', realtime, 'realtime');
  renderDmTable('dm-table-daily', 'dm-count-daily', daily, 'daily');
}

// ==================== Attribution Page ====================
function setupAttribution() {
  const btn = document.querySelector('.attr-btn');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const indicator = document.querySelector('.attr-controls select')?.value || '金银比';
    const start = document.querySelector('.attr-controls input[type="date"]:first-of-type')?.value || '';
    const end = document.querySelector('.attr-controls input[type="date"]:last-of-type')?.value || '';

    if (!start || !end) return;

    const result = await API.post('/api/attribution', { indicator, start, end });
    if (!result) {
      document.querySelector('.attr-report .report-text').innerHTML = '<p>查询失败，请重试</p>';
      return;
    }

    // Update price chart
    if (result.data && result.data.length) {
      const values = result.data.map(d => d.value).filter(v => v != null);
      const labels = result.data.map(d => d.date || '');
      const canvas = document.getElementById('chartAttributionPrice');
      if (canvas) {
        destroyChart(canvas);
        createAttrChart('chartAttributionPrice', 'line', '#4a9eff', indicator, { values, labels });
      }
    }

    // Update report
    const reportDiv = document.querySelector('.attr-report .report-text');
    if (reportDiv) {
      reportDiv.innerHTML = `
        <p><strong>指标：${indicator}</strong></p>
        <p>区间：${start} 至 ${end}</p>
        <br>
        ${result.analysis ? `<p>${result.analysis}</p>` : ''}
        ${result.start_value != null ? `<p>起始值: ${result.start_value} → 结束值: ${result.end_value}</p>` : ''}
        ${result.change != null ? `<p>变动: ${result.change > 0 ? '+' : ''}${fmtNum(result.change, 2)}</p>` : ''}
      `;
    }
  });
}

function destroyChart(canvas) {
  const charts = Chart.instances;
  if (charts) {
    Object.values(charts).forEach(c => { if (c.canvas === canvas) c.destroy(); });
  }
}

function createAttrChart(id, type, color, label, data) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  const values = (data && data.values && data.values.length) ? data.values : [50, 50];
  const labels = (data && data.labels && data.labels.length) ? data.labels : ['', ''];
  new Chart(ctx, {
    type: type,
    data: {
      labels: labels,
      datasets: [{
        label: label || '',
        data: values,
        borderColor: color,
        backgroundColor: color + '20',
        borderWidth: 2,
        pointRadius: type === 'bar' ? 0 : 3,
        tension: 0.3,
        fill: type === 'line',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#5a6278', font: { size: 10 } } },
        y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#5a6278', font: { size: 10 } }, beginAtZero: false }
      },
      animation: { duration: 600 }
    }
  });
}

// ==================== Header Update ====================
function updateHeader(data) {
  // Last update time
  const lastUpd = document.querySelector('.last-update');
  if (lastUpd && data && data.global_updated_at) {
    lastUpd.textContent = `更新于 ${data.global_updated_at.slice(11, 19)}`;
  }
}

// ==================== Main Init ====================
async function initDashboard() {
  try {
    // Only fetch overview data + macro cache; other pages load on first visit
    const [data, macro, prediction] = await Promise.all([
      API.get('/api/data'),
      API.get('/api/macro'),
      API.get('/api/prediction/summary')
    ]);
    _cachedMacro = macro;
    renderOverview(data, macro);
    renderPrediction(prediction);
    updateHeader(data);
    _pageLoaded.overview = true;

    // 如果当前 URL 指向非总览页面（如刷新时），触发对应懒加载
    const pathToId = { '/': 'overview', '/macro': 'macro', '/attribution': 'attribution', '/events': 'events', '/config': 'config', '/data-management': 'data-mgmt', '/realtime': 'realtime' };
    const initialPage = pathToId[window.location.pathname] || 'overview';
    if (initialPage !== 'overview') {
      await ensurePageLoaded(initialPage);
    }
  } catch (err) {
    console.error('Dashboard init error:', err);
  }
}

// ==================== Lazy Loading ====================
async function ensurePageLoaded(pageId) {
  if (_pageLoaded[pageId]) return;

  switch (pageId) {
    case 'macro':
      if (_cachedMacro) await renderMacro(_cachedMacro);
      break;
    case 'events':
      await renderEvents();
      break;
    case 'config':
      await renderConfig();
      break;
    case 'data-mgmt':
      await renderDataMgmt();
      break;
    case 'attribution':
      setupAttribution();
      break;
    case 'realtime':
      // 调用实时探查页面的数据加载函数
      console.log('实时探查页面：开始加载数据');
      if (typeof window.loadRealtimeData === 'function') {
        // 延迟执行以确保DOM完全准备好
        setTimeout(window.loadRealtimeData, 100);
      } else {
        console.warn('实时探查数据加载函数未找到');
      }
      break;
    // commodities, simtrade: no API data yet
  }
  _pageLoaded[pageId] = true;
}
window.ensurePageLoaded = ensurePageLoaded; // used by base.html popstate

// 实时探查页面自动刷新定时器
let realtimeRefreshTimer = null;

// 启动实时探查页面自动刷新
function startRealtimeRefresh() {
  if (realtimeRefreshTimer) {
    clearInterval(realtimeRefreshTimer);
  }
  
  // 每30秒刷新一次实时探查页面数据
  realtimeRefreshTimer = setInterval(() => {
    // 检查当前页面是否为实时探查页面
    const currentPage = document.querySelector('.page.active');
    if (currentPage && currentPage.id === 'page-realtime') {
      // 如果是实时探查页面，刷新数据
      if (typeof window.loadRealtimeData === 'function') {
        console.log('定时刷新实时探查数据');
        window.loadRealtimeData();
      }
    }
  }, 30000); // 30秒
}

// 在dashboard初始化后启动定时器
setTimeout(startRealtimeRefresh, 2000);

// Start
initDashboard();
