/**
 * SQUEEZE OS v4.1 | Settings Panel
 * Schwab API config with real error/success feedback.
 */

const SETTINGS_API_BASE = window.SQUEEZE_OS_CONFIG?.apiBase || 'http://127.0.0.1:8182/api';

const SettingsPanel = {
    init(windowId) {
        const container = document.getElementById(`content-${windowId}`);

        container.innerHTML = `
            <div class="settings-grid">
                <div class="settings-section">
                    <h3>SCHWAB API CONFIG</h3>
                    <p style="font-size:9px; color:var(--neon-blue); margin-bottom:10px; border:1px solid rgba(0,212,255,0.3); padding:8px; border-radius:4px; line-height:1.3; background:rgba(0,212,255,0.03);">
                        💡 <b>CAN'T WAIT FOR PORTAL UPDATES?</b><br>
                        Enter your <i>existing</i> Callback URL from the Schwab Dashboard below. SQUEEZE OS will automatically align to it so you can login NOW without waiting for Schwab to update.
                    </p>
                    <div id="schwab-msg-${windowId}" class="schwab-msg"></div>
                    <div class="input-group">
                        <label>REGISTERED CALLBACK URL (FROM SCHWAB DASHBOARD)</label>
                        <input type="text" id="sk-redirect-${windowId}" placeholder="https://127.0.0.1:8183/" class="hg-input">
                    </div>
                    <div class="divider"></div>
                    <div class="input-group">
                        <label>APP KEY</label>
                        <input type="password" id="sk-key-${windowId}" placeholder="Schwab App Key" class="hg-input">
                    </div>
                    <div class="input-group">
                        <label>APP SECRET</label>
                        <input type="password" id="sk-sec-${windowId}" placeholder="Schwab App Secret" class="hg-input">
                    </div>
                    <button class="save-btn" onclick="SettingsPanel.saveSchwab('${windowId}')">SAVE & AUTHENTICATE</button>

                    <div class="input-group" style="margin-top:15px; border-top:1px solid rgba(255,255,255,0.05); padding-top:15px;">
                        <label>STEP 2: PASTE REDIRECT URL AFTER SCHWAB LOGIN</label>
                        <input type="text" id="sk-code-${windowId}" placeholder="Paste the https://127.0.0.1:8183/?code=... URL here" class="hg-input">
                        <button class="save-btn" style="background:var(--neon-purple,#a855f7);" onclick="SettingsPanel.authenticateManual('${windowId}')">EXCHANGE CODE</button>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>INSTITUTIONAL BACKUPS</h3>
                    <div class="input-group">
                        <label>ALPACA API KEY</label>
                        <input type="password" id="sk-alpaca-key-${windowId}" placeholder="Alpaca Key" class="hg-input">
                    </div>
                    <div class="input-group">
                        <label>ALPACA SECRET</label>
                        <input type="password" id="sk-alpaca-sec-${windowId}" placeholder="Alpaca Secret" class="hg-input">
                    </div>
                    <div class="divider"></div>
                    <div class="input-group">
                        <label>POLYGON API KEY</label>
                        <input type="password" id="sk-poly-key-${windowId}" placeholder="Polygon Key" class="hg-input">
                    </div>
                    <div class="input-group">
                        <label>ALPHA VANTAGE KEY</label>
                        <input type="password" id="sk-av-key-${windowId}" placeholder="Alpha Vantage Key" class="hg-input">
                    </div>
                    <button class="save-btn" style="background:var(--neon-purple,#a855f7);" onclick="SettingsPanel.saveBackups('${windowId}')">SAVE BACKUP KEYS</button>
                </div>

                <div class="settings-section">
                    <h3>DISCORD SIGNALS</h3>

                    <div class="input-group">
                        <label>MAIN WEBHOOK (Squeeze + System)</label>
                        <input type="text" id="discord-wh-${windowId}" placeholder="https://discord.com/api/webhooks/..." class="hg-input">
                    </div>
                    <div class="input-group">
                        <label>FLOW WEBHOOK (Whale Flow + Sweeps)</label>
                        <input type="text" id="discord-flow-wh-${windowId}" placeholder="https://discord.com/api/webhooks/..." class="hg-input">
                    </div>
                    <div style="display:flex; gap:10px;">
                        <button class="save-btn" style="flex:2; background:var(--neon-green,#22c55e);color:black;" onclick="SettingsPanel.saveDiscord('${windowId}')">SAVE WEBHOOKS</button>
                        <button class="save-btn" style="flex:1; background:#475569; color:white;" onclick="SettingsPanel.testDiscord('${windowId}')">TEST</button>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>SYSTEM CONNECTION</h3>
                    <div class="input-group">
                        <label>HTTP BACKEND: <span class="neon-blue" id="backend-url-display">https://127.0.0.1:8182</span></label>
                        <p style="font-size:9px; color:var(--text-dim); margin-bottom:10px;">Backend connection is active. No manual SSL whitelisting required.</p>
                    </div>
                </div>

                <div class="settings-footer">
                    <span>SQUEEZE OS v4.1-BEAST</span>
                    <span class="neon-green">ARCANE MONITOR ACTIVE</span>
                </div>
            </div>
        `;

        this.setupStyles();
        this.loadSaved(windowId);
    },

    async loadSaved(windowId) {
        // 1. Try Local Storage first
        const saved = localStorage.getItem('schwab_keys');
        if (saved) {
            try {
                const d = JSON.parse(saved);
                document.getElementById(`sk-key-${windowId}`).value = d.apiKey || 'cOb3GLiEmhfxGyfWUSDvaqqYayNUTVuCexRlzRbSumWvz5I6';
                document.getElementById(`sk-sec-${windowId}`).value = d.apiSecret || 'Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I';
                document.getElementById(`sk-redirect-${windowId}`).value = d.redirectUri || 'https://127.0.0.1:8182/callback';
            } catch (e) { }
        } else {
            document.getElementById(`sk-key-${windowId}`).value = 'cOb3GLiEmhfxGyfWUSDvaqqYayNUTVuCexRlzRbSumWvz5I6';
            document.getElementById(`sk-sec-${windowId}`).value = 'Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I';
            document.getElementById(`sk-redirect-${windowId}`).value = 'https://127.0.0.1:8182/callback';
        }

        // 2. Fetch Institutional Defaults from Server
        try {
            const r = await fetch(`${SETTINGS_API_BASE}/settings`);
            const data = await r.json();

            // Schwab Keys (Hardcoded fallbacks already set, but server overrides if present)
            if (data.schwabKey) document.getElementById(`sk-key-${windowId}`).value = data.schwabKey;
            if (data.schwabSecret) document.getElementById(`sk-sec-${windowId}`).value = data.schwabSecret;

            // Backup Keys
            document.getElementById(`sk-alpaca-key-${windowId}`).value = data.alpacaKey || 'AKV39V1APUHWMFCQ2GA0';
            document.getElementById(`sk-alpaca-sec-${windowId}`).value = data.alpacaSecret || 'edlztEfaib5gGj0hQbfoV4Ezm6vdy8FnuFfW9Mx9';
            if (data.polyKey) document.getElementById(`sk-poly-key-${windowId}`).value = data.polyKey;
            if (data.avKey) document.getElementById(`sk-av-key-${windowId}`).value = data.avKey;

            // Discord Webhooks
            if (data.webhook) document.getElementById(`discord-wh-${windowId}`).value = data.webhook;
            if (data.flow_webhook) document.getElementById(`discord-flow-wh-${windowId}`).value = data.flow_webhook;

            this.showMsg(windowId, '🏢 Institutional parameters synchronized from backend', 'success');
        } catch (e) {
            console.warn('[Settings] Could not fetch server defaults');
        }

        const backups = localStorage.getItem('backup_keys');
        if (backups) {
            try {
                const b = JSON.parse(backups);
                if (b.alpacaKey) document.getElementById(`sk-alpaca-key-${windowId}`).value = b.alpacaKey;
                if (b.alpacaSecret) document.getElementById(`sk-alpaca-sec-${windowId}`).value = b.alpacaSecret;
                if (b.polyKey) document.getElementById(`sk-poly-key-${windowId}`).value = b.polyKey;
                if (b.avKey) document.getElementById(`sk-av-key-${windowId}`).value = b.avKey;
            } catch (e) { }
        }

        const hooks = localStorage.getItem('discord_webhook');
        if (hooks) document.getElementById(`discord-wh-${windowId}`).value = hooks;
        const flowHooks = localStorage.getItem('discord_flow_webhook');
        if (flowHooks) document.getElementById(`discord-flow-wh-${windowId}`).value = flowHooks;
    },

    showMsg(windowId, text, type) {
        const el = document.getElementById(`schwab-msg-${windowId}`);
        if (!el) return;
        el.textContent = text;
        el.className = 'schwab-msg ' + (type || 'info');
        el.style.display = 'block';
    },

    async saveSchwab(windowId) {
        const btn = event.target;
        const oldText = btn.textContent;
        btn.textContent = '⏳ SAVING...';
        btn.disabled = true;

        const key = document.getElementById(`sk-key-${windowId}`).value.trim() || 'cOb3GLiEmhfxGyfWUSDvaqqYayNUTVuCexRlzRbSumWvz5I6';
        const secret = document.getElementById(`sk-sec-${windowId}`).value.trim() || 'Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I';
        const redir = document.getElementById(`sk-redirect-${windowId}`).value.trim() || 'https://127.0.0.1:8182/callback';

        localStorage.setItem('schwab_keys', JSON.stringify({ apiKey: key, apiSecret: secret, redirectUri: redir }));
        this.showMsg(windowId, '⏳ Keys saved. Requesting auth URL from server...', 'info');

        if (window.SchwabIntegration) {
            window.SchwabIntegration.apiKey = key;
            window.SchwabIntegration.apiSecret = secret;
        }

        // PERSIST TO SERVER
        try {
            await fetch(`${SETTINGS_API_BASE}/settings/schwab`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, secret })
            });
        } catch (e) {
            console.error('[Settings] Persistent save failed:', e);
        }

        try {
            const url = new URL(`${SETTINGS_API_BASE}/auth/url`);
            url.searchParams.append('client_id', key);
            url.searchParams.append('client_secret', secret);
            url.searchParams.append('redirect_uri', redir);

            const r = await fetch(url);
            const data = await r.json();

            if (data.status === 'success' && data.url) {
                this.showMsg(windowId, '✅ Auth URL received — opening Schwab login...', 'success');
                const popup = window.open(data.url, 'SchwabAuth', 'width=600,height=700,scrollbars=yes');
                if (!popup || popup.closed) {
                    this.showMsg(windowId, '⚠️ POPUP BLOCKED! You MUST allow popups for 127.0.0.1 or copy/paste this URL manually: ' + data.url, 'error');
                } else {
                    this.showMsg(windowId, '✅ Schwab login window opened. AFTER LOGIN: Copy the entire URL of the page you land on and paste it into STEP 2 below.', 'success');
                }
            } else {
                this.showMsg(windowId, '❌ ' + (data.message || 'Server could not create auth URL. Check API key validity.'), 'error');
            }
        } catch (e) {
            this.showMsg(windowId, '❌ Cannot reach backend. Is server.py running?', 'error');
        } finally {
            btn.textContent = oldText;
            btn.disabled = false;
        }
    },

    async authenticateManual(windowId) {
        const input = document.getElementById(`sk-code-${windowId}`).value.trim();
        if (!input) {
            this.showMsg(windowId, '❌ Paste the redirect URL or auth code first!', 'error');
            return;
        }

        let code = input;
        if (input.includes('code=')) {
            try {
                const url = new URL(input);
                code = url.searchParams.get('code');
            } catch (e) {
                const params = new URLSearchParams(input.split('?')[1] || input);
                code = params.get('code') || input;
            }
        }

        if (!code) {
            this.showMsg(windowId, '❌ Could not extract auth code from that URL', 'error');
            return;
        }

        this.showMsg(windowId, '⏳ Exchanging code for access tokens...', 'info');

        const saved = JSON.parse(localStorage.getItem('schwab_keys') || '{}');

        try {
            const r = await fetch(`${SETTINGS_API_BASE}/auth/exchange`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code: code,
                    client_id: saved.apiKey,
                    client_secret: saved.apiSecret,
                    redirect_uri: saved.redirectUri || 'https://127.0.0.1:8182/callback'
                })
            });
            const data = await r.json();

            if (data.status === 'success') {
                this.showMsg(windowId, '✅ SCHWAB AUTHENTICATED! Real-time quotes + options chains NOW ACTIVE. Restart server for full effect.', 'success');
                if (window.SchwabIntegration) {
                    window.SchwabIntegration.status = 'ONLINE';
                    window.SchwabIntegration.updateStatus();
                }
            } else {
                this.showMsg(windowId, `❌ ${data.message || 'Token exchange failed. The auth code may have expired or the Redirect URI is mismatched.'}`, 'error');
            }
        } catch (e) {
            this.showMsg(windowId, '❌ Cannot reach backend. Is server.py running?', 'error');
        }
    },

    async saveBackups(windowId) {
        const alpKey = document.getElementById(`sk-alpaca-key-${windowId}`).value.trim();
        const alpSec = document.getElementById(`sk-alpaca-sec-${windowId}`).value.trim();
        const polyKey = document.getElementById(`sk-poly-key-${windowId}`).value.trim();
        const avKey = document.getElementById(`sk-av-key-${windowId}`).value.trim();

        const backupKeys = { alpacaKey: alpKey, alpacaSecret: alpSec, polyKey: polyKey, avKey: avKey };
        localStorage.setItem('backup_keys', JSON.stringify(backupKeys));

        this.showMsg(windowId, '⏳ Saving backup keys to backend...', 'info');

        try {
            const r = await fetch(`${SETTINGS_API_BASE}/settings/backups`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(backupKeys)
            });
            const data = await r.json();
            if (data.status === 'success') {
                this.showMsg(windowId, '✅ Backup keys saved and active', 'success');
            } else {
                this.showMsg(windowId, '❌ Server failed to save backup keys', 'error');
            }
        } catch (e) {
            this.showMsg(windowId, '❌ Cannot reach backend at 127.0.0.1:8182 to save backups', 'error');
        }
    },

    async saveDiscord(windowId) {
        const wh = document.getElementById(`discord-wh-${windowId}`).value.trim();
        const flowWh = document.getElementById(`discord-flow-wh-${windowId}`).value.trim();
        if (!wh) {
            this.showMsg(windowId, '❌ Enter a main webhook URL', 'error');
            return;
        }
        this.showMsg(windowId, '⏳ Syncing webhooks...', 'info');
        try {
            const r = await fetch(`${SETTINGS_API_BASE}/settings/discord`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ webhook: wh, flow_webhook: flowWh })
            });
            const data = await r.json();
            if (data.status === 'success') {
                localStorage.setItem('discord_webhook', wh);
                if (flowWh) localStorage.setItem('discord_flow_webhook', flowWh);
                this.showMsg(windowId, '✅ Discord targets synchronized!', 'success');
            } else {
                this.showMsg(windowId, '❌ Save failed: ' + data.message, 'error');
            }
        } catch (e) {
            this.showMsg(windowId, '❌ Cannot reach backend at 127.0.0.1:8182 to save webhook', 'error');
        }
    },

    async testDiscord(windowId) {
        const wh = document.getElementById(`discord-wh-${windowId}`).value.trim();
        const flowWh = document.getElementById(`discord-flow-wh-${windowId}`).value.trim();
        if (!wh) {
            this.showMsg(windowId, '❌ Enter a webhook URL first', 'error');
            return;
        }
        this.showMsg(windowId, '⏳ Sending test alert...', 'info');
        try {
            const r = await fetch(`${SETTINGS_API_BASE}/settings/discord`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ webhook: wh, flow_webhook: flowWh, test: true })
            });
            const data = await r.json();
            if (data.status === 'success') {
                this.showMsg(windowId, '✅ TEST SENT! Check your Discord channel.', 'success');
            } else {
                this.showMsg(windowId, '❌ Test failed: ' + data.message, 'error');
            }
        } catch (e) {
            this.showMsg(windowId, '❌ Backend unreachable', 'error');
        }
    },

    setupStyles() {
        if (document.getElementById('settings-styles')) return;
        const style = document.createElement('style');
        style.id = 'settings-styles';
        style.textContent = `
            .settings-grid { display:flex; flex-direction:column; gap:20px; }
            .settings-section { border:1px solid rgba(255,255,255,0.05); padding:15px; border-radius:8px; background:rgba(255,255,255,0.01); }
            .settings-section h3 { font-size:10px; color:#64748b; margin-bottom:12px; letter-spacing:2px; }
            .input-group { margin-bottom:10px; }
            .input-group label { display:block; font-size:9px; color:#475569; margin-bottom:4px; font-weight:700; }
            .divider { height:1px; background:rgba(255,255,255,0.05); margin:15px 0; }
            .save-btn { width:100%; background:var(--neon-blue); color:black; border:none; padding:10px; border-radius:4px; font-weight:800; font-size:11px; cursor:pointer; margin-top:10px; transition:opacity 0.2s; }
            .save-btn:hover { opacity:0.85; }
            .toggle-group { display:flex; justify-content:space-between; align-items:center; font-size:11px; margin-bottom:8px; color:var(--text-dim); }
            .settings-footer { display:flex; justify-content:space-between; font-size:8px; color:#334155; border-top:1px solid rgba(255,255,255,0.05); padding-top:10px; }

            .schwab-msg { display:none; padding:8px 10px; border-radius:4px; font-size:10px; font-family:var(--font-mono,monospace); margin-bottom:10px; word-break:break-all; line-height:1.5; }
            .schwab-msg.info { display:block; background:rgba(0,150,255,0.1); border:1px solid rgba(0,150,255,0.3); color:#60a5fa; }
            .schwab-msg.success { display:block; background:rgba(0,255,100,0.1); border:1px solid rgba(0,255,100,0.3); color:#4ade80; }
            .schwab-msg.error { display:block; background:rgba(255,50,50,0.1); border:1px solid rgba(255,50,50,0.3); color:#f87171; }
        `;
        document.head.appendChild(style);
    }
};

window.SettingsPanel = SettingsPanel;
