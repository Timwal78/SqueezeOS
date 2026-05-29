from flask import Blueprint, jsonify, request
import os
import time
import threading
import logging
from core.state import state
from core.legacy import mmle, clean_data, get_service

logger = logging.getLogger("SqueezeOS-MMLE")
mmle_bp = Blueprint('mmle', __name__)

_vix_cache = {"vix": None, "vix9d": None, "vvix": None, "ts": 0}
_VIX_TTL = 60  # seconds

def _fetch_vix_data():
    """Pull VIX, VIX9D, VVIX from Tradier/Polygon (best-effort)."""
    global _vix_cache
    try:
        # Use Polygon for indices if possible
        poly_key = os.getenv("POLYGON_API_KEY", "")
        if poly_key:
            import requests as _req
            for sym, key in [("I:VIX", "vix"), ("I:VIX9D", "vix9d"), ("I:VVIX", "vvix")]:
                try:
                    r = _req.get(
                        f"https://api.polygon.io/v2/last/trade/{sym}",
                        params={"apiKey": poly_key}, timeout=5
                    )
                    if r.ok:
                        _vix_cache[key] = r.json().get("results", {}).get("p")
                except Exception:
                    pass
        _vix_cache["ts"] = time.time()
    except Exception as e:
        logger.warning(f"[MMLE] VIX fetch failed: {e}")

def _get_bars_from_tradier(symbol: str, limit: int = 200):
    """Fetch recent 1-min bars from Tradier timesales for MMLE analysis."""
    try:
        tradier_key = os.getenv("TRADIER_PRODUCTION_API_KEY") or os.getenv("TRADIER_API_KEY", "")
        if not tradier_key:
            return []
        import requests as _req
        h = {"Authorization": f"Bearer {tradier_key}", "Accept": "application/json"}
        # Fallback to sandbox if not live
        is_live = os.environ.get('TRADIER_LIVE', 'false').lower() == 'true'
        base_url = "https://api.tradier.com/v1" if is_live else "https://sandbox.tradier.com/v1"
        
        r = _req.get(
            f"{base_url}/markets/timesales",
            params={"symbol": symbol, "interval": "1min", "session_filter": "all"},
            headers=h, timeout=8
        )
        if not r.ok:
            return []
        data = r.json().get("series", {}).get("data", [])
        if not data:
            return []
        bars = []
        for d in data[slice(-limit, None)]:
            c = float(d.get("close", 0))
            bars.append({
                "open":   float(d.get("open", c)),
                "high":   float(d.get("high", c)),
                "low":    float(d.get("low", c)),
                "close":  c,
                "volume": float(d.get("volume", 0)),
            })
        return bars
    except Exception as e:
        logger.warning(f"[MMLE] Bar fetch failed for {symbol}: {e}")
        return []

@mmle_bp.route('/<symbol>', methods=['GET'])
def api_mmle(symbol):
    """
    MMLE Beast Mode analysis for a symbol.
    Returns VPIN, Axis Collapse, TNT State, Call/Put Walls, Composite Score.
    """
    symbol = symbol.upper().strip()
    if not mmle:
        return jsonify({"status": "error", "message": "MMLE Engine not loaded"}), 500

    # Optional Python override from query params
    override = {}
    if request.args.get("override_state"):
        override["state"] = request.args.get("override_state")
    if request.args.get("call_wall"):
        try: override["call_wall"] = float(request.args.get("call_wall"))
        except ValueError: pass
    if request.args.get("put_wall"):
        try: override["put_wall"] = float(request.args.get("put_wall"))
        except ValueError: pass

    # Refresh VIX cache if stale
    if time.time() - _vix_cache["ts"] > _VIX_TTL:
        threading.Thread(target=_fetch_vix_data, daemon=True).start()

    bars = _get_bars_from_tradier(symbol)
    if not bars:
        return jsonify({"error": f"No bar data available for {symbol}", "symbol": symbol}), 503

    result = mmle.analyze(
        symbol=symbol,
        bars=bars,
        vix_data=_vix_cache if _vix_cache["vix"] else None,
        python_override=override or None,
    )
    
    # Store in global state for telemetry
    with state.lock:
        state.beast_signals = clean_data([result]) + state.beast_signals
        if len(state.beast_signals) > 50:
            del state.beast_signals[50:]
        
    return jsonify(clean_data(result))

@mmle_bp.route('/vix', methods=['GET'])
def api_mmle_vix():
    """Return cached VIX / VIX9D / VVIX values."""
    if time.time() - _vix_cache["ts"] > _VIX_TTL:
        _fetch_vix_data()
    return jsonify(_vix_cache)

@mmle_bp.route('/cascade/<symbol>', methods=['GET'])
def get_cascade(symbol):
    """
    Fractal Cascade multi-timeframe alignment.
    Mapped from legacy server_v5 to support mobile battle computer.
    """
    symbol = symbol.upper().strip()
    sml = get_service("sml")
    dm = get_service("dm")
    
    if not sml or not dm:
        return jsonify({"status": "error", "message": "SML or Data service unavailable"}), 503
    
    try:
        # Get history from data provider
        history = dm.get_history(symbol)
        if not history:
            return jsonify({"status": "error", "message": f"No history available for {symbol}"}), 404
        
        # Compute cascade
        data = sml.compute_fractal_cascade(symbol, {symbol: history})
        
        return jsonify(clean_data({
            "status": "success",
            "data": data
        }))
    except Exception as e:
        logger.error(f"Cascade computation failed for {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
