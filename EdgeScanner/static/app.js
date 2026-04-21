'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let allSetups = [];
let pollTimer = null;

// ── Polling ───────────────────────────────────────────────────────────────────
async function fetchSetups() {
  try {
    const res = await fetch('/api/setups?limit=100');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allSetups = data.setups || [];
    updateStatus(data.status, data.last_scan);
    updateStats(allSetups);
    renderSetups(applyFilters(allSetups));
  } catch (e) {
    setStatusDot('error', 'Connection error');
  }
}

async function fetchHealth() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    setStatusDot(data.scan_status, formatStatus(data.scan_status, data.last_scan, data.scan_count));
  } catch (_) {
    setStatusDot('error', 'Offline');
  }
}

function startPolling() {
  fetchSetups();
  fetchHealth();
  pollTimer = setInterval(() => {
    fetchSetups();
    fetchHealth();
  }, 15_000);
}

// ── Trigger scan ──────────────────────────────────────────────────────────────
async function triggerScan() {
  const btn = document.getElementById('btnScan');
  btn.disabled = true;
  btn.textContent = '⟳ Scanning...';
  try {
    await fetch('/api/scan');
    setStatusDot('scanning', 'Scan triggered — results in ~30s');
    // Poll more aggressively while scanning
    clearInterval(pollTimer);
    const quick = setInterval(async () => {
      const r = await fetch('/api/health').then(x => x.json()).catch(() => ({}));
      if (r.scan_status !== 'scanning') {
        clearInterval(quick);
        startPolling();
        btn.disabled = false;
        btn.textContent = '⟳ Scan Now';
      }
    }, 3_000);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = '⟳ Scan Now';
  }
}

// ── Custom scan ───────────────────────────────────────────────────────────────
async function runCustomScan() {
  const input = document.getElementById('customSymbols').value.trim();
  if (!input) return;

  const symbols = input.split(/[,\s]+/).map(s => s.toUpperCase()).filter(Boolean);
  if (!symbols.length) return;

  const btn = document.querySelector('.btn-custom');
  btn.disabled = true;
  btn.textContent = 'Scanning...';
  setStatusDot('scanning', `Scanning ${symbols.length} symbols...`);

  try {
    const res = await fetch('/api/scan/custom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols }),
    });
    const data = await res.json();
    allSetups = data.setups || [];
    updateStats(allSetups);
    renderSetups(applyFilters(allSetups));
    setStatusDot('idle', `Custom scan complete — ${data.count} setups`);
  } catch (e) {
    setStatusDot('error', 'Custom scan failed');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Scan';
  }
}

// ── Filters ───────────────────────────────────────────────────────────────────
function applyFilters(setups) {
  if (!setups) setups = allSetups;
  const dir      = document.getElementById('filterDir').value;
  const pattern  = document.getElementById('filterPattern').value;
  const minScore = parseFloat(document.getElementById('filterScore').value) || 0;

  return setups.filter(s => {
    if (dir !== 'all' && s.direction !== dir) return false;
    if (pattern !== 'all' && !s.pattern?.includes(pattern)) return false;
    if (s.edge_score < minScore) return false;
    return true;
  });
}

