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
        this.checkBackendStatus();
        setInterval(() => this.checkBackendStatus(), 30000);
    },

    loadKeys() {
        const saved = localStorage.getItem('schwab_keys');
        if (saved) {
            try {
                const data = JSON.parse(saved);
                this.apiKey = data.apiKey || '';
                this.apiSecret = data.apiSecret || '';
                this.redirectUri = data.redirectUri || 'https://127.0.0.1:8183/';
            } catch (e) { }
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
            url.searchParams.append('redirect_uri', this.redirectUri || 'https://127.0.0.1:8183/');

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
                    redirect_uri: this.redirectUri || 'https://127.0.0.1:8183/'
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
