/**
 * SQUEEZE OS v4 | Unusual Options Flow Component
 * Institutional tracking of large options orders with Live Backend.
 */

const FLOW_API_BASE = window.SQUEEZE_OS_CONFIG?.apiBase || 'http://127.0.0.1:8182/api';

const OptionsFlow = {
    baseUrl: FLOW_API_BASE,

    init(windowId) {
        console.log(`🔥 Initializing Options Flow in window ${windowId}`);
        const container = document.getElementById(`content-${windowId}`);

        container.innerHTML = `
            <div class="flow-container">
                <div class="flow-header">
                    <div class="flow-stat">BULLISH: <span class="neon-green" id="bull-pct-${windowId}">--%</span></div>
                    <div class="flow-stat">BEARISH: <span class="neon-red" id="bear-pct-${windowId}">--%</span></div>
                    <div class="flow-stat">ALERTS: <span class="neon-blue" id="alert-count-${windowId}">0</span></div>
                </div>
                <div class="flow-table-wrapper">
                    <table class="flow-table">
                        <thead>
                            <tr>
                                <th>EXP</th>
                                <th>SYMBOL</th>
                                <th>STRIKE</th>
                                <th>TYPE</th>
                                <th>VOL/OI</th>
                                <th>PRICE</th>
                                <th>SIG</th>
                            </tr>
                        </thead>
                        <tbody id="flow-body-${windowId}">
                            <!-- Flow data injected here -->
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        this.setupStyles();
        this.startStream(windowId);
    },

    async startStream(windowId) {
        const performScan = async () => {
            try {
                const r = await fetch(`${this.baseUrl}/market/flow`);
                const data = await r.json();
                if (data.status === 'success') {
                    this.renderFlow(windowId, data.data);
                }
            } catch (e) {
                console.error('Options flow fetch failed:', e);
            }
        };

        performScan();
        setInterval(performScan, 60000); // Options flow scan every minute
    },

    renderFlow(windowId, alerts) {
        if (!window.seenOptionsCache) window.seenOptionsCache = new Set();

        const body = document.getElementById(`flow-body-${windowId}`);
        if (!body) return;

        // Calculate sentiment
        const calls = alerts.filter(a => a.type === 'CALL').length;
        const puts = alerts.filter(a => a.type === 'PUT').length;
        const total = calls + puts || 1;

        document.getElementById(`bull-pct-${windowId}`).textContent = `${Math.round((calls / total) * 100)}%`;
        document.getElementById(`bear-pct-${windowId}`).textContent = `${Math.round((puts / total) * 100)}%`;
        document.getElementById(`alert-count-${windowId}`).textContent = alerts.length;

        body.innerHTML = alerts.map(f => {
            const score = f.unusual_score || 0;
            const priority = score >= 70 ? 'EXTREME' : score >= 50 ? 'HIGH' : score >= 30 ? 'MODERATE' : 'LOW';

            const key = f.symbol + f.strike + f.expiry_formatted + f.type;
            const isNew = !window.seenOptionsCache.has(key);
            window.seenOptionsCache.add(key);

            return `
                <tr class="${(f.type || 'call').toLowerCase()} ${isNew ? 'anim-new-row' : ''}">
                    <td>${f.expiry_formatted || f.expiry || '—'}</td>
                    <td class="bold">${f.symbol}</td>
                    <td>$${f.strike || 0}</td>
                    <td class="type-cell">${f.sweep_label || f.type || '—'}</td>
                    <td class="neon-blue">${(f.vol_oi_ratio || 0).toFixed(1)}x</td>
                    <td>$${(f.price || 0).toFixed(2)}</td>
                    <td><span class="sig-badge ${priority === 'EXTREME' ? 'extreme' : ''}">${priority}</span></td>
                </tr>
            `;
        }).join('');
    },

    setupStyles() {
        if (document.getElementById('flow-styles')) return;
        const style = document.createElement('style');
        style.id = 'flow-styles';
        style.textContent = `
            .flow-container { display: flex; flex-direction: column; height: 100%; gap: 10px; }
            .flow-header { display: flex; gap: 20px; font-size: 10px; font-weight: 800; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 10px; }
            .flow-table-wrapper { flex: 1; overflow: auto; }
            .flow-table { width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono'; font-size: 11px; }
            .flow-table th { text-align: left; padding: 10px; color: #64748b; font-size: 9px; border-bottom: 1px solid rgba(255,255,255,0.05); }
            .flow-table td { padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.02); }
            
            .flow-table tr.call { background: rgba(0, 255, 136, 0.02); }
            .flow-table tr.put { background: rgba(255, 71, 87, 0.02); }
            .flow-table tr.call .type-cell { color: var(--neon-green); font-weight: 800; }
            .flow-table tr.put .type-cell { color: var(--neon-red); font-weight: 800; }
            
            .bold { font-weight: 800; color: white; }
            .sig-badge { font-size: 8px; font-weight: 900; padding: 2px 4px; border: 1px solid rgba(255,255,255,0.1); border-radius: 3px; color: var(--text-dim); }
            .sig-badge.extreme { background: var(--neon-red); color: white; border-color: transparent; box-shadow: 0 0 5px var(--neon-red); }
        `;
        document.head.appendChild(style);
    }
};

window.OptionsFlow = OptionsFlow;
