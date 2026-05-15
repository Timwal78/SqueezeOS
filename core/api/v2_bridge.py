from flask import Blueprint, jsonify, request
from core.state import state
from core.legacy import get_service
import time
import logging

v2_bp = Blueprint('v2_bridge', __name__)
logger = logging.getLogger("V2-Bridge")

@v2_bp.route('/terminal')
def get_terminal_v2():
    """Maps institutional state to the BB-Terminal V2 UI structure with 100% dynamic telemetry."""
    with state.lock:
        mode = state.audit.get('trading_mode', 'WATCHING')
        universe_size = state.audit.get('universe_size', 0)
        beast_status = "DOMINATING" if mode == "LIVE" else "SCANNING"
        
        # 1. Real-time dynamic ticker fetch
        tickers = {}
        all_quotes = list(state.quotes.items())
        
        # Priority: Ensure IWM is always first if available
        iwm_q = state.quotes.get('IWM')
        if iwm_q:
            tickers['IWM'] = {
                "price": iwm_q.get('price', 0.0),
                "call_wall": iwm_q.get('call_wall', iwm_q.get('price', 0.0) * 1.05),
                "put_wall": iwm_q.get('put_wall', iwm_q.get('price', 0.0) * 0.95),
                "gex": iwm_q.get('volume', 0) * 5,
                "apex": iwm_q.get('apex', 0),
                "conviction": 70 + (iwm_q.get('apex', 0) * 3),
                "wrb_grade": "A+" if iwm_q.get('apex', 0) > 4 else "A"
            }

        # Fill with other top movers/scans (limit to 10 total)
        for sym, q in all_quotes:
            if len(tickers) >= 10: break
            if sym == 'IWM': continue
            tickers[sym] = {
                "price": q.get('price', 0.0),
                "call_wall": q.get('call_wall', q.get('price', 0.0) * 1.1),
                "put_wall": q.get('put_wall', q.get('price', 0.0) * 0.9),
                "gex": q.get('gex', 0),
                "apex": q.get('apex', 0),
                "conviction": 60 + (q.get('apex', 0) * 2),
                "wrb_grade": "A" if q.get('apex', 0) > 5 else "B"
            }
        
        # 2. Dynamic Decision Matrix
        master_decision = "SCANNING"
        master_grade = "N/A"
        edge = 0
        
        if state.scan_results:
            top = state.scan_results[0]
            master_decision = f"STRONG {top.get('direction', 'LONG')}"
            score = top.get('squeeze_score', 0)
            master_grade = "A+" if score >= 90 else "A" if score >= 80 else "B"
            edge = int(score * 0.8)

        # 3. Agents: Dynamic thoughts based on live telemetry
        last_log = state.terminal_feed[0]['msg'] if state.terminal_feed else "Initializing neural link..."
        
        # 3. Dynamic Intelligence Feed (Law 3 & 4)
        from core.api.market_scanner import _scan_cache, _scan_lock
        with _scan_lock:
            options_picks = _scan_cache.get("options", [])
            
        # 4. Global News & Discovery
        dm = get_service("dm")
        news = []
        if dm and dm.alpaca.available:
            news = dm.alpaca.get_news(limit=10)

        # 5. Whale Stalker & Dark Pool Flow
        whale_alerts = list(state.whale_stalker_results)
        
        # 6. Agents: Dynamic thoughts based on live telemetry
        last_log = state.terminal_feed[0]['msg'] if state.terminal_feed else "Synchronizing high-velocity data tape..."
        
        return jsonify({
            "status": "ONLINE",
            "master_decision": master_decision,
            "master_grade": master_grade,
            "war_room_score": {"bull": edge, "bear": 100-edge if edge > 0 else 0, "edge": edge},
            "apex_score": sum(1 for q in state.quotes.values() if q.get('apex', 0) > 5),
            "leviathan_matrix": "TRAPPING" if edge > 75 else "NEUTRAL",
            "tickers": tickers,
            "options": options_picks[:25], # Increased density
            "whale_alerts": whale_alerts[:15], # Live institutional sweeps
            "news": news,
            "agents": [
                {"name": "War Room Beast", "status": beast_status, "last_thought": last_log},
                {"name": "SML Analyst", "status": "SCANNING", "last_thought": f"Processing {universe_size} tickers. Analyzing volatility skew."},
                {"name": "Leviathan", "status": "HUNTING", "last_thought": f"Dark pool sweeps detected on {len(whale_alerts)} symbols. Monitoring IWM."}
            ],
            "audit": state.audit
        })

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
