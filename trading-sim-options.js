/* ═══════════════════════════════════════════════════════
   OPTIONS ENGINE — Black-Scholes, Greeks, Strategies, Chain
   ═══════════════════════════════════════════════════════ */

const OptionsEngine = (() => {

  /* ─── Black-Scholes ─── */
  function normCDF(x) {
    const a1=0.254829592, a2=-0.284496736, a3=1.421413741, a4=-1.453152027, a5=1.061405429, p=0.3275911;
    const sign = x < 0 ? -1 : 1;
    x = Math.abs(x) / Math.SQRT2;
    const t = 1 / (1 + p * x);
    const y = 1 - (((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);
    return 0.5 * (1 + sign * y);
  }

  function normPDF(x) { return Math.exp(-0.5*x*x) / Math.sqrt(2*Math.PI); }

  function calcPrice(S, K, T, sigma, type = 'call', r = 0.05) {
    if (T <= 0) return type === 'call' ? Math.max(0, S-K) : Math.max(0, K-S);
    if (sigma <= 0) return type === 'call' ? Math.max(0, S-K) : Math.max(0, K-S);
    const d1 = (Math.log(S/K) + (r + 0.5*sigma*sigma)*T) / (sigma*Math.sqrt(T));
    const d2 = d1 - sigma*Math.sqrt(T);
    if (type === 'call') return S*normCDF(d1) - K*Math.exp(-r*T)*normCDF(d2);
    return K*Math.exp(-r*T)*normCDF(-d2) - S*normCDF(-d1);
  }

  function calcGreeks(S, K, T, sigma, type = 'call', r = 0.05) {
    if (T <= 0) return { delta: type==='call'?1:0, gamma:0, theta:0, vega:0, rho:0 };
    const d1 = (Math.log(S/K) + (r + 0.5*sigma*sigma)*T) / (sigma*Math.sqrt(T));
    const d2 = d1 - sigma*Math.sqrt(T);
    const nd1 = normPDF(d1);
    const delta = type==='call' ? normCDF(d1) : normCDF(d1)-1;
    const gamma = nd1 / (S * sigma * Math.sqrt(T));
    const theta = type==='call'
      ? (-S*nd1*sigma/(2*Math.sqrt(T)) - r*K*Math.exp(-r*T)*normCDF(d2))/365
      : (-S*nd1*sigma/(2*Math.sqrt(T)) + r*K*Math.exp(-r*T)*normCDF(-d2))/365;
    const vega = S*nd1*Math.sqrt(T)/100;
    const rho  = type==='call' ? K*T*Math.exp(-r*T)*normCDF(d2)/100 : -K*T*Math.exp(-r*T)*normCDF(-d2)/100;
    return { delta:+delta.toFixed(4), gamma:+gamma.toFixed(5), theta:+theta.toFixed(4), vega:+vega.toFixed(4), rho:+rho.toFixed(4) };
  }

  /* ─── Chain Generation ─── */
  function generateChain(sym, S, iv, expiries) {
    const chain = {};
    expiries.forEach(exp => {
      const dte = Math.max(1, Math.round((new Date(exp) - new Date()) / 86400000));
      const T   = dte / 365;
      const strikes = generateStrikes(S);
      chain[exp] = strikes.map(K => {
        const ivSkew = iv * (1 + 0.1 * Math.abs(Math.log(S/K)));
        const callP  = calcPrice(S, K, T, ivSkew, 'call');
        const putP   = calcPrice(S, K, T, ivSkew, 'put');
        const callG  = calcGreeks(S, K, T, ivSkew, 'call');
        const putG   = calcGreeks(S, K, T, ivSkew, 'put');
        const spread = Math.max(0.01, callP * 0.02);
        const callOI = Math.round(1000 + Math.random()*5000);
        const putOI  = Math.round(800  + Math.random()*4000);
        return {
          strike: K, dte, T,
          call: { bid:+(callP-spread).toFixed(2), ask:+(callP+spread).toFixed(2), mid:+callP.toFixed(2), iv:+ivSkew.toFixed(3), oi:callOI, vol:Math.round(callOI*0.3), ...callG, itm: S > K },
          put:  { bid:+(putP-spread).toFixed(2),  ask:+(putP+spread).toFixed(2),  mid:+putP.toFixed(2),  iv:+ivSkew.toFixed(3), oi:putOI,  vol:Math.round(putOI*0.3),  ...putG, itm: S < K },
        };
      });
    });
    return chain;
  }

  function generateStrikes(S) {
    const step = S < 5 ? 0.5 : S < 20 ? 1 : S < 100 ? 2.5 : S < 300 ? 5 : S < 1000 ? 10 : 25;
    const atm = Math.round(S / step) * step;
    const strikes = [];
    for (let i = -10; i <= 10; i++) strikes.push(+(atm + i * step).toFixed(2));
    return strikes.filter(k => k > 0);
  }

  function getExpiries() {
    const dates = [];
    const now = new Date();
    // This Friday (0DTE), next 4 Fridays, then monthly
    for (let i = 0; i < 8; i++) {
      const d = new Date(now);
      d.setDate(d.getDate() + (i === 0 ? (5 - d.getDay() + 7) % 7 || 7 : i * 7));
      dates.push(d.toISOString().slice(0, 10));
    }
    return [...new Set(dates)].slice(0, 6);
  }

  /* ─── Current Chain State ─── */
  let _currentChain = {};
  let _currentSym   = '';
  let _chainView    = 'standard';
  let _ivChart      = null;
  let _pnlChart     = null;

  function init() {
    populateChainSymbol();
    renderMiniChain();
    renderStrategyList();
  }

  function populateChainSymbol() {
    const sel = $('chain-sym-sel');
    if (!sel) return;
    const syms = Object.keys(_state.symbols).sort();
    sel.innerHTML = syms.map(s => `<option value="${s}">${s}</option>`).join('');
  }

  function loadChain(sym) {
    if (!sym) sym = _currentSym || _state.ui.currentSymbol;
    const s = _state.symbols[sym];
    if (!s) return;
    _currentSym = sym;
    const expiries = getExpiries();
    _currentChain = generateChain(sym, s.price, s.iv, expiries);

    // Populate expiry selector
    const sel = $('chain-expiry-sel');
    if (sel) sel.innerHTML = expiries.map(e => `<option value="${e}">${e} (${Math.round((new Date(e)-new Date())/86400000)}d)</option>`).join('');

    renderChainStats(sym, s);
    renderChainTable(expiries[1]);
    renderIVSmile(sym, s, expiries[1]);
  }

  function renderChainStats(sym, s) {
    const el = $('chain-stats-bar');
    if (!el) return;
    const stats = [
      { l:'SYMBOL', v:sym }, { l:'PRICE', v:'$'+s.price.toFixed(2) },
      { l:'IV (ATM)', v:(s.iv*100).toFixed(1)+'%' }, { l:'IV RANK', v:Math.round(Math.random()*100)+'%' },
      { l:'CHANGE', v:(s.changePct>=0?'+':'')+(s.changePct*100).toFixed(2)+'%' },
      { l:'VOLUME', v:(s.vol/1e6).toFixed(1)+'M' },
    ];
    el.innerHTML = stats.map(st => `<div class="csb-item"><div class="csb-l">${st.l}</div><div class="csb-v">${st.v}</div></div>`).join('');
    const aimv = $('chain-atm-iv');
    if (aimv) aimv.textContent = `ATM IV: ${(s.iv*100).toFixed(1)}%`;
  }

  function filterExpiry(exp) { renderChainTable(exp); renderIVSmile(_currentSym, _state.symbols[_currentSym], exp); }
  function setChainView(v) { _chainView = v; filterExpiry($('chain-expiry-sel')?.value); }

  function renderChainTable(exp) {
    const thead = $('chain-thead');
    const tbody = $('chain-tbody');
    if (!thead || !tbody) return;
    const rows = _currentChain[exp];
    if (!rows) return;
    const S = _state.symbols[_currentSym]?.price || 0;

    let ths = '';
    if (_chainView === 'standard') {
      ths = `<tr>
        <th colspan="5" class="calls-header">CALLS</th>
        <th class="strike-header">STRIKE</th>
        <th colspan="5" class="puts-header">PUTS</th>
      </tr><tr>
        <th class="calls-header">BID</th><th class="calls-header">ASK</th><th class="calls-header">DELTA</th><th class="calls-header">IV</th><th class="calls-header">OI</th>
        <th class="strike-header">—</th>
        <th class="puts-header">BID</th><th class="puts-header">ASK</th><th class="puts-header">DELTA</th><th class="puts-header">IV</th><th class="puts-header">OI</th>
      </tr>`;
    } else if (_chainView === 'greeks') {
      ths = `<tr>
        <th colspan="5" class="calls-header">CALLS — GREEKS</th>
        <th class="strike-header">STRIKE</th>
        <th colspan="5" class="puts-header">PUTS — GREEKS</th>
      </tr><tr>
        <th class="calls-header">Δ Delta</th><th class="calls-header">Γ Gamma</th><th class="calls-header">Θ Theta</th><th class="calls-header">ν Vega</th><th class="calls-header">ρ Rho</th>
        <th class="strike-header">—</th>
        <th class="puts-header">Δ Delta</th><th class="puts-header">Γ Gamma</th><th class="puts-header">Θ Theta</th><th class="puts-header">ν Vega</th><th class="puts-header">ρ Rho</th>
      </tr>`;
    } else if (_chainView === 'oi') {
      ths = `<tr>
        <th colspan="3" class="calls-header">CALLS</th><th class="strike-header">STRIKE</th><th colspan="3" class="puts-header">PUTS</th>
      </tr><tr>
        <th class="calls-header">OI</th><th class="calls-header">VOL</th><th class="calls-header">OI/VOL</th>
        <th class="strike-header">—</th>
        <th class="puts-header">OI</th><th class="puts-header">VOL</th><th class="puts-header">OI/VOL</th>
      </tr>`;
    }
    thead.innerHTML = ths;

    tbody.innerHTML = rows.map(row => {
      const isATM = Math.abs(row.strike - S) < S * 0.005;
      const callITM = S > row.strike;
      const putITM  = S < row.strike;
      let cells = '';
      if (_chainView === 'standard') {
        cells = `
          <td class="${callITM?'chain-itm-call':''} chain-bid">${row.call.bid}</td>
          <td class="${callITM?'chain-itm-call':''} chain-ask">${row.call.ask}</td>
          <td class="${callITM?'chain-itm-call':''} chain-greek">${row.call.delta}</td>
          <td class="${callITM?'chain-itm-call':''} chain-iv-val">${(row.call.iv*100).toFixed(1)}%</td>
          <td class="${callITM?'chain-itm-call':''} chain-oi">${row.call.oi.toLocaleString()}</td>
          <td class="chain-strike-cell">${row.strike}</td>
          <td class="${putITM?'chain-itm-put':''} chain-bid">${row.put.bid}</td>
          <td class="${putITM?'chain-itm-put':''} chain-ask">${row.put.ask}</td>
          <td class="${putITM?'chain-itm-put':''} chain-greek">${row.put.delta}</td>
          <td class="${putITM?'chain-itm-put':''} chain-iv-val">${(row.put.iv*100).toFixed(1)}%</td>
          <td class="${putITM?'chain-itm-put':''} chain-oi">${row.put.oi.toLocaleString()}</td>`;
      } else if (_chainView === 'greeks') {
        cells = `
          <td class="${callITM?'chain-itm-call':''} chain-greek">${row.call.delta}</td>
          <td class="${callITM?'chain-itm-call':''} chain-greek">${row.call.gamma}</td>
          <td class="${callITM?'chain-itm-call':''} chain-greek" style="color:#ff4757">${row.call.theta}</td>
          <td class="${callITM?'chain-itm-call':''} chain-greek">${row.call.vega}</td>
          <td class="${callITM?'chain-itm-call':''} chain-greek">${row.call.rho}</td>
          <td class="chain-strike-cell">${row.strike}</td>
          <td class="${putITM?'chain-itm-put':''} chain-greek">${row.put.delta}</td>
          <td class="${putITM?'chain-itm-put':''} chain-greek">${row.put.gamma}</td>
          <td class="${putITM?'chain-itm-put':''} chain-greek" style="color:#ff4757">${row.put.theta}</td>
          <td class="${putITM?'chain-itm-put':''} chain-greek">${row.put.vega}</td>
          <td class="${putITM?'chain-itm-put':''} chain-greek">${row.put.rho}</td>`;
      } else if (_chainView === 'oi') {
        cells = `
          <td class="chain-oi">${row.call.oi.toLocaleString()}</td>
          <td class="chain-oi">${row.call.vol.toLocaleString()}</td>
          <td class="chain-greek">${(row.call.oi/Math.max(row.call.vol,1)).toFixed(1)}</td>
          <td class="chain-strike-cell">${row.strike}</td>
          <td class="chain-oi">${row.put.oi.toLocaleString()}</td>
          <td class="chain-oi">${row.put.vol.toLocaleString()}</td>
          <td class="chain-greek">${(row.put.oi/Math.max(row.put.vol,1)).toFixed(1)}</td>`;
      }
      return `<tr class="${isATM?'chain-atm-row':''}" onclick="OptionsEngine.selectRow(${row.strike},'${exp}')">
        ${cells}
      </tr>`;
    }).join('');
  }

  function selectRow(strike, exp) {
    const sym = _currentSym || _state.ui.currentSymbol;
    const S   = _state.symbols[sym]?.price || 0;
    const rows = _currentChain[exp];
    const row = rows?.find(r => r.strike === strike);
    if (!row) return;
    // Open trade options panel with this row pre-selected
    buildOptionsOrder(sym, strike, exp, row, S);
  }

  function buildOptionsOrder(sym, strike, exp, row, S) {
    const el = $('opts-order-builder');
    if (!el) return;
    el.innerHTML = `
      <div style="margin-bottom:14px">
        <div style="font-size:18px;font-weight:900;color:#fff;font-family:var(--mono)">${sym} — Strike $${strike}</div>
        <div style="font-size:11px;color:var(--text2)">Expiry: ${exp} (${row.call.dte}d)</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
        <div style="background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.3);border-radius:8px;padding:12px">
          <div style="color:#00ff88;font-family:var(--mono);font-weight:700;margin-bottom:8px">CALL</div>
          <div style="font-family:var(--mono);font-size:12px;display:flex;flex-direction:column;gap:4px">
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Bid/Ask</span><span>$${row.call.bid} / $${row.call.ask}</span></div>
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Delta</span><span>${row.call.delta}</span></div>
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">IV</span><span>${(row.call.iv*100).toFixed(1)}%</span></div>
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Theta</span><span style="color:#ff4757">${row.call.theta}/day</span></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px">
            <button class="btn-primary" onclick="SimEngine.executeOptionTrade('${sym}',${strike},'${exp}','call','BUY',1)">Buy Call</button>
            <button class="btn-glass" onclick="SimEngine.executeOptionTrade('${sym}',${strike},'${exp}','call','SELL',1)">Sell Call</button>
          </div>
        </div>
        <div style="background:rgba(255,71,87,0.06);border:1px solid rgba(255,71,87,0.3);border-radius:8px;padding:12px">
          <div style="color:#ff4757;font-family:var(--mono);font-weight:700;margin-bottom:8px">PUT</div>
          <div style="font-family:var(--mono);font-size:12px;display:flex;flex-direction:column;gap:4px">
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Bid/Ask</span><span>$${row.put.bid} / $${row.put.ask}</span></div>
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Delta</span><span>${row.put.delta}</span></div>
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">IV</span><span>${(row.put.iv*100).toFixed(1)}%</span></div>
            <div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Theta</span><span style="color:#ff4757">${row.put.theta}/day</span></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px">
            <button class="btn-primary" onclick="SimEngine.executeOptionTrade('${sym}',${strike},'${exp}','put','BUY',1)">Buy Put</button>
            <button class="btn-glass" onclick="SimEngine.executeOptionTrade('${sym}',${strike},'${exp}','put','SELL',1)">Sell Put</button>
          </div>
        </div>
      </div>`;
    renderPnLDiagram(sym, strike, exp, S, row);
  }

  function renderPnLDiagram(sym, strike, exp, S, row) {
    const ctx = $('pnl-diag-chart')?.getContext('2d');
    if (!ctx) return;
    const prices = [];
    const step = S * 0.005;
    for (let p = S * 0.7; p <= S * 1.3; p += step) prices.push(+p.toFixed(2));
    const callPnl = prices.map(p => (Math.max(0, p - strike) - row.call.mid) * 100);
    const putPnl  = prices.map(p => (Math.max(0, strike - p) - row.put.mid) * 100);
    if (_pnlChart) { _pnlChart.destroy(); _pnlChart = null; }
    _pnlChart = new Chart(ctx, {
      type: 'line',
      data: { labels: prices, datasets: [
        { label:'Call P&L', data:callPnl, borderColor:'#00ff88', backgroundColor:'rgba(0,255,136,0.05)', fill:true, pointRadius:0, borderWidth:2 },
        { label:'Put P&L',  data:putPnl,  borderColor:'#ff4757', backgroundColor:'rgba(255,71,87,0.05)',  fill:true, pointRadius:0, borderWidth:2 },
      ]},
      options: {
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{labels:{color:'#888',font:{size:10}}} },
        scales:{
          x:{ ticks:{color:'#666',maxTicksLimit:6,callback:v=>'$'+prices[v]?.toFixed(0)}, grid:{color:'rgba(255,255,255,0.04)'} },
          y:{ ticks:{color:'#888',callback:v=>'$'+v}, grid:{color:'rgba(255,255,255,0.04)'},
              afterBuildTicks: ax => { ax.chart.options.plugins.annotation = { annotations:{ zero:{ type:'line', y:0, borderColor:'rgba(255,255,255,0.2)', borderWidth:1 } } }; } }
        }
      }
    });
    const mxCall = Math.max(...callPnl);
    const mxPut  = Math.max(...putPnl);
    const el = $('pnl-diag-stats');
    if (el) el.innerHTML = `
      <div class="pds-item"><div class="pds-l">CALL MAX PROFIT</div><div class="pds-v pos">$${mxCall > 9999 ? '∞' : mxCall.toFixed(0)}</div></div>
      <div class="pds-item"><div class="pds-l">PUT MAX PROFIT</div><div class="pds-v pos">$${mxPut > 9999 ? '∞' : mxPut.toFixed(0)}</div></div>
      <div class="pds-item"><div class="pds-l">COST (1 CONTRACT)</div><div class="pds-v">${'$'+(row.call.mid*100).toFixed(0)} / $${(row.put.mid*100).toFixed(0)}</div></div>`;
  }

  function renderIVSmile(sym, s, exp) {
    const ctx = $('iv-smile-chart')?.getContext('2d');
    if (!ctx) return;
    const rows  = _currentChain[exp];
    if (!rows) return;
    const strikes = rows.map(r => r.strike);
    const callIVs = rows.map(r => r.call.iv * 100);
    const putIVs  = rows.map(r => r.put.iv * 100);
    if (_ivChart) { _ivChart.destroy(); _ivChart = null; }
    _ivChart = new Chart(ctx, {
      type:'line',
      data:{ labels:strikes, datasets:[
        { label:'Call IV', data:callIVs, borderColor:'#00ff88', backgroundColor:'rgba(0,255,136,0.05)', fill:false, pointRadius:3, borderWidth:2 },
        { label:'Put IV',  data:putIVs,  borderColor:'#ff4757', backgroundColor:'rgba(255,71,87,0.05)',  fill:false, pointRadius:3, borderWidth:2 },
      ]},
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{labels:{color:'#888',font:{size:10}}} },
        scales:{ x:{ticks:{color:'#666',maxTicksLimit:8},grid:{color:'rgba(255,255,255,0.04)'}}, y:{ticks:{color:'#888',callback:v=>v+'%'},grid:{color:'rgba(255,255,255,0.04)'}} }
      }
    });
  }

  function renderMiniChain(exp) {
    const sym = _state.ui.currentSymbol;
    const s   = _state.symbols[sym];
    if (!s) return;
    if (!exp) {
      const expiries = getExpiries();
      exp = expiries[1];
      const sel = $('opts-expiry-sel');
      if (sel) sel.innerHTML = expiries.map(e => `<option value="${e}">${e}</option>`).join('');
      _currentChain = generateChain(sym, s.price, s.iv, expiries);
    }
    const el  = $('opts-chain-mini');
    if (!el) return;
    const rows = _currentChain[exp];
    if (!rows) return;
    const S = s.price;
    el.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(6,1fr);font-family:var(--mono);font-size:9px;color:var(--text3);padding:5px 8px;border-bottom:1px solid var(--border);letter-spacing:0.5px;text-transform:uppercase">
        <span>C-BID</span><span>C-ASK</span><span>STRIKE</span><span>P-BID</span><span>P-ASK</span><span>P-IV</span>
      </div>` +
      rows.map(row => {
        const isATM = Math.abs(row.strike - S) < S * 0.008;
        return `<div class="chain-mini-row ${isATM?'cmr-atm':''} ${S>row.strike?'itm-call':'itm-put'}"
          style="grid-template-columns:repeat(6,1fr)"
          onclick="OptionsEngine.buildOptionsOrder('${sym}',${row.strike},'${exp}',${JSON.stringify(row).replace(/"/g,"'")},${S})">
          <span class="chain-bid">${row.call.bid}</span>
          <span class="chain-ask">${row.call.ask}</span>
          <span class="chain-strike-cell" style="font-weight:700">${row.strike}</span>
          <span class="chain-bid">${row.put.bid}</span>
          <span class="chain-ask">${row.put.ask}</span>
          <span class="chain-iv-val">${(row.put.iv*100).toFixed(0)}%</span>
        </div>`;
      }).join('');
  }

  function renderStrategyList() {
    const el = $('opts-strategy-list');
    if (!el) return;
    el.innerHTML = STRATEGIES.map(s => `
      <div class="opts-strat-item" onclick="OptionsEngine.loadStrategy('${s.id}')">
        <div class="opts-strat-name">${s.icon} ${s.name}</div>
        <div class="opts-strat-tags">${s.tags.map(t=>`<span class="strat-tag ${t}">${t}</span>`).join('')}</div>
      </div>`).join('');
  }

  function loadStrategy(id) {
    const s = STRATEGIES.find(s => s.id === id);
    if (!s) return;
    document.querySelectorAll('.opts-strat-item').forEach(el => el.classList.toggle('selected', el.textContent.includes(s.name)));
    SimApp.showStratModal(id);
  }

  /* ─── Strategy Library ─── */
  const STRATEGIES = [
    {
      id:'long_call', name:'Long Call', icon:'📈', tags:['bullish','beginner'],
      desc:'Buy a call option to profit from upward price movement with limited risk.',
      detail:`<h3>Long Call</h3><p>The most basic bullish options strategy. You buy a call option, giving you the <strong>right to buy 100 shares</strong> at the strike price before expiration.</p>
      <div class="lesson-highlight"><strong>When to use:</strong> When you're bullish on a stock and expect a significant upward move.</div>
      <div class="lesson-example"><div class="lesson-example-title">Example</div><p>SPY is at $445. You buy a $450 call expiring in 30 days for $3.50 ($350 total). If SPY rises to $460, your call is worth ~$10+, giving you a 185%+ gain. If SPY stays below $450, you lose the $350 premium.</p></div>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Unlimited</li><li><strong>Max Loss:</strong> Premium paid</li><li><strong>Break-even:</strong> Strike + Premium</li></ul>`,
    },
    {
      id:'long_put', name:'Long Put', icon:'📉', tags:['bearish','beginner'],
      desc:'Buy a put option to profit from downward price movement.',
      detail:`<h3>Long Put</h3><p>Buy a put option to profit when a stock falls. Gives you the <strong>right to sell 100 shares</strong> at the strike price.</p>
      <div class="lesson-highlight"><strong>When to use:</strong> When you're bearish and expect a significant price decline.</div>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Strike - Premium (stock can go to $0)</li><li><strong>Max Loss:</strong> Premium paid</li><li><strong>Break-even:</strong> Strike - Premium</li></ul>`,
    },
    {
      id:'covered_call', name:'Covered Call', icon:'🛡️', tags:['neutral','beginner','income'],
      desc:'Own 100 shares, sell a call to collect premium and enhance returns.',
      detail:`<h3>Covered Call</h3><p>You own 100 shares AND sell a call option above the current price. You collect the premium as income.</p>
      <div class="lesson-highlight"><strong>When to use:</strong> When you own stock and want to generate extra income. You're okay selling at the strike price.</div>
      <div class="lesson-example"><div class="lesson-example-title">Example</div><p>You own 100 AAPL shares at $189. Sell the $195 call for $2.50. You collect $250 immediately. If AAPL stays below $195, you keep the premium. If AAPL rises above $195, your shares get called away at $195.</p></div>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Premium + (Strike - Purchase Price)</li><li><strong>Max Loss:</strong> Stock goes to $0 minus premium collected</li></ul>`,
    },
    {
      id:'cash_secured_put', name:'Cash-Secured Put', icon:'💰', tags:['neutral','beginner','income'],
      desc:'Sell a put while holding cash to buy the stock if assigned.',
      detail:`<h3>Cash-Secured Put</h3><p>Sell a put option and hold the cash needed to buy the shares if assigned. A great way to <strong>get paid to buy stocks you want at a discount</strong>.</p>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Premium collected</li><li><strong>Max Loss:</strong> Strike Price - Premium (you buy the stock)</li><li><strong>Break-even:</strong> Strike - Premium</li></ul>`,
    },
    {
      id:'bull_call_spread', name:'Bull Call Spread', icon:'🟢📈', tags:['bullish','intermediate'],
      desc:'Buy a lower call, sell a higher call. Reduces cost but caps profit.',
      detail:`<h3>Bull Call Spread (Debit Spread)</h3><p>Buy a lower-strike call and sell a higher-strike call with the same expiration. This reduces your cost but also caps your maximum profit.</p>
      <div class="lesson-example"><div class="lesson-example-title">Example</div><p>SPY at $445. Buy $445 call @ $5.00, Sell $455 call @ $2.00. Net debit = $3.00 ($300). Max profit = $7.00 ($700) if SPY reaches $455+. Max loss = $3.00 ($300).</p></div>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> (Width of strikes - debit) × 100</li><li><strong>Max Loss:</strong> Debit paid</li><li><strong>Best for:</strong> Moderately bullish outlook</li></ul>`,
    },
    {
      id:'bear_put_spread', name:'Bear Put Spread', icon:'🔴📉', tags:['bearish','intermediate'],
      desc:'Buy a higher put, sell a lower put. Limits cost and profit.',
      detail:`<h3>Bear Put Spread (Debit Spread)</h3><p>Buy a higher-strike put and sell a lower-strike put. Reduces premium paid while limiting your downside profit.</p>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> (Width of strikes - debit) × 100</li><li><strong>Max Loss:</strong> Debit paid</li></ul>`,
    },
    {
      id:'straddle', name:'Long Straddle', icon:'⚡', tags:['neutral','intermediate','volatility'],
      desc:'Buy both a call and put at the same strike. Profits from big moves either way.',
      detail:`<h3>Long Straddle</h3><p>Buy a call AND a put at the same strike and expiration. Profits when the stock makes a BIG move in either direction.</p>
      <div class="lesson-highlight"><strong>Best for:</strong> High-impact events like earnings, FDA decisions, or FOMC announcements where direction is uncertain but a big move is expected.</div>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Unlimited (in either direction)</li><li><strong>Max Loss:</strong> Total premium paid (both legs)</li><li><strong>Break-even:</strong> Strike ± Total Premium</li></ul>`,
    },
    {
      id:'strangle', name:'Long Strangle', icon:'🎭', tags:['neutral','intermediate','volatility'],
      desc:'Buy OTM call and OTM put. Cheaper than straddle, needs bigger move.',
      detail:`<h3>Long Strangle</h3><p>Similar to a straddle, but buy an OTM call and OTM put. Less expensive but requires a larger move to profit.</p>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Unlimited</li><li><strong>Max Loss:</strong> Total premium paid</li><li><strong>Cost:</strong> Cheaper than straddle</li></ul>`,
    },
    {
      id:'iron_condor', name:'Iron Condor', icon:'🦅', tags:['neutral','advanced','income'],
      desc:'Sell OTM call spread + OTM put spread. Collect premium in range-bound markets.',
      detail:`<h3>Iron Condor</h3><p>Sell an OTM call spread AND an OTM put spread simultaneously. This is a <strong>4-leg options strategy</strong> that profits when the stock stays within a defined range.</p>
      <div class="lesson-example"><div class="lesson-example-title">Example (SPY at $445)</div>
        <p>Sell $460 call / Buy $465 call (Bear call spread, collect $1.00)<br>
        Sell $430 put / Buy $425 put (Bull put spread, collect $1.00)<br>
        Total credit = $2.00 ($200). Max profit if SPY stays between $430-$460.</p>
      </div>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Net credit collected</li><li><strong>Max Loss:</strong> Width of widest spread - credit</li><li><strong>POP:</strong> ~70%</li></ul>`,
    },
    {
      id:'iron_butterfly', name:'Iron Butterfly', icon:'🦋', tags:['neutral','advanced','income'],
      desc:'Sell ATM straddle, buy OTM wings. High credit, narrow profit zone.',
      detail:`<h3>Iron Butterfly</h3><p>Sell an ATM call and ATM put, then buy OTM call and OTM put as wings. Collects maximum premium but has a narrow profit zone.</p>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Net credit (at exact strike at expiry)</li><li><strong>Max Loss:</strong> Wing width - credit</li></ul>`,
    },
    {
      id:'calendar_spread', name:'Calendar Spread', icon:'📅', tags:['neutral','advanced'],
      desc:'Sell near-term option, buy further-dated option at same strike.',
      detail:`<h3>Calendar Spread (Time Spread)</h3><p>Sell a near-term option and buy a longer-term option at the same strike. Profits from time decay differential and IV changes.</p>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> When stock is at strike at near-term expiry</li><li><strong>Max Loss:</strong> Debit paid</li><li><strong>Benefits from:</strong> Rising IV, stock near strike</li></ul>`,
    },
    {
      id:'diagonal_spread', name:'Diagonal Spread', icon:'⬈', tags:['intermediate','advanced'],
      desc:'Like a calendar spread but with different strikes. LEAPS + short-term selling.',
      detail:`<h3>Diagonal Spread</h3><p>Similar to calendar spread but uses different strikes. Often used with LEAPS (Long-dated options) to reduce cost basis through repeated short-term option sales.</p>`,
    },
    {
      id:'pmcc', name:'Poor Man\'s Covered Call', icon:'💡', tags:['bullish','advanced','income'],
      desc:'Buy a LEAPS call, sell near-term OTM calls. Mimics covered call with less capital.',
      detail:`<h3>Poor Man's Covered Call (PMCC)</h3><p>Buy a deep ITM LEAPS call as a stock substitute, then sell short-term OTM calls against it. Generates income like a covered call but requires much less capital.</p>
      <div class="lesson-highlight"><strong>Capital efficient:</strong> Use ~$2,000-$5,000 instead of $18,000+ for 100 shares of AAPL.</div>`,
    },
    {
      id:'protective_put', name:'Protective Put', icon:'🛡️', tags:['bearish','intermediate'],
      desc:'Own stock + buy a put. Insurance against downside.',
      detail:`<h3>Protective Put</h3><p>You own 100 shares and buy a put option as insurance against a price decline. Like buying car insurance for your stock.</p>
      <ul class="lesson-list"><li><strong>Max Profit:</strong> Unlimited (minus premium)</li><li><strong>Max Loss:</strong> Purchase Price - Strike + Premium</li></ul>`,
    },
    {
      id:'collar', name:'Collar', icon:'🔒', tags:['neutral','intermediate'],
      desc:'Own stock + buy put + sell call. Zero-cost hedge with capped upside.',
      detail:`<h3>Collar</h3><p>Own 100 shares + buy a protective put + sell a covered call. The premium from the call offsets the cost of the put, creating a near-zero cost hedge.</p>
      <ul class="lesson-list"><li><strong>Upside capped</strong> at call strike</li><li><strong>Downside protected</strong> to put strike</li><li><strong>Cost:</strong> Often near zero or small credit</li></ul>`,
    },
    {
      id:'ratio_spread', name:'Ratio Spread', icon:'⚖️', tags:['advanced'],
      desc:'Buy 1 option, sell 2 further OTM options. Free or credit trade with defined risk.',
      detail:`<h3>Ratio Spread</h3><p>Buy 1 near-ATM option and sell 2 further OTM options. Can create a zero-cost or credit position with defined downside risk.</p>`,
    },
    {
      id:'backspread', name:'Backspread', icon:'🚀', tags:['advanced','volatility'],
      desc:'Sell 1 option, buy 2 further OTM options. Profits from big breakout moves.',
      detail:`<h3>Backspread (Reverse Ratio)</h3><p>Sell 1 near-ATM option and buy 2 further OTM options. Benefits from large breakout moves and increasing volatility.</p>`,
    },
    {
      id:'jade_lizard', name:'Jade Lizard', icon:'🦎', tags:['advanced','income'],
      desc:'Sell OTM put + sell OTM call spread. No upside risk, defined downside.',
      detail:`<h3>Jade Lizard</h3><p>Sell an OTM put + sell an OTM call spread. The total credit must exceed the width of the call spread to eliminate any upside risk. Used in low-IV environments or after a big selloff.</p>`,
    },
    {
      id:'broken_wing', name:'Broken Wing Butterfly', icon:'🦗', tags:['advanced','income'],
      desc:'Asymmetric butterfly. Collect credit upfront, profit zone on one side.',
      detail:`<h3>Broken Wing Butterfly</h3><p>An asymmetric butterfly where the wings are at unequal distances from the body. Can be structured to collect a credit and profit in a wider range on one side.</p>`,
    },
    {
      id:'short_strangle', name:'Short Strangle', icon:'💎', tags:['neutral','advanced','income'],
      desc:'Sell OTM call + OTM put. High probability trade, undefined risk.',
      detail:`<h3>Short Strangle</h3><p>Sell an OTM call and OTM put simultaneously. Profit zone is between the two strikes. High probability of profit (~70%+) but undefined maximum risk.</p>
      <div class="lesson-warning"><strong>⚠️ Risk Warning:</strong> Undefined risk strategy. Use only with adequate margin and risk management.</div>`,
    },
  ];

  return {
    init, loadChain, filterExpiry, setChainView, selectRow, buildOptionsOrder,
    renderMiniChain, renderStrategyList, loadStrategy, calcPrice, calcGreeks,
    generateChain, getExpiries, STRATEGIES,
  };
})();
