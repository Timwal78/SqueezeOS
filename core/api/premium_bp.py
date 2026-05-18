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
import time
import logging
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.state import state, sse_queues


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

# proof402_integration.py lives at repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from proof402_integration import require_payment

logger = logging.getLogger("SqueezeOS-Premium")
premium_bp = Blueprint('premium', __name__)


# ── /api/council ─────────────────────────────────────────────────────────────

@premium_bp.route('/council', methods=['POST', 'GET'])
@require_payment
def council():
    """
    AI Council Verdict — multi-engine signal aggregate.
    Returns regime, bias, risk score, and actionable thesis for a symbol or IWM.
    """
    body = request.get_json(silent=True) or {}
    symbol = (body.get('symbol') or request.args.get('symbol', 'IWM')).upper()

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
                history = {"1D": bars}
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

    # Derive top-level verdict
    sml_data = verdict["engines"].get("sml", {})
    regime = sml_data.get("regime", "UNKNOWN")
    trend = sml_data.get("trend_score", 0)
    bias = "BULLISH" if trend > 0.2 else "BEARISH" if trend < -0.2 else "NEUTRAL"

    confidence = min(100, int(abs(trend) * 200))
    verdict["verdict"] = {
        "symbol": symbol,
        "bias": bias,
        "regime": regime,
        "confidence": confidence,
        "thesis": f"{symbol} regime={regime} trend_score={round(trend, 3)} → {bias}",
        "timestamp": time.time(),
    }

    _broadcast_sse({
        'type': 'COUNCIL_VERDICT',
        'symbol': symbol,
        'bias': bias,
        'regime': regime,
        'confidence': confidence,
        'ts': time.time(),
    })

    return jsonify(verdict)


# ── /api/scan ─────────────────────────────────────────────────────────────────

@premium_bp.route('/scan', methods=['GET', 'POST'])
@require_payment
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
@require_payment
def options_flow():
    """
    Options intelligence — sweeps, whales, unusual volume for requested symbol.
    Default symbol: IWM
    """
    body = request.get_json(silent=True) or {}
    symbol = (body.get('symbol') or request.args.get('symbol', 'IWM')).upper()

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
@require_payment
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
