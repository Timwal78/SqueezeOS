/**
 * SQUEEZE OS v5.0 | Analytical Engine Orchestrator
 * Drives the "Beast Mode" Arcane Monitor UI with real-time Schwab data.
 */
const AnalyticalEngine = {
    activeSymbol: 'AMC',
    favorites: ['AMC', 'GME'],
    scanData: [],
    flowData: [],
    intelData: [],
    gex_cache: {},
    gammaSignals: [],
    gammaChartInstance: null,
    recommendationData: [],
    reversalData: null,
    shadowTrades: [],
    terminalFeed: [],
    perfData: null,
    equityChartInstance: null,
    lastInteraction: Date.now(),
    optionsIntelData: {},
    forcedMoveData: {},
    mmIntelData: {},
    cascadeData: {},
    _spotlightActive: false,
    _spotlightInterval: null,
    _spotlightIndex: 0,
    lastDiscoveryTS: 0,
    lastScanTS: 0,
    scoreCache: {},

    async init() {
        console.log("🕯️ Awakening Arcane Monitor Engine...");
        this.refreshAll();

        // Interaction listeners to pause auto-rotation
        document.addEventListener('mousedown', () => this.handleInteraction());
        document.addEventListener('keypress', () => this.handleInteraction());

        // Global Search listener
        const searchInput = document.getElementById('global-search');
        if (searchInput) {
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.search();
            });
        }
        // Orchestrated heartbeats to prevent thundering herd and freezing
        // Use recursive setTimeout instead of setInterval for safety
        const heartbeat = async (fn, interval) => {
            await fn();
            setTimeout(() => heartbeat(fn, interval), interval);
        };

        // GRIMOIRE + FEEDS: Active symbol quote + terminal waterfall (3s — slowed for readability)
        heartbeat(async () => {
            await this.updateGrimoire();
            await this.updateTerminalFeed();
            await this.updateFirehose();
        }, 3000);

        // FAST: Alarms + Flow + Reversal + Top Movers (3s)
        heartbeat(async () => {
            await this.updateAlarms();
            await this.updateFlow();
            await this.updateReversal();
            await this.updateTradingStatus();
            this.renderTopMovers();
        }, 3000);

        // MEDIUM: Intel, Beast, Gamma, Discovery (10s sync)
        heartbeat(async () => {
            await this.updateIntel();
            await this.updateBeastSignals();
            await this.updateGammaSignals();
            await this.updateDiscovery();
            this.renderActionBoard();
        }, 10000);

        // SLOW: Performance (20s)
        heartbeat(async () => {
            await this.updatePerformance();
            await this.updateDiscovery();
            await this.updateBalances();
        }, 20000);

        // AUTO-ROTATE: Cycle top tickers SLOWER if idle (12s interval, 25s idle threshold)
        setInterval(() => {
            if (Date.now() - this.lastInteraction > 25000) {
                this.autoRotate();
            }
        }, 12000);

        // AUDIT: Compliance check (60s)
        heartbeat(async () => {
            await this.updateAudit();
        }, 60000);
    },

    handleInteraction() {
        this.lastInteraction = Date.now();
    },

    autoRotate() {
        if (!this.scanData || this.scanData.length < 2) return;
        // Law 3: Avoid Mega caps for rotation unless they are top score
        // Sweet spot: prefer $2-$60 stocks
        const pool = this.scanData.filter(s => {
            if (s.is_mega && s.squeeze_score <= 60) return false;
            const price = s.price || 0;
            // Prefer sweet spot but include anything with high squeeze
            if (price >= 2 && price <= 60) return true;
            if (s.squeeze_score > 70) return true;
            return false;
        });
        if (pool.length === 0) return;

        const currentIndex = pool.findIndex(s => s.symbol === this.activeSymbol);
        const nextIndex = (currentIndex + 1) % pool.length;
        const nextSymbol = pool[nextIndex].symbol;

        console.log(`🔄 Auto-rotating to ${nextSymbol} (${pool.length} in pool)...`);
        this.selectSymbol(nextSymbol);
    },

    async refreshAll() {
        await Promise.all([
            this.updateAlarms(),
            this.updateGrimoire(),
            this.updateFlow(),
            this.updateIntel(),
            this.updateWhales(),
            this.updateBeastSignals(),
            this.updateGammaSignals(),
            this.updateTerminalFeed(),
            this.updateReversal(),
            this.updatePerformance(),
            this.updateFirehose(),
            this.updateDiscovery(),
            this.updateTradingStatus(),
            this.updateBalances()
        ]);
        this.renderTopMovers();
    },

    // ── SCAN: Fetch full scan results for ticker board ────────
    async updateScan() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/market/scan');
            const data = await r.json();
            if (data.status === 'success') {
                this.scanData = data.data;
                this.lastScanTS = Date.now();
                const syncEl = document.getElementById('action-sync');
                if (syncEl) syncEl.textContent = `SYNCED ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`;
            }
        } catch (e) {
            console.warn('Scan sync failure:', e.message);
        }
    },

    // ── ALARMS: Real-time Vol/OI Spikes ──────────────────────
    async updateAlarms() {
        try {
            // Always fetch scan data too for ticker board
            await this.updateScan();
            const r = await fetch('http://127.0.0.1:8182/api/market/alarms');
            const data = await r.json();
            if (data.status === 'success') {
                this.alarmData = data.data;
            }
            this.renderAlarms();
        } catch (e) {
            console.warn('Alarms sync failure:', e.message);
        }
    },

    renderAlarms() {
        const list = document.getElementById('chronicle-list');
        if (!list) return;

        if (!this.alarmData || this.alarmData.length === 0) {
            list.innerHTML = '';
            return;
        }

        const dataStr = JSON.stringify(this.alarmData);
        if (this.lastAlarmStr === dataStr) return;
        this.lastAlarmStr = dataStr;

        list.innerHTML = this.alarmData.map(f => {
            const clr = f.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)';
            const agg = f.contracts > 1 ? `💎CLUSTER` : (f.max_heat >= 80 ? '⚡SWEEP' : '🔥SPIKE');
            const isFresh = (Date.now() / 1000) - f.seen_time < 60;
            const pulseClass = isFresh ? 'heat-pulse' : '';
            const strikeDisplay = f.cluster_count && f.cluster_count > 1
                ? `${f.strikes[0]} +${f.cluster_count - 1} STRIKES`
                : `$${f.strikes[0]}`;

            return `
                <div class="data-row ${pulseClass}" style="cursor:pointer;" onclick="AnalyticalEngine.selectSymbol('${f.symbol}')">
                    <div class="sym-badge" style="color:white; font-weight:900;">${f.symbol}</div>
                    <div style="color:${clr}; font-size:9px; font-weight:800;">${agg}</div>
                    <div class="price-box" style="color:var(--neon-blue); font-weight:800;">${f.max_heat}</div>
                    <div class="score-box" style="color:white;">${strikeDisplay}</div>
                </div>
            `;
        }).join('');
    },

    // ── GRIMOIRE: Detailed Active View ────────────────────────
    async updateGrimoire() {
        if (!this.activeSymbol) return;
        try {
            const r = await fetch(`http://127.0.0.1:8182/api/market/quotes?symbols=${this.activeSymbol}`);
            const data = await r.json();
            if (data.status === 'success' && data.data[this.activeSymbol]) {
                const quote = data.data[this.activeSymbol];
                // Show data immediately — never block on GEX/regime preload
                this.renderGrimoire(quote, false);
            } else {
                this.renderGrimoire({ symbol: this.activeSymbol, error: 'NO_DATA' });
            }
        } catch (e) {
            console.error('Grimoire link failure:', e);
            this.renderGrimoire({ symbol: this.activeSymbol, error: 'CONNECTION_FAILED' });
        }
    },

    renderGrimoire(quote, isPreloading = false) {
        const details = document.getElementById('grimoire-details');
        const badge = document.getElementById('active-symbol-badge');
        if (!details || !badge) return;

        if (isPreloading) {
            badge.textContent = quote.symbol;
            details.innerHTML = `
                <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:300px; color:var(--neon-blue);">
                    <div class="spinner" style="width:40px; height:40px;"></div>
                    <div style="margin-top:20px; font-weight:900; letter-spacing:2px; font-family:var(--font-mono);">PRE-LOADING INSTITUTIONAL REGIME...</div>
                    <div style="font-size:10px; color:var(--text-dim); margin-top:10px;">TRIGGERING SML FRACTAL CASCADE ASYNC</div>
                </div>
            `;
            return;
        }

        if (!quote || quote.error) {
            const msg = quote?.error === 'NO_DATA' ? '⚠️ DATA PROVIDERS OFFLINE - CHECK API KEYS' : '⚠️ BACKEND UNREACHABLE - RESTART SERVER.PY';
            details.innerHTML = `<div class="loading-msg">${msg}</div>`;
            badge.textContent = quote?.symbol || '--';
            return;
        }

        badge.textContent = quote.symbol;
        badge.style.display = 'inline-block';
        badge.className = `badge ${this.favorites.includes(quote.symbol) ? 'neon-yellow' : 'neon-blue'}`;

        // Data Fusion: FIND SQUEEZE SCORE
        const sqz = this.scanData.find(s => s.symbol === quote.symbol) || { squeeze_score: null, squeeze_level: 'AWAITING DATA' };

        // Data Fusion: FIND TOP OPTIONS ALERT
        const flow = this.flowData.filter(f => f.symbol === quote.symbol)
            .sort((a, b) => b.unusual_score - a.unusual_score)[0];

        // Beast Score — Weighted institutional fusion v4.5
        // 50% squeeze structure + 30% flow conviction + 20% institutional signal bonus
        const sqzScore = sqz.squeeze_score !== null ? sqz.squeeze_score : 0;
        const flowScore = flow ? (flow.unusual_score || 0) : null;

        let fused = flowScore !== null ? (sqzScore * 0.6 + flowScore * 0.4) : sqzScore;
        
        // Institutional Convergence Bonuses
        let bonus = 0;
        
        // 1. Beast Pro Signal Bonus (+15)
        const hasBeast = (this.beastData || []).some(b => b.symbol === quote.symbol);
        if (hasBeast) bonus += 15;
        
        // 2. Recommendation Status Bonus (+10)
        const isPick = (this.recommendationData || []).some(p => p.symbol === quote.symbol);
        if (isPick) bonus += 10;
        
        // 3. Direction agreement bonus (+10)
        if (flow && ((sqz.direction === 'BULLISH' && flow.sentiment === 'BULLISH') ||
                     (sqz.direction === 'BEARISH' && flow.sentiment === 'BEARISH'))) {
            bonus += 10;
        }

        // 4. GEX Regime Bonus (+15 for short gamma = squeeze fuel)
        const gexProfile = this.gex_cache?.[quote.symbol];
        if (gexProfile && gexProfile.profile_shape === 'short_gamma') bonus += 15;

        // 5. MM Intel - HJB Hedge Pressure Bonus (+10 for aggressive hedging)
        const hjb = gexProfile?.hjb_hedge_rate || 0;
        if (Math.abs(hjb) > 5.0) bonus += 10;

        const beastScore = Math.min(100, Math.round(fused + bonus));

        const changeColor = quote.changePct >= 0 ? 'neon-green' : 'neon-red';
        const volRatio = quote.volRatio || (quote.avgVolume > 0 ? (quote.volume / quote.avgVolume) : 0);

        // GEX regime badge
        const gexBadge = gexProfile 
            ? `<span class="badge ${gexProfile.profile_shape === 'short_gamma' ? 'badge-extreme' : 'badge-high'}" style="font-size:8px; margin-left:5px;">${gexProfile.profile_shape === 'short_gamma' ? '⚡SHORT Γ' : '🛡️LONG Γ'}</span>` 
            : '';

        details.innerHTML = `
            <div style="display:grid; grid-template-columns: 1.2fr 1fr; gap:20px; padding:15px; background:rgba(255,255,255,0.01)">
                <div class="stat-block">
                    <label style="font-size:9px; color:var(--text-dim); letter-spacing:2px;">PRICE ACTION / LIVE</label>
                    <div style="font-size:42px; font-weight:950; font-family:var(--font-mono); color:white; line-height:1; letter-spacing:-1px;">$${quote.price.toFixed(2)}</div>
                    <div class="${changeColor}" style="font-size:16px; font-weight:800; margin-top:8px; display:flex; align-items:center; gap:5px;">
                        <span>${quote.changePct >= 0 ? '▲' : '▼'} ${Math.abs(quote.changePct).toFixed(2)}%</span>
                        <span style="font-size:9px; color:var(--text-dim); font-weight:400;">(${quote.change >= 0 ? '+' : ''}${quote.change.toFixed(2)})</span>
                        ${gexBadge}
                    </div>
                    <div style="margin-top:12px; font-size:9px; color:var(--text-dim); letter-spacing:1px;">
                        SWEET SPOT: $2-$60 | LIVE SCANNING
                    </div>
                </div>
                <div class="stat-block" style="text-align:right; border-left:1px solid var(--glass-border); padding-left:20px;">
                    <label style="font-size:9px; color:var(--text-dim); letter-spacing:2px;">BEAST SCORE</label>
                    <div style="font-size:54px; font-weight:950; color:${beastScore >= 80 ? 'var(--neon-red)' : 'var(--neon-green)'}; line-height:0.8; text-shadow:0 0 20px ${beastScore >= 80 ? 'rgba(255,71,87,0.4)' : 'rgba(0,255,136,0.4)'}">${beastScore}</div>
                    <div style="font-size:9px; color:${beastScore >= 80 ? 'var(--neon-red)' : 'var(--neon-green)'}; font-weight:800; letter-spacing:1px; margin-top:5px;">
                        CONVERGENCE: ${hasBeast ? 'ELITE' : isPick ? 'HIGH' : gexProfile ? 'GEX FUSED' : 'UNIFIED'}
                    </div>
                    
                    <!-- Flow Bias removed: was not populating usefully -->
                    <button onclick="AnalyticalEngine.addToWatchlist('${quote.symbol}')" style="margin-top:8px; background:rgba(0,212,255,0.1); border:1px solid var(--neon-blue); color:var(--neon-blue); padding:3px 10px; border-radius:3px; cursor:pointer; font-size:8px; font-weight:800; letter-spacing:1px; font-family:var(--font-mono);">
                        📡 TRACK GEX
                    </button>
                </div>
            </div>

            <div style="margin-top:10px; border-top:1px solid var(--glass-border); padding:20px 15px; display:grid; grid-template-columns: repeat(3, 1fr); gap:20px; background:rgba(0,0,0,0.2)">
                <div>
                    <label style="font-size:11px; color:var(--text-dim); letter-spacing:1px; font-weight:700;">SQUEEZE LEVEL</label>
                    <div style="font-size:20px; font-weight:900; color:${sqz.squeeze_level !== 'AWAITING DATA' ? 'var(--neon-blue)' : 'var(--text-muted)'}; margin-top:4px;">${sqz.squeeze_level}${sqz.tier ? ` <span style="font-size:11px; color:var(--text-dim); font-weight:400;">[${sqz.tier}]</span>` : ''}</div>
                    <div style="font-size:12px; color:var(--text-dim); margin-top:4px;">SIGNAL: ${sqz.squeeze_score !== null ? sqz.squeeze_score : '--'} / 100</div>
                    ${sqz.analysis_components ? `<div style="margin-top:8px; display:flex; gap:4px; flex-wrap:wrap;">
                        ${['volume_profile', 'compression', 'momentum', 'vwap_position', 'rsi_engine', 'money_flow', 'price_structure', 'trend_alignment'].map(k => {
            const v = sqz.analysis_components[k] || 0;
            const maxMap = {
                'volume_profile': 20,
                'compression': 15,
                'momentum': 15,
                'vwap_position': 10,
                'rsi_engine': 10,
                'money_flow': 10,
                'price_structure': 10,
                'trend_alignment': 10
            };
            const max = maxMap[k] || 10;
            const pct = Math.min(v / max * 100, 100);
            const label = k.split('_').map(w => w[0].toUpperCase()).join('');
            const clr = pct > 70 ? 'var(--neon-green)' : pct > 40 ? 'var(--neon-blue)' : 'var(--text-dim)';
            return `<div style="text-align:center;" title="${k}: ${v}/${max}"><div style="width:32px;height:14px;background:rgba(255,255,255,0.05);border-radius:2px;overflow:hidden;"><div style="height:100%;width:${pct}%;background:${clr};"></div></div><div style="font-size:8px;color:var(--text-dim);margin-top:1px;">${label}</div></div>`;
        }).join('')}
                    </div>` : ''}</div>
                <div style="text-align:center;">
                    <label style="font-size:9px; color:var(--text-dim); letter-spacing:1px;">RELATIVE VOLUME</label>
                    <div style="font-size:16px; font-weight:900; color:var(--neon-purple); margin-top:4px;">${volRatio.toFixed(1)}x</div>
                    <div style="font-size:11px; color:var(--text-dim); margin-top:2px;">DAILY: ${(quote.volume / 1000000).toFixed(1)}M</div>
                </div>
                <div style="text-align:right;">
                    <label style="font-size:9px; color:var(--text-dim); letter-spacing:1px;">BID / ASK SPREAD</label>
                    <div style="font-size:16px; font-weight:900; color:white; margin-top:4px;">
                        <span style="color:${quote.bid ? 'var(--neon-blue)' : 'var(--text-muted)'}">$${quote.bid ? quote.bid.toFixed(2) : '--'}</span>
                        <span style="color:var(--text-dim); opacity:0.3; margin:0 5px;">|</span>
                        <span style="color:${quote.ask ? 'var(--neon-orange)' : 'var(--text-muted)'}">$${quote.ask ? quote.ask.toFixed(2) : '--'}</span>
                    </div>
                    <div style="font-size:11px; color:var(--text-dim); margin-top:2px;">INSTITUTIONAL FEED</div>
                </div>
            </div>

            ${flow ? `
            <div style="margin:8px 15px; padding:10px; background:rgba(255,255,255,0.03); border-radius:4px; border-left:3px solid ${flow.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)'}">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:14px; font-weight:950; color:${flow.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)'}">
                            ${flow.sentiment === 'BULLISH' ? '🐳 BUYING' : '🚨 SELLING'} $${flow.strike} ${flow.type}
                        </span>
                        <span style="font-size:10px; color:var(--text-dim); margin-left:8px;">EXP ${flow.expiry_formatted}</span>
                    </div>
                    <span class="badge ${flow.unusual_score > 70 ? 'badge-extreme' : 'badge-high'}" style="font-size:11px;">HEAT ${flow.unusual_score}</span>
                </div>
                <div style="font-size:10px; color:var(--text-dim); margin-top:4px; font-family:var(--font-mono);">
                    VOL:${flow.volume} OI:${flow.open_interest} ${flow.implied_volatility ? `IV:${(flow.implied_volatility*100).toFixed(0)}%` : ''} ${flow.delta ? `Δ:${flow.delta}` : ''}
                </div>
            </div>
            ` : ''}
        `;
    },

    // ── SPELLS: Options Flow ──────────────────────────────────
    async updateFlow() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/market/flow');
            const data = await r.json();
            if (data.status === 'success') {
                this.flowData = data.data;
                this.renderFlow();
            }
        } catch (e) {
            console.warn('Flow sync failure:', e.message);
        }
    },

    renderFlow() {
        if (!this.flowData) return;
        const list = document.getElementById('spell-list');
        if (!list) return;

        // Skip if same data
        const dataStr = JSON.stringify(this.flowData);
        if (this.lastFlowStr === dataStr) return;
        this.lastFlowStr = dataStr;

        if (!window.seenFlowFeed) window.seenFlowFeed = new Set();
        // LAW 4: PREVENT MEMORY CORRUPTION (Limit set size)
        if (window.seenFlowFeed.size > 500) window.seenFlowFeed.clear();

        list.innerHTML = this.flowData.map(f => {
            const key = f.symbol + f.strike + f.expiry_formatted + f.type + f.seen_time;
            const isNew = !window.seenFlowFeed.has(key);
            window.seenFlowFeed.add(key);

            const isFresh = (Date.now() / 1000) - f.seen_time < 60;
            const pulseClass = isFresh ? 'heat-pulse' : '';
            const convictionClass = (f.unusual_score && f.unusual_score >= 80) ? 'high-conviction-row' : '';

            const action = (f.sentiment === 'BULLISH' && f.type === 'CALL') ? '🐳 WHALE BUYING' :
                (f.sentiment === 'BEARISH' && f.type === 'PUT') ? '🐳 WHALE BUYING' :
                    (f.sentiment === 'BEARISH' && f.type === 'CALL') ? '🚨 WHALE DUMPING' :
                        (f.sentiment === 'BULLISH' && f.type === 'PUT') ? '🚨 WHALE SELLING' : '👁️ WATCHING';
            return `
            <div class="flow-row ${f.sentiment === 'BULLISH' ? 'flow-bull' : 'flow-bear'} ${isNew ? 'anim-new-row' : ''} ${pulseClass} ${convictionClass}">
                <div class="flow-sym">${f.symbol}</div>
                <div class="flow-details">
                    <span style="font-weight:900; color:${f.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)'}; font-size:10px;">${action}</span>
                    <span class="flow-strike">$${f.strike} ${f.sweep_label || f.type}</span>
                    <span class="flow-exp">${f.expiry_formatted}</span>
                </div>
                <div class="flow-score">${f.unusual_score}</div>
            </div>
        `}).join('');
    },

    async updateIntel() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/market/intel');
            const data = await r.json();
            if (data.status === 'success') {
                this.intelData = data.data;
                this.renderIntel();
            }
        } catch (e) {
            console.warn('Intel sync failure:', e.message);
        }
    },

    async updateBeastSignals() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/beast/signals');
            const data = await r.json();
            if (data.status === 'ok') {
                this.beastData = data.data;
                this.renderIntel(); // Merged render
            }
        } catch (e) {
            console.error('Beast Signals link failure:', e);
        }
    },

    async fetchOptionsIntel(symbol) {
        try {
            const r = await fetch(`${this.apiBase || 'http://127.0.0.1:8182/api'}/options/intelligence/${symbol}`);
            if (r.ok) {
                const data = await r.json();
                this.optionsIntelData[symbol] = data;
                return data;
            }
        } catch (e) { console.warn('[OPTIONS] Intel fetch failed:', e); }
        return null;
    },

    async fetchForcedMove(symbol) {
        try {
            const r = await fetch(`${this.apiBase || 'http://127.0.0.1:8182/api'}/forced-move/${symbol}`);
            if (r.ok) {
                const data = await r.json();
                this.forcedMoveData[symbol] = data;
                return data;
            }
        } catch (e) { console.warn('[FME] Fetch failed:', e); }
        return null;
    },

    async fetchMMIntel(symbol) {
        try {
            const r = await fetch(`${this.apiBase || 'http://127.0.0.1:8182/api'}/mm-intel/${symbol}`);
            if (r.ok) {
                const data = await r.json();
                this.mmIntelData[symbol] = data;
                return data;
            }
        } catch (e) { console.warn('[MM] Intel fetch failed:', e); }
        return null;
    },

    async fetchCascade(symbol) {
        try {
            const r = await fetch(`${this.apiBase || 'http://127.0.0.1:8182/api'}/cascade/${symbol}`);
            if (r.ok) {
                const data = await r.json();
                this.cascadeData[symbol] = data;
                return data;
            }
        } catch (e) { console.warn('[CASCADE] Fetch failed:', e); }
        return null;
    },

    renderIntel() {
        const list = document.getElementById('intel-list');
        if (!list) return;

        // Skip if same data (Intel + Beast + Gamma)
        const combinedKey = JSON.stringify([this.intelData, this.beastData, this.gammaSignals]);
        if (this.lastIntelKey === combinedKey) return;
        this.lastIntelKey = combinedKey;

        // Merge Intel + Beast
        const beastEntries = (this.beastData || []).map(b => ({
            type: 'BEAST',
            symbol: b.symbol,
            action: b.action,
            score: b.score,
            price: b.price,
            seen_time: b.ts,
            label: b.is_mega ? '🔥MEGA' : '⚡BEAST'
        }));

        const combined = [...(this.intelData || []), ...beastEntries]
            .sort((a, b) => (b.seen_time || 0) - (a.seen_time || 0));

        if (combined.length === 0) {
            list.innerHTML = '';
            return;
        }

        let html = combined.map(item => {
            if (item.type === 'SYSTEM') {
                return `
                    <div class="intel-row system-msg" style="color:var(--text-dim); border-left: 2px solid rgba(255,255,255,0.1)">
                        <span style="opacity:0.6; font-size:8px;">[${item.time || 'SYSTEM'}]</span> ${item.msg.split('] ')[1] || item.msg}
                    </div>
                `;
            }

            // BEAST TYPE
            if (item.type === 'BEAST') {
                return `
                    <div class="intel-row beast-signal" style="cursor:pointer; border-left: 2px solid var(--neon-purple); background:rgba(166,77,255,0.05)" onclick="AnalyticalEngine.selectSymbol('${item.symbol}')">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-weight:950; color:white;">${item.symbol}</span>
                            <span style="font-size:9px; font-weight:900; color:var(--neon-purple);">${item.label} ${item.action}</span>
                        </div>
                        <div style="font-size:9px; color:var(--text-dim); margin-top:2px;">
                            SIGNAL AT $${item.price} | SCORE: ${item.score}
                        </div>
                    </div>
                `;
            }

            // FLOW TYPE
            const clr = item.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)';
            const prem = item.premium >= 1000000 ? `$${(item.premium / 1000000).toFixed(1)}M` : 
                       item.premium >= 1000 ? `$${(item.premium / 1000).toFixed(0)}K` : `$${item.premium}`;
            
            return `
                <div class="intel-row flow-signal" style="cursor:pointer; border-left: 2px solid ${clr}" onclick="AnalyticalEngine.selectSymbol('${item.symbol}')">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:900; color:white;">${item.symbol}</span>
                        <span style="font-size:9px; font-weight:800; color:${clr}">${item.label}</span>
                    </div>
                    <div style="font-size:9px; color:var(--text-dim); margin-top:2px;">
                        $${item.strike} | Exp ${item.expiry} | ${prem}
                    </div>
                </div>
            `;
        }).join('');

        // Inject Gamma Flow Fusion Signals into Intel
        if (this.gammaSignals && this.gammaSignals.length > 0) {
            const gammaEntries = this.gammaSignals.map(s => {
                const label = s.signal_type.replace(/_/g, ' ').toUpperCase();
                const clr = s.signal_type.includes('squeeze') ? 'var(--neon-red)' : 'var(--neon-green)';
                return `
                    <div class="intel-row gamma-fusion" style="cursor:pointer; border-left: 2px solid ${clr}; background:rgba(255,255,255,0.02)" onclick="AnalyticalEngine.selectSymbol('${s.ticker}')">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-weight:950; color:white;">${s.ticker}</span>
                            <span style="font-size:9px; font-weight:900; color:${clr};">💎 FLOW FUSION</span>
                        </div>
                        <div style="font-size:10px; color:white; font-weight:700; margin-top:4px;">${label} @ $${s.strike}</div>
                        <div style="font-size:9px; color:var(--text-dim); margin-top:2px;">
                            URGENCY: ${s.urgency_score.toFixed(1)} | CONF: ${s.confidence.toUpperCase()}
                        </div>
                    </div>
                `;
            });
            html = gammaEntries.join('') + html;
        }

        list.innerHTML = html;
    },

    // ── NEWS: Price Moving Intel ──────────────────────────────
    async updateNews() {
        try {
            // FIREHOSE: If no symbol active or search query, fetch global news
            const sym = this.activeSymbol || '';
            const url = sym ? `http://127.0.0.1:8182/api/market/news?symbol=${sym}&limit=15` : `http://127.0.0.1:8182/api/market/news?limit=30`;
            const r = await fetch(url);
            const data = await r.json();
            if (data.status === 'success') {
                this.newsData = data.data;
                this.renderNews();
            }
        } catch (e) {
            console.error('News link failure:', e);
        }
    },

    renderNews() {
        const list = document.getElementById('news-list');
        if (!list) return;

        if (!this.newsData || this.newsData.length === 0) {
            list.innerHTML = '';
            return;
        }

        list.innerHTML = this.newsData.map(post => {
            const time = post.published_utc ? new Date(post.published_utc).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--';
            const tickers = (post.tickers || []).join(', ') || 'GLOBAL';
            const isTargeted = this.activeSymbol && post.tickers && post.tickers.includes(this.activeSymbol);
            
            return `
                <div class="intel-row ${isTargeted ? 'high-heat' : ''}" style="padding:10px; border-bottom:1px solid rgba(255,255,255,0.05);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span style="color:${isTargeted ? 'var(--neon-green)' : 'var(--neon-blue)'}; font-weight:900; font-size:10px;">${tickers}</span>
                        <span style="color:var(--text-dim); font-size:9px;">${time}</span>
                    </div>
                    <div style="color:white; font-size:11px; line-height:1.3; font-weight:600;">${post.title || 'Institutional Briefing...'}</div>
                    <div style="color:var(--text-dim); font-size:9px; margin-top:4px;">Source: ${post.publisher?.name || 'Bloomberg/Terminal'}</div>
                </div>
            `;
        }).join('');
    },



    // ── DISCOVERY: Universal Mean Reversion ──────────────────
    async updateDiscovery() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/market/discovery');
            const data = await r.json();
            if (data.status === 'success') {
                this.discoveryData = data.data;
                this.discoveryTS = data.ts;
                this.lastDiscoveryTS = Date.now();
                const syncEl = document.getElementById('discovery-sync');
                if (syncEl) syncEl.textContent = `SYNCED ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`;
                this.renderDiscovery();
            }
        } catch (e) {
            console.warn('Discovery sync failure:', e.message);
        }
    },

    renderDiscovery() {
        const list = document.getElementById('discovery-list');
        const tsBadge = document.getElementById('discovery-ts');
        if (!list) return;

        if (!this.discoveryData || this.discoveryData.length === 0) {
            list.innerHTML = `<div class="loading-msg">WAITING FOR NEXT SCAN CYCLE...</div>`;
            return;
        }

        if (this.discoveryTS) {
            const timeStr = new Date(this.discoveryTS * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (tsBadge) tsBadge.textContent = `SYNC: ${timeStr}`;
        }

        list.innerHTML = this.discoveryData.map(o => {
            const clr = o.status.includes('OVERSOLD') ? 'var(--neon-green)' : 'var(--neon-red)';
            const isFresh = o.triggered;
            const pulseClass = isFresh ? 'heat-pulse' : '';
            return `
                <div class="radar-row clickable ${pulseClass}" onclick="AnalyticalEngine.selectSymbol('${o.symbol}')" style="font-size:11px; padding:6px 10px;">
                    <div class="radar-sym" style="width:60px;">${o.symbol}</div>
                    <div class="radar-details" style="flex:1;">
                        <span style="color:${clr}; font-weight:800; font-size:10px;">${o.status}</span>
                        <span style="color:var(--text-dim); font-size:9px; margin-left:5px;">RSI:${o.rsi} Z:${o.z_score}</span>
                        <div style="font-size:8px; color:var(--neon-blue); letter-spacing:0.5px; margin-top:1px;">${o.flags || ''}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-weight:900; color:white;">$${o.price}</div>
                        <div style="font-size:9px; font-weight:800; color:var(--neon-blue);">${o.confidence}%</div>
                    </div>
                </div>
            `;
        }).join('');
    },

    async search() {
        const input = document.getElementById('global-search');
        if (!input) return;
        const sym = input.value.trim().toUpperCase();
        if (!sym) return;

        console.log(`🔎 Searching for ${sym}...`);
        // Always select the symbol — let the quote fetch determine if data exists
        this.selectSymbol(sym);
        input.value = '';

        // Also try the search endpoint if it exists (non-blocking)
        try {
            const r = await fetch(`http://127.0.0.1:8182/api/search?q=${sym}`);
            if (!r.ok) console.warn(`Search API returned ${r.status} for ${sym}`);
        } catch (e) {
            // Search endpoint may not exist — that's fine, selectSymbol already fired
        }
    },

    // ── WHALES/PICKS: Institutional Intelligence ───────────────
    async updateRecommendations() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/market/recommendations');
            const data = await r.json();
            if (data.status === 'success') {
                this.recommendationData = data.data;
                this.renderRecommendations();
            }
        } catch (e) {
            console.error('Recommendations link failure:', e);
        }
    },

    renderRecommendations() {
        const list = document.getElementById('recommendations-list');
        if (!list) return;

        if (!this.recommendationData || this.recommendationData.length === 0) {
            list.innerHTML = '';
            return;
        }

        list.innerHTML = this.recommendationData.map(p => {
            const sym = p.symbol || '?';
            const clr = p.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)';
            const prem = p.total_premium ? (p.total_premium >= 1000000 ? `$${(p.total_premium / 1000000).toFixed(1)}M` : `$${(p.total_premium / 1000).toFixed(0)}K`) : '$0';
            const strike = p.strike || 'OTM';
            const type = p.type || 'CALL';
            const expiry = p.expiry_formatted || 'WKLY';
            
            return `
                <div class="radar-row clickable" onclick="AnalyticalEngine.selectSymbol('${sym}')" style="border-left: 2px solid ${clr}; padding: 15px; margin-bottom: 8px;">
                    <div class="radar-sym" style="font-size: 18px;">${sym}</div>
                    <div class="radar-details" style="flex:1; margin-left: 15px;">
                        <span style="color:white; font-weight:900; font-size:14px; letter-spacing: 1px;">
                            ${p.sentiment || 'WATCH'} ${type} @ $${strike}
                        </span>
                        <span class="radar-exp" style="font-size:10px; color: var(--neon-blue); font-weight: 800; margin-top: 4px;">
                            DATE: ${expiry} | ${prem} PREM FUSION
                        </span>
                    </div>
                    <div class="badge ${p.conviction === 'HIGH' ? 'neon-green' : 'neon-blue'}" style="font-size:10px; padding:5px 10px; border-radius: 4px;">${p.conviction || 'ANALYZING'}</div>
                </div>
            `;
        }).join('');
    },

    // ── AUDIT: Manifesto Transparency (Law 4) ──────────────────
    toggleAudit() {
        const el = document.getElementById('audit-overlay');
        if (!el) return;
        el.style.display = (el.style.display === 'block') ? 'none' : 'block';
        if (el.style.display === 'block') this.updateAudit();
    },

    async updateAudit() {
        try {
            const [statusRes, verificationRes] = await Promise.all([
                fetch('http://127.0.0.1:8182/api/status/audit'),
                fetch('http://127.0.0.1:8182/api/status/verification')
            ]);
            
            this.auditData = await statusRes.json();
            const vData = await verificationRes.json();
            if (vData.status === 'success') {
                this.verificationData = vData.data;
            }
            
            this.renderAudit();
        } catch (e) {
            console.error('Audit link failure:', e);
        }
    },

    renderAudit() {
        const d = this.auditData || {};
        const v = this.verificationData || {};
        const vClr = v.status === 'OPTIMAL' ? 'pill-compliant' : 'pill-enforced';
        
        const list = document.getElementById('audit-content');
        if (!list) return;

        list.innerHTML = `
            <div class="audit-stat">
                <label>LAW 2: 100% FETCH (UNIVERSE COVERAGE)</label>
                <div class="val">${d.universe_size || 0} Assets <span class="status-pill pill-compliant">ACTIVE</span></div>
            </div>
            <div class="audit-stat">
                <label>LAW 3: MEGA CAP ADVERTISING</label>
                <div class="val">${d.mega_caps_filtered || 0} Suppressed <span class="status-pill pill-enforced">ENFORCED</span></div>
            </div>
            <div class="audit-stat">
                <label>INSTITUTIONAL VERIFICATION (HJB/KALMAN)</label>
                <div class="val">
                    ${v.accuracy ? (v.accuracy * 100).toFixed(1) : '0'}% Accuracy 
                    <span class="status-pill ${vClr}">${v.status || 'PENDING'}</span>
                </div>
                <div style="font-size:7px; color:var(--text-dim); margin-top:2px;">
                    Risk Reduction: ${v.risk_reduction ? v.risk_reduction.toFixed(1) : '0'}% | Verified 1D ago
                </div>
            </div>
            <div class="audit-stat">
                <label>LAW 1: SQUEEZE SCORING ENGINE</label>
                <div class="val">v4.2 Sigmoid <span class="status-pill pill-compliant">VERIFIED</span></div>
            </div>
        `;
    },
    
    // ── GAMMA PROFILE: GEX Charting ───────────────────────────
    async updateGammaProfile() {
        if (!this.activeSymbol) return;
        try {
            const r = await fetch(`http://127.0.0.1:8182/api/market/gex?symbol=${this.activeSymbol}`);
            const data = await r.json();
            if (data.status === 'success') {
                this.gex_cache[this.activeSymbol] = data.data;
                this.renderGammaChart(data.data);
            }
        } catch (e) {
            console.error('GEX link failure:', e);
        }
    },

    renderGammaChart(data) {
        const ctx = document.getElementById('gammaChart')?.getContext('2d');
        if (!ctx) return;

        const strikes = Object.keys(data.by_strike).map(Number).sort((a,b) => a-b);
        const values = strikes.map(s => data.by_strike[s.toString()]);
        
        // Find Zero Gamma (closest strike to price where profile crosses or sign changes)
        // For now, just emphasize the max and min
        const colors = values.map(v => v >= 0 ? 'rgba(0, 255, 136, 0.6)' : 'rgba(255, 71, 87, 0.6)');

        if (this.gammaChartInstance) {
            this.gammaChartInstance.destroy();
        }

        this.gammaChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: strikes,
                datasets: [{
                    label: 'Net GEX ($)',
                    data: values,
                    backgroundColor: colors,
                    borderColor: colors.map(c => c.replace('0.6', '1')),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 9 } },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                        ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 9 } },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });

        const stats = document.getElementById('gamma-stats');
        if (stats) {
            const total = (data.total_gex / 1e6).toFixed(1);
            const clr = data.total_gex >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
            const shape = (data.profile_shape || '').toUpperCase().replace('_', ' ');
            const zgl = data.zero_gamma_line || 0;
            const callW = data.call_wall || data.max_gamma_strike || 0;
            const putW = data.put_wall || data.min_gamma_strike || 0;
            const expMove = ((data.expected_move || 0) * 100).toFixed(2);
            const avgIV = ((data.iv_surface_avg || 0) * 100).toFixed(0);
            const maxOI = data.max_oi_strike || 0;
            const invZ = data.inventory_z || 0;
            const hjb = data.hjb_hedge_rate || 0;
            
            const stressClr = Math.abs(invZ) > 2.0 ? 'var(--neon-red)' : (Math.abs(invZ) > 1.0 ? 'var(--neon-yellow)' : 'var(--neon-green)');
            const invPct = Math.min(100, Math.max(0, (invZ + 3) / 6 * 100)); // Map -3 to +3 to 0-100

            stats.innerHTML = `
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:10px;">
                    <div>
                        <span style="color:var(--text-dim);">NET GEX</span><br>
                        <span style="color:${clr}; font-weight:900; font-size:13px;">$${total}M</span>
                        <span style="color:${clr}; font-size:8px; font-weight:800;"> ${shape}</span>
                    </div>
                    <div style="text-align:right;">
                        <span style="color:var(--text-dim);">EXP. MOVE</span><br>
                        <span style="color:var(--neon-blue); font-weight:900; font-size:13px;">±${expMove}%</span>
                        <span style="color:var(--text-dim); font-size:8px;"> IV:${avgIV}%</span>
                    </div>
                </div>
                
                <div style="margin-top:8px; padding-top:8px; border-top:1px solid var(--glass-border);">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="color:var(--text-dim); font-size:8px; letter-spacing:1px;">DEALER INVENTORY STRESS</span>
                        <span style="color:${stressClr}; font-weight:900; font-size:10px;">Z: ${invZ.toFixed(2)}</span>
                    </div>
                    <div style="height:4px; width:100%; background:rgba(255,255,255,0.05); border-radius:2px; margin-top:4px; position:relative; overflow:hidden;">
                        <div style="position:absolute; left:50%; height:100%; width:1px; background:rgba(255,255,255,0.2); z-index:1;"></div>
                        <div style="height:100%; width:${Math.abs(invPct-50)}%; background:${stressClr}; position:absolute; left:${Math.min(50, invPct)}%; border-radius:1px;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px;">
                        <span style="color:var(--text-dim); font-size:7px;">HJB HEDGE RATE</span>
                        <span style="color:var(--neon-blue); font-weight:800; font-size:8px;">u*: ${hjb.toFixed(2)} pts</span>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; font-size:9px; margin-top:8px; padding-top:8px; border-top:1px solid var(--glass-border);">
                    <div>
                        <span style="color:var(--neon-green);">▲ CALL WALL</span><br>
                        <span style="color:white; font-weight:800;">$${Number(callW).toFixed(0)}</span>
                    </div>
                    <div style="text-align:center;">
                        <span style="color:var(--neon-blue);">◆ ZGL</span><br>
                        <span style="color:white; font-weight:800;">$${Number(zgl).toFixed(2)}</span>
                    </div>
                    <div style="text-align:right;">
                        <span style="color:var(--neon-red);">▼ PUT WALL</span><br>
                        <span style="color:white; font-weight:800;">$${Number(putW).toFixed(0)}</span>
                    </div>
                </div>
                ${maxOI ? `<div style="font-size:8px; color:var(--text-dim); margin-top:4px; text-align:center;">📌 PIN MAGNET: $${Number(maxOI).toFixed(0)}</div>` : ''}
            `;
        }
    },

    async updateGammaSignals() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/market/signals');
            const data = await r.json();
            if (data.status === 'success') {
                this.gammaSignals = data.data;
                this.renderIntel(); // Merged into intel feed
            }
        } catch (e) {
            console.error('GEX Signals link failure:', e);
        }
    },

    // ── HELPERS ──────────────────────────────────────────────
    async addToWatchlist(symbol) {
        const btn = document.querySelector(`button[onclick*="addToWatchlist('${symbol}')"]`);
        try {
            if (btn) { btn.textContent = '⏳ TRACKING...'; btn.disabled = true; }
            const r = await fetch('http://127.0.0.1:8182/api/watchlist', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol })
            });
            const data = await r.json();
            if (data.status === 'success') {
                console.log(`📡 ${symbol} added to GEX watchlist`);
                if (btn) { btn.textContent = '✅ GEX TRACKING'; btn.style.borderColor = 'var(--neon-green)'; btn.style.color = 'var(--neon-green)'; }
                this.updateGammaProfile();
            } else {
                if (btn) { btn.textContent = '❌ FAILED'; }
            }
        } catch (e) {
            console.error('Watchlist add error:', e);
            if (btn) { btn.textContent = '❌ OFFLINE'; }
        }
        // Reset button after 3s
        setTimeout(() => { if (btn) { btn.textContent = '📡 TRACK GEX'; btn.disabled = false; btn.style.borderColor = ''; btn.style.color = ''; } }, 3000);
    },

    switchTab(tabId) {
        // No-op — tabs removed, all panels visible at once
    },

    // ── PERFORMANCE ANALYTICS: Verified Track Record ──────────
    async updatePerformance() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/performance/stats');
            const data = await r.json();
            if (data.status === 'success') {
                this.perfData = data.stats;
                this.renderPerformance();
            }
        } catch (e) {
            console.error('Performance sync error:', e);
        }
    },

    renderPerformance() {
        if (typeof this.updatePerfBadge === 'function') this.updatePerfBadge();
        const grid = document.getElementById('perf-stats-grid');
        if (!grid || !this.perfData) return;

        const d = this.perfData;
        const pnlColor = d.total_pnl >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
        
        grid.innerHTML = `
            <div class="grimoire-card">
                <div class="card-label">TOTAL PNL</div>
                <div class="card-value" style="color:${pnlColor}">$${d.total_pnl.toFixed(2)}</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">WIN RATE</div>
                <div class="card-value">${d.win_rate.toFixed(1)}%</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">PROFIT FACTOR</div>
                <div class="card-value">${d.profit_factor.toFixed(2)}</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">SHARPE RATIO</div>
                <div class="card-value">${d.sharpe_ratio.toFixed(2)}</div>
            </div>
            <div class="grimoire-card" style="grid-column: span 2;">
                <div class="card-label">MAX DRAWDOWN</div>
                <div class="card-value" style="color:var(--neon-red)">$${d.max_drawdown.toFixed(2)}</div>
            </div>
        `;

        this.renderEquityChart();
    },

    renderEquityChart() {
        const ctx = document.getElementById('equityChart');
        if (!ctx || !this.perfData || !this.perfData.equity_curve) return;

        const curve = this.perfData.equity_curve;
        if (curve.length < 2) return;

        const labels = curve.map((_, i) => i);
        const values = curve.map(c => c.pnl);

        if (this.equityChartInstance) {
            this.equityChartInstance.data.labels = labels;
            this.equityChartInstance.data.datasets[0].data = values;
            this.equityChartInstance.update('none');
            return;
        }

        this.equityChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Equity PnL',
                    data: values,
                    borderColor: '#22d3ee',
                    backgroundColor: 'rgba(34, 211, 238, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 9 } }
                    }
                }
            }
        });
    },

    // ── SHADOW TRADING: BYOK Execution ───────────────────────
    async updateShadowTrades() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/trade/active');
            const data = await r.json();
            if (data.status === 'success') {
                this.shadowTrades = data.active || [];
                this.renderShadow();
            }
        } catch (e) {
            console.warn('Shadow Trades sync failure:', e.message);
        }
    },

    renderShadow() {
        const list = document.getElementById('shadow-list');
        if (!list) return;

        if (!this.shadowTrades || this.shadowTrades.length === 0) {
            list.innerHTML = `<div class="loading-msg">NO ACTIVE SHADOW TRADES</div>`;
            return;
        }

        list.innerHTML = this.shadowTrades.map(t => {
            const pnl = (t.current_price - t.entry_price) * t.qty * (t.side === 'SELL' ? -1 : 1);
            const pnlColor = pnl >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
            const age = Math.round((Date.now() / 1000 - t.opened_at) / 60);

            return `
                <div class="intel-row trade-row" style="border-left: 2px solid ${pnlColor}; background:rgba(255,255,255,0.01); margin-bottom:5px; padding:10px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:950; color:white;">${t.symbol} <span style="font-size:9px; color:var(--text-dim);">${t.side} ${t.qty}</span></span>
                        <span style="font-weight:900; color:${pnlColor}; font-size:12px;">$${pnl.toFixed(2)}</span>
                    </div>
                    <div style="font-size:9px; color:var(--text-dim); margin-top:4px; display:flex; justify-content:space-between;">
                        <span>ENTRY: $${t.entry_price.toFixed(2)} | NOW: $${t.current_price.toFixed(2)}</span>
                        <span>AGE: ${age}M</span>
                    </div>
                    <div style="font-size:9px; color:white; margin-top:4px; display:flex; gap:10px;">
                        <span style="color:var(--neon-red); font-weight:800;">SL: $${t.sl.toFixed(2)}</span>
                        <span style="color:var(--neon-green); font-weight:800;">TP: $${t.tp.toFixed(2)}</span>
                        <span style="color:var(--neon-blue); font-weight:800;">REGIME: ${t.regime}</span>
                    </div>
                </div>
            `;
        }).join('');
    },

    async executeShadowTrade(side) {
        const sym = this.activeSymbol;
        if (!sym) return;

        console.log(`🚀 Triggering SHADOW ${side} for ${sym}...`);
        
        try {
            const r = await fetch('http://127.0.0.1:8182/api/trade/shadow', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol: sym, side: side, qty: 100 })
            });
            const data = await r.json();
            
            // New Institutional Audit flow
            this.renderTradeAudit(data);

            if (data.status === 'success') {
                this.updateTerminalFeed(); 
                this.updateShadowTrades();
                this.updateDeltaNeutrality();
            }
        } catch (e) {
            console.warn('Execution error:', e.message);
            this.renderTradeAudit({ status: 'error', message: e.message, symbol: sym, side: side });
        }
    },

    // ── INTEL TAB SWITCHER ──────────────────────────
    switchIntelTab(tab) {
        const tabs = ['options', 'fme', 'mm', 'cascade'];
        tabs.forEach(t => {
            const content = document.getElementById(`intel-${t}-content`);
            const btn = document.getElementById(`btn-intel-${t}`);
            if (content) content.style.display = t === tab ? 'block' : 'none';
            if (btn) btn.classList.toggle('active', t === tab);
        });
        // Render content for selected tab
        const sym = this.activeSymbol;
        if (!sym) return;
        if (tab === 'options') {
            const el = document.getElementById('intel-options-content');
            if (el) el.innerHTML = this.renderOptionsPanel(sym);
        } else if (tab === 'fme') {
            const el = document.getElementById('intel-fme-content');
            if (el) el.innerHTML = this.renderForcedMovePanel(sym);
        } else if (tab === 'mm') {
            const el = document.getElementById('intel-mm-content');
            if (el) el.innerHTML = this.renderMMIntelPanel(sym);
        } else if (tab === 'cascade') {
            const el = document.getElementById('intel-cascade-content');
            if (el) el.innerHTML = this.renderCascadePanel ? this.renderCascadePanel(sym) : '<div style="color:var(--text-muted);">AWAITING CASCADE DATA...</div>';
        }
    },

    // ── CASCADE PANEL RENDERER ──────────────────────────
    renderCascadePanel(symbol) {
        const data = this.cascadeData[symbol];
        if (!data) return '<div style="color:var(--text-muted);padding:10px;">AWAITING CASCADE DATA...</div>';

        const alignment = data.cascade_alignment_score || data.alignment_score || 0;
        const bias = data.cascade_bias || data.bias || 'NEUTRAL';
        const biasCol = alignment > 25 ? 'var(--neon-green)' : alignment > 10 ? '#00CC66' : alignment < -25 ? 'var(--neon-red)' : alignment < -10 ? '#FF6600' : 'var(--neon-yellow)';

        let html = `<div style="font-size:12px;">`;
        html += `<div style="margin-bottom:8px;font-weight:900;color:var(--neon-orange);">FRACTAL CASCADE</div>`;
        html += `<div style="text-align:center;margin:8px 0;">`;
        html += `<div style="font-size:20px;font-weight:900;color:${biasCol};">${bias}</div>`;
        html += `<div style="font-size:11px;color:var(--text-muted);">Alignment: ${alignment.toFixed(1)}%</div>`;
        html += `</div>`;

        // Alignment bar
        const pct = Math.min(Math.abs(alignment), 100);
        const dir = alignment >= 0 ? 'bull' : 'bear';
        html += `<div class="cascade-bar"><div class="cascade-bar-fill ${dir}" style="width:${pct/2}%;"></div><div class="cascade-bar-center"></div></div>`;

        // Per-timeframe grid
        const tfs = data.cascade_timeframes || data.timeframes || {};
        const tfOrder = ['6M', '3M', '1M', '2W', '1W', '4D', '2D', '1D'];
        html += `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-top:8px;">`;
        tfOrder.forEach(tf => {
            const t = tfs[tf];
            if (!t) { html += `<div style="text-align:center;padding:4px;background:rgba(255,255,255,0.02);border-radius:3px;"><div style="font-size:9px;color:var(--text-muted);">${tf}</div><div style="font-size:9px;color:#555;">OFF</div></div>`; return; }
            const dirCol = t.direction > 0 ? 'var(--neon-green)' : t.direction < 0 ? 'var(--neon-red)' : 'var(--neon-yellow)';
            const label = t.direction > 0 ? 'LONG' : t.direction < 0 ? 'SHORT' : 'AVOID';
            html += `<div style="text-align:center;padding:4px;background:rgba(255,255,255,0.03);border-radius:3px;border:1px solid rgba(255,255,255,0.05);">`;
            html += `<div style="font-size:9px;color:var(--text-muted);">${tf}</div>`;
            html += `<div style="font-size:10px;font-weight:700;color:${dirCol};">${label}</div>`;
            if (t.state) html += `<div style="font-size:8px;color:#666;">${t.state}</div>`;
            html += `</div>`;
        });
        html += `</div>`;

        // Counts
        const bulls = data.cascade_bull_count || data.bull_count || 0;
        const bears = data.cascade_bear_count || data.bear_count || 0;
        html += `<div style="margin-top:6px;font-size:10px;text-align:center;color:var(--text-muted);">${bulls} BULL | ${bears} BEAR</div>`;
        html += `</div>`;
        return html;
    },
    selectSymbol(symbol) {
        this.activeSymbol = symbol;
        this.updateGrimoire();
        this.renderWhales();
        this.fetchOptionsIntel(symbol);
        this.fetchForcedMove(symbol);
        this.fetchMMIntel(symbol);
        this.fetchCascade(symbol);
        // Render intel panels after fetch calls
        setTimeout(() => {
            this.switchIntelTab('options');
        }, 500);
    },

    getSqueezeLevel(volRatio, change) {
        if (volRatio > 5 && Math.abs(change) > 10) return "EXTREME BREAKOUT";
        if (volRatio > 3) return "HIGH VOL ACCUMULATION";
        if (volRatio > 1.5) return "MODERATE PRESSURE";
        return "STABLE CHANNEL";
    },

    async updateAudit() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/status/audit');
            const data = await r.json();
            if (data.status === 'success') {
                this.renderAudit(data.compliance);
            }
        } catch (e) {
            console.error('Audit link failure:', e);
        }
    },

    renderAudit(c) {
        const content = document.getElementById('audit-content');
        if (!content) return;

        content.innerHTML = `
            <div class="audit-stat">
                <label>${c.law_2.label}</label>
                <div class="val">${c.law_2.value} <span class="status-pill pill-compliant">${c.law_2.status}</span></div>
                <div style="font-size:8px; color:var(--text-dim); margin-top:5px;">Scanned: ${c.law_2.scanned} / Total: ${c.law_2.total}</div>
            </div>
            <div class="audit-stat">
                <label>${c.law_3.label}</label>
                <div class="val">${c.law_3.value} <span class="status-pill pill-enforced">${c.law_3.status}</span></div>
                <div style="font-size:8px; color:var(--text-dim); margin-top:5px;">Mega Cap spam silenced today.</div>
            </div>
            <div class="audit-stat">
                <label>SYSTEM UPTIME</label>
                <div class="val">${c.uptime}</div>
            </div>
        `;
    },

    toggleAudit() {
        const overlay = document.getElementById('audit-overlay');
        if (overlay) {
            const isShown = overlay.style.display === 'block';
            overlay.style.display = isShown ? 'none' : 'block';
            if (!isShown) this.updateAudit();
        }
    },

    // ── STREAM MODE TOGGLE ──────────────────────────
    toggleStreamMode() {
        document.body.classList.toggle('stream-overlay');
        const btn = document.getElementById('stream-mode-btn');
        const indicator = document.getElementById('stream-indicator');
        const isActive = document.body.classList.contains('stream-overlay');
        if (btn) btn.classList.toggle('active', isActive);
        if (indicator) indicator.style.display = isActive ? 'inline-flex' : 'none';
    },

    // ── SPOTLIGHT AUTO-ROTATION ──────────────────────────
    toggleSpotlight() {
        this._spotlightActive = !this._spotlightActive;
        const overlay = document.getElementById('spotlight-overlay');
        const btn = document.getElementById('spotlight-btn');

        if (this._spotlightActive) {
            if (overlay) overlay.style.display = 'block';
            if (btn) btn.classList.add('active');
            this._spotlightIndex = 0;
            this.renderSpotlight();
            this._spotlightInterval = setInterval(() => this.rotateSpotlight(), 8000);
        } else {
            if (overlay) overlay.style.display = 'none';
            if (btn) btn.classList.remove('active');
            if (this._spotlightInterval) clearInterval(this._spotlightInterval);
        }
    },

    rotateSpotlight() {
        const hotSymbols = (this.scanData || [])
            .filter(s => (s.squeeze_score || 0) >= 30 && s.price >= 2 && s.price <= 60)
            .sort((a, b) => (b.squeeze_score || 0) - (a.squeeze_score || 0));

        if (hotSymbols.length === 0) return;
        this._spotlightIndex = (this._spotlightIndex + 1) % hotSymbols.length;
        this.renderSpotlight();
    },

    renderSpotlight() {
        const hotSymbols = (this.scanData || [])
            .filter(s => (s.squeeze_score || 0) >= 30 && s.price >= 2 && s.price <= 60)
            .sort((a, b) => (b.squeeze_score || 0) - (a.squeeze_score || 0));

        if (hotSymbols.length === 0) {
            const header = document.getElementById('spotlight-header');
            if (header) header.innerHTML = '<div style="color:var(--neon-yellow);font-size:24px;font-weight:900;margin-top:40vh;">SCANNING FOR SIGNALS...</div>';
            return;
        }

        const idx = this._spotlightIndex % hotSymbols.length;
        const sym = hotSymbols[idx];
        const symbol = sym.symbol;
        const fme = this.forcedMoveData[symbol] || {};
        const mm = this.mmIntelData[symbol] || {};
        const opts = this.optionsIntelData[symbol] || {};

        // Fetch fresh data for this symbol
        this.fetchForcedMove(symbol);
        this.fetchMMIntel(symbol);
        this.fetchOptionsIntel(symbol);

        // Use scan data for price info (it comes from real quotes)
        const priceCol = (sym.changePct || 0) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
        const changePct = (sym.changePct || 0).toFixed(2);
        const action = fme.action || mm.signal || 'SCANNING';
        const actionClass = action.includes('BUY') || action.includes('LONG') || action.includes('FULL SIZE') ? 'buy' : action.includes('SELL') || action.includes('SHORT') ? 'sell' : action.includes('FORCED') ? 'forced' : '';

        const header = document.getElementById('spotlight-header');
        if (header) {
            header.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <span class="spotlight-symbol">${symbol}</span>
                        <span class="spotlight-price" style="color:${priceCol};margin-left:16px;">$${(sym.price || 0).toFixed(2)}</span>
                        <span style="color:${priceCol};font-size:16px;margin-left:8px;">${changePct}%</span>
                    </div>
                    <div>
                        <span style="color:#555;font-size:12px;">${idx + 1}/${hotSymbols.length}</span>
                        ${action !== 'SCANNING' ? `<span class="spotlight-action ${actionClass}">${action}</span>` : ''}
                    </div>
                </div>
                <div style="color:#555;font-size:11px;margin-top:4px;">SQUEEZE: ${sym.squeeze_score || '--'} | BEAST: ${sym.beast_score || '--'} | HEAT: ${sym.heat || '--'}</div>
            `;
        }

        // Left panel: FME + MM Intel
        const left = document.getElementById('spotlight-left');
        if (left) {
            left.innerHTML = `<div class="spotlight-card">${this.renderForcedMovePanel(symbol)}</div><div class="spotlight-card" style="margin-top:12px;">${this.renderMMIntelPanel(symbol)}</div>`;
        }

        // Right panel: Options Intel
        const right = document.getElementById('spotlight-right');
        if (right) {
            right.innerHTML = `<div class="spotlight-card hot">${this.renderOptionsPanel(symbol)}</div>`;
        }
    },

    // ── RMRE: Regime Intelligence ───────────────────────────
    async updateRegime() {
        try {
            const r = await fetch(`http://127.0.0.1:8182/api/market/regime?symbol=${this.activeSymbol}`);
            const data = await r.json();
            if (data.status === 'success') {
                this.regimeData = data.data;
                this.renderRegime();
            }
        } catch (e) {
            console.error('Regime link failure:', e);
        }
    },

    renderRegime() {
        const container = document.getElementById('regime-content');
        const modifierBadge = document.getElementById('regime-modifier');
        if (!container || !this.regimeData) return;

        const d = this.regimeData;

        // Update Modifier Badge
        const mod = d.beast_modifier || 0;
        const modClass = mod > 0 ? 'modifier-pos' : (mod < 0 ? 'modifier-neg' : 'modifier-neu');
        const modText = mod > 0 ? `+${mod} BOOST` : (mod < 0 ? `${mod} DRAG` : 'NEUTRAL');
        if (modifierBadge) {
            modifierBadge.className = `badge ${modClass}`;
            modifierBadge.innerText = modText;
        }

        const regimeColor = (d.regime && (d.regime.includes('risk_off') || d.regime.includes('deleveraging'))) ? 'var(--neon-red)' : (d.regime && (d.regime.includes('risk_on') || d.moass_watch)) ? 'var(--neon-green)' : 'var(--neon-blue)';
        const decisionClass = d.decision === 'BUY NOW' ? 'decision-buy' : d.decision === 'SELL NOW' ? 'decision-sell' : 'decision-wait';

        container.innerHTML = `
            <div class="regime-header" style="display:flex; justify-content:space-between; align-items:center;">
                <div class="regime-name" style="color:${regimeColor}; font-weight:950; font-size:14px; letter-spacing:1px;">
                    ${d.moass_watch ? '🚀 MOASS WATCH' : (d.regime_label || 'NEUTRAL')}
                </div>
                <div style="font-size:9px; color:var(--text-dim);">${d.target || 'MARKET'} FOCUS</div>
            </div>

            <div style="margin-top:8px; display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                <div style="padding:10px; background:rgba(255,255,255,0.03); border-radius:6px; border:1px solid var(--glass-border);">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:8px; color:var(--text-dim); letter-spacing:1.5px;">SML FRACTAL LIFECYCLE</span>
                        <span class="badge ${d.lifecycle === 'TRIGGERED' || d.lifecycle === 'ACTIVE' ? 'badge-extreme' : 'badge-high'}" style="font-size:10px; border-radius:2px;">${d.lifecycle || 'DORMANT'}</span>
                    </div>
                    <div style="font-size:10px; color:white; font-weight:700; margin-top:5px; font-family:var(--font-mono);">
                        STATE: ${d.regime_label} / ${d.decision}
                    </div>
                </div>
                <div style="padding:10px; background:rgba(0, 212, 255, 0.05); border-radius:6px; border:1px solid rgba(0, 212, 255, 0.1);">
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; text-align:center;">
                        <div>
                            <div style="font-size:7px; color:var(--text-dim);">PRECURSOR</div>
                            <div style="font-size:14px; font-weight:950; color:white;">${d.precursor_score?.toFixed(1) || '0.0'}</div>
                        </div>
                        <div>
                            <div style="font-size:7px; color:var(--text-dim);">SQZ SCORE</div>
                            <div style="font-size:14px; font-weight:950; color:var(--neon-blue);">${d.squeeze_score?.toFixed(1) || '0.0'}</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="chain-container">
                <div class="chain-row">
                    <div class="chain-label">
                        <span style="color:var(--neon-green)">BULL CHAIN</span>
                        <span>${d.bull_chain || 0}%</span>
                    </div>
                    <div class="chain-bar-bg">
                        <div class="chain-bar-fill bull-fill" style="width: ${d.bull_chain || 0}%"></div>
                    </div>
                </div>
                <div class="chain-row">
                    <div class="chain-label">
                        <span style="color:var(--neon-red)">BEAR CHAIN</span>
                        <span>${d.bear_chain || 0}%</span>
                    </div>
                    <div class="chain-bar-bg">
                        <div class="chain-bar-fill bear-fill" style="width: ${d.bear_chain || 0}%"></div>
                    </div>
                </div>
            </div>

            <div style="margin-top:10px; display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                <div class="confidence-meter-container" style="margin:0; padding:10px; height:auto;">
                    <div class="conf-label" style="font-size:7px;">CONVICTION</div>
                    <div class="conf-val" style="color:${(d.confidence || 0) >= 60 ? 'var(--neon-green)' : (d.confidence || 0) >= 40 ? 'var(--neon-blue)' : 'var(--neon-red)'}; font-size:18px;">
                        ${d.confidence || 0}%
                    </div>
                    <div style="font-size:7px; color:rgba(255,255,255,0.4); margin-top:2px;">H-PROX: ${d.hurst_val?.toFixed(2) || 0.5}</div>
                </div>
                <div style="background:rgba(255,255,255,0.03); padding:8px; border-radius:4px; border:1px solid var(--glass-border); line-height:1.2;">
                    <div style="font-size:7px; color:var(--text-dim); letter-spacing:1px; margin-bottom:4px;">INSTITUTIONAL RISK RANGES</div>
                    <div style="font-size:8px; color:white; display:flex; justify-content:space-between;">
                        <span style="color:var(--neon-blue)">${d.risk_ranges?.st?.label || 'ST'}:</span> <span>$${d.risk_ranges?.st?.low || '--'} - $${d.risk_ranges?.st?.high || '--'}</span>
                    </div>
                    <div style="font-size:8px; color:white; display:flex; justify-content:space-between; margin-top:2px;">
                        <span style="color:var(--neon-purple)">${d.risk_ranges?.it?.label || 'IT'}:</span> <span>$${d.risk_ranges?.it?.low || '--'} - $${d.risk_ranges?.it?.high || '--'}</span>
                    </div>
                    <div style="font-size:8px; color:white; display:flex; justify-content:space-between; margin-top:2px;">
                        <span style="color:var(--neon-orange)">${d.risk_ranges?.lt?.label || 'LT'}:</span> <span>$${d.risk_ranges?.lt?.low || '--'} - $${d.risk_ranges?.lt?.high || '--'}</span>
                    </div>
                </div>
            </div>

            <div class="component-scores" style="margin-top:10px; grid-template-columns: repeat(4, 1fr);">
                <div class="comp-score">
                    <div class="comp-label">MACRO</div>
                    <div class="comp-val" style="color:${(d.macro_score || 0) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)'}">${(d.macro_score || 0) > 0 ? '+' : ''}${(d.macro_score || 0).toFixed(1)}</div>
                </div>
                <div class="comp-score">
                    <div class="comp-label">RISK</div>
                    <div class="comp-val" style="color:${(d.risk_score || 0) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)'}">${(d.risk_score || 0) > 0 ? '+' : ''}${(d.risk_score || 0).toFixed(1)}</div>
                </div>
                <div class="comp-score">
                    <div class="comp-label">BASKET</div>
                    <div class="comp-val" style="color:${(d.basket_score || 0) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)'}">${(d.basket_score || 0) > 0 ? '+' : ''}${(d.basket_score || 0).toFixed(1)}</div>
                </div>
                <div class="comp-score">
                    <div class="comp-label">TARGET</div>
                    <div class="comp-val" style="color:${(d.target_score || 0) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)'}">${(d.target_score || 0) > 0 ? '+' : ''}${(d.target_score || 0).toFixed(1)}</div>
                </div>
            </div>

            <div class="decision-box ${decisionClass}" style="margin-top:10px; font-weight:900; letter-spacing:2px; font-size:12px;">
                ${d.decision || 'WAITING FOR DATA'}
            </div>
        `;
    },

    // ── LIVE TERMINAL: Chronological Event Stream ─────────────
    async updateTerminalFeed() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/terminal/feed?limit=50');
            const data = await r.json();
            if (data.status === 'success') {
                this.terminalFeed = data.data;
                this.renderTerminalFeed();
            }
        } catch (e) {
            console.error('Terminal feed error:', e);
        }
    },

    renderTerminalFeed() {
        if (!this.terminalFeed) return;
        const list = document.getElementById('terminal-list');
        if (!list) return;

        // Skip if same data
        const dataStr = JSON.stringify(this.terminalFeed);
        if (this.lastTerminalStr === dataStr) return;
        this.lastTerminalStr = dataStr;

        // Update badge counts
        const scanBadge = document.getElementById('badge-scan-count');
        const flowBadge = document.getElementById('badge-flow-count');
        if (scanBadge) scanBadge.textContent = `${(this.scanData || []).length}`;
        if (flowBadge) flowBadge.textContent = `${(this.flowData || []).length}`;

        if (this.terminalFeed.length === 0) {
            list.innerHTML = '';
            return;
        }

        // Filter OUT flow events from scanner feed — those belong in the firehose pane
        const scannerEvents = this.terminalFeed.filter(evt => evt.type !== 'FLOW');

        list.innerHTML = scannerEvents.map(evt => {
            let clr = 'var(--text-main)';
            if (evt.type === 'MOASS') clr = 'var(--neon-pink)';
            else if (evt.type === 'SCAN') clr = 'var(--neon-cyan, var(--neon-blue))';
            else if (evt.type === 'REVERSAL') clr = 'var(--neon-yellow)';
            else if (evt.type === 'GAMMA') clr = 'var(--neon-purple)';
            else if (evt.type === 'BEAST') clr = 'var(--neon-orange)';
            else if (evt.type === 'DISCOVERY') clr = 'var(--neon-green)';
            else if (evt.type === 'PATTERN') clr = 'var(--neon-blue)';
            else if (evt.type === 'SYSTEM') clr = 'var(--neon-blue)';

            return `
                <div class="intel-row terminal-event" style="border-left: 2px solid ${clr}">
                    <span class="time">${evt.time_str}</span>
                    <span class="type" style="color:${clr}">${evt.type}</span>
                    <span class="msg">${evt.msg}</span>
                </div>
            `;
        }).join('');
    },

    // ── REVERSAL: Buy/Sell/Watch Graded Signals ──────────────
    async updateReversal() {
        try {
            if (!this.activeSymbol) return;
            const r = await fetch(`http://127.0.0.1:8182/api/market/reversal?symbol=${this.activeSymbol}`);
            if (!r.ok) {
                // Server returned 404/500 — try building grade from scanData
                if (this.scanData && this.scanData.length > 0) {
                    const sym = this.scanData.find(s => s.symbol === this.activeSymbol);
                    if (sym && sym.squeeze_score > 0) {
                        const score = sym.squeeze_score || 0;
                        const price = sym.price || 0;
                        const dir = sym.direction || 'NEUTRAL';
                        const signal = dir === 'BULLISH' ? (score >= 55 ? 'BUY' : 'WATCH') : dir === 'BEARISH' ? (score >= 55 ? 'SELL' : 'WATCH') : 'WATCH';
                        const target = dir === 'BULLISH' ? +(price * 1.05).toFixed(2) : dir === 'BEARISH' ? +(price * 0.95).toFixed(2) : +price.toFixed(2);
                        const stop = dir === 'BULLISH' ? +(price * 0.98).toFixed(2) : dir === 'BEARISH' ? +(price * 1.02).toFixed(2) : +price.toFixed(2);
                        const risk = Math.abs(price - stop);
                        const rr = risk > 0 ? +(Math.abs(target - price) / risk).toFixed(1) : 0;
                        const grade = score >= 75 ? 'A' : score >= 55 ? 'B' : score >= 40 ? 'C' : 'D';
                        this.reversalData = { symbol: this.activeSymbol, grade, signal, target, stop, rr, score };
                        this.renderReversal();
                        return;
                    }
                }
                this.reversalData = null;
                this.renderReversal();
                return;
            }
            const data = await r.json();
            if (data.status === 'success') {
                this.reversalData = data.data;
                this.renderReversal();
            } else {
                this.reversalData = null;
                this.renderReversal();
            }
        } catch (e) {
            console.error('Reversal signal error:', e);
        }
    },

    renderReversal() {
        const badge = document.getElementById('reversal-badge');
        if (!badge) return;

        if (!this.reversalData || !this.reversalData.grade) {
            badge.innerHTML = '';
            return;
        }

        const d = this.reversalData;
        const clr = d.grade === 'A' ? 'var(--neon-green)' : (d.grade === 'B' ? 'var(--neon-yellow)' : 'var(--neon-blue)');
        const sigClr = d.signal === 'BUY' ? 'var(--neon-green)' : (d.signal === 'SELL' ? 'var(--neon-red)' : 'var(--text-dim)');

        badge.innerHTML = `
            <div class="rev-setup-badge" style="border-color:${clr}; color:${clr}; flex-direction:row; gap:12px; justify-content:center; padding:6px 15px;">
                <span class="grade">${d.grade}-SETUP</span>
                <span class="signal" style="color:${sigClr}">${d.signal} ${d.symbol}</span>
                <span class="rev-details" style="margin-top:0;">TGT: $${d.target}</span>
                <span class="rev-details" style="margin-top:0;">STP: $${d.stop}</span>
                <span class="rev-details" style="margin-top:0;">R:R ${d.rr}:1</span>
            </div>
        `;
    },

    // ── PERFORMANCE ANALYTICS: Verified Track Record ──────────
    async updatePerformance() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/performance/stats');
            const data = await r.json();
            if (data.status === 'success') {
                this.perfData = data.stats;
                this.renderPerformance();
            }
        } catch (e) {
            console.error('Performance sync error:', e);
        }
    },

    renderPerformance() {
        if (typeof this.updatePerfBadge === 'function') this.updatePerfBadge();
        const grid = document.getElementById('perf-stats-grid');
        if (!grid || !this.perfData) return;

        const d = this.perfData;
        const pnlColor = d.total_pnl >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
        
        grid.innerHTML = `
            <div class="grimoire-card">
                <div class="card-label">TOTAL PNL</div>
                <div class="card-value" style="color:${pnlColor}">$${d.total_pnl.toFixed(2)}</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">WIN RATE</div>
                <div class="card-value">${d.win_rate.toFixed(1)}%</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">PROFIT FACTOR</div>
                <div class="card-value">${d.profit_factor.toFixed(2)}</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">SHARPE RATIO</div>
                <div class="card-value">${d.sharpe_ratio.toFixed(2)}</div>
            </div>
            <div class="grimoire-card">
                <div class="card-label">MAX DRAWDOWN</div>
                <div class="card-value" style="color:var(--neon-red)">$${d.max_drawdown.toFixed(2)}</div>
            </div>
            <div class="grimoire-card" style="border: 1px solid var(--neon-purple); background: rgba(168, 85, 247, 0.05);">
                <div class="card-label" style="color:var(--neon-purple)">HEDGED PNL</div>
                <div class="card-value" style="color:${(d.hedged_pnl || 0) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)'}">$${(d.hedged_pnl || 0).toFixed(2)}</div>
            </div>
            ${this.hedgeProxy ? `
            <div class="grimoire-card" style="grid-column: span 2; border: 1px solid var(--neon-purple); background: rgba(168, 85, 247, 0.05);">
                <div class="card-label" style="color:var(--neon-purple)">HEDGE PROXY (BETA: ${this.hedgeProxy.portfolio_beta})</div>
                <div class="card-value" style="font-size:14px; color:white;">${this.hedgeProxy.recommended_hedge}</div>
                <div style="font-size:7px; color:var(--text-dim); margin-top:2px;">NOTIONAL: $${this.hedgeProxy.total_notional.toLocaleString()}</div>
            </div>
            ` : ''}
        `;

        this.renderEquityChart();
    },

    renderEquityChart() {
        const ctx = document.getElementById('equityChart');
        if (!ctx || !this.perfData || !this.perfData.equity_curve) return;

        const curve = this.perfData.equity_curve;
        if (curve.length < 2) return;

        const labels = curve.map((_, i) => i);
        const values = curve.map(c => c.pnl);

        if (this.equityChartInstance) {
            this.equityChartInstance.data.labels = labels;
            this.equityChartInstance.data.datasets[0].data = values;
            this.equityChartInstance.update('none');
            return;
        }

        if (typeof Chart === 'undefined') {
            console.warn("Chart.js not loaded yet. Skipping equity chart render.");
            return;
        }

        this.equityChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Equity PnL',
                    data: values,
                    borderColor: '#22d3ee',
                    backgroundColor: 'rgba(34, 211, 238, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 9 } }
                    }
                }
            }
        });
    },

    // ── INSTITUTIONAL IQ: Delta Neutrality Engine ──────────
    async updateDeltaNeutrality() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/trade/positions');
            const data = await r.json();
            if (data.status === 'success') {
                this.deltaStress = data.delta_stress;
                this.renderDeltaNeutrality();
            }
        } catch (e) {
            console.error('Delta Neutrality sync error:', e);
        }
    },

    renderDeltaNeutrality() {
        const panel = document.getElementById('delta-neutrality-panel');
        if (!panel || !this.deltaStress) return;

        const d = this.deltaStress;
        const netDelta = (d.net_delta_stress || 0).toFixed(2);
        const stressLevel = Math.abs(d.net_delta_stress || 0) > 1000 ? 'stressed' : (Math.abs(d.net_delta_stress || 0) > 200 ? 'exposed' : 'neutral');
        const badgeText = stressLevel.toUpperCase();
        
        panel.innerHTML = `
            <div class="delta-neutral-badge ${stressLevel}">
                <div style="font-size: 8px; opacity: 0.8; letter-spacing: 1px;">PORTFOLIO STATE</div>
                <div style="font-size: 14px;">${badgeText}</div>
            </div>
            
            <div style="margin-bottom: 20px;">
                <label style="font-size: 9px; color: var(--text-dim); letter-spacing: 1px; display: block; margin-bottom: 5px;">BETA-ADJUSTED DELTA (SPY)</label>
                <div style="font-size: 24px; font-weight: 950; color: white; font-family: var(--font-mono);">${netDelta}</div>
                <div style="font-size: 9px; color: var(--text-dim); margin-top: 2px;">Exposure: $${(d.total_notional || 0).toLocaleString()}</div>
            </div>

            <div style="padding: 10px; background: rgba(255,149,0,0.05); border: 1px solid rgba(255,149,0,0.2); border-radius: 4px;">
                <label style="font-size: 8px; color: var(--neon-orange); font-weight: 900; letter-spacing: 1px; display: block; margin-bottom: 5px;">HJB OPTIMAL HEDGE</label>
                <div style="font-size: 13px; font-weight: 900; color: white;">${d.recommended_hedge || 'NO HEDGE REQ'}</div>
                <div style="font-size: 7px; color: var(--text-dim); margin-top: 4px; line-height: 1.2;">
                    Shadow hedge maintains market neutrality against SPDR sectors using beta-weighted inventory balancing.
                </div>
            </div>

            <div style="margin-top: 20px;">
                <label style="font-size: 8px; color: var(--text-dim); letter-spacing: 1px; display: block; margin-bottom: 5px;">WATCHLIST BETA COV</label>
                <div style="display: flex; gap: 4px; flex-wrap: wrap;">
                    ${Object.entries(d.watchlist_betas || {}).map(([sym, beta]) => `
                        <div style="font-size: 8px; background: rgba(255,255,255,0.05); padding: 2px 5px; border-radius: 2px; color: white;">
                            ${sym}: ${beta.toFixed(2)}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    },

    // ── TRADE AUDIT: Institutional Protection ──────────────
    closeExecutionAudit() {
        const overlay = document.getElementById('execution-audit-overlay');
        if (overlay) overlay.style.display = 'none';
    },

    renderTradeAudit(result) {
        const overlay = document.getElementById('execution-audit-overlay');
        const content = document.getElementById('execution-audit-content');
        if (!overlay || !content) return;

        overlay.style.display = 'block';
        
        const statusClass = result.status === 'success' || result.status === 'ALREADY_HAVE_TARGET' ? 'passed' : 'failed';
        const title = result.status === 'success' ? 'TRADE EXECUTED' : (result.rejected_by ? 'TRADE REJECTED' : 'EXECUTION FAILED');
        
        let html = `
            <div style="text-align: center; margin-bottom: 20px;">
                <div style="font-size: 10px; color: var(--text-dim); letter-spacing: 2px;">AUDIT RESULT</div>
                <div style="font-size: 24px; font-weight: 900; color: ${result.status === 'success' ? 'var(--neon-green)' : 'var(--neon-red)'}">${title}</div>
            </div>

            <div class="audit-log-entry info">
                SYMBOL: ${result.symbol || 'UNKNOWN'} | SIDE: ${result.side || '--'} | QTY: ${result.qty || '--'}
            </div>
        `;

        if (result.audit_log) {
            result.audit_log.forEach(log => {
                const logClass = log.status === 'PASSED' ? 'passed' : (log.status === 'FAILED' ? 'failed' : 'info');
                html += `
                    <div class="audit-log-entry ${logClass}">
                        <div style="display: flex; justify-content: space-between; font-weight: 900;">
                            <span>${log.component}</span>
                            <span>${log.status}</span>
                        </div>
                        <div style="font-size: 10px; opacity: 0.8; margin-top: 2px;">${log.reason}</div>
                    </div>
                `;
            });
        }

        if (result.message && !result.audit_log) {
            html += `<div class="audit-log-entry failed">REASON: ${result.message}</div>`;
        }

        content.innerHTML = html;
    },

    updatePerfBadge() {
        if (!this.perfData) return;
        const d = this.perfData;
        const badgePnl = document.getElementById('badge-pnl');
        const badgeHedgedPnl = document.getElementById('badge-hedged-pnl');
        const badgeDelta = document.getElementById('badge-delta');
        const badgeWr = document.getElementById('badge-wr');

        if (badgePnl) {
            badgePnl.innerText = `$${d.total_pnl.toFixed(2)}`;
            badgePnl.className = `perf-val ${d.total_pnl >= 0 ? 'pos' : 'neg'}`;
        }
        if (badgeHedgedPnl) {
            badgeHedgedPnl.innerText = `$${(d.hedged_pnl || 0).toFixed(2)}`;
            badgeHedgedPnl.className = `perf-val ${(d.hedged_pnl || 0) >= 0 ? 'pos' : 'neg'}`;
        }
        if (badgeDelta && this.deltaStress) {
            const netDelta = this.deltaStress.net_delta_stress || 0;
            badgeDelta.innerText = netDelta.toFixed(1);
            badgeDelta.className = `perf-val ${Math.abs(netDelta) > 500 ? 'neg' : 'pos'}`;
        }
        if (badgeWr) badgeWr.innerText = `${d.win_rate.toFixed(1)}%`;
    },

    // ── OPTIONS INTELLIGENCE PANEL ────────────────────────
    renderOptionsPanel(symbol) {
        const data = this.optionsIntelData[symbol];
        if (!data) return '<div style="color:var(--text-muted);padding:10px;">AWAITING OPTIONS DATA...</div>';

        let html = '';

        // Sweeps section
        const sweeps = data.sweeps || [];
        html += '<div style="margin-bottom:8px;"><span style="color:var(--neon-orange);font-weight:900;">SWEEPS</span>';
        if (sweeps.length === 0) {
            html += ' <span style="color:var(--text-muted);">None detected</span></div>';
        } else {
            html += ` <span style="color:var(--neon-green);">${sweeps.length} found</span></div>`;
            sweeps.slice(0, 5).forEach(s => {
                const col = s.type === 'CALL' ? 'var(--neon-green)' : 'var(--neon-red)';
                html += `<div style="font-size:11px;padding:2px 0;"><span style="color:${col};">${s.type} $${s.strike}</span> ${s.expiry} | Vol:${s.vol} OI:${s.oi} | <span style="color:var(--neon-blue);">Score:${s.sweep_score}</span></div>`;
            });
        }

        // Unusual Volume section
        const unusual = data.unusual_volume || [];
        html += '<div style="margin:8px 0;"><span style="color:var(--neon-purple);font-weight:900;">UNUSUAL VOLUME</span>';
        if (unusual.length === 0) {
            html += ' <span style="color:var(--text-muted);">None detected</span></div>';
        } else {
            html += ` <span style="color:var(--neon-green);">${unusual.length} strikes</span></div>`;
            unusual.slice(0, 5).forEach(u => {
                const sevCol = u.severity === 'CRITICAL' ? 'var(--neon-red)' : u.severity === 'EXTREME' ? 'var(--neon-orange)' : 'var(--neon-yellow)';
                html += `<div style="font-size:11px;padding:2px 0;"><span style="color:${sevCol};">${u.severity}</span> ${u.type} $${u.strike} ${u.expiry} | Vol/OI: ${u.vol_oi_ratio?.toFixed(1)}x</div>`;
            });
        }

        // Whales section
        const whales = data.whales || [];
        html += '<div style="margin:8px 0;"><span style="color:var(--neon-blue);font-weight:900;">WHALE WATCH</span>';
        if (whales.length === 0) {
            html += ' <span style="color:var(--text-muted);">No large blocks</span></div>';
        } else {
            html += ` <span style="color:var(--neon-green);">${whales.length} detected</span></div>`;
            whales.forEach(w => {
                const dirCol = w.direction === 'BULLISH' ? 'var(--neon-green)' : w.direction === 'BEARISH' ? 'var(--neon-red)' : 'var(--neon-yellow)';
                const premium = (w.premium_total / 1000).toFixed(0);
                html += `<div style="font-size:11px;padding:2px 0;"><span style="color:${dirCol};">${w.size_class}</span> ${w.type} $${w.strike} ${w.expiry} | $${premium}K | <span style="color:${dirCol};">${w.direction}</span></div>`;
            });
        }

        // Recommendations section
        const recs = data.recommendations || [];
        html += '<div style="margin:8px 0;"><span style="color:var(--neon-green);font-weight:900;">TOP CONTRACTS</span></div>';
        if (recs.length > 0) {
            recs.slice(0, 3).forEach((r, i) => {
                html += `<div style="font-size:11px;padding:2px 0;"><span style="color:var(--neon-orange);">#${i+1}</span> ${r.type} $${r.strike} ${r.expiry} | Δ${r.delta?.toFixed(2)} | ${r.dte}DTE | Score:${r.overall_score?.toFixed(0)}</div>`;
                if (r.recommendation_text) html += `<div style="font-size:10px;color:var(--text-muted);padding-left:16px;">${r.recommendation_text}</div>`;
            });
        }

        // Flow summary
        const flow = data.flow_summary || {};
        if (flow.put_call_ratio != null) {
            html += '<div style="margin:8px 0;"><span style="color:var(--neon-cyan);font-weight:900;">FLOW</span>';
            const pcCol = flow.put_call_ratio > 1.2 ? 'var(--neon-red)' : flow.put_call_ratio < 0.8 ? 'var(--neon-green)' : 'var(--neon-yellow)';
            html += ` P/C: <span style="color:${pcCol};">${flow.put_call_ratio?.toFixed(2)}</span>`;
            if (flow.max_pain) html += ` | MaxPain: $${flow.max_pain}`;
            if (flow.net_positioning) html += ` | <span style="color:var(--neon-blue);">${flow.net_positioning}</span>`;
            html += '</div>';
        }

        return html;
    },

    // ── FORCED MOVE ENGINE PANEL ──────────────────────────
    renderForcedMovePanel(symbol) {
        const data = this.forcedMoveData[symbol];
        if (!data) return '<div style="color:var(--text-muted);padding:10px;">AWAITING FME DATA...</div>';

        const p = data.pressure || {};
        const t = data.trigger || {};
        const a = data.acceleration || {};
        const c = data.commitment || {};

        const pCol = p.state === 'LOADED' ? 'var(--neon-red)' : p.state === 'BUILD' ? 'var(--neon-orange)' : 'var(--text-muted)';
        const tCol = t.state === 'TRIGGERING' ? 'var(--neon-yellow)' : t.state === 'ARMED' ? 'var(--neon-orange)' : t.state === 'FALSE' ? 'var(--neon-purple)' : 'var(--text-muted)';
        const aCol = a.state === 'VIOLENT' ? 'var(--neon-green)' : a.state === 'CLEAN' ? '#00CC66' : 'var(--text-muted)';
        const cCol = c.state === 'FORCED' ? '#FF1493' : c.state === 'COMMITTED' ? 'var(--neon-blue)' : c.state === 'FRAGILE' ? 'var(--neon-orange)' : 'var(--neon-red)';

        const actCol = data.action?.includes('FULL SIZE') ? '#FF1493' : data.action?.includes('ADD') ? 'var(--neon-green)' : data.action?.includes('EXIT') ? 'var(--neon-red)' : 'var(--neon-yellow)';

        return `
            <div style="font-size:12px;">
                <div style="margin-bottom:6px;font-weight:900;color:#FF1493;">FORCED MOVE ENGINE</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
                    <div>L1 PRESSURE: <span style="color:${pCol};font-weight:700;">${p.state || '--'}</span> ${p.score?.toFixed(0) || '--'}</div>
                    <div>L2 TRIGGER: <span style="color:${tCol};font-weight:700;">${t.state || '--'}</span> ${t.score?.toFixed(0) || '--'}</div>
                    <div>L3 ACCEL: <span style="color:${aCol};font-weight:700;">${a.state || '--'}</span> ${a.score?.toFixed(0) || '--'}</div>
                    <div>L4 COMMIT: <span style="color:${cCol};font-weight:700;">${c.state || '--'}</span> ${c.score?.toFixed(0) || '--'}</div>
                </div>
                <div style="margin-top:6px;padding:4px;background:rgba(255,255,255,0.05);border-radius:4px;">
                    <span style="color:${actCol};font-weight:900;font-size:13px;">${data.action || 'WAIT'}</span>
                    <span style="color:var(--text-muted);margin-left:8px;">SIZE: ${data.size_pct || 0}%</span>
                    ${a.dead_setup ? '<span style="color:#FF00FF;margin-left:8px;">⚠ DEAD SETUP</span>' : ''}
                </div>
            </div>
        `;
    },

    // ── TOP MOVERS: Derived from scan data — shows top squeeze candidates ───────
    renderTopMovers() {
        const list = document.getElementById('top-movers-list');
        if (!list) return;
        if (!this.scanData || this.scanData.length === 0) { list.innerHTML = ''; return; }

        const movers = [...this.scanData]
            .filter(s => s.squeeze_score !== null && s.squeeze_score > 30)
            .sort((a, b) => (b.squeeze_score || 0) - (a.squeeze_score || 0))
            .slice(0, 5);

        if (movers.length === 0) { list.innerHTML = ''; return; }

        list.innerHTML = `<div style="font-size:9px; color:var(--text-dim); padding:4px 8px; letter-spacing:1px; font-weight:700; border-bottom:1px solid var(--glass-border);">TOP SQUEEZE MOVERS</div>` +
            movers.map(m => {
                const clr = m.squeeze_score >= 60 ? 'var(--neon-green)' : 'var(--neon-blue)';
                return `<div class="data-row" style="cursor:pointer; font-size:11px;" onclick="AnalyticalEngine.selectSymbol('${m.symbol}')">
                    <span style="color:white; font-weight:900; min-width:50px;">${m.symbol}</span>
                    <span style="color:var(--text-dim); font-size:10px;">SQZ:${m.squeeze_score}</span>
                    <span style="color:${clr}; font-weight:800;">${m.squeeze_level || ''}</span>
                </div>`;
            }).join('');

        // Also update Action Board
        this.renderActionBoard();
    },

    // ── ACTION BOARD: Quick-glance best setups ranked ───────────
    renderActionBoard() {
        const board = document.getElementById('action-board-content');
        if (!board) return;
        if (!this.scanData || this.scanData.length === 0) {
            board.innerHTML = '<div class="loading-msg">SCANNING FOR TOP SETUPS...</div>';
            return;
        }

        const candidates = [...this.scanData]
            .filter(s => s.squeeze_score !== null)
            .map(s => {
                const sym = s.symbol;
                const sqzScore = s.squeeze_score || 0;
                const flow = (this.flowData || []).filter(f => f.symbol === sym);
                const bullFlow = flow.filter(f => f.sentiment === 'BULLISH').length;
                const bearFlow = flow.filter(f => f.sentiment === 'BEARISH').length;
                const topHeat = flow.length > 0 ? Math.max(...flow.map(f => f.unusual_score || 0)) : 0;
                const hasBeast = (this.beastData || []).some(b => b.symbol === sym);
                const gex = this.gex_cache?.[sym];
                const isShortGamma = gex?.profile_shape === 'short_gamma';

                let score = sqzScore;
                if (bullFlow > bearFlow) score += 10;
                if (hasBeast) score += 15;
                if (isShortGamma) score += 10;
                if (topHeat >= 70) score += 10;

                return { sym, sqzScore, score: Math.min(100, score), level: s.squeeze_level, tier: s.tier, bullFlow, bearFlow, topHeat, hasBeast, isShortGamma, flowCount: flow.length };
            })
            .sort((a, b) => b.score - a.score)
            .slice(0, 10);

        if (candidates.length === 0) {
            board.innerHTML = '<div class="loading-msg">NO QUALIFYING SETUPS</div>';
            return;
        }

        board.innerHTML = candidates.map((c, i) => {
            const scoreClr = c.score >= 70 ? 'var(--neon-green)' : c.score >= 45 ? 'var(--neon-blue)' : 'var(--text-dim)';
            const flowIcon = c.bullFlow > c.bearFlow ? '🟢' : c.bearFlow > c.bullFlow ? '🔴' : '⚪';
            
            // Flash logic: Check if score changed
            const prevScore = this.scoreCache[c.sym];
            const hasChanged = prevScore !== undefined && prevScore !== c.score;
            this.scoreCache[c.sym] = c.score;
            const flashClass = hasChanged ? 'action-row-update' : '';

            const badges = [];
            if (c.hasBeast) badges.push('<span style="color:var(--neon-purple);font-size:9px;font-weight:800;">BEAST</span>');
            if (c.isShortGamma) badges.push('<span style="color:var(--neon-orange);font-size:9px;font-weight:800;">⚡Γ</span>');
            if (c.topHeat >= 70) badges.push('<span style="color:var(--neon-red);font-size:9px;font-weight:800;">🔥HOT</span>');

            return `<div class="data-row ${flashClass}" style="cursor:pointer; padding:6px 8px; font-size:11px;" onclick="AnalyticalEngine.selectSymbol('${c.sym}')">
                <div style="display:flex; align-items:center; gap:6px; flex:1;">
                    <span style="color:var(--text-dim); font-size:9px; min-width:14px;">${i+1}.</span>
                    <span style="color:white; font-weight:900; min-width:48px; font-size:12px;">${c.sym}</span>
                    <span style="color:${scoreClr}; font-weight:900; font-size:13px; min-width:28px;">${c.score}</span>
                    <span style="color:var(--text-dim); font-size:10px;">${c.level || ''}${c.tier ? ' ['+c.tier+']' : ''}</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    ${badges.join(' ')}
                    <span style="font-size:10px;">${flowIcon} ${c.flowCount > 0 ? c.flowCount+'f' : ''}</span>
                </div>
            </div>`;
        }).join('');
    },

    // ── LIVE FIREHOSE: Fast-Moving Options Waterfall ──────
    _firehoseBuffer: [],
    _firehoseMax: 150,

    async updateFirehose() {
        try {
            const [flowRes, termRes] = await Promise.all([
                fetch('http://127.0.0.1:8182/api/market/flow'),
                fetch('http://127.0.0.1:8182/api/terminal/feed?limit=30')
            ]);
            const flowData = await flowRes.json();
            const termData = await termRes.json();

            const newEntries = [];
            const now = Date.now() / 1000;

            // Merge flow data into firehose
            if (flowData.status === 'success') {
                (flowData.data || []).forEach(f => {
                    const key = `F_${f.symbol}_${f.strike}_${f.type}_${f.seen_time}`;
                    if (!this._firehoseBuffer.some(e => e.key === key)) {
                        const action = (f.sentiment === 'BULLISH' && f.type === 'CALL') ? 'CALL BUY' :
                            (f.sentiment === 'BEARISH' && f.type === 'PUT') ? 'PUT BUY' :
                            (f.sentiment === 'BEARISH' && f.type === 'CALL') ? 'CALL SELL' : 'PUT SELL';
                        const icon = f.sentiment === 'BULLISH' ? '🟢' : '🔴';
                        newEntries.push({
                            key, ts: f.seen_time || now, type: 'FLOW',
                            html: `<span style="color:var(--text-dim);">${new Date((f.seen_time || now) * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span> ${icon} <span style="color:white;font-weight:900;">${f.symbol}</span> <span style="color:${f.sentiment === 'BULLISH' ? 'var(--neon-green)' : 'var(--neon-red)'};font-weight:800;">${action}</span> $${f.strike} ${f.expiry_formatted || ''} <span style="color:var(--neon-blue);">HEAT:${f.unusual_score || 0}</span> ${f.unusual_score >= 80 ? '🔥🔥' : f.unusual_score >= 60 ? '🔥' : ''}`
                        });
                    }
                });
            }

            // Merge terminal events
            if (termData.status === 'success') {
                (termData.data || []).forEach(t => {
                    const key = `T_${t.type}_${t.ts}`;
                    if (!this._firehoseBuffer.some(e => e.key === key)) {
                        let clr = 'var(--text-dim)';
                        if (t.type === 'FLOW') clr = t.msg.includes('🟢') ? 'var(--neon-green)' : 'var(--neon-red)';
                        else if (t.type === 'BEAST') clr = 'var(--neon-purple)';
                        else if (t.type === 'GAMMA') clr = 'var(--neon-blue)';
                        else if (t.type === 'MOASS') clr = 'var(--neon-pink)';
                        newEntries.push({
                            key, ts: t.ts, type: t.type,
                            html: `<span style="color:var(--text-dim);">${t.time_str}</span> <span style="color:${clr};font-weight:700;">[${t.type}]</span> ${t.msg}`
                        });
                    }
                });
            }

            // Add new entries and trim
            if (newEntries.length > 0) {
                this._firehoseBuffer = [...newEntries, ...this._firehoseBuffer].slice(0, this._firehoseMax);
                this._firehoseBuffer.sort((a, b) => b.ts - a.ts);
                this.renderFirehose();
            }
        } catch (e) {
            console.warn('Firehose update error:', e.message);
        }
    },

    renderFirehose() {
        const list = document.getElementById('firehose-list');
        if (!list) return;

        const countBadge = document.getElementById('firehose-count');
        if (countBadge) countBadge.textContent = `${this._firehoseBuffer.length} FLOWS`;

        if (this._firehoseBuffer.length === 0) {
            list.innerHTML = '';
            return;
        }

        // Render with scroll animation
        const wasAtTop = list.scrollTop < 30;
        list.innerHTML = this._firehoseBuffer.map((entry, i) => {
            const fresh = i < 3 ? ' style="background:rgba(0,255,136,0.03); animation: firehose-flash 0.5s ease-out;"' : '';
            return `<div class="firehose-row"${fresh}>${entry.html}</div>`;
        }).join('');

        if (wasAtTop) list.scrollTop = 0;
    },

    // ── MM INTELLIGENCE PANEL ─────────────────────────────
    renderMMIntelPanel(symbol) {
        const data = this.mmIntelData[symbol];
        if (!data) return '<div style="color:var(--text-muted);padding:10px;">AWAITING MM INTEL...</div>';

        const invCol = data.inv_z > 0.5 ? 'var(--neon-red)' : data.inv_z < -0.5 ? 'var(--neon-green)' : 'var(--neon-yellow)';
        const invDir = data.inv_z > 0.5 ? 'LONG (absorbed selling)' : data.inv_z < -0.5 ? 'SHORT (absorbed buying)' : 'FLAT';
        const sigCol = data.signal === 'LONG' ? 'var(--neon-green)' : data.signal === 'SHORT' ? 'var(--neon-red)' : 'var(--text-muted)';
        const confCol = data.signal_confidence > 80 ? 'var(--neon-green)' : data.signal_confidence > 50 ? 'var(--neon-yellow)' : 'var(--text-muted)';
        const pinTxt = data.strike_pin?.near_strike ? `PINNING $${data.strike_pin.nearest_strike?.toFixed(2)}` : `Near $${data.strike_pin?.nearest_strike?.toFixed(2) || '--'}`;

        return `
            <div style="font-size:12px;">
                <div style="margin-bottom:6px;font-weight:900;color:var(--neon-blue);">MM INTELLIGENCE v3</div>
                <div>Inventory: <span style="color:${invCol};font-weight:700;">${invDir}</span> (${data.inv_z?.toFixed(2) || '--'}σ)</div>
                <div>Flow: <span style="color:var(--neon-blue);">${data.flow_type || '--'}</span> Q:${data.flow_quality?.toFixed(1) || '--'}</div>
                <div>Hedge Rate: <span style="color:var(--neon-cyan);">${data.optimal_hedge_rate?.toFixed(4) || '--'}</span></div>
                <div>Gamma: ${data.gamma_pressure?.toFixed(2) || '--'} | Pin: ${pinTxt}</div>
                <div>Signal: <span style="color:${sigCol};font-weight:900;">${data.signal || 'NONE'}</span> <span style="color:${confCol};">${data.signal_confidence?.toFixed(0) || '--'}%</span></div>
                <div>Target: <span style="color:var(--neon-green);">$${data.tactical_target?.toFixed(2) || '--'}</span> (tactical) | <span style="color:var(--neon-orange);">$${data.structural_target?.toFixed(2) || '--'}</span> (macro)</div>
            </div>
        `;
    },

    // ── LIVE TRADING CONTROLS ─────────────────────────────
    async updateTradingStatus() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/trading/status');
            const data = await r.json();
            if (data.status === 'success') {
                const btn = document.getElementById('trading-mode-btn');
                if (btn) {
                    const live = data.live_mode;
                    btn.textContent = live ? 'LIVE (ARMED)' : 'SHADOW';
                    btn.style.background = live ? 'rgba(255, 20, 147, 0.15)' : 'rgba(0, 163, 255, 0.1)';
                    btn.style.borderColor = live ? 'var(--neon-pink)' : 'var(--neon-blue)';
                    btn.style.color = live ? 'var(--neon-pink)' : 'var(--neon-blue)';
                    
                    // Also update the discovery board badge if it exists
                    const discBadge = document.getElementById('trading-mode-badge');
                    if (discBadge) {
                        discBadge.textContent = live ? 'LIVE TRADING' : 'SHADOW MODE';
                        discBadge.style.background = live ? 'var(--neon-pink)' : 'var(--neon-blue)';
                    }
                }
            }
        } catch (e) {
            console.warn('Trading status sync failure:', e.message);
        }
    },

    async updateBalances() {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/trading/balances');
            const data = await r.json();
            if (data.status === 'success') {
                const b = data.balances;
                const alpacaEq = parseFloat(b.alpaca?.equity || 0);
                const schwabEq = parseFloat(b.schwab?.equity || 0);
                const total = alpacaEq + schwabEq;

                const equityDisplay = document.getElementById('total-equity');
                if (equityDisplay) {
                    equityDisplay.textContent = `$${total.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    equityDisplay.title = `Alpaca: $${alpacaEq.toFixed(2)} | Schwab: $${schwabEq.toFixed(2)}`;
                }
            }
        } catch (e) {
            console.warn('Balance sync failure:', e.message);
        }
    },

    async toggleTradingMode() {
        // Safe check current state
        const btn = document.getElementById('trading-mode-btn');
        const isShadow = btn?.textContent.includes('SHADOW');

        if (isShadow) {
            const confirmed = confirm("🚨 WARNING: ARMING LIVE TRADING 🚨\n\nThis will allow SqueezeOS to place REAL orders using your API keys.\n\nRisk Limits:\n- Max $500 per trade\n- Forced 5% Stop Loss\n\nAre you sure you want to go LIVE?");
            if (confirmed) {
                await this.setTradingMode(true);
            }
        } else {
            await this.setTradingMode(false);
        }
    },

    async setTradingMode(live) {
        try {
            const r = await fetch('http://127.0.0.1:8182/api/trading/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ live: live })
            });
            const data = await r.json();
            if (data.status === 'success') {
                await this.updateTradingStatus();
                console.log(`📡 Trading mode updated: ${live ? 'LIVE' : 'SHADOW'}`);
            }
        } catch (e) {
            alert('Failsafe Triggered: Could not update trading mode.');
        }
    }
};

window.AnalyticalEngine = AnalyticalEngine;
AnalyticalEngine.init();
