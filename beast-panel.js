/**
 * BEAST MODE Paper Trading Panel — SqueezeOS Pro
 * Handles overlay toggle, data polling, and strategy architect interaction.
 */
const BeastPanel = (() => {
    let _visible = false;
    let _pollTimer = null;
    let _sse = null;
    const API = window.location.origin;

    function toggle() {
        const el = document.getElementById('beast-overlay');
        if (!el) return;
        _visible = !_visible;
        el.style.display = _visible ? 'block' : 'none';
        if (_visible) {
            refresh();
            initSSE();
            _pollTimer = setInterval(refresh, 30000); // 30s poll
        } else {
            if (_pollTimer) clearInterval(_pollTimer);
            if (_sse) {
                _sse.close();
                _sse = null;
            }
        }
    }

    function initSSE() {
        if (_sse) return;
        console.log('[BEAST] Initializing Institutional SSE...');
        _sse = new EventSource(`${API}/api/beast/events`);
        
        _sse.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleLiveEvent(data);
            } catch(e) {}
        };
        
        _sse.onerror = (e) => {
            if (_sse) {
                _sse.close();
                _sse = null;
            }
            setTimeout(initSSE, 5000);
        };
    }

    function handleLiveEvent(data) {
        // High Conviction Flash
        if (data.type === 'BEAST_ALERT' || (data.score && data.score >= 75)) {
            showHighConvictionAlert(data);
        }
    }

    function showHighConvictionAlert(data) {
        const alertDiv = document.createElement('div');
        alertDiv.className = 'beast-alert-toast';
        alertDiv.style = `
            position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
            background: rgba(255, 20, 147, 0.9); color: white; padding: 12px 24px;
            border-radius: 4px; border: 2px solid #fff; z-index: 10000;
            font-family: var(--font-mono); font-weight: 900; box-shadow: 0 0 20px #FF1493;
            pointer-events: none;
        `;
        alertDiv.innerHTML = `🔥 HIGH CONVICTION: ${data.msg || data.symbol}`;
        document.body.appendChild(alertDiv);
        setTimeout(() => alertDiv.remove(), 4000);
    }

    async function refresh() {
        try {
            const [paperRes, readyRes, kdpRes] = await Promise.all([
                fetch(`${API}/api/beast/paper`).then(r => r.json()).catch(() => null),
                fetch(`${API}/api/beast/readiness`).then(r => r.json()).catch(() => null),
                fetch(`${API}/api/beast/kdp`).then(r => r.json()).catch(() => null)
            ]);
            if (readyRes) renderReadiness(readyRes);
            if (paperRes) {
                renderHedger(paperRes.hedger_snapshots || []);
                renderGex(paperRes.gex_regimes || []);
                renderIwm(paperRes.iwm_odte || {});
                renderTrades(paperRes.shadow_trades || [], paperRes.trade_history || []);
            }
            if (kdpRes && kdpRes.data) renderKdp(kdpRes.data);
        } catch (e) {
            console.error('[BEAST] Refresh failed:', e);
        }
    }

    function renderReadiness(data) {
        const el = document.getElementById('beast-readiness-content');
        if (!el) return;
        const checks = data.checks || [];
        const status = data.status || 'UNKNOWN';
        const statusColor = status === 'GO' ? '#00FF7F' : '#FF1493';
        let html = `<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
            <span style="font-size:18px;font-weight:900;color:${statusColor};font-family:var(--font-mono);letter-spacing:2px;">${status === 'GO' ? '✅ GO FOR LIVE' : '🛑 NO-GO'}</span>
            <span style="font-size:10px;color:var(--text-dim);">${data.recommendation || ''}</span>
        </div>`;
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;">';
        for (const c of checks) {
            const icon = c.passed ? '✅' : '❌';
            const border = c.passed ? 'rgba(0,255,127,0.3)' : 'rgba(255,20,147,0.3)';
            const bg = c.passed ? 'rgba(0,255,127,0.05)' : 'rgba(255,20,147,0.05)';
            html += `<div style="border:1px solid ${border};background:${bg};padding:8px 10px;border-radius:3px;">
                <div style="font-size:11px;font-weight:700;color:#fff;">${icon} ${c.name}</div>
                <div style="font-size:9px;color:var(--text-dim);margin-top:3px;">${c.detail || ''}</div>
            </div>`;
        }
        html += '</div>';
        el.innerHTML = html;
    }

    function renderHedger(snapshots) {
        const el = document.getElementById('beast-hedger-content');
        if (!el) return;
        if (!snapshots.length) {
            el.innerHTML = '<div style="color:var(--text-dim);font-size:11px;">No hedger data yet — waiting for first cycle...</div>';
            return;
        }
        let html = '';
        for (const s of snapshots) {
            const statusColor = s.status === 'NEUTRAL' ? '#00FF7F' : s.status === 'DRY_RUN' ? '#FFD700' : s.status === 'HEDGER_OFFLINE' ? '#FF1493' : '#FF8C00';
            const snap = s.snapshot || {};
            html += `<div style="border-bottom:1px solid rgba(255,255,255,0.05);padding:6px 0;font-family:var(--font-mono);font-size:11px;">
                <span style="color:${statusColor};font-weight:700;">${s.symbol || '?'}</span>
                <span style="color:var(--text-dim);margin-left:8px;">${s.status}</span>
                ${snap.net_delta !== undefined ? `<span style="margin-left:8px;color:#fff;">Δ=${snap.net_delta}</span>` : ''}
                ${snap.option_gamma !== undefined ? `<span style="margin-left:8px;color:var(--text-dim);">Γ=${snap.option_gamma}</span>` : ''}
                ${s.delta_from_target ? `<span style="margin-left:8px;color:${Math.abs(s.delta_from_target) > 10 ? '#FF1493' : '#00FF7F'};">ΔTarget=${s.delta_from_target}</span>` : ''}
            </div>`;
        }
        el.innerHTML = html;
    }

    function renderGex(regimes) {
        const el = document.getElementById('beast-gex-content');
        if (!el) return;
        if (!regimes.length) {
            el.innerHTML = '<div style="color:var(--text-dim);font-size:11px;">Waiting for GEX scan data...</div>';
            return;
        }
        let html = '';
        for (const g of regimes) {
            const regimeColor = g.regime === 'POSITIVE_GAMMA' ? '#00FF7F' : g.regime === 'NEGATIVE_GAMMA' ? '#FF1493' : '#FFD700';
            html += `<div style="border:1px solid rgba(255,255,255,0.08);padding:8px 10px;border-radius:3px;margin-bottom:6px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-weight:700;color:#fff;font-size:13px;">${g.symbol || '?'}</span>
                    <span style="color:${regimeColor};font-weight:700;font-size:11px;background:rgba(0,0,0,0.3);padding:2px 8px;border-radius:2px;">${g.regime || '?'}</span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:6px;font-size:10px;color:var(--text-dim);">
                    <div>Call Wall: <span style="color:#00FF7F;">${g.call_wall ? '$' + Number(g.call_wall).toFixed(2) : 'N/A'}</span></div>
                    <div>Put Wall: <span style="color:#FF1493;">${g.put_wall ? '$' + Number(g.put_wall).toFixed(2) : 'N/A'}</span></div>
                    <div>Zero-γ: <span style="color:#FFD700;">${g.zero_gamma ? '$' + Number(g.zero_gamma).toFixed(2) : 'N/A'}</span></div>
                </div>
                <div style="font-size:9px;color:var(--text-dim);margin-top:4px;">Total GEX: ${g.total_gex ? Number(g.total_gex).toLocaleString() : '?'}</div>
            </div>`;
        }
        el.innerHTML = html;
    }

    function renderIwm(data) {
        const el = document.getElementById('beast-iwm-content');
        if (!el) return;
        if (!data || !data.best_contracts) {
            el.innerHTML = '<div style="color:var(--text-dim);font-size:11px;">Waiting for IWM Sentinel...</div>';
            return;
        }
        
        const bias = data.bias || 'NEUTRAL';
        const biasColor = bias === 'BULLISH' ? '#00FF7F' : bias === 'BEARISH' ? '#FF1493' : '#FFD700';
        
        let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;border-bottom:1px solid rgba(0,255,127,0.1);padding-bottom:6px;">
            <span style="font-size:10px;color:var(--text-dim);">INSTITUTIONAL BIAS</span>
            <span style="color:${biasColor};font-weight:900;letter-spacing:1px;font-size:12px;">${bias}</span>
        </div>`;
        
        const best = data.best_contracts || [];
        for (const c of best.slice(0, 5)) {
            const sideColor = c.side === 'call' ? '#00FF7F' : '#FF1493';
            const scoreColor = c.score > 70 ? '#00FF7F' : c.score > 40 ? '#FFD700' : '#FF1493';
            html += `<div style="border:1px solid rgba(255,255,255,0.05);padding:6px 8px;border-radius:3px;margin-bottom:4px;background:rgba(0,0,0,0.2);">
                <div style="display:flex;justify-content:space-between;font-size:11px;">
                    <span style="color:${sideColor};font-weight:700;">${c.side.toUpperCase()} $${c.strike}</span>
                    <span style="color:${scoreColor};font-weight:900;">SCORE: ${c.score}</span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px;font-size:9px;color:var(--text-dim);">
                    <div>Spread: <span style="color:#fff;">${c.spread_pct}%</span></div>
                    <div>Delta: <span style="color:#fff;">${c.delta}</span></div>
                    <div>IV/RV: <span style="color:#fff;">${c.iv_rv_ratio || 'N/A'}</span></div>
                    <div>DTE: <span style="color:#fff;">${c.dte}</span></div>
                </div>
            </div>`;
        }

        const parity = data.parity_watch || [];
        if (parity.length > 0) {
            html += `<div style="margin-top:10px; border-top:1px solid rgba(255,255,255,0.08); padding-top:6px;">
                <div style="font-size:10px; color:#FFD700; font-weight:700; margin-bottom:4px;">⚖️ PARITY GAPS</div>`;
            for (const p of parity.slice(0, 3)) {
                html += `<div style="font-size:9px; color:var(--text-dim); display:flex; justify-content:space-between;">
                    <span>$${p.strike} Strike</span>
                    <span style="color:${Math.abs(p.gap) > 0.4 ? '#FF1493' : '#fff'};">$${p.gap.toFixed(3)}</span>
                </div>`;
            }
            html += `</div>`;
        }

        html += `<button onclick="BeastPanel.shareIntel('IWM', '${bias}')" style="width:100%; margin-top:8px; background:rgba(0,163,255,0.1); border:1px solid var(--neon-blue); color:var(--neon-blue); font-size:9px; padding:4px; cursor:pointer; font-family:var(--font-mono);">SHARE INTEL</button>`;

        el.innerHTML = html;
    }

    function shareIntel(sym, bias) {
        const text = `🦅 INSTITUTIONAL INTEL [${sym}]\nBias: ${bias}\nTime: ${new Date().toLocaleTimeString()}\nSource: SqueezeOS Pro Institutional Sentinel`;
        navigator.clipboard.writeText(text).then(() => alert('Intel copied to clipboard.'));
    }

    function renderKdp(data) {
        const el = document.getElementById('beast-kdp-content');
        if (!el) return;
        if (!data || !data.top_contracts) {
            el.innerHTML = '<div style="color:var(--text-dim);font-size:11px;">Waiting for KDP Sentinel...</div>';
            return;
        }

        let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;border-bottom:1px solid rgba(0,212,255,0.1);padding-bottom:6px;">
            <span style="font-size:10px;color:var(--text-dim);">INSTITUTIONAL TRACKER</span>
            <span style="color:var(--neon-blue);font-weight:900;letter-spacing:1px;font-size:12px;">KDP ACTIVE</span>
        </div>`;

        const top = data.top_contracts || [];
        if (top.length === 0) {
            html += '<div style="color:var(--text-dim);font-size:11px;">No high-conviction flow detected.</div>';
        }

        for (const c of top.slice(0, 5)) {
            const sideColor = c.type === 'CALL' ? '#00FF7F' : '#FF1493';
            const scoreColor = c.score > 70 ? '#00FF7F' : c.score > 40 ? '#FFD700' : '#FF1493';
            html += `<div style="border:1px solid rgba(255,255,255,0.05);padding:6px 8px;border-radius:3px;margin-bottom:4px;background:rgba(0,0,0,0.2);">
                <div style="display:flex;justify-content:space-between;font-size:11px;">
                    <span style="color:${sideColor};font-weight:700;">${c.type} $${c.strike}</span>
                    <span style="color:${scoreColor};font-weight:900;">SCORE: ${c.score}</span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px;font-size:9px;color:var(--text-dim);">
                    <div>Squeeze: <span style="color:#fff;">${c.squeeze_score || 'N/A'}</span></div>
                    <div>Hurst: <span style="color:#fff;">${c.hurst || 'N/A'}</span></div>
                    <div>Delta: <span style="color:#fff;">${c.delta || 'N/A'}</span></div>
                    <div>OI/Vol: <span style="color:#fff;">${c.oi_vol_ratio || 'N/A'}x</span></div>
                </div>
            </div>`;
        }
        el.innerHTML = html;
    }

    function renderTrades(active, history) {
        const el = document.getElementById('beast-trades-content');
        if (!el) return;
        if (!active.length && !history.length) {
            el.innerHTML = '<div style="color:var(--text-dim);font-size:11px;">No shadow trades recorded yet.</div>';
            return;
        }
        let html = '';
        if (active.length) {
            html += '<div style="font-size:10px;color:#FFD700;font-weight:700;margin-bottom:4px;">ACTIVE POSITIONS</div>';
            html += '<table style="width:100%;border-collapse:collapse;font-size:10px;font-family:var(--font-mono);">';
            html += '<tr style="color:var(--text-dim);border-bottom:1px solid rgba(255,255,255,0.1);"><th>SYM</th><th>SIDE</th><th>QTY</th><th>ENTRY</th><th>CURRENT</th><th>PnL</th><th>REGIME</th></tr>';
            for (const t of active) {
                const pnl = ((t.current_price - t.entry_price) * t.qty * (t.side === 'SELL' ? -1 : 1)).toFixed(2);
                const pnlColor = pnl >= 0 ? '#00FF7F' : '#FF1493';
                html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.03);">
                    <td style="color:#fff;font-weight:700;padding:3px 4px;">${t.symbol}</td>
                    <td style="color:${t.side === 'BUY' ? '#00FF7F' : '#FF1493'};">${t.side}</td>
                    <td>${t.qty}</td>
                    <td>$${Number(t.entry_price).toFixed(2)}</td>
                    <td>$${Number(t.current_price).toFixed(2)}</td>
                    <td style="color:${pnlColor};font-weight:700;">$${pnl}</td>
                    <td style="color:var(--text-dim);">${t.regime || '?'}</td>
                </tr>`;
            }
            html += '</table>';
        }
        if (history.length) {
            html += '<div style="font-size:10px;color:var(--text-dim);font-weight:700;margin:8px 0 4px;">RECENT CLOSED</div>';
            for (const t of history.slice(0, 10)) {
                const pnlColor = (t.pnl || 0) >= 0 ? '#00FF7F' : '#FF1493';
                html += `<div style="font-size:10px;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.03);">
                    <span style="color:#fff;">${t.symbol}</span>
                    <span style="color:${pnlColor};margin-left:8px;font-weight:700;">$${Number(t.pnl || 0).toFixed(2)}</span>
                    <span style="color:var(--text-dim);margin-left:8px;">${t.exit_reason || ''}</span>
                </div>`;
            }
        }
        el.innerHTML = html;
    }

    async function runArchitect() {
        const input = document.getElementById('beast-thesis-input');
        const content = document.getElementById('beast-architect-content');
        if (!input || !content) return;
        const thesis = input.value.trim();
        if (!thesis) {
            content.innerHTML = '<div style="color:#FF1493;">Enter a thesis first.</div>';
            return;
        }
        content.innerHTML = '<div style="color:#FFD700;">⏳ Running Strategy Architect...</div>';
        try {
            const res = await fetch(`${API}/api/beast/architect`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({thesis})
            });
            const data = await res.json();
            if (data.error) {
                content.innerHTML = `<div style="color:#FF1493;">Error: ${data.error}</div>`;
                return;
            }
            let html = `<div style="margin-bottom:8px;">
                <span style="color:#FFD700;font-weight:700;">${data.symbol || '?'}</span>
                <span style="color:var(--text-dim);margin-left:8px;">$${data.spot || '?'} | Exp: ${data.expiry || '?'}</span>
                <span style="color:var(--text-dim);margin-left:8px;">Dir: ${data.thesis?.direction || '?'} | Mag: ${data.thesis?.magnitude || '?'}</span>
            </div>`;
            const strats = data.strategies || [];
            if (!strats.length) {
                html += '<div style="color:var(--text-dim);">No strategies matched thesis.</div>';
            }
            for (const s of strats) {
                const scoreColor = s.score > 0.6 ? '#00FF7F' : s.score > 0.4 ? '#FFD700' : '#FF1493';
                html += `<div style="border:1px solid rgba(255,255,255,0.1);padding:8px;border-radius:3px;margin-bottom:6px;">
                    <div style="display:flex;justify-content:space-between;">
                        <span style="color:#fff;font-weight:700;">${s.name}</span>
                        <span style="color:${scoreColor};font-weight:700;">Score: ${s.score}</span>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-top:4px;font-size:9px;color:var(--text-dim);">
                        <div>POP: <span style="color:#fff;">${(s.pop * 100).toFixed(1)}%</span></div>
                        <div>Max Profit: <span style="color:#00FF7F;">$${s.max_profit}</span></div>
                        <div>Max Loss: <span style="color:#FF1493;">$${s.max_loss}</span></div>
                        <div>R/R: <span style="color:#FFD700;">${s.risk_reward}x</span></div>
                    </div>
                    <div style="font-size:9px;color:var(--text-dim);margin-top:4px;">${s.rationale}</div>
                    <div style="margin-top:4px;">${(s.legs || []).map(l =>
                        `<span style="font-size:9px;padding:1px 4px;border-radius:2px;margin-right:4px;background:${l.type === 'CALL' ? 'rgba(0,255,127,0.1)' : 'rgba(255,20,147,0.1)'};color:${l.type === 'CALL' ? '#00FF7F' : '#FF1493'};">${l.action} ${l.type} $${l.strike} @$${l.mid}</span>`
                    ).join('')}</div>
                </div>`;
            }
            content.innerHTML = html;
        } catch (e) {
            content.innerHTML = `<div style="color:#FF1493;">Request failed: ${e.message}</div>`;
        }
    }

    return { toggle, refresh, runArchitect };
})();
