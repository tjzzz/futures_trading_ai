// ── State ──
let charts = {};
const FACTOR_ORDER = ["opportunity_cost","currency","safe_haven","inflation","positioning","structural_demand","silver_specific"];
const FACTOR_LABELS = { opportunity_cost:"机会成本", currency:"货币", safe_haven:"避险需求",
  inflation:"通胀预期", positioning:"持仓动量", structural_demand:"结构性需求", silver_specific:"银价专用" };
const SEVERITY_ICONS = { s:"🔴", a:"🟡", b:"⚪" };
const SEVERITY_LABELS = { s:"严重", a:"重要", b:"一般" };
const FACTOR_HISTORY = {
  opportunity_cost: "treasury",
  currency: "dxy",
  safe_haven: "gold",
  inflation: "tips",
  positioning: "gold",
  structural_demand: "silver",
  silver_specific: "silver",
};
const FACTOR_SPARK_COLORS = {
  opportunity_cost: "#f5a623",
  currency: "#4a9eff",
  safe_haven: "#f0b90b",
  inflation: "#a78bfa",
  positioning: "#2dd4a0",
  structural_demand: "#9e9e9e",
  silver_specific: "#c0c0c0",
};

// ── Utils ──
const $ = id => document.getElementById(id);
const fetchJSON = url => fetch(url).then(r => r.json());
const ago = ts => { if(!ts) return '--'; let d=new Date(ts.replace(' ','T')+'+08:00'), s=(Date.now()-d)/1000;
  if(s<60) return '刚刚'; if(s<3600) return Math.floor(s/60)+'m前'; if(s<86400) return Math.floor(s/3600)+'h前';
  return Math.floor(s/86400)+'d前'; };

function fmtDir(d, opts) {
  const arrow = (opts && opts.arrow);
  if(!d||d==='neutral'||d==='--') return arrow ? '<span style="color:var(--text2)">→</span>' : '<span style="color:var(--text2)">中性</span>';
  if(d==='bullish') return arrow ? '<span style="color:var(--teal)">▲</span>' : '<span style="color:var(--teal)">看多</span>';
  if(d==='bearish') return arrow ? '<span style="color:var(--coral)">▼</span>' : '<span style="color:var(--coral)">看空</span>';
  if(d==='up') return '<span style="color:var(--teal)">↑ +</span>';
  if(d==='down') return '<span style="color:var(--coral)">↓ -</span>';
  return d;
}

function fmtChange(change) {
  if(change==null) return '';
  const c = Number(change);
  const cls = c >= 0 ? 'color:var(--teal)' : 'color:var(--coral)';
  const sign = c >= 0 ? '+' : '';
  return `<span style="${cls}">${sign}${c.toFixed(2)}</span>`;
}

function fmtPct(pct) {
  if(pct==null) return '';
  const p = Number(pct);
  const cls = p >= 0 ? 'color:var(--teal)' : 'color:var(--coral)';
  const sign = p >= 0 ? '+' : '';
  return `<span style="${cls}">${sign}${p.toFixed(2)}%</span>`;
}

function fmtStrength(s) { return s != null ? s.toFixed(2) : '--'; }

function getFactorDir(f) {
  const sigs = f && f.data && f.data.signals; if(!sigs) return null;
  const b = ['short','mid','long'].filter(p => sigs[p] && sigs[p].direction==='bullish').length;
  const be = ['short','mid','long'].filter(p => sigs[p] && sigs[p].direction==='bearish').length;
  if(b > be) return 'bullish';
  if(be > b) return 'bearish';
  return 'neutral';
}
function getFactorStrength(f) {
  const sigs = f && f.data && f.data.signals; if(!sigs) return 0;
  const vals = ['short','mid','long'].map(p => sigs[p] && sigs[p].strength).filter(x => x != null);
  return vals.length ? vals.reduce((a,b) => a+b, 0) / vals.length : 0;
}

// ── Tab Switching ──
document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-'+tab).classList.add('active');

    // Re-fit charts when switching to factor or monitor tab
    if(tab === 'factors') {
      FACTOR_ORDER.forEach(key => {
        const c = charts['ftrend-'+key];
        if(c) setTimeout(() => { try { c.timeScale().fitContent(); } catch(e) {} }, 50);
      });
    }
  });
});

// ── Clock ──
function tick() { $('clock').textContent = new Date().toLocaleTimeString('zh-CN',{hour12:false,hour:'2-digit',minute:'2-digit'}); }
setInterval(tick,10000); tick();

