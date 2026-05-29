(function () {
  'use strict';

  const SCRIPT = document.currentScript;
  const SERVER = SCRIPT.src.replace(/\/badge\.js.*$/, '');
  const ENDPOINT_ID = new URLSearchParams(SCRIPT.src.split('?')[1] || '').get('endpoint') || '';
  const REFRESH_MS = parseInt(new URLSearchParams(SCRIPT.src.split('?')[1] || '').get('refresh') || '30000', 10);

  // ── Styles ──────────────────────────────────────────────────────────────────
  const CSS = `
    .proof402-badge-wrap {
      display: inline-flex; flex-direction: column;
      font-family: 'Courier New', monospace; font-size: 11px;
    }
    .proof402-badge {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 8px 14px;
      background: #0a0a0a;
      border: 1px solid #7c3aed;
      border-radius: 8px;
      text-decoration: none;
      color: #a78bfa;
      box-shadow: 0 0 10px rgba(124,58,237,0.25);
      transition: box-shadow .3s;
      cursor: default;
    }
    .proof402-badge:hover { box-shadow: 0 0 18px rgba(124,58,237,0.5); }
    .proof402-shield { flex-shrink: 0; }
    .proof402-lines { display: flex; flex-direction: column; gap: 2px; }
    .proof402-main  { color: #e2e8f0; font-size: 12px; font-weight: bold; letter-spacing: .5px; }
    .proof402-live  { color: #06b6d4; font-size: 10px; }
    .proof402-sub   { color: #6d28d9; font-size: 9px; letter-spacing: .5px; }
    .proof402-dot   {
      display: inline-block; width: 6px; height: 6px; border-radius: 50%;
      background: #10b981; margin-right: 4px;
      animation: proof402-pulse 2s infinite;
    }
    @keyframes proof402-pulse {
      0%,100% { opacity:1; } 50% { opacity:.3; }
    }
  `;

  // ── SVG shield ──────────────────────────────────────────────────────────────
  const SHIELD = `<svg class="proof402-shield" width="16" height="16" viewBox="0 0 24 24"
    fill="none" stroke="#7c3aed" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    <path d="M9 12l2 2 4-4" stroke="#10b981" stroke-width="2"/>
  </svg>`;

  // ── State ───────────────────────────────────────────────────────────────────
  let container = null;
  let liveEl    = null;
  let lastCount = null;
  let lastTime  = null;

  function relTime(isoString) {
    if (!isoString) return null;
    const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
    if (diff < 5)   return 'just now';
    if (diff < 60)  return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  }

  // ── Fetch + render ──────────────────────────────────────────────────────────
  async function fetchAndRender() {
    try {
      const [statsRes, epRes] = await Promise.all([
        fetch(`${SERVER}/v1/stats`),
        ENDPOINT_ID ? fetch(`${SERVER}/v1/leaderboard`) : Promise.resolve(null),
      ]);

      const stats = statsRes.ok ? await statsRes.json() : null;
      const lb    = epRes && epRes.ok ? await epRes.json() : null;

      let ep = null;
      if (lb && ENDPOINT_ID) {
        ep = (lb.endpoints || []).find(e => e.id === ENDPOINT_ID);
      }

      const totalCalls = stats?.total_calls ?? 0;
      const callsLabel = ep ? ep.total_calls : totalCalls;
      const priceLabel = ep ? `${ep.price} ${ep.asset}` : null;

      // Build live line
      let liveLine = '';
      if (totalCalls !== lastCount) {
        lastCount = totalCalls;
        lastTime = new Date().toISOString();
      }
      const ago = relTime(lastTime);
      if (priceLabel && ago) {
        liveLine = `Last: ${ago} · ${priceLabel}`;
      } else if (ago) {
        liveLine = `Last payment: ${ago}`;
      } else {
        liveLine = `${callsLabel} settled calls`;
      }

      if (liveEl) liveEl.textContent = liveLine;
    } catch (_) {
      if (liveEl) liveEl.textContent = 'Verifying on XRP Ledger…';
    }
  }

  // ── Inject badge ─────────────────────────────────────────────────────────────
  function inject() {
    // Style tag
    if (!document.getElementById('proof402-styles')) {
      const style = document.createElement('style');
      style.id = 'proof402-styles';
      style.textContent = CSS;
      document.head.appendChild(style);
    }

    // Build badge
    container = document.createElement('div');
    container.className = 'proof402-badge-wrap';
    container.innerHTML = `
      <div class="proof402-badge" title="Verified by 402Proof · XRP Ledger">
        ${SHIELD}
        <div class="proof402-lines">
          <div class="proof402-main">AI Agents Can Pay Here</div>
          <div class="proof402-live"><span class="proof402-dot"></span><span id="proof402-live-text">Connecting…</span></div>
          <div class="proof402-sub">VERIFIED BY 402PROOF · XRP LEDGER</div>
        </div>
      </div>`;

    SCRIPT.parentNode.insertBefore(container, SCRIPT.nextSibling);
    liveEl = container.querySelector('#proof402-live-text');

    fetchAndRender();
    setInterval(fetchAndRender, REFRESH_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
