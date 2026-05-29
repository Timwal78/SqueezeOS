/**
 * SML BATTLE COMPUTER & MMLE MODULE — SqueezeOS Pro
 * Pairs institutional resonance metrics with market maker footprint data.
 */
const LeftWingModule = (() => {
    let _pollTimer = null;

    function init() {
        console.log('[BATTLE-COMPUTER] Initializing Resonance Monitor...');
        refresh();
        _pollTimer = setInterval(refresh, 2000); // 2s poll for real-time battle state
    }

    async function refresh() {
        try {
            // 1. Fetch Battle Summary (Resonance Engine)
            const battleRes = await fetch('/api/battle/summary');
            const battleJson = await battleRes.json();
            
            // 2. Fetch MMLE (Beast Mode) for active symbol
            const activeSym = (window.AnalyticalEngine && window.AnalyticalEngine.activeSymbol) || 'AMC';
            const mmleRes = await fetch(`/api/mmle/${activeSym}`);
            const mmleJson = await mmleRes.json();

            updateUI(battleJson, mmleJson, activeSym);
        } catch (e) {
            console.error('[BATTLE] Sync failed:', e);
            updateStatusDot('offline');
        }
    }

    function updateUI(battle, mmle, symbol) {
        // Find relevant battle data for the symbol or basket
        let battleData = null;
        if (symbol === 'GME') battleData = battle.gme;
        else if (symbol === 'AMC') battleData = battle.amc;
        else battleData = battle.basket;

        if (!battleData) return;

        // ── 1. BATTLE STATE HUD ──────────────────────────────────
        const scoreEl = document.getElementById('battle-score');
        const stateEl = document.getElementById('battle-state');
        const actionEl = document.getElementById('battle-action');
        const containerEl = document.getElementById('battle-state-container');

        if (scoreEl) {
            scoreEl.innerText = battleData.composite_score.toFixed(1);
            const clr = battleData.composite_score > 50 ? 'var(--neon-green)' : 
                        battleData.composite_score > 0 ? 'var(--neon-blue)' : 'var(--neon-red)';
            scoreEl.style.color = clr;
            if (containerEl) {
                containerEl.style.borderColor = clr + '44';
                containerEl.style.boxShadow = `inset 0 0 10px ${clr}11`;
            }
        }
        if (stateEl) {
            stateEl.innerText = battleData.battle_state.toUpperCase();
            stateEl.style.color = battleData.resonance > 0.7 ? 'var(--neon-pink)' : '#fff';
        }
        if (actionEl) {
            actionEl.innerText = battleData.resonance > 0.8 ? '🔥 MAXIMUM RESONANCE' : 
                                battleData.resonance > 0.5 ? '⚡ SIGNAL STRENGTHENING' : '📡 MONITORING CYCLES';
        }

        // ── 2. MMLE PAIRED METRICS ──────────────────────────────
        const tntEl = document.getElementById('mmle-tnt');
        const vpinEl = document.getElementById('mmle-vpin');
        const axisEl = document.getElementById('mmle-axis');
        const peakEl = document.getElementById('battle-peak');

        if (mmle && mmle.status === 'success') {
            const m = mmle;
            if (tntEl) {
                tntEl.innerText = m.state || '--';
                tntEl.style.color = (m.state || '').includes('TNT') ? 'var(--neon-red)' : 
                                    (m.state === 'COMPRESSED') ? 'var(--neon-yellow)' : 'var(--neon-blue)';
            }
            if (vpinEl) {
                const z = m.vpin_z || 0;
                vpinEl.innerText = z.toFixed(2) + ' σ';
                vpinEl.style.color = z > 1.5 ? 'var(--neon-red)' : 'var(--neon-pink)';
            }
            if (axisEl) {
                const axes = m.active_axes || 0;
                axisEl.innerText = m.axis_collapse ? `COLLAPSE (${axes})` : `STABLE (${axes})`;
                axisEl.style.color = m.axis_collapse ? 'var(--neon-amber)' : 'var(--text-dim)';
            }
            
            const cWall = document.getElementById('mmle-call-wall');
            const pWall = document.getElementById('mmle-put-wall');
            if (cWall) cWall.innerText = m.call_wall ? `$${m.call_wall.toFixed(2)}` : '--';
            if (pWall) pWall.innerText = m.put_wall ? `$${m.put_wall.toFixed(2)}` : '--';
        }

        if (peakEl) {
            peakEl.innerText = battleData.peak_trading_window || 'N/A';
        }

        // ── 3. BATTLE LOG & TELEMETRY ────────────────────────────
        const feedEl = document.getElementById('lw-mission-feed');
        if (feedEl) {
            const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            let logLine = `<div style="padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:9px;">
                <span style="color:var(--text-muted); font-size:8px;">[${timeStr}]</span> 
                <span style="color:var(--neon-blue); font-weight:700;">${symbol}</span>: 
                RES ${(battleData.resonance * 100).toFixed(0)}% | 
                FTD ${battleData.active_anchors} | 
                COMP ${mmle.composite || 0}%
            </div>`;
            
            if (feedEl.innerHTML.includes('INITIALIZING')) feedEl.innerHTML = '';
            
            const currentLines = feedEl.querySelectorAll('div');
            if (currentLines.length > 8) {
                currentLines[currentLines.length - 1].remove();
            }
            feedEl.insertAdjacentHTML('afterbegin', logLine);
        }

        updateStatusDot('live');
    }

    function updateStatusDot(state) {
        const dot = document.getElementById('lw-status-dot');
        if (!dot) return;
        dot.className = 'status-dot ' + (state === 'live' ? 'live' : '');
    }

    async function getAIBriefing() {
        const overlay = document.getElementById('briefing-overlay');
        const textEl = document.getElementById('briefing-text');
        const btn = document.getElementById('btn-ai-briefing');

        if (!overlay || !textEl) return;

        overlay.style.display = 'flex';
        textEl.innerText = '📡 DISPATCHING CRYPTOGRAPHIC REQUEST TO AI CORE...\n\nGENERATING COMMANDER\'S BRIEFING...';
        if (btn) { btn.disabled = true; btn.innerText = '⏳ ANALYZING...'; }

        try {
            const res = await fetch('/api/ai/briefing');
            const json = await res.json();
            
            if (json.status === 'success') {
                textEl.innerText = json.briefing;
            } else {
                textEl.innerText = '❌ BRIEFING FAILED: ' + json.message;
            }
        } catch (e) {
            console.error('[AI] Briefing failed:', e);
            textEl.innerText = '❌ AI CORE OFFLINE OR NETWORK ERROR.';
        } finally {
            if (btn) { btn.disabled = false; btn.innerText = '📋 COMMANDER\'S BRIEFING'; }
        }
    }

    async function getSMLBrief() {
        const overlay = document.getElementById('briefing-overlay');
        const textEl  = document.getElementById('briefing-text');
        const btn     = document.getElementById('btn-sml-brief');

        if (!overlay || !textEl) return;
        overlay.style.display = 'flex';
        textEl.innerText = '🔥 GENERATING BEASTMODE BRIEF...\n\nScriptMasterLabs Protocol Active — Stand By.';
        if (btn) { btn.disabled = true; btn.innerText = '⏳ GENERATING...'; }

        try {
            const res  = await fetch('/api/scriptmaster/ai_brief');
            const json = await res.json();
            if (json.status === 'success') {
                textEl.innerText = json.brief;
            } else {
                textEl.innerText = '❌ BEASTMODE BRIEF FAILED: ' + json.message;
            }
        } catch (e) {
            textEl.innerText = '❌ BEASTMODE NODE OFFLINE.';
        } finally {
            if (btn) { btn.disabled = false; btn.innerText = '🔥 BEASTMODE'; }
        }
    }

    async function runProtocol(protocol) {
        const btn = document.getElementById(`btn-${protocol.toLowerCase()}`);
        const logEl = document.getElementById('sml-mission-log');

        if (btn) { btn.style.borderColor = '#ff6a00'; btn.style.opacity = '0.5'; }

        try {
            const res  = await fetch('/api/scriptmaster/run_protocol', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ protocol })
            });
            const json = await res.json();

            if (json.status === 'success') {
                const logLine = `<div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                    <span style="color:#ff6a00; font-size:8px;">[${new Date().toLocaleTimeString()}]</span>
                    <span style="color:#fff; font-weight:700;"> ${protocol}</span> DISPATCHED
                </div>`;
                if (logEl) {
                    if (logEl.innerHTML.includes('AWAITING')) logEl.innerHTML = '';
                    logEl.insertAdjacentHTML('afterbegin', logLine);
                }
                // Refresh mission log after 2s
                setTimeout(refreshSMLLog, 2000);
            }
        } catch (e) {
            console.error('[SML] Protocol dispatch failed:', e);
        } finally {
            if (btn) { btn.style.opacity = '1'; }
        }
    }

    async function refreshSMLLog() {
        try {
            const res  = await fetch('/api/scriptmaster/mission_log?limit=8');
            const json = await res.json();
            const logEl = document.getElementById('sml-mission-log');
            if (!logEl || !json.log) return;

            if (json.log.length === 0) return;
            logEl.innerHTML = json.log.map(entry => `
                <div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04);">
                    <span style="color:#ff6a00; font-size:8px;">[${entry.ts_str}]</span>
                    <span style="color:rgba(255,255,255,0.7); font-size:8px;"> ${entry.protocol}</span>
                    <span style="color:var(--text-dim); font-size:8px;"> ${entry.action} — ${entry.result}</span>
                </div>
            `).join('');
        } catch (e) { /* silent */ }
    }

    return { init, getAIBriefing, getSMLBrief, runProtocol };
})();

document.addEventListener('DOMContentLoaded', () => {
    LeftWingModule.init();
});