// ═══════════════════════ 行情概览 ═══════════════════════

async function loadOverview() {
  const [snap, factors, events] = await Promise.all([
    fetchJSON('/api/snapshot'), fetchJSON('/api/factors'), fetchJSON('/api/events')
  ]);
  $('overview-time').textContent = '更新: '+(snap.global_updated_at||'--');

  // ── Price cards ──
  const gf = snap.gold_futures||{}, sf = snap.silver_futures||{}, gs = snap.gold_silver_ratio||{};

  const renderCard = (cardId, value, chgPct, prevClose, colorClass, prefix) => {
    const card = $(cardId);
    card.querySelector('.price-value').textContent = value != null ? prefix+Number(value).toLocaleString() : '--';
    const chEl = card.querySelector('.price-change');
    if(chgPct!=null) {
      const p = Number(chgPct);
      chEl.innerHTML = (p>=0?'▲ ':'▼ ')+Math.abs(p).toFixed(2)+'%';
      chEl.className = 'price-change '+(p>=0?'up':'down');
    } else { chEl.innerHTML = '--'; chEl.className='price-change'; }
    card.querySelector('.price-sub').textContent = prevClose ? '昨收 '+prefix+Number(prevClose).toLocaleString() : '';
  };

  renderCard('gold-card', gf.value, gf.change_pct, gf.prev_close, 'gold', '$');
  renderCard('silver-card', sf.value, sf.change_pct, sf.prev_close, 'silver', '$');

  $('ratio-card').querySelector('.price-value').textContent = gs.value ? Number(gs.value).toFixed(2) : '--';
  $('ratio-card').querySelector('.price-change').innerHTML = gs.value ? '金银比' : '--';
  $('ratio-card').querySelector('.price-sub').textContent = gs.updated_at ? ago(gs.updated_at) : '';

  // ── Trend chart (TradingView Lightweight Charts) ──
  const [goldData, silverData] = await Promise.all([
    fetchJSON('/api/history/gold'), fetchJSON('/api/history/silver')
  ]);
  if(goldData && goldData.length && silverData && silverData.length) {
    const container = document.getElementById('chart-trend');
    if(container) {
      if(charts.trendChart) { charts.trendChart.remove(); delete charts.trendChart; }
      const lc = LightweightCharts;
      const chart = lc.createChart(container, {
        autoSize: true, height: 280,
        layout: {
          textColor: '#8b92a8',
          background: { type: 'solid', color: 'transparent' },
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(255,255,255,0.04)' },
          horzLines: { color: 'rgba(255,255,255,0.06)' },
        },
        timeScale: {
          borderColor: 'rgba(255,255,255,0.08)',
          timeVisible: false,
          ticksVisible: true,
        },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)', visible: false },
        crosshair: { mode: lc.CrosshairMode.Normal },
      });

      // Gold series (left axis)
      const goldSeries = chart.addAreaSeries({
        lineColor: '#f0b90b',
        topColor: 'rgba(240,185,11,0.25)',
        bottomColor: 'rgba(240,185,11,0.02)',
        lineWidth: 2,
        priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
        priceScaleId: 'gold',
      });
      chart.priceScale('gold').applyOptions({
        scaleMargins: { top: 0.05, bottom: 0.15 },
        textColor: '#f0b90b',
      });
      goldSeries.setData(goldData.map(d => ({ time: d.d, value: d.v })));

      // Silver series (right axis)
      const silverSeries = chart.addAreaSeries({
        lineColor: '#a0a0a0',
        topColor: 'rgba(192,192,192,0.2)',
        bottomColor: 'rgba(192,192,192,0.01)',
        lineWidth: 2,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        priceScaleId: 'silver',
      });
      chart.priceScale('silver').applyOptions({
        scaleMargins: { top: 0.05, bottom: 0.15 },
        visible: true,
        textColor: '#a0a0a0',
      });
      silverSeries.setData(silverData.map(d => ({ time: d.d, value: d.v })));

      // Legend
      const legend = document.createElement('div');
      legend.style.cssText = 'position:absolute;top:8px;left:12px;display:flex;gap:16px;font-size:12px;pointer-events:none;z-index:2';
      legend.innerHTML = `<span style="color:#f0b90b">● 黄金 $${goldData[goldData.length-1].v.toFixed(1)}</span>
        <span style="color:#a0a0a0">● 白银 $${silverData[silverData.length-1].v.toFixed(2)}</span>`;
      container.style.position = 'relative';
      container.appendChild(legend);
      charts.trendChart = chart;
    }
  }

  // ── Radar & Judgment ──
  if(factors && factors.factors) {
    const dirs = FACTOR_ORDER.map(k => {
      const f = factors.factors[k]; if(!f) return 0;
      const sigs = f.data && f.data.signals;
      if(!sigs) return 0;
      const periods = ['short','mid','long'];
      const bullish = periods.filter(p => sigs[p] && sigs[p].direction==='bullish').length;
      const bearish = periods.filter(p => sigs[p] && sigs[p].direction==='bearish').length;
      if(bullish > bearish) return 1;
      if(bearish > bullish) return -1;
      return 0;
    });
    const radarCtx = document.getElementById('chart-radar');
    if(radarCtx) {
      if(charts.radar) charts.radar.destroy();
      charts.radar = new Chart(radarCtx, {
        type: 'radar', data: {
          labels: FACTOR_ORDER.map(k => FACTOR_LABELS[k]),
          datasets: [{
            data: dirs.map(d => Math.abs(d)),
            backgroundColor: 'rgba(74,158,255,0.12)',
            borderColor: '#4a9eff',
            borderWidth: 2, pointRadius: 5,
            pointBackgroundColor: dirs.map(d => d>0 ? '#2dd4a0' : d<0 ? '#ff6b6b' : '#8b92a8'),
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { r: {
            min: 0, max: 1,
            ticks: { display: false, stepSize: 0.2 },
            grid: { color: 'rgba(255,255,255,0.06)' },
            angleLines: { color: 'rgba(255,255,255,0.06)' },
            pointLabels: { color: '#8b92a8', font: { size: 12, weight:'500' } }
          } }
        }
      });
    }

    // Judgment panel
    const sigs = FACTOR_ORDER.map(k => factors.factors[k]).filter(Boolean);
    const dirsList = sigs.map(getFactorDir).filter(Boolean);
    const bullish = dirsList.filter(d => d==='bullish').length;
    const bearish = dirsList.filter(d => d==='bearish').length;
    const netDir = bullish > bearish ? 'bullish' : bearish > bullish ? 'bearish' : 'neutral';
    $('j-direction').innerHTML = fmtDir(netDir);
    const conLevel = dirsList.filter(d => d!=='neutral').length;
    $('j-confidence').textContent = conLevel >= 4 ? '高 ('+conLevel+'/7)' : conLevel >= 2 ? '中 ('+conLevel+'/7)' : '低 ('+conLevel+'/7)';

    // Dominant factor (strongest signal)
    let strongest = null, strongestStr = 0;
    sigs.forEach(s => {
      const str = getFactorStrength(s);
      if(str > strongestStr) { strongestStr = str; strongest = s; }
    });
    const domDir = strongest ? getFactorDir(strongest) : '';
    const domVal = strongest ? FACTOR_LABELS[strongest.label||'']||strongest.label||'--' : '--';
    $('j-dominant').innerHTML = domVal + (domDir ? ' '+fmtDir(domDir, {arrow:true}) : '');

    // Period signals
    const byPeriod = { short: [], mid: [], long: [] };
    sigs.forEach(s => {
      const sigsData = s.data && s.data.signals;
      if(!sigsData) return;
      ['short','mid','long'].forEach(p => {
        if(sigsData[p]) {
          const sp = sigsData[p];
          const label = FACTOR_LABELS[s.label||'']||s.label||'';
          byPeriod[p].push({...sp, label});
        }
      });
    });
    ['short','mid','long'].forEach(p => {
      const arr = byPeriod[p].filter(Boolean);
      const b = arr.filter(x => x.direction==='bullish').length;
      const be = arr.filter(x => x.direction==='bearish').length;
      const net = b - be;
      const pLabel = {short:'短期',mid:'中期',long:'长期'}[p];
      $('j-'+p).innerHTML = net>0 ? fmtDir('bullish') : net<0 ? fmtDir('bearish') : fmtDir('neutral') +
        ` <span style="color:var(--text3);font-size:12px">(${b}看多/${be}看空)</span>`;
    });
  }

  // ── Indicator chips with changes ──
  const ind = $('indicator-row'); ind.innerHTML = '';
  const items = [
    {k:'dxy',l:'DXY',f:'change_pct'},{k:'vix',l:'VIX'},{k:'sp500',l:'S&P 500',f:'change_pct'},
    {k:'treasury_10y',l:'US10Y',fmt: v => v+'%',f:'change_bp',fbp: true},
    {k:'tips_10y',l:'TIPS 10Y',fmt: v => v+'%'},
    {k:'oil_wti',l:'WTI 原油',fmt: v => '$'+v},
  ];
  items.forEach(({k,l,f,fmt,fbp}) => {
    const v = snap[k]||{};
    const val = v.value;
    const chip = document.createElement('div'); chip.className = 'indicator-chip';
    let chgHtml = '';
    if(f && v[f] != null) {
      const chg = Number(v[f]);
      const sign = chg >= 0 ? '+' : '';
      const unit = fbp ? 'bp' : '%';
      const cls = chg >= 0 ? 'color:var(--teal)' : 'color:var(--coral)';
      chgHtml = `<div class="chip-change"><span style="${cls}">${sign}${chg.toFixed(2)}${unit}</span></div>`;
    }
    chip.innerHTML = `<div class="chip-label">${l}</div>
      <div class="chip-value">${val!=null ? (fmt ? fmt(val) : Number(val).toLocaleString()) : '--'}</div>
      ${chgHtml}`;
    ind.appendChild(chip);
  });

  // ── Events with severity icons ──
  const evtData = snap.events || {};
  const allEvents = [];
  (evtData.active_s||[]).forEach(t => allEvents.push({title:t, severity:'s'}));
  (evtData.active_a||[]).forEach(t => allEvents.push({title:t, severity:'a'}));

  const evtList = $('events-list'); evtList.innerHTML = '';
  if(allEvents.length) {
    allEvents.forEach(e => {
      const el = document.createElement('div'); el.className = 'event-item';
      const icon = SEVERITY_ICONS[e.severity]||'🔔';
      const sevLabel = SEVERITY_LABELS[e.severity]||'';
      el.innerHTML = `<div class="event-icon">${icon}</div>
        <div><div class="event-title">${e.title}</div>
        <div class="event-meta"><span class="event-tag">${sevLabel}</span></div></div>`;
      evtList.appendChild(el);
    });
  } else {
    evtList.innerHTML = '<div style="color:var(--text3);padding:12px;">暂无活跃事件</div>';
  }
}

// ═══════════════════════ 七因子 ═══════════════════════

async function loadFactors() {
  const data = await fetchJSON('/api/factors');
  $('factors-time').textContent = '更新: '+(data.updated_at||'--');
  const container = $('factor-cards'); container.innerHTML = '';
  if(!data || !data.factors) { container.innerHTML = '<div style="color:var(--text3)">暂无数据</div>'; return; }

  const periodLabels = { short:'短', mid:'中', long:'长' };
  const metricLabels = {
    tips_10y: 'TIPS 10Y', tips_10y_trend_20d: '趋势',
    nominal_10y: '名义利率',
    dxy: 'DXY', dxy_change_d: '变动', dxy_vs_200ma: 'vs 200MA', dxy_trend_60d: '60日趋势',
    gold_vs_200ma: 'vs 200MA', gold_vs_50ma: 'vs 50MA',
    rsi_14: 'RSI(14)', macd_signal: 'MACD',
    silver_vs_200ma: 'vs 200MA',
    gs_ratio: '金银比',
    cpi_yoy: 'CPI 同比', pce_core: '核心PCE', breakeven_10y: '盈亏平衡',
    fedwatch_prob: '加息概率',
    gold_efficiency_ratio: '效率比', silver_efficiency_ratio: '效率比',
    gold_volume_z: '成交量 Z', silver_volume_z: '成交量 Z',
  };

  const metricPriorities = {
    opportunity_cost: ['nominal_10y','tips_10y'],
    currency: ['dxy','dxy_trend_60d','dxy_vs_200ma'],
    safe_haven: ['rsi_14','gold_vs_200ma','vix'],
    inflation: ['tips_10y','breakeven_10y','cpi_yoy','pce_core'],
    positioning: ['rsi_14','gold_vs_200ma','gold_vs_50ma','gold_efficiency_ratio'],
    structural_demand: ['silver_vs_200ma','gs_ratio'],
    silver_specific: ['rsi_14','silver_vs_200ma','silver_efficiency_ratio'],
  };

  FACTOR_ORDER.forEach(key => {
    const f = data.factors[key]; if(!f) return;
    const dir = getFactorDir(f) || 'neutral';
    const strength = getFactorStrength(f);
    const fSigs = (f.data && f.data.signals) || {};
    const d = f.data||{};
    const sec = document.createElement('div'); sec.className = 'factor-section';

    // Header
    const headerHtml = `<div class="factor-header">
      <div class="factor-name">${FACTOR_LABELS[key]||key}</div>
      <div class="factor-signal ${dir}">
        ${dir==='bullish'?'▲ 看多':dir==='bearish'?'▼ 看空':'→ 中性'}
        ${strength != null ? ' <span style="opacity:0.7">| 强度 '+strength.toFixed(1)+'</span>' : ''}
      </div>
    </div>`;

    // Left side: key metrics + 3-period direction chips
    let leftHtml = '<div class="factor-left">';

    // Priority metrics (2-3 key metrics for this factor)
    const priority = metricPriorities[key] || [];
    const showMetrics = priority.map(k => {
      const v = d[k];
      if(!v) return null;
      const label = metricLabels[k]||k;
      let valStr = '';
      if(v && typeof v === 'object' && v.value != null) {
        valStr = v.value;
      } else {
        valStr = typeof v === 'number' ? v.toFixed(2) : String(v);
      }
      return { label, valStr };
    }).filter(Boolean).slice(0,3);

    if(showMetrics.length) {
      leftHtml += '<div class="factor-metrics">';
      showMetrics.forEach(m => {
        leftHtml += `<div class="factor-metric"><div class="m-label">${m.label}</div>
          <div class="m-value">${m.valStr}</div></div>`;
      });
      leftHtml += '</div>';
    }

    // Three-cycle direction chips (compact inline)
    leftHtml += '<div class="factor-periods">';
    ['short','mid','long'].forEach(p => {
      const s = fSigs[p]||{};
      const dClass = s.direction==='bullish'?'dir-up':s.direction==='bearish'?'dir-down':'dir-neu';
      const arrow = s.direction==='bullish'?'▲':s.direction==='bearish'?'▼':'→';
      leftHtml += `<div class="period-chip ${dClass}">
        <span class="p-label">${periodLabels[p]}</span>
        <span class="p-arrow">${arrow}</span>
        <span class="p-str">${fmtStrength(s.strength)}</span>
      </div>`;
    });
    leftHtml += '</div></div>';

    // Right side: trend chart container
    const rightHtml = `<div class="factor-right"><div id="ftrend-${key}" class="factor-trend-chart"></div></div>`;

    sec.innerHTML = headerHtml + '<div class="factor-body">' + leftHtml + rightHtml + '</div>';
    container.appendChild(sec);
  });

  // ── Factor trend charts (Lightweight Charts) ──
  const hdata = {};
  await Promise.all(
    [...new Set(FACTOR_ORDER.map(k => FACTOR_HISTORY[k]).filter(Boolean))].map(async sym => {
      try {
        const resp = await fetchJSON('/api/history/'+sym);
        hdata[sym] = resp || [];
      } catch(e) { hdata[sym] = []; }
    })
  );

  FACTOR_ORDER.forEach(key => {
    const sym = FACTOR_HISTORY[key];
    if(!sym) return;
    const data = hdata[sym];
    if(!data || !data.length) return;
    const container = document.getElementById('ftrend-'+key);
    if(!container) return;
    const color = FACTOR_SPARK_COLORS[key]||'#4a9eff';

    if(charts['ftrend-'+key]) { charts['ftrend-'+key].remove(); delete charts['ftrend-'+key]; }

    try {
      const lc = LightweightCharts;
      const chart = lc.createChart(container, {
        width: container.clientWidth || 300, height: 130,
        layout: {
          textColor: '#5a6278',
          background: { type: 'solid', color: 'transparent' },
          fontSize: 10,
        },
        grid: {
          vertLines: { color: 'rgba(255,255,255,0.03)' },
          horzLines: { color: 'rgba(255,255,255,0.04)' },
        },
        timeScale: {
          borderColor: 'rgba(255,255,255,0.06)',
          timeVisible: false,
          ticksVisible: true,
          fixLeftEdge: true,
          fixRightEdge: true,
        },
        leftPriceScale: { visible: false },
        rightPriceScale: { visible: false },
        crosshair: { mode: lc.CrosshairMode.Normal },
        handleScroll: false,
        handleScale: false,
      });

      const series = chart.addAreaSeries({
        lineColor: color,
        topColor: color+'33',
        bottomColor: color+'05',
        lineWidth: 2,
        priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
      });
      series.setData(data.map(d => ({ time: d.d, value: d.v })));
      chart.timeScale().fitContent();
      charts['ftrend-'+key] = chart;
    } catch(e) {
      console.warn('Factor chart error ['+key+']:', e);
    }
  });
}

// ═══════════════════════ 数据监控 ═══════════════════════

async function loadMonitor() {
  const [snap, monitor] = await Promise.all([fetchJSON('/api/snapshot'), fetchJSON('/api/monitor')]);
  $('monitor-time').textContent = '更新: '+(snap.global_updated_at||'--');

  const realtime = [
    {k:'gold_futures',n:'COMEX 黄金',s:'akshare 新浪外盘'},
    {k:'silver_futures',n:'COMEX 白银',s:'akshare 新浪外盘'},
    {k:'gold_price',n:'黄金现货',s:'gold-api.com'},
    {k:'dxy',n:'美元指数 DXY',s:'yfinance'},
  ];
  const daily = [
    {k:'vix',n:'VIX 恐慌指数',s:'CBOE CSV'},
    {k:'sp500',n:'标普500',s:'FRED CSV'},
    {k:'treasury_10y',n:'美债 10Y',s:'U.S. Treasury'},
    {k:'tips_10y',n:'TIPS 10Y',s:'FRED CSV'},
    {k:'shfe_gold',n:'沪金',s:'akshare 上期所'},
    {k:'shfe_silver',n:'沪银',s:'akshare 上期所'},
    {k:'usdcnh',n:'美元/人民币',s:'yfinance'},
  ];

  const grid = $('monitor-grid'); grid.innerHTML = '';

  function buildSection(title, items) {
    let html = `<div class="monitor-section-title">${title}</div>`;
    items.forEach(({k,n,s}) => {
      const v = monitor[k]||{};
      const ts = v.updated_at||'';
      const minAgo = ts ? Math.floor((Date.now()-new Date(ts.replace(' ','T')+'+08:00').getTime())/60000) : -1;

      let status, statusLabel;
      if(minAgo < 0) { status='pending'; statusLabel='待获取'; }
      else if(minAgo > 2880) { status='pending'; statusLabel='已过期'; }
      else if(minAgo > 180) { status='backup'; statusLabel=Math.floor(minAgo/60)+'h前'; }
      else { status='active'; statusLabel=minAgo<60?minAgo+'m前':Math.floor(minAgo/60)+'h前'; }

      const valDisplay = v.value!=null
        ? (typeof v.value==='number' ? Number(v.value).toLocaleString(undefined,{maximumFractionDigits:2}) : v.value)
        : '--';

      html += `<div class="monitor-item">
        <div><div class="monitor-name">${n}</div><div class="monitor-source">${s}</div></div>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:12px;color:var(--text2)">${valDisplay}</span>
          <span class="dm-status ${status}"><span class="dm-status-dot"></span>${statusLabel}</span>
        </div>
      </div>`;
    });
    return html;
  }

  grid.innerHTML = buildSection('实时采集', realtime) + buildSection('日频采集', daily);

  // V0-style coverage bar
  const allKeys = ['gold_price','silver_price','gold_silver_ratio','dxy','vix','sp500',
    'treasury_10y','treasury_30y','tips_10y','gold_futures','silver_futures','shfe_gold','shfe_silver','usdcnh'];
  const fresh = allKeys.filter(k => {
    const v = monitor[k]; if(!v||!v.updated_at) return false;
    const minAgo = Math.floor((Date.now()-new Date(v.updated_at.replace(' ','T')+'+08:00').getTime())/60000);
    return minAgo >= 0 && minAgo < 2880;
  });
  const stale = allKeys.length - fresh.length;
  const pct = Math.round(fresh.length/allKeys.length*100);
  const barClass = pct >= 80 ? 'fresh' : pct >= 50 ? 'aging' : 'stale';
  $('coverage-bar').innerHTML = `<div class="coverage-wrap">
    <div class="coverage-track"><div class="coverage-fill ${barClass}" style="width:${pct}%"></div></div>
    <div class="coverage-info">
      <span class="ci-range"><span class="num">${fresh.length}</span>/${allKeys.length} 新鲜 (${pct}%)</span>
      <span class="ci-count">已过期 ${stale} 个字段</span>
    </div>
  </div>`;
}

// ═══════════════════════ Init ═══════════════════════

loadOverview();
loadFactors();
loadMonitor();
setInterval(() => { loadOverview(); loadMonitor(); }, 30000);
setInterval(() => loadFactors(), 300000);