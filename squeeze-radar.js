/**
 * SQUEEZE OS v4 | Squeeze Radar Pro Component
 * Institutional scanning engine with Live Backend Link.
 */

const API_BASE = window.SQUEEZE_OS_CONFIG?.apiBase || 'http://127.0.0.1:8182/api';

const SqueezeRadar = {
    baseUrl: API_BASE,

    init(windowId) {
        console.log(`📡 Initializing Squeeze Radar in window ${windowId}`);
        const container = document.getElementById(`content-${windowId}`);

        container.innerHTML = `
            <div class="radar-container">
                <div class="radar-header">
                    <div class="scan-status" id="scan-status-${windowId}">SCANNING: <span class="neon-green">ACTIVE</span></div>
                    <div class="scan-mode">MODE: <span class="neon-blue">INSTITUTIONAL</span></div>
                </div>
                <div class="radar-list" id="radar-list-${windowId}">
                    <div class="radar-item header">
                        <span>SYMBOL</span>
                        <span>SCORE</span>
                        <span>SIGNAL</span>
                    </div>
                </div>
            </div>
        `;

        this.setupStyles();
        this.startScanning(windowId);
    },

    async startScanning(windowId) {
        const listEl = document.getElementById(`radar-list-${windowId}`);
        if (!listEl) return;

        const performScan = async () => {
            try {
                const r = await fetch(`${this.baseUrl}/market/scan`);
                const data = await r.json();
                if (data.status === 'success') {
                    this.renderItems(windowId, data.data);
                }
            } catch (e) {
                console.error('Radar scan failed:', e);
                const statusEl = document.getElementById(`scan-status-${windowId}`);
                if (statusEl) statusEl.innerHTML = 'SCANNING: <span class="neon-red">ERROR</span>';
            }
        };

        performScan();
        setInterval(performScan, 30000); // Scan every 30s for institutional density
    },

    renderItems(windowId, items) {
        const listEl = document.getElementById(`radar-list-${windowId}`);
        if (!listEl) return;

        let html = `
            <div class="radar-item header">
                <span>SYMBOL</span>
                <span>SCORE</span>
                <span>SIGNAL</span>
            </div>
        `;

        items.forEach(item => {
            const score = item.squeeze_score || 0;
            const signal = item.squeeze_level || 'NONE';
            const signalClass = signal.toLowerCase();
            html += `
                <div class="radar-item" onclick="if(window.AnalyticalEngine) AnalyticalEngine.selectSymbol('${item.symbol}')">
                    <span class="r-symbol">${item.symbol}</span>
                    <span class="r-score">${score}</span>
                    <span class="r-signal sig-${signalClass}">${signal}</span>
                </div>
            `;
        });
        listEl.innerHTML = html;
    },

    setupStyles() {
        if (document.getElementById('radar-styles')) return;
        const style = document.createElement('style');
        style.id = 'radar-styles';
        style.textContent = `
            .radar-container { display: flex; flex-direction: column; height: 100%; }
            .radar-header { display: flex; justify-content: space-between; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); margin-bottom: 10px; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
            .radar-list { display: flex; flex-direction: column; gap: 5px; }
            .radar-item { display: grid; grid-template-columns: 2fr 1fr 2fr; padding: 10px; background: rgba(255,255,255,0.02); border-radius: 4px; font-family: 'JetBrains Mono'; font-size: 11px; align-items: center; border: 1px solid transparent; transition: all 0.2s; }
            .radar-item.header { background: transparent; color: #64748b; font-size: 9px; font-weight: 800; border: none; padding-top: 5px; }
            .radar-item:not(.header):hover { background: rgba(0, 212, 255, 0.05); border-color: rgba(0, 212, 255, 0.2); cursor: pointer; }
            
            .r-symbol { color: white; font-weight: 700; }
            .r-score { color: var(--neon-blue); }
            .r-signal { font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 3px; text-align: center; }
            
            .sig-extreme { background: var(--neon-red); color: white; box-shadow: 0 0 10px var(--neon-red); }
            .sig-high { background: var(--neon-orange); color: white; }
            .sig-moderate { background: var(--neon-blue); color: black; }
            .sig-low { background: #334155; color: #94a3b8; }
            
            .neon-red { color: var(--neon-red); }
        `;
        document.head.appendChild(style);
    }
};

window.SqueezeRadar = SqueezeRadar;
