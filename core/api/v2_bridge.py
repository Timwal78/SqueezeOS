from flask import Blueprint, jsonify, request
from core.state import state
from core.legacy import get_service
import time
import logging

v2_bp = Blueprint('v2_bridge', __name__)
logger = logging.getLogger("V2-Bridge")

@v2_bp.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "bridge": "v2_institutional",
        "universe": state.audit.get('universe_size', 0),
        "uptime": time.time() - state.audit.get('uptime_start', time.time())
    })

# ────── Equity V1 Legacy Support ──────

@v2_bp.route('/equity/price/quote')
def get_quote():
    symbol = request.args.get('symbol', '').upper()
    dm = get_service("dm")
    if not dm or not dm.tradier.available:
        return jsonify({"results": []})
    q = dm.tradier.get_quotes([symbol])
    return jsonify({"results": [q.get(symbol, {})]})

@v2_bp.route('/equity/price/historical')
def get_historical():
    symbol = request.args.get('symbol', '').upper()
    interval = request.args.get('interval', '1Day') # Standardize on 1Day
    if interval == '1d': interval = '1Day'
    
    dm = get_service("dm")
    if not dm:
        return jsonify({"results": []})
        
    # Standardize historical fetch across providers
    h = dm.get_historical_bars(symbol, timeframe=interval)
    
    # Map Alpaca/Tradier keys to UI-expected keys (date, open, high, low, close, volume)
    mapped = []
    for bar in h:
        mapped.append({
            "date": bar.get("t") or bar.get("date") or bar.get("datetime") or bar.get("timestamp"),
            "open": bar.get("o") or bar.get("open", 0),
            "high": bar.get("h") or bar.get("high", 0),
            "low": bar.get("l") or bar.get("low", 0),
            "close": bar.get("c") or bar.get("close", 0),
            "volume": bar.get("v") or bar.get("volume", 0)
        })
    return jsonify({"results": mapped})

@v2_bp.route('/news/company')
def get_company_news():
    dm = get_service("dm")
    if not dm or not dm.alpaca.available:
        return jsonify({"results": []})
    n = dm.alpaca.get_news(limit=10)
    return jsonify({"results": n})
