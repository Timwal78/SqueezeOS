"""
SqueezeOS Premium API — 402Proof Gated Endpoints
═══════════════════════════════════════════════════
4 live endpoints gated by RLUSD micropayment via 402Proof x402 protocol.

  POST /api/council  — 0.10 RLUSD — AI council verdict (multi-engine aggregate)
  GET  /api/scan     — 0.05 RLUSD — Full $1-$50 market scanner results
  GET  /api/options  — 0.05 RLUSD — Options intelligence flow summary
  GET  /api/iwm      — 0.03 RLUSD — IWM 0DTE institutional scanner
"""

import sys
import os
import re
import time
import logging
import threading
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.state import state, sse_queues
import core.signal_history as signal_history

_SYMBOL_RE = re.compile(r'^[A-Z0-9.]{1,10}$')


def _validate_symbol(raw: str) -> tuple:
    """Return (cleaned_symbol, error_response_or_None).
    Sanitizes and validates a ticker symbol input.
    """
    cleaned = raw.upper().strip()[:10]
    if not _SYMBOL_RE.match(cleaned):
        return None, jsonify({"error": "invalid symbol", "message": "Symbol must be 1-10 uppercase alphanumeric characters"}), 400
    return cleaned, None


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

# proof402_integration.py lives at repo root (kept as secondary XRPL/RLUSD rail)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from x402_flask import x402_guard

logger = logging.getLogger("SqueezeOS-Premium")
premium_bp = Blueprint('premium', __name__)

# Rate limiting — 30 requests/min per IP on premium endpoints
from core.rate_limiter import premium_limiter as _premium_rl
from flask import request as _req

@premium_bp.before_request
def _rate_limit_premium():
    ip = _req.remote_addr or "unknown"
    if not _premium_rl.allow(ip, _req.path):
        return jsonify({"error": "rate_limit_exceeded", "message": "Too many requests. Retry after 60s."}), 429


# ── /api/council ─────────────────────────────────────────────────────────────

@premium_bp.route('/council', methods=['POST', 'GET'])
@x402_guard(price_usdc="0.10", description="AI Council Verdict — multi-engine signal aggregate. Returns regime (EXECUTION/STEALTH/CONFLICT/COLLAPSE), directional bias, confidence (0-100), and full institutional thesis for any equity symbol.")
def council():
    """
    AI Council Verdict — multi-engine signal aggregate.
    Returns regime, bias, risk score, and actionable thesis for a symbol or IWM.
    """
    body = request.get_json(silent=True) or {}
    raw_symbol = body.get('symbol') or request.args.get('symbol', 'IWM')
    symbol, err = _validate_symbol(raw_symbol)
    if err:
        return err

    dm = get_service('dm')
    if not dm:
        return jsonify({"error": "data_manager offline"}), 503

    verdict = {"symbol": symbol, "ts": time.time(), "engines": {}}

    # SML Engine signal
    try:
        sml = get_service('sml')
        if sml and dm:
            bars = clean_data(dm.get_bars(symbol, timeframe='1D', limit=60))
            if bars:
                history = {symbol: bars}
                cascade = sml.compute_fractal_cascade(symbol, history)
                verdict["engines"]["sml"] = cascade
    except Exception as e:
        logger.warning(f"[COUNCIL] SML engine error: {e}")

    # Battle Computer signal
    try:
        from datetime import datetime
        battle = get_service('battle')
        if battle:
            summary = battle.get_battle_summary(datetime.now().strftime('%Y-%m-%d'))
            verdict["engines"]["battle"] = summary
    except Exception as e:
        logger.warning(f"[COUNCIL] Battle engine error: {e}")

    # Market state from SqueezeOS state
    try:
        audit = state.audit
        verdict["engines"]["market_state"] = {
            "uptime": time.time() - audit.get("uptime_start", time.time()),
            "terminal_feed": state.terminal_feed[-5:] if hasattr(state, "terminal_feed") else [],
        }
    except Exception as e:
        logger.warning(f"[COUNCIL] State error: {e}")

    # Derive top-level verdict from cascade output
    sml_data = verdict["engines"].get("sml", {})

    # Cascade returns: cascade_bias, alignment_score, bull_count, bear_count, avoid_count
    cascade_bias = sml_data.get("cascade_bias", "")
    alignment    = float(sml_data.get("alignment_score", 0))
    bull_count   = int(sml_data.get("bull_count", 0))
    bear_count   = int(sml_data.get("bear_count", 0))

    # Map cascade_bias to clean directional bias
    cb_upper = cascade_bias.upper()
    if "BEAR" in cb_upper:
        bias = "BEARISH"
    elif "BULL" in cb_upper:
        bias = "BULLISH"
    else:
        bias = "NEUTRAL"

    # Confidence = alignment_score capped at 100
    confidence = min(100, int(alignment))

    # Regime from timeframe majority
    if bull_count > bear_count:
        regime = "BULLISH_EXPANSION"
    elif bear_count > bull_count:
        regime = "BEARISH_CONTRACTION"
    else:
        regime = "CONSOLIDATION"

    thesis = sml_data.get("cascade_meaning") or \
             f"{symbol} — {cascade_bias} | alignment={round(alignment,1)} bull={bull_count} bear={bear_count}"

    verdict["verdict"] = {
        "symbol":     symbol,
        "bias":       bias,
        "regime":     regime,
        "confidence": confidence,
        "thesis":     thesis,
        "alignment_score": alignment,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "timestamp":  time.time(),
    }

    council_evt = {
        'type':       'COUNCIL_VERDICT',
        'symbol':     symbol,
        'bias':       bias,
        'regime':     regime,
        'confidence': confidence,
        'ts':         time.time(),
    }

    # Signal Embargo Window — PNE rank-1 winners get exclusive access for N seconds.
    # PNE gateway injects X-PNE-Embargo: <seconds> when the caller won rank-1.
    # During embargo: verdict returns immediately to winner; SSE + history delayed for all others.
    try:
        embargo_secs = max(0, min(300, int(request.headers.get('X-PNE-Embargo', '0'))))
    except (ValueError, TypeError):
        embargo_secs = 0

    if embargo_secs > 0:
        pne_rank = request.headers.get('X-PNE-Rank', '?')
        logger.info(f"[EMBARGO] {symbol} embargoed for {embargo_secs}s (PNE rank={pne_rank})")

        def _deferred_publish(evt, sym, delay):
            time.sleep(delay)
            _broadcast_sse(evt)
            signal_history.record(sym, 'COUNCIL_VERDICT', evt)

        t = threading.Thread(target=_deferred_publish, args=(council_evt, symbol, embargo_secs), daemon=True)
        t.start()

        verdict["embargo"] = {"active": True, "seconds": embargo_secs, "pne_rank": pne_rank}
    else:
        _broadcast_sse(council_evt)
        signal_history.record(symbol, 'COUNCIL_VERDICT', council_evt)

    return jsonify(verdict)