// Called by onchange on filter selects
function applyFilters() {
  renderSetups(applyFilters(allSetups));
}
// Override to avoid shadowing
window.applyFilters = function() {
  renderSetups(filterSetups(allSetups));
};
function filterSetups(setups) {
  const dir      = document.getElementById('filterDir').value;
  const pattern  = document.getElementById('filterPattern').value;
  const minScore = parseFloat(document.getElementById('filterScore').value) || 0;
  return setups.filter(s => {
    if (dir !== 'all' && s.direction !== dir) return false;
    if (pattern !== 'all' && !s.pattern?.includes(pattern)) return false;
    if (s.edge_score < minScore) return false;
    return true;
  });
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function updateStats(setups) {
  const bull = setups.filter(s => s.direction === 'bullish').length;
  const bear = setups.filter(s => s.direction === 'bearish').length;
  const top  = setups.length ? Math.max(...setups.map(s => s.edge_score)) : 0;

  document.getElementById('statTotal').textContent = setups.length;
  document.getElementById('statBull').textContent  = bull;
  document.getElementById('statBear').textContent  = bear;
  document.getElementById('statTop').textContent   = setups.length ? top.toFixed(1) : '—';
}

function updateStatus(status, lastScan) {
  setStatusDot(status, formatStatus(status, lastScan));
}

function setStatusDot(status, text) {
  const dot  = document.getElementById('statusDot');
  const span = document.getElementById('statusText');
  dot.className = `status-dot ${status}`;
  if (text) span.textContent = text;
}

function formatStatus(status, lastScan, count) {
  if (status === 'scanning') return 'Scanning...';
  if (status === 'error')    return 'Scan error';
  if (!lastScan) return 'Awaiting first scan';
  const d = new Date(lastScan);
  const ago = Math.round((Date.now() - d) / 60_000);
  const timeStr = ago < 1 ? 'just now' : `${ago}m ago`;
  return `Last scan ${timeStr}${count ? ` · #${count}` : ''}`;
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderSetups(setups) {
  const grid  = document.getElementById('setupsGrid');
  const empty = document.getElementById('emptyState');

  document.getElementById('statLast').textContent = setups.length
    ? new Date().toLocaleTimeString()
    : '—';

  if (!setups.length) {
    grid.innerHTML = '';
    grid.appendChild(empty);
    empty.style.display = '';
    return;
  }

  empty.style.display = 'none';
  grid.innerHTML = setups.map(buildCard).join('');
}

function buildCard(s) {
  const grade     = s.grade || 'NA';
  const dir       = s.direction || 'bullish';
  const edgeFill  = edgeBarClass(s.edge_score);
  const probScore = s.probability_score;
  const conv      = s.conviction;

  const aiBlock = s.ai_commentary ? `
    <div class="ai-block">
      <div class="ai-label">◆ AI Analysis</div>
      <div>${esc(s.ai_commentary)}</div>
      ${probScore != null ? `<div class="ai-probability">Probability score: <strong>${probScore}</strong>/100</div>` : ''}
    </div>
    ${conv ? `<div class="conviction conv-${esc(conv)}">${esc(conv)} CONVICTION</div>` : ''}
    ${s.bull_case || s.bear_case ? `
    <div class="case-row">
      ${s.bull_case ? `<div class="case-pill bull-pill"><div class="case-pill-label">▲ Bull</div>${esc(s.bull_case)}</div>` : ''}
      ${s.bear_case ? `<div class="case-pill bear-pill"><div class="case-pill-label">▼ Bear</div>${esc(s.bear_case)}</div>` : ''}
    </div>` : ''}
  ` : '<div style="color:var(--muted);font-size:11px;">AI analysis pending...</div>';

  const metrics = buildMetrics(s);

  return `
  <div class="setup-card ${esc(dir)}">
    <div class="card-header">
      <div>
        <div class="card-symbol">${esc(s.symbol)}</div>
        <div class="card-pattern">${esc(s.pattern)}</div>
      </div>
      <div class="card-grade grade-${esc(grade)}">${esc(grade)}</div>
    </div>
    <div class="card-body">
      <div class="edge-bar-wrap">
        <div class="edge-bar-label">
          <span>Edge Score</span>
          <span>${s.edge_score?.toFixed(1)}</span>
        </div>
        <div class="edge-bar-track">
          <div class="edge-bar-fill ${edgeFill}" style="width:${s.edge_score}%"></div>
        </div>
      </div>

      ${s.entry ? `
      <div class="trade-plan">
        <div class="plan-item">
          <div class="plan-label">Entry</div>
          <div class="plan-val entry">$${s.entry}</div>
        </div>
        <div class="plan-item">
          <div class="plan-label">Stop</div>
          <div class="plan-val stop">$${s.stop}</div>
        </div>
        <div class="plan-item">
          <div class="plan-label">Target</div>
          <div class="plan-val target">$${s.target}</div>
        </div>
      </div>
      <div class="card-metrics">
        <div class="metric"><div class="metric-label">R:R</div><div class="metric-val">${s.rr_ratio}×</div></div>
        <div class="metric"><div class="metric-label">Risk %</div><div class="metric-val">${s.risk_pct}%</div></div>
        <div class="metric"><div class="metric-label">Shares/$1K</div><div class="metric-val">${s.position_size_1k}</div></div>
      </div>` : ''}

      ${metrics}
      ${aiBlock}
    </div>
  </div>`;
}

function buildMetrics(s) {
  const items = [];
  if (s.rsi       != null) items.push(['RSI',     s.rsi]);
  if (s.rvol      != null) items.push(['RVOL',    s.rvol + 'x']);
  if (s.z_score   != null) items.push(['Z-Score', s.z_score]);
  if (s.hurst     != null) items.push(['Hurst',   s.hurst]);
  if (s.momentum  != null) items.push(['Momentum', s.momentum.toFixed(3)]);
  if (s.impulse_pct != null) items.push(['Impulse', s.impulse_pct + '%']);
  if (s.breakout_pct != null) items.push(['Brkout', s.breakout_pct + '%']);

  if (!items.length) return '';
  return `<div class="card-metrics">
    ${items.map(([l, v]) => `
      <div class="metric">
        <div class="metric-label">${esc(l)}</div>
        <div class="metric-val">${esc(String(v))}</div>
      </div>`).join('')}
  </div>`;
}

function edgeBarClass(score) {
  if (score >= 75) return 'high';
  if (score >= 55) return 'mid';
  return 'low';
}

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ──────────────────────────────────────────────────────────────────────
startPolling();
