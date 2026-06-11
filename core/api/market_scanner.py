"""
SQUEEZE OS v6.6 — Market-Wide Scanner API
═════════════════════════════════════════════
Full $1-$50 universe scan with options intelligence.
Maximizes Tradier sandbox rate: 60 req/min market data.
Batch quotes = 1 call for 50+ symbols.
"""

from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.state import state, sse_queues
import time
import logging
import threading
from squeeze_analyzer import SqueezeAnalyzer
import core.signal_history as signal_history

try:
    from discord_alerts import DiscordAlerts
    _discord = DiscordAlerts()
except Exception:
    _discord = None


def _broadcast_sse(event: dict):
    """Push an event to all connected SSE clients."""
    dead = []
    for q in list(sse_queues):
        try:
            q.put_nowait(event)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            sse_queues.remove(q)
        except ValueError:
            pass

logger = logging.getLogger("Market-Scanner")
market_bp = Blueprint('market', __name__)

# ── Cached scan results (refreshed by background thread) ──
_autoexec_running = False  # single-run guard for the detached auto-exec worker
_scan_cache = {
    "quotes": {},
    "options": [],
    "last_update": 0,
    "scan_count": 0
}
_scan_lock = threading.Lock()
_analyzer = None  # singleton — load once, reuse every cycle

# ── FULL MARKET UNIVERSE ──
# Tradier batch quotes = 1 API call for ALL of these. Zero reason to limit.
# Post-filter to $1-$50 after fetch. Benchmarks always included.
# ── INSTITUTIONAL UNIVERSE MANDATE (Law 2) ──
# Absolutely no hardcoded watchlists. Discovery is 100% dynamic from the live tape.
MANDATORY_TICKERS = ["IWM", "GME", "AMC"] # Core focus, everything else dynamically fetched

def _discover_universe(dm):
    """
    100% FETCH — calls dm.discover_universe() which runs:
      1. Polygon grouped daily  — entire US market OHLCV in one call, sorted by momentum heat
      2. Alpaca most-actives + movers — live gainers/losers
      3. Tradier quotes — execution-grade data
    Returns the full live symbol list. Mandatory tickers always included.
    """
    try:
        discovered = dm.discover_universe()
        symbols = set(discovered.keys())
        symbols.update(MANDATORY_TICKERS)
        logger.info(f"[DISCOVERY] Live universe: {len(symbols)} tickers")
        return list(symbols)
    except Exception as e:
        logger.error(f"[DISCOVERY] dm.discover_universe() failed: {e}")
        return list(MANDATORY_TICKERS)