# ── /api/scan ─────────────────────────────────────────────────────────────────

@premium_bp.route('/scan', methods=['GET', 'POST'])
@x402_guard(price_usdc="0.05", description="Full universe market scan — squeeze signals and grade-A options picks across the $1-$50 universe (up to 250 symbols).")
def scan():
    """
    Full $1-$50 market scanner — live squeeze + options picks.
    Returns cached background scan results (updated every cycle).
    """
    from core.api.market_scanner import _scan_cache, _scan_lock

    with _scan_lock:
        data = {
            "quotes":       dict(_scan_cache["quotes"]),
            "options":      list(_scan_cache["options"]),
            "last_update":  _scan_cache["last_update"],
            "scan_count":   _scan_cache["scan_count"],
            "universe_size": len(_scan_cache["quotes"]),
            "ts": time.time(),
        }

    age = time.time() - data["last_update"] if data["last_update"] else None
    data["cache_age_seconds"] = round(age, 1) if age else None

    return jsonify(data)


# ── /api/options ──────────────────────────────────────────────────────────────

@premium_bp.route('/options', methods=['GET', 'POST'])
@x402_guard(price_usdc="0.05", description="Institutional options flow scanner — sweeps, whale detection, unusual volume, dark-pool prints. Tradier brokerage-grade feed.")
def options_flow():
    """
    Options intelligence — sweeps, whales, unusual volume for requested symbol.
    Default symbol: IWM
    """
    body = request.get_json(silent=True) or {}
    raw_symbol = body.get('symbol') or request.args.get('symbol', 'IWM')
    symbol, err = _validate_symbol(raw_symbol)
    if err:
        return err

    dm = get_service('dm')
    if not dm:
        return jsonify({"error": "data_manager offline"}), 503

    try:
        from options_intelligence import OptionsIntelligence
        oi = OptionsIntelligence()

        chain = dm.get_options_chain(symbol) if hasattr(dm, 'get_options_chain') else {}
        if not chain:
            return jsonify({"symbol": symbol, "error": "no chain data", "ts": time.time()}), 200

        result = oi.scan_symbol(symbol, chain)
        return jsonify({"symbol": symbol, "ts": time.time(), "flow": result})

    except Exception as e:
        logger.error(f"[OPTIONS] {e}")
        return jsonify({"symbol": symbol, "error": str(e), "ts": time.time()}), 500


# ── /api/iwm ──────────────────────────────────────────────────────────────────

@premium_bp.route('/iwm', methods=['GET', 'POST'])
@x402_guard(price_usdc="0.03", description="IWM 0DTE contract scorer — scored by delta/gamma profile, parity watch, realized vol, expiry-day institutional activity.")
def iwm():
    """
    IWM 0DTE institutional scanner — scored contracts, parity watch, regime.
    """
    dm = get_service('dm')
    if not dm:
        return jsonify({"error": "data_manager offline"}), 503

    try:
        from iwm_odte_engine import IwmOdteEngine
        engine = IwmOdteEngine(dm)

        chain = dm.get_options_chain('IWM') if hasattr(dm, 'get_options_chain') else {}
        bars  = clean_data(dm.get_bars('IWM', timeframe='1D', limit=30)) if hasattr(dm, 'get_bars') else []
        price_data = dm.get_quote('IWM') if hasattr(dm, 'get_quote') else {}
        underlying_price = float(price_data.get('last', price_data.get('close', 0)))

        rv = engine.get_realized_vol(bars) if bars else None

        scored = []
        if chain and underlying_price:
            for exp_key, exp_data in chain.items():
                for side in ('calls', 'puts'):
                    for contract in exp_data.get(side, []):
                        snap = exp_data.get('snapshots', {}).get(contract.get('symbol', ''), {})
                        s = engine.score_contract(contract, snap, underlying_price, rv)
                        if s:
                            scored.append(s)

        scored.sort(key=lambda x: x.get('score', 0), reverse=True)
        parity = engine.get_parity_watch(scored) if hasattr(engine, 'get_parity_watch') else []

        return jsonify({
            "symbol": "IWM",
            "underlying_price": underlying_price,
            "realized_vol": round(rv, 4) if rv else None,
            "top_contracts": scored[:20],
            "parity_watch": parity,
            "ts": time.time(),
        })

    except Exception as e:
        logger.error(f"[IWM] {e}")
        return jsonify({"symbol": "IWM", "error": str(e), "ts": time.time()}), 500
