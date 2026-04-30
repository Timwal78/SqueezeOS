/**
 * SQUEEZE OS v4.1 | Schwab API Integration
 * Handles auth state tracking and status display.
 * Auth flow is now driven from Settings panel.
 */

const SCHWAB_API_BASE = window.SQUEEZE_OS_CONFIG?.apiBase || 'http://127.0.0.1:8182/api';

const SchwabIntegration = {
    apiKey: '',
    apiSecret: '',
    status: 'OFFLINE',
    baseUrl: SCHWAB_API_BASE,

    init() {
        this.loadKeys();
        this.registerAuthBridge();
        this.checkBackendStatus();
        setInterval(() => this.checkBackendStatus(), 30000);
    },

    loadKeys() {
        const saved = localStorage.getItem('schwab_keys');
        if (saved) {
            try {
                const data = JSON.parse(saved);
                this.apiKey = data.apiKey || 'cOb3GLiEmhfxGyfWUSDvaqqYayNUTVuCexRlzRbSumWvz5I6';
                this.apiSecret = data.apiSecret || 'Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I';
                this.redirectUri = data.redirectUri || 'https://127.0.0.1:8182/callback';
            } catch (e) { }
        } else {
            this.apiKey = 'cOb3GLiEmhfxGyfWUSDvaqqYayNUTVuCexRlzRbSumWvz5I6';
            this.apiSecret = 'Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I';
            this.redirectUri = 'https://127.0.0.1:8182/callback';
        }
    },

    async checkBackendStatus() {
        const start = Date.now();
        try {
            const url = new URL(`${this.baseUrl}/auth/status`);
            if (this.apiKey) {
                url.searchParams.append('client_id', this.apiKey);
                url.searchParams.append('client_secret', this.apiSecret);
            }
            const r = await fetch(url);
            const data = await r.json();

            const latency = Date.now() - start;
            this.updateLatency(latency);

            // Sync with server.py status response
            if (data.status === 'ONLINE') {
                this.status = 'ONLINE';
            } else if (this.apiKey) {
                this.status = 'AUTH_REQUIRED';
            } else {
                this.status = 'OFFLINE';
            }

            // Update Backend Indicator (if it exists)
            const backendEl = document.getElementById('backend-status');
            if (backendEl) {
                backendEl.textContent = 'ONLINE';
                backendEl.className = 'status-indicator online';
            }
        } catch (e) {
            this.status = 'OFFLINE';
            const backendEl = document.getElementById('backend-status');
            if (backendEl) {
                backendEl.textContent = 'OFFLINE';
                backendEl.className = 'status-indicator offline';
            }
        }
        this.updateStatus();
    },

    updateStatus() {
        const statusEl = document.getElementById('schwab-status');
        if (statusEl) {
            statusEl.textContent = this.status;
            statusEl.className = `status-indicator ${this.status.toLowerCase()}`;
        }

        const statusBox = document.querySelector('.stat-item .value');
        if (statusBox) {
            statusBox.textContent = this.status;
            statusBox.style.color = this.status === 'ONLINE' ? '#22c55e' : this.status === 'AUTH_REQUIRED' ? '#f59e0b' : '#64748b';
        }
    },

    updateLatency(ms) {
        const latencyEl = document.getElementById('latency-val');
        if (latencyEl) {
            latencyEl.textContent = `${ms}ms`;
            latencyEl.style.color = ms < 200 ? '#22c55e' : (ms < 500 ? '#f59e0b' : '#ef4444');
        }
    },

    async getAuthUrl() {
        if (!this.apiKey || !this.apiSecret) {
            console.warn('[Schwab] No keys — open Settings to configure');
            return;
        }
        try {
            const url = new URL(`${this.baseUrl}/auth/url`);
            url.searchParams.append('client_id', this.apiKey);
            url.searchParams.append('client_secret', this.apiSecret);
            url.searchParams.append('redirect_uri', this.redirectUri || 'http://localhost:8182/callback');

            const r = await fetch(url);
            const data = await r.json();
            if (data.status === 'success' && data.url) {
                const popup = window.open(data.url, 'SchwabAuth', 'width=600,height=700,scrollbars=yes');
                if (!popup || popup.closed) {
                    console.error('[Schwab] Popup blocked — open Settings and use manual auth');
                }
                this.status = 'AUTH_REQUIRED';
                this.updateStatus();
            } else {
                console.error('[Schwab] Auth URL failed:', data.message || 'Unknown error');
            }
        } catch (e) {
            console.error('[Schwab] Backend not responding');
        }
    },

    async exchangeCode(code) {
        this.status = 'CONNECTING';
        this.updateStatus();
        try {
            const r = await fetch(`${this.baseUrl}/auth/exchange`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code,
                    client_id: this.apiKey,
                    client_secret: this.apiSecret,
                    redirect_uri: this.redirectUri || 'http://localhost:8182/callback'
                })
            });
            const data = await r.json();
            if (data.status === 'success') {
                this.status = 'ONLINE';
                this.updateStatus();
                console.log('[Schwab] ✅ Authenticated');
            } else {
                this.status = 'ERROR';
                this.updateStatus();
                console.error('[Schwab] Exchange failed:', data.message);
            }
        } catch (e) {
            this.status = 'ERROR';
            this.updateStatus();
        }
    },

    registerAuthBridge() {
        window.addEventListener('message', async (event) => {
            if (event.data?.type === 'SCHWAB_AUTH_CODE') {
                const code = event.data.code;
                console.log('[Schwab] 🔑 Auth Bridge: Captured code:', code);
                await this.exchangeCode(code);
            }
        });
    },

    async initTokenHub(windowId) {
        const container = document.getElementById(`content-${windowId}`);
        container.innerHTML = `
            <div style="padding:15px; font-family:var(--font-mono); font-size:11px; color:#cbd5e1;">
                <p style="color:var(--neon-blue); font-weight:800; margin-bottom:15px; border-bottom:1px solid rgba(0,212,255,0.2); padding-bottom:10px;">
                    📡 SYSTEM BRIDGE: SCHWAB OAUTH TOKENS
                </p>
                <div id="hub-loader-${windowId}">Fetching active institutional session...</div>
                <div id="hub-content-${windowId}" style="display:none;">
                    <div class="token-group" style="margin-bottom:15px;">
                        <label style="display:block; font-size:9px; color:#64748b; margin-bottom:4px;">ACCESS TOKEN</label>
                        <div style="display:flex; gap:8px;">
                            <input type="password" id="hub-at-${windowId}" readonly style="flex:1; background:rgba(0,0,0,0.4); border:1px solid rgba(255,255,255,0.1); color:#fff; padding:6px; border-radius:3px; font-size:10px;">
                            <button onclick="SchwabIntegration.copyToClipboard('hub-at-${windowId}')" style="background:rgba(0,163,255,0.2); border:1px solid var(--neon-blue); color:var(--neon-blue); padding:4px 8px; border-radius:3px; cursor:pointer; font-size:10px; font-weight:800;">COPY</button>
                        </div>
                    </div>
                    <div class="token-group" style="margin-bottom:15px;">
                        <label style="display:block; font-size:9px; color:#64748b; margin-bottom:4px;">REFRESH TOKEN</label>
                        <div style="display:flex; gap:8px;">
                            <input type="password" id="hub-rt-${windowId}" readonly style="flex:1; background:rgba(0,0,0,0.4); border:1px solid rgba(255,255,255,0.1); color:#fff; padding:6px; border-radius:3px; font-size:10px;">
                            <button onclick="SchwabIntegration.copyToClipboard('hub-rt-${windowId}')" style="background:rgba(0,163,255,0.2); border:1px solid var(--neon-blue); color:var(--neon-blue); padding:4px 8px; border-radius:3px; cursor:pointer; font-size:10px; font-weight:800;">COPY</button>
                        </div>
                    </div>
                    <div id="hub-status-${windowId}" style="font-size:10px; color:var(--neon-green);">
                        Session active. Refresh managed by SqueezeOS.
                    </div>
                </div>
            </div>
        `;

        try {
            const r = await fetch(`${this.baseUrl}/auth/tokens`);
            const data = await r.json();
            if (data.status === 'success') {
                document.getElementById(`hub-loader-${windowId}`).style.display = 'none';
                document.getElementById(`hub-content-${windowId}`).style.display = 'block';
                document.getElementById(`hub-at-${windowId}`).value = data.access_token || 'MISSING';
                document.getElementById(`hub-rt-${windowId}`).value = data.refresh_token || 'MISSING';
                
                const expires = new Date(data.expires_at * 1000);
                document.getElementById(`hub-status-${windowId}`).textContent = `Session active. Token expires at: ${expires.toLocaleTimeString()}`;
            } else {
                document.getElementById(`hub-loader-${windowId}`).textContent = '🛑 No active session found. Authenticate in Settings.';
                document.getElementById(`hub-loader-${windowId}`).style.color = '#f87171';
            }
        } catch (e) {
            document.getElementById(`hub-loader-${windowId}`).textContent = '🛑 Backend unreachable.';
        }
    },

    copyToClipboard(elementId) {
        const el = document.getElementById(elementId);
        el.type = 'text';
        el.select();
        document.execCommand('copy');
        el.type = 'password';
        
        const btn = event.target;
        const oldText = btn.textContent;
        btn.textContent = 'COPIED!';
        btn.style.background = 'var(--neon-green)';
        btn.style.color = 'black';
        setTimeout(() => {
            btn.textContent = oldText;
            btn.style.background = '';
            btn.style.color = '';
        }, 1500);
    }
};

window.SchwabIntegration = SchwabIntegration;
SchwabIntegration.init();

document.addEventListener('DOMContentLoaded', () => {
    const statusBox = document.querySelector('.stat-item');
    if (statusBox) {
        statusBox.style.cursor = 'pointer';
        statusBox.onclick = () => SchwabIntegration.getAuthUrl();
    }
});