def _run_scan():
    """Background scanner: batch quote + options chain fetch (100% Dynamic)."""
    dm = get_service("dm")
    if not dm:
        return

    # 1. Dynamically build universe (Law 2 Compliance)
    dynamic_universe = _discover_universe(dm)

    # 2. Batch quotes (1 API call for all symbols via Tradier)
    tradier = getattr(dm, 'tradier', None)
    alpaca = getattr(dm, 'alpaca', None)
    quotes = {}
    
    if tradier and tradier.available:
        quotes = tradier.get_quotes(dynamic_universe)
    if not quotes and alpaca and alpaca.available:
        # Fallback to Alpaca
        quotes = alpaca.get_snapshots(dynamic_universe)

    # Filter to Institutional Focus: $1-$50 OR Mandatory Targets (IWM)
    sweet = {}
    for sym, q in quotes.items():
        price = q.get('price', 0)
        if 1.0 <= price <= 50.0 or sym in MANDATORY_TICKERS:
            # We track the 'sweet_spot' flag for S3 grading
            q['sweet_spot'] = (1.0 <= price <= 50.0)
            sweet[sym] = q

    # 2. Sort by volume ratio (most active first)
    sorted_syms = sorted(sweet.keys(),
                         key=lambda s: sweet[s].get('volRatio', 0), reverse=True)

    # 3. Options chain scan for top movers (Law 2 & 4 Compliance)
    options_picks = []
    chain_count = 0
    max_chains = 40  # Institutional capacity increased per user request

    for sym in sorted_syms:
        if chain_count >= max_chains:
            break
        q = sweet[sym]
        price = q.get('price', 0)
        if price < 1:
            continue

        # Dynamic Momentum Thresholds: Priority for Squeeze Candidates
        vol_ratio = q.get('volRatio', 0)
        change_pct = abs(q.get('changePct', 0))
        if vol_ratio < 1.1 and change_pct < 1.0 and sym not in MANDATORY_TICKERS:
            continue

        if tradier and tradier.available:
            chain_data = tradier.get_option_chains(sym)
            if chain_data and chain_data.get('options'):
                chain_count += 1
                # Grade the options (Law 3: S3 Standard)
                picks = _grade_options(sym, price, q, chain_data['options'])
                options_picks.extend(picks)
            time.sleep(0.5)  # Institutional rate limit optimization

    with _scan_lock:
        _scan_cache["quotes"] = sweet
        _scan_cache["options"] = options_picks
        _scan_cache["last_update"] = time.time()
        _scan_cache["scan_count"] += 1

    # Update global state
    with state.lock:
        state.quotes.update(sweet)
        state.audit["universe_size"] = len(sweet)
        
        # 4. Technical Pattern Analysis (Golden Cross, Double Bottom, Momentum)
        global _analyzer
        try:
            if _analyzer is None:
                _analyzer = SqueezeAnalyzer()
            technical_results = _analyzer.analyze_batch(sweet)
        except Exception as e:
            logger.error(f"[SCAN] SqueezeAnalyzer failed: {e}")
            technical_results = []
        
        # Combine Technical Squeezes & High-Grade Options into CEO triggers
        ceo_triggers = []
        
        # A) Add Technical Squeezes (Score 80+)
        squeeze_hits = []
        for r in technical_results:
            if r.get('squeeze_score', 0) >= 80:
                ceo_triggers.append(r)
                squeeze_hits.append(r)
                evt = {
                    'type': 'SQUEEZE_ALERT',
                    'symbol': r['symbol'],
                    'score': r['squeeze_score'],
                    'direction': r.get('direction', 'UNKNOWN'),
                    'price': r.get('price'),
                    'ts': time.time(),
                }
                _broadcast_sse(evt)
                signal_history.record(r['symbol'], 'SQUEEZE_ALERT', evt)

        # NOTE: Discord firing moved OUTSIDE state.lock (see below) —
        # blocking webhooks while holding the lock starved gunicorn web
        # threads and caused Render health-check kills.

        # B) Add High-Grade Options
        flow_hits = []
        for p in options_picks:
            if p.get('score', 0) >= 80:  # Grade A or high B
                ceo_triggers.append({
                    'symbol': p['symbol'],
                    'squeeze_score': p['score'],
                    'direction': 'BULLISH' if p['type'] == 'call' else 'BEARISH',
                    'price': p['stock_price']
                })
                sweep = {
                    'type': 'OPTIONS_SWEEP',
                    'symbol': p['symbol'],
                    'strike': p['strike'],
                    'option_type': p['type'],
                    'expiration': p['expiration'],
                    'grade': p['grade'],
                    'score': p['score'],
                    'mid': p['mid'],
                    'ts': time.time(),
                }
                _broadcast_sse(sweep)
                signal_history.record(p['symbol'], 'OPTIONS_SWEEP', sweep)
                flow_hits.append({
                    'symbol': p['symbol'],
                    'unusual_score': p['score'],
                    'strike': p['strike'],
                    'type': p['type'].upper(),
                    'expiry_formatted': p.get('expiration', ''),
                    'days_to_expiry': p.get('dte', 0),
                    'price': p.get('mid', 0),
                    'bid': p.get('bid', 0),
                    'ask': p.get('ask', 0),
                    'volume': p.get('volume', 0),
                    'open_interest': p.get('open_interest', 0),
                    'implied_volatility': p.get('iv', 0),
                    'sentiment': 'BULLISH' if p['type'] == 'call' else 'BEARISH',
                    'is_sweep': p.get('grade') in ('A', 'A+'),
                    'alert_priority': 'EXTREME' if p.get('score', 0) >= 90 else 'HIGH',
                    'source': 'Tradier',
                })

        if ceo_triggers:
            # Sort highest scores first
            ceo_triggers.sort(key=lambda x: x.get('squeeze_score', 0), reverse=True)
            state.scan_results = ceo_triggers + state.scan_results
            
            # Deduplicate by symbol while preserving highest score
            seen = set()
            deduped = []
            for item in state.scan_results:
                if item['symbol'] not in seen:
                    seen.add(item['symbol'])
                    deduped.append(item)
            
            state.scan_results = deduped
            if len(state.scan_results) > 200:
                del state.scan_results[200:]

    # ── Discord alerts: fired AFTER state.lock releases, on a detached
    #    thread so neither web requests nor the scan loop ever wait on
    #    webhook rate-limit sleeps. (Fix for Render health-check kills.)
    if (squeeze_hits or flow_hits) and _discord:
        def _fire_alerts(_squeeze=list(squeeze_hits), _flow=list(flow_hits)):
            try:
                if _squeeze:
                    _discord.fire_squeeze_alerts(_squeeze)
                if _flow:
                    _discord.fire_flow_alerts(_flow)
            except Exception as _de:
                logger.warning(f"[DISCORD] alert dispatch failed: {_de}")
        threading.Thread(target=_fire_alerts, daemon=True, name="discord-alerts").start()

    logger.info(f"[SCAN] {len(sweet)} symbols | {len(options_picks)} options picks | {len(technical_results)} technical scans | cycle #{_scan_cache['scan_count']}")

    # ── AUTO-EXECUTION HOOK (non-blocking) ───────────────────────────────────
    # Runs convergence analysis + alerting/execution on a DETACHED thread so it
    # NEVER blocks the scan loop or starves gunicorn health checks. A single-run
    # guard ensures only one auto-exec pass runs at a time (skips if the prior
    # one is still working — prevents pile-up under slow upstream APIs).
    global _autoexec_running
    if not _autoexec_running:
        _autoexec_running = True
        _syms_snapshot = list(sorted_syms)
        _sweet_snapshot = dict(sweet)

        def _autoexec_worker():
            global _autoexec_running
            try:
                from core.api import auto_exec
                auto_exec.run_auto_execution(_sweet_snapshot, _syms_snapshot, dm)
            except Exception as _ae:
                logger.warning(f"[SCAN] auto-exec worker error (non-fatal): {_ae}")
            finally:
                _autoexec_running = False

        threading.Thread(target=_autoexec_worker, daemon=True, name="SML-AutoExec").start()


def _grade_options(symbol, price, quote, options):
    """
    Grade options 0DTE to 14 days out.
    Returns list of picks with strike/date/grade/explanation.
    """
    from datetime import datetime, timedelta
    picks = []
    now = datetime.now()
    max_exp = now + timedelta(days=14)
    change_pct = quote.get('changePct', 0)
    vol_ratio = quote.get('volRatio', 0)

    for opt in options:
        try:
            exp_str = opt.get('expiration_date', '')
            if not exp_str:
                continue
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d')
            if exp_date < now or exp_date > max_exp:
                continue

            dte = (exp_date - now).days
            strike = float(opt.get('strike', 0))
            opt_type = opt.get('option_type', 'call')
            bid = float(opt.get('bid', 0))
            ask = float(opt.get('ask', 0))
            mid = (bid + ask) / 2 if bid and ask else 0
            volume = int(opt.get('volume', 0) or 0)
            oi = int(opt.get('open_interest', 0) or 0)
            iv = float(opt.get('greeks', {}).get('mid_iv', 0) or 0) if isinstance(opt.get('greeks'), dict) else 0
            delta = float(opt.get('greeks', {}).get('delta', 0) or 0) if isinstance(opt.get('greeks'), dict) else 0

            # Skip illiquid
            if mid < 0.05 or (bid == 0 and ask == 0):
                continue
            if mid > 5.0:
                continue  # Keep it cheap for retail

            # ── GRADING ──
            score = 0
            reasons = []

            # Volume/OI signal
            if volume > 0 and oi > 0 and volume > oi * 0.5:
                score += 25
                reasons.append(f"Vol/OI {volume}/{oi}")

            # Tight spread = liquid
            spread_pct = (ask - bid) / mid * 100 if mid > 0 else 999
            if spread_pct < 15:
                score += 15
                reasons.append("Tight spread")
            elif spread_pct < 30:
                score += 8

            # Delta sweet spot (0.30-0.45 = institutional squeeze target per user mandate)
            abs_delta = abs(delta)
            if 0.30 <= abs_delta <= 0.45:
                score += 45
                reasons.append(f"Institutional Δ{delta:.2f}")
            elif 0.20 <= abs_delta <= 0.55:
                score += 20
                reasons.append(f"Delta {delta:.2f}")

            # Momentum alignment
            if change_pct > 2.0 and opt_type == 'call':
                score += 15
                reasons.append(f"Momentum +{change_pct:.1f}%")
            elif change_pct < -2.0 and opt_type == 'put':
                score += 15
                reasons.append(f"Momentum {change_pct:.1f}%")

            # 0DTE premium
            if dte == 0:
                score += 10
                reasons.append("0DTE")
            elif dte <= 3:
                score += 5

            # Volume ratio boost
            if vol_ratio > 2.0:
                score += 10
                reasons.append(f"VolRatio {vol_ratio:.1f}x")

            if score < 40:  # Minimum threshold for C grade (Filter out D/F grades)
                continue

            # ── DIRECTIVE ──
            if score >= 70:
                grade = "A"
                directive = "BUY"
            elif score >= 55:
                grade = "B"
                directive = "BUY"
            elif score >= 40:
                grade = "C"
                directive = "HOLD"
            else:
                grade = "D"
                directive = "HOLD"

            # ── PLAIN ENGLISH ──
            if directive == "BUY" and opt_type == "call":
                explanation = f"{symbol} is moving up {change_pct:+.1f}% with {vol_ratio:.1f}x normal volume. This ${strike} call expiring {exp_str} has strong flow at ${mid:.2f}. {' + '.join(reasons)}."
            elif directive == "BUY" and opt_type == "put":
                explanation = f"{symbol} is selling off {change_pct:+.1f}%. This ${strike} put expiring {exp_str} at ${mid:.2f} is catching institutional flow. {' + '.join(reasons)}."
            else:
                explanation = f"{symbol} ${strike} {opt_type} expiring {exp_str} at ${mid:.2f}. Watch for confirmation. {' + '.join(reasons)}."

            picks.append({
                "symbol": symbol,
                "strike": strike,
                "type": opt_type,
                "expiration": exp_str,
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": round(mid, 2),
                "volume": volume,
                "oi": oi,
                "iv": round(iv * 100, 1) if iv else 0,
                "delta": round(delta, 3),
                "score": score,
                "grade": grade,
                "directive": directive,
                "explanation": explanation,
                "stock_price": price,
                "stock_change": round(change_pct, 2),
                "vol_ratio": round(vol_ratio, 2),
            })
        except Exception:
            continue

    # Sort by score descending
    picks.sort(key=lambda x: -x['score'])
    return picks[:5]  # Top 5 per symbol


# ── Background Scanner Thread ──
_scanner_thread = None

def start_market_scanner():
    global _scanner_thread
    def loop():
        logger.info("📡 [MARKET] Full Universe Scanner Active")
        time.sleep(5)  # Wait for services to init
        while True:
            try:
                _run_scan()
            except Exception as e:
                logger.error(f"[MARKET] Scan error: {e}")
            # Back off to 30s when no data — avoids OOM spin on cold/empty Tradier
            with _scan_lock:
                symbol_count = len(_scan_cache.get("quotes", {}))
            interval = 3 if symbol_count > 0 else 30
            time.sleep(interval)
    _scanner_thread = threading.Thread(target=loop, daemon=True, name="SML-Market-Scanner")
    _scanner_thread.start()


# ── API Endpoints ──

@market_bp.route('/scan', methods=['GET'])
def get_scan():
    with _scan_lock:
        return jsonify(clean_data({
            "status": "success",
            "quotes": _scan_cache["quotes"],
            "options": _scan_cache["options"],
            "last_update": _scan_cache["last_update"],
            "scan_count": _scan_cache["scan_count"],
            "universe_size": len(_scan_cache["quotes"])
        }))

@market_bp.route('/options/<symbol>', methods=['GET'])
def get_options(symbol):
    """Fetch fresh options chain for a specific symbol."""
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager offline"}), 503

    tradier = getattr(dm, 'tradier', None)
    if not tradier or not tradier.available:
        return jsonify({"status": "error", "message": "Tradier not configured"}), 503

    symbol = symbol.upper().strip()
    quotes = tradier.get_quotes([symbol])
    q = quotes.get(symbol, {})
    price = q.get('price', 0)

    chain_data = tradier.get_option_chains(symbol)
    if not chain_data or not chain_data.get('options'):
        return jsonify({"status": "error", "message": f"No options data for {symbol}"}), 404

    picks = _grade_options(symbol, price, q, chain_data['options'])
    return jsonify(clean_data({
        "status": "success",
        "symbol": symbol,
        "price": price,
        "picks": picks,
        "chain_count": len(chain_data['options'])
    }))

@market_bp.route('/news', methods=['GET'])
def get_news():
    """Fetch live market news from Alpaca."""
    dm = get_service("dm")
    if not dm or not getattr(dm, 'alpaca', None):
        return jsonify({"status": "error", "message": "Alpaca offline"}), 503
    news = dm.alpaca.get_news(limit=15)
    return jsonify(clean_data({"status": "success", "news": news}))
