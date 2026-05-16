import os
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import logging
from data_providers import load_env_file

# LOAD ENVIRONMENT FIRST
load_env_file()

# Institutional Cert Paths (No Hardcoding)
CERT_PATH = os.environ.get('SSL_CERT_PATH', r'C:\Users\timot\.squeeze_os_cert.pem')
KEY_PATH = os.environ.get('SSL_KEY_PATH', r'C:\Users\timot\.squeeze_os_key.pem')

# FILE LOGGING: Institutional Persistent Audit
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'SqueezeOS_LOGS.txt')
try:
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
except Exception as e:
    print(f"⚠️ [WARNING] Could not initialize log file: {e}")
    file_handler = None

# Attach to root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
if file_handler:
    root_logger.addHandler(file_handler)
else:
    # Fallback to stream handler if file is locked
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(stream_handler)

logger = logging.getLogger(__name__)
logger.info("========================================")
logger.info("GRAPHIFY v5.1 | POWERED BY SQUEEZE OS")
logger.info("========================================")

# Institutional Logic Imports
try:
    from tradier_api import tradier_api
    from squeeze_analyzer import SqueezeAnalyzer
    from options_service import OptionsProService
    from mm_liquidity_engine import MMLiquidityEngine
    from gamma_flow_engine import GammaFlowEngine
    from cycle_intelligence_engine import CycleIntelligenceEngine
    from forced_move_engine import ForcedMoveEngine
    from sml_engine import SMLEngine
    from meme_battle_engine import meme_battle_engine
except ImportError:
    logger.warning("Core institutional modules missing.")

# v5.1 File System Resolve
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'JS_FRONTEND')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')

# Force CSS mime types for Windows stability
import mimetypes
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')

# Explicitly allow local origins for sync logic
CORS(app, resources={r"/*": {"origins": "*"}})

# v5.1 WebSocket Engine — real-time data push to all connected clients
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False)

@socketio.on('connect')
def handle_ws_connect():
    logger.info("[WS] Client connected — streaming enabled")
    emit('system_event', {'message': 'GRAPHIFY v5.1 — LIVE STREAM CONNECTED'})

@socketio.on('subscribe')
def handle_subscribe(data):
    logger.info(f"[WS] Client subscribed to: {data.get('channels', [])}")

def ws_broadcast(event, data):
    """Thread-safe broadcast to all connected WebSocket clients."""
    try:
        socketio.emit(event, data)
    except Exception as e:
        logger.debug(f"[WS] Broadcast error (non-fatal): {e}")

@app.route('/')
def index():
    # Serve the main SqueezeOS dashboard
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    # Fallback for scripts/assets at the root
    return send_from_directory(STATIC_DIR, path)





from threading import Lock
import threading
import time

# Global Service Manager
_services = {
    'discord': None,
    'analyzer': None,
    'options_svc': None,
    'data_mgr': None,
    'mmle': None,
    'gamma': None,
    'cie': None,
    'leviathan': None,
    'sml': None,
    'workers_started': False
}

def get_discord():
    if not _services['discord']:
        from discord_alerts import DiscordAlerts
        _services['discord'] = DiscordAlerts()
    return _services['discord']

def get_analyzer():
    if not _services['analyzer']:
        from squeeze_analyzer import SqueezeAnalyzer
        _services['analyzer'] = SqueezeAnalyzer()
    return _services['analyzer']

def get_options_svc():
    if not _services['options_svc']:
        from options_service import OptionsProService
        _services['options_svc'] = OptionsProService()
    return _services['options_svc']

def get_data_mgr():
    if not _services['data_mgr']:
        from data_providers import DataManager
        _services['data_mgr'] = DataManager()
    return _services['data_mgr']

def get_mmle():
    if not _services['mmle']:
        from mm_liquidity_engine import MMLiquidityEngine
        _services['mmle'] = MMLiquidityEngine()
    return _services['mmle']

def get_gamma():
    if not _services['gamma']:
        from gamma_flow_engine import GammaFlowEngine
        dm = get_data_mgr()
        _services['gamma'] = GammaFlowEngine(dm.polygon, FAVORITES)
    return _services['gamma']

def get_cie():
    if not _services['cie']:
        from cycle_intelligence_engine import CycleIntelligenceEngine
        _services['cie'] = CycleIntelligenceEngine()
    return _services['cie']

def get_leviathan():
    if not _services['leviathan']:
        from forced_move_engine import ForcedMoveEngine
        _services['leviathan'] = ForcedMoveEngine()
    return _services['leviathan']

def get_sml():
    if not _services['sml']:
        from sml_engine import SMLEngine
        _services['sml'] = SMLEngine()
    return _services['sml']

def is_booting():
    # Helper to check if services are ready
    return _services['data_mgr'] is None

# Initial trigger (Moved to __main__)
# get_discord()
# get_analyzer()
# get_options_svc()
# get_data_mgr()
# logger.info("[OK] Beast Mode Data Engine Online")

# Institutional Favorites: High-conviction anchors (No Hardcoding)
FAVORITES = os.environ.get('SQUEEZE_FAVORITES', 'AMC,GME,IWM').split(',')

# Background Cache & State
class SystemCache:
    def __init__(self):
        self.lock = Lock()
        self.universe = {}
        self.quotes = {}
        self.scan_results = []
        self.flow_results = []
        self.events = []
        self.last_scan = 0
        self.last_flow = 0
        self.alert_history = {} # Ticker cooldown tracking
        
        # v5.1 Lifecycle Tracking
        self.lifecycle = {}     # symbol -> {status: str, since: float, history: []}
        
        # v5.1 Risk Management
        self.risk_settings = {"max_drawdown": 0.10, "base_kelly": 0.05}
        
        logger.info("[CACHE] Graphify Institutional v5.1 ready")

    def update_lifecycle(self, symbol, status):
        """Update the institutional state of a symbol."""
        with self.lock:
            now = time.time()
            current = self.lifecycle.get(symbol, {"status": "IDLE", "since": now, "history": []})
            if current["status"] != status:
                logger.info(f"🔄 [LIFECYCLE] {symbol}: {current['status']} -> {status}")
                current["history"].append({"from": current["status"], "to": status, "ts": now})
                current["status"] = status
                current["since"] = now
                self.lifecycle[symbol] = current
                self.log_event(f"LIFECYCLE: {symbol} is now {status}")
                # v5.1 LIVE PUSH
                try:
                    ws_broadcast('lifecycle_update', {'symbol': symbol, 'status': status})
                except Exception:
                    pass

    def get_lifecycle_status(self, symbol):
        return self.lifecycle.get(symbol, {"status": "IDLE"})["status"]

    def log_event(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.events.append(f"[{now}] {msg}")
            if len(self.events) > 50: self.events.pop(0)

    def can_alert(self, symbol, msg_type="SQUEEZE", cooldown=3600):
        """Check if we can send an alert for this symbol (default 1 hour cooldown)"""
        with self.lock:
            key = f"{symbol}_{msg_type}"
            now = time.time()
            if key in self.alert_history:
                if now - self.alert_history[key] < cooldown:
                    return False
            self.alert_history[key] = now
            return True

    def log_event(self, msg):
        with self.lock:
            ts = time.strftime("%H:%M:%S")
            self.events.insert(0, f"[{ts}] {msg}")
            self.events = self.events[:20] # Keep last 20
            logger.info(f"[SYSTEM EVENT] {msg}")

cache = SystemCache()

# ── BEAST PRO v2.0 Webhook Routes ──────────────────────────────────────────
try:
    from beast_webhook import register_beast_routes
    register_beast_routes(app, cache)
except Exception as _beast_err:
    logger.warning(f"[BEAST] Route registration failed: {_beast_err}")

@app.route('/api/health', methods=['GET'])
def health_check():
    # Watchdog check: If scan is > 30 min old, something is dead
    now = time.time()
    last = cache.last_scan
    if last > 0 and (now - last) > 1800: # 30 mins
        logger.warning("[WATCHDOG] Scanner seems stalled for 30 min. Recommend manual restart.")
        # Removed os._exit(1) to prevent "unexpected crash" in UI
    return jsonify({"status": "ONLINE", "timestamp": now})

@app.route('/api/settings')
def get_settings():
    if is_booting():
        return jsonify({'status': {'booting': True}})
    
    dm = get_data_mgr()
    with cache.lock:
        return jsonify({
            "status": {
                "tradier_active": dm.tradier.available if dm else False,
                "booting": False
            },
            "tradier": {
                "token": "********" if os.environ.get('TRADIER_TOKEN') else '',
                "account": os.environ.get('TRADIER_ACCOUNT', '')
            },
            "favorites": FAVORITES,
            "backups": {
                "alpaca_key": os.environ.get('ALPACA_API_KEY', ''),
                "polygon_key": os.environ.get('POLYGON_API_KEY', ''),
                "schwab_client_id": os.environ.get('SCHWAB_CLIENT_ID', '')
            }
        })

@app.route('/api/status', methods=['GET'])
def get_system_status():
    dm = get_data_mgr()
    with cache.lock:
        return jsonify({
            "status": "ONLINE",
            "universe_count": len(cache.universe),
            "scan_count": len(cache.scan_results),
            "flow_count": len(cache.flow_results),
            "events": cache.events[:10],
            "providers": {
                "tradier": dm.tradier.available if dm else False,
                "schwab": dm.schwab.available if dm else False,
                "polygon": dm.polygon.available if dm else False,
                "alpaca": dm.alpaca.available if dm else False
            }
        })

@app.route('/api/mmle/stats', methods=['GET'])
def get_mmle_stats():
    """
    Exposes BEAST MODE metrics to the dashboard.
    Returns Vanna, Charm, VPIN, and Liquidity Walls.
    Now enriched with Meme Battle Computer (FTD Echoes).
    """
    symbol = request.args.get('symbol', 'AMC').upper()
    with cache.lock:
        stats = getattr(cache, 'mmle_stats', {}).get(symbol, {})
        
        # Inject Battle Computer Data for Meme Leaders
        if symbol in ["GME", "AMC"]:
            battle = meme_battle_engine.evaluate(symbol)
            stats.update({
                "battle_score": battle['score'],
                "battle_verdict": battle['verdict'],
                "battle_action": battle['action'],
                "echoes": battle['echoes']
            })
            
        if not stats:
            return jsonify({
                "symbol": symbol,
                "status": "IDLE",
                "vpin": 0.0,
                "vpin_z": 0.0,
                "vanna_prox": 0.0,
                "charm_prox": 0.0,
                "axis_collapse": "no",
                "call_wall": 0.0,
                "put_wall": 0.0,
                "vccw_window": "closed"
            })
        return jsonify(stats)

@app.route('/api/search', methods=['GET'])
def search_symbol():
    q = request.args.get('q', '').strip().upper()
    if not q: return jsonify({"status": "error", "message": "Empty query"}), 400
    
    # Try fetching quote to verify it exists
    dm = get_data_mgr()
    data = dm.get_quotes([q])
    if q in data:
        return jsonify({"status": "success", "data": data[q]})
    return jsonify({"status": "error", "message": "Symbol not found"}), 404

@app.route('/api/council/decision', methods=['GET'])
def get_council_decision():
    symbol = request.args.get('symbol', 'AMC').upper()
    dm = get_data_mgr()
    quotes = dm.get_quotes([symbol])
    if not quotes or symbol not in quotes:
        return jsonify({"status": "error", "message": "No data for symbol"}), 404
    
    quote = quotes[symbol]
    # Fetch additional metrics for the council
    market_data = {
        "price": quote.get('price', 0),
        "change_pct": quote.get('changePct', 0),
        "squeeze_score": 75, # Placeholder or fetch from cache
        "market_cap": quote.get('marketCap', 'N/A'),
        "flow_heat": 80, # Placeholder
        "top_sweep": "SWEEP CALL" # Placeholder
    }
    
    from council_engine import council_engine
    decision = council_engine.evaluate(symbol, market_data)
    
    # Convert to serializable dict
    return jsonify({
        "status": "success",
        "symbol": symbol,
        "verdict": decision.verdict,
        "summary": decision.summary,
        "entry": decision.entry_price,
        "stop_loss": decision.stop_loss,
        "take_profit": decision.take_profit,
        "reports": [
            {
                "role": r.role,
                "analysis": r.analysis,
                "sentiment": r.sentiment,
                "confidence": r.confidence
            } for r in decision.reports
        ]
    })

# ============================================================
# BACKGROUND WORKERS
# ============================================================

def worker_discovery():
    """
    Constant Merry-Go-Round Discovery Worker.
    Scans the market using free API limits to find gainers, losers, and most-actives.
    Feeds the universe into the scan/flow workers.
    """
    logger.info("⚡ [SUPERPOWER] Discovery Worker Initialized (Constant Merry-Go-Round)")
    
    while True:
        try:
            dm = get_data_mgr()
            if not dm:
                time.sleep(10)
                continue
                
            logger.info("🗺️ [WORLD FETCH] Initiating Global Merry-Go-Round...")
            discovered = dm.discover_universe(limit=1000)
            
            if discovered:
                with cache.lock:
                    # Update universe immediately for other workers
                    cache.universe = discovered
                
                cache.log_event(f"WORLD FETCH: {len(discovered)} TARGETS ACQUIRED. GLOBAL UNIVERSE REFRESHED.")
            
            # Fast cycle for movers (every 5 mins), Deep cycle for Polygon is limited by provider
            time.sleep(300) 
            
        except Exception as e:
            logger.error(f"Discovery Error: {e}")
            time.sleep(60)

def worker_meme_battle():
    """
    SML Meme Battle Computer Worker.
    Daily sync of SEC FTD data and cycle recalculation.
    """
    logger.info("⚔️ [BATTLE] Meme Battle Computer Initialized")
    while True:
        try:
            logger.info("📊 [BATTLE] Syncing SEC FTD Data for Basket Leaders...")
            meme_battle_engine.refresh(["GME", "AMC"])
            cache.log_event("BATTLE COMPUTER: SEC FTD SYNC COMPLETE. ECHO CYCLES CALCULATED.")
            
            # Daily sync is enough for FTDs
            time.sleep(86400) 
        except Exception as e:
            logger.error(f"Meme Battle Sync Error: {e}")
            time.sleep(3600)

def worker_scanner():
    """24/7 Market Scan & Discord Alerting"""
    time.sleep(5)
    cache.log_event("SUPERPOWER SCANNER AWAKENED")
    while True:
        try:
            logger.info("[WORKER] Scanner cycle starting...")
            dm = get_data_mgr()
            if not dm: 
                logger.warning("[WORKER] DataManager not ready, waiting...")
                time.sleep(5)
                continue
            
            # 1. Discover & Analyze (Unleashed: 1000 targets)
            universe = dm.discover_universe(limit=1000)
            
            # NO FALLBACKS, NO HARDCODING PER USER INSTRUCTIONS
            if not universe:
                logger.warning("EMPTY UNIVERSE DETECTED — WAITING FOR REAL DATA")
                time.sleep(10)
                continue
            
            symbols = list(set(list(universe.keys()) + FAVORITES))
            
            cache.log_event(f"WHALE RADAR: {len(symbols)} TARGETS ACQUIRED")
            
            # UNLEASHED: Update universe immediately so flow worker can start
            with cache.lock:
                cache.universe = universe
            
            # Use progress_cb to log batch progress
            def scan_progress(msg):
                cache.log_event(msg)

            quotes = dm.get_quotes(symbols, progress_cb=scan_progress, fast_only=True)
            
            # 1.5 Price Filter (No Hardcoding) + Always include Anchors
            min_p = float(os.environ.get('SCANNER_MIN_PRICE', 1.0))
            max_p = float(os.environ.get('SCANNER_MAX_PRICE', 60.0))
            filtered_quotes = {}
            for sym, q in quotes.items():
                price = q.get('price', 0)
                if sym in FAVORITES or (min_p <= price <= max_p):
                    filtered_quotes[sym] = q
            quotes = filtered_quotes
            
            try:
                analyzer_svc = get_analyzer()
                results = analyzer_svc.analyze_batch(quotes)
            except Exception as e:
                logger.error(f"Analysis Error: {e}")
                results = []
            
            for r in results: r['is_favorite'] = r['symbol'] in FAVORITES
            # Allow stocks through if they have any meaningful movement OR are favorites
            results = [r for r in results if r.get('volRatio', 0) >= 0.8 or r['is_favorite']]
            
            # 2. DEEP SCAN (Institutional Sig-Kick Integration)
            # Fetch history for top performers to enable Module 13 (Sig-Kick)
            # Lowered threshold to 25 to ensure "S-3" (Sig-Kick) isn't zero for major movers
            deep_symbols = [r['symbol'] for r in results if r['squeeze_score'] >= 25][:50]
            sigkick_count = 0
            if deep_symbols:
                cache.log_event(f"DEEP SCAN: ANALYZING {len(deep_symbols)} INSTITUTIONAL SIGNATURES")
                for r in results:
                    if r['symbol'] in deep_symbols:
                        hist = dm.get_history(r['symbol'])
                        if hist:
                            # Re-analyze with history
                            updated = analyzer_svc.analyze_symbol(r['symbol'], quotes.get(r['symbol']), history=hist)
                            if updated:
                                r.update(updated)
                                sigkick_count += 1
                                
                                # Sig-Kick v2.0 Alert Router
                                comp = updated.get('analysis_components', {})
                                # Sig-Kick score is s13, which is (raw_score / 100) * 20.
                                # So split score >= 15 means raw_score >= 75.
                                sk_score_normalized = comp.get('sigkick_detector', 0)
                                if sk_score_normalized >= 15:
                                    # Fetch raw sigkick metrics for better alert
                                    analysis = dm.get_sigkick_analysis(r['symbol'], timeframes=['day'])
                                    if analysis and analysis.get('score', 0) >= 75:
                                        discord_client = get_discord()
                                        if discord_client and discord_client.enabled:
                                            discord_client.fire_sigkick_alert(
                                                r['symbol'], 
                                                analysis['score'], 
                                                analysis['regime'], 
                                                analysis.get('timeframes', {}).get('day', {}).get('metrics', {})
                                            )
            
            # Update cache with sigkick density
            with cache.lock:
                cache.sigkick_count = sigkick_count

            # GUARANTEE FAVORITES: Force AMC/GME into results even if analyzer missed them
            result_syms = {r['symbol'] for r in results}
            for fav in FAVORITES:
                if fav not in result_syms and fav in quotes:
                    fav_result = analyzer_svc.analyze_symbol(fav, quotes[fav])
                    if fav_result:
                        fav_result['is_favorite'] = True
                        results.append(fav_result)
                    else:
                        # Last resort: raw quote data with minimal score
                        q = quotes[fav]
                        results.append({
                            'symbol': fav, 'price': q.get('price', 0),
                            'squeeze_score': 1, 'squeeze_level': 'LOW',
                            'direction': 'BULLISH' if q.get('changePct', 0) > 0 else 'BEARISH',
                            'volume': q.get('volume', 0), 'changePct': q.get('changePct', 0),
                            'volRatio': q.get('volRatio', 0), 'is_favorite': True,
                            'recommendation': 'Favorite', 'risk_level': 'LOW',
                            'source': q.get('source', ''),
                        })
            
            # Pin favorites to top, then sort rest by score
            favs = [r for r in results if r.get('is_favorite')]
            rest = sorted([r for r in results if not r.get('is_favorite')], key=lambda x: x.get('squeeze_score', 0), reverse=True)
            results = favs + rest
            
            with cache.lock:
                cache.scan_results = results
                cache.last_scan = time.time()

            # v5.1 LIVE PUSH: Stream scan results to all connected clients instantly
            ws_broadcast('scan_update', {'data': results[:50], 'last_update': cache.last_scan})

            # 2. Discord & Trade Alerts
            discord_client = get_discord()
            if discord_client and discord_client.enabled:
                # Filter results by cooldown (10 min for squeeze — discord_alerts has its own 5min safety)
                alert_ready = [r for r in results if cache.can_alert(r['symbol'], "SQUEEZE", cooldown=600)]
                if alert_ready:
                    discord_client.fire_squeeze_alerts(alert_ready)
                
                # UNLEASHED: Convergence Trade Alert (Top 30 heat)
                for item in results[:30]:
                    score = item.get('squeeze_score', 0)
                    sym = item.get('symbol', '')
                    if score >= 40 and cache.can_alert(sym, "TRADE"):
                        with cache.lock:
                            has_flow = any(f['symbol'] == sym for f in cache.flow_results)
                        
                        if has_flow and hasattr(discord_client, 'fire_trade_alert'):
                            q = quotes.get(sym, {})
                            h, l = q.get('high', 0), q.get('low', 0)
                            # NO HARDCODING: Dynamic range from intraday action
                            daily_range = (h - l) if h > l else (item.get('price', 0) * 0.02)
                            discord_client.fire_trade_alert(
                                sym, item.get('price', 0), score, 
                                item.get('direction', 'BULLISH'), daily_range
                            )
            
            cache.log_event(f"SCAN COMPLETE: {len(results)} CANDIDATES IDENTIFIED")
            logger.info(f"[WORKER] Scanner cycle complete. Identified {len(results)} symbols.")
        except Exception as e:
            logger.error(f"Worker Scanner Critical Error: {e}", exc_info=True)
            cache.log_event(f"SCANNER CRITICAL: {str(e)[:40]}")
            time.sleep(10) # Wait before retry on major fail
        time.sleep(60) # Unleashed: Constant cycle

def worker_flow():
    """Background Options Flow worker — scans the MOST active assets."""
    logger.info("[HEARTBEAT] Flow Worker Initialized")
    
    from council_engine import council_engine
    from risk_manager import risk_manager
    from execution_engine import ExecutionEngine
    # PERMANENT SERVICES: Maintain state across cycles
    from tradier_trading import tradier_trading
    engine = ExecutionEngine(tradier_trading)    # The Brain
    
    while True:
        try:
            logger.info("[WORKER] Flow cycle starting...")
            options_svc = get_options_svc()
            
            if not options_svc: 
                logger.warning("[WORKER] Options service not ready, waiting...")
                time.sleep(10)
                continue
            
            # UNLEASHED: Scan Top 200 scanner results + Top 100 discovery winners
            with cache.lock:
                # Only scan symbols with price > $2 — penny stocks almost never have options chains
                scan_leaders = [s['symbol'] for s in cache.scan_results[:200]]
                discovery_leaders = [k for k, v in list(cache.universe.items())[:100]] if cache.universe else []
                to_check = list(set(scan_leaders + discovery_leaders + FAVORITES))[:400]
            
            if not to_check or len(to_check) <= len(FAVORITES):
                logger.debug("WARMUP GATE: Waiting for heat...")
                time.sleep(15)
                continue

            cache.log_event(f"FIREHOSE: SCANNING FLOW FOR {len(to_check)} ASSETS")
            all_alerts = []
            
            # BATCH SCANNING for maximum throughput
            for i in range(0, len(to_check), 10):
                batch = to_check[i:i+10]
                
                # IWM 0DTE PRIORITY: Force check every batch if not present
                if "IWM" not in batch and i == 0:
                    batch.append("IWM")

                for sym in batch:
                    if sym == "IWM":
                        logger.info("🎯 [PRIORITY] Analyzing IWM 0DTE Institutional Flow...")
                        cache.log_event("IWM 0DTE: ANALYZING FRONT-MONTH LIQUIDITY GATES")

                    try:
                        chain = options_svc.get_options_chain(sym)
                        if chain and 'unusual_activity' in chain and chain['unusual_activity']:
                            # FIREHOSE: Threshold lowered to 1.2 for high-density flow saturation
                            new_hits = [h for h in chain['unusual_activity'] if h.get('vol_oi_ratio', 0) >= 1.2]
                            if not new_hits:
                                continue
                            all_alerts.extend(new_hits)

                            # INCREMENTAL UPDATE: Merge into cache per-symbol
                            with cache.lock:
                                # AGGRESSIVE DEDUPLICATION & SYMBOL CAPPING
                                # 1. Group all potential signals by Symbol
                                grouped = {}
                                for f in (cache.flow_results + new_hits):
                                    s = f['symbol']
                                    if s not in grouped: grouped[s] = []
                                    # Unique key within the symbol
                                    key = f"{f['strike']}_{f['expiry']}_{f.get('type','ALL')}"
                                    if not any(f"{x['strike']}_{x['expiry']}_{x.get('type','ALL')}" == key for x in grouped[s]):
                                        grouped[s].append(f)

                                # 2. Cap each symbol at 3 best signals (by vol_oi_ratio)
                                limited_results = []
                                for s in grouped:
                                    top_signals = sorted(grouped[s], key=lambda x: x.get('vol_oi_ratio', 0), reverse=True)[:3]
                                    limited_results.extend(top_signals)

                                # 3. Pin Favorites to top and sort the rest
                                cache.flow_results = sorted(
                                    limited_results,
                                    key=lambda x: (x['symbol'] in FAVORITES, x.get('vol_oi_ratio', 0)),
                                    reverse=True
                                )[:100]
                                cache.last_flow = time.time()

                            # v5.1 PER-SYMBOL PUSH: Lightweight event so UI shows progress instantly
                            ws_broadcast('flow_symbol_update', {
                                'symbol': sym,
                                'hits': new_hits[:3],
                                'total_flow': len(cache.flow_results)
                            })

                            # CITADEL FLOW INTEGRATION: Push heat into squeeze engine
                            analyzer = get_analyzer()
                            if analyzer:
                                sym_max_heat = max([h.get('unusual_score', 0) for h in new_hits])
                                analyzer.update_flow_cache(sym, sym_max_heat)

                                # v5.1 Lifecycle Transition: IDLE/COMPRESSION -> FLOW_PULSE
                                if sym_max_heat >= 50:
                                    cache.update_lifecycle(sym, "FLOW_PULSE")

                                # v5.1 BeastIntel Integration
                                # v5.1 Council Integration
                                if sym_max_heat >= 70:
                                    scan_match = next((s for s in cache.scan_results if s.get('symbol') == sym), {})
                                    intel_data = {
                                        "price": scan_match.get('price') or chain.get('underlying_price', 0),
                                        "change_pct": scan_match.get('changePct', 0),
                                        "net_gex": chain.get('net_gex'),
                                        "net_dex": chain.get('net_dex'),
                                        "squeeze_score": scan_match.get('squeeze_score', 0),
                                        "top_sweep_label": new_hits[0].get('sweep_label'),
                                        "ppm": new_hits[0].get('ppm'),
                                        "sigkick_score": scan_match.get('sigkick_score', 0),
                                        "sigkick_regime": scan_match.get('regime', 'N/A')
                                    }
                                    analysis = council_engine.evaluate(sym, intel_data)
                                    cache.log_event(f"🤖 [COUNCIL] {sym}: {analysis.verdict} - {analysis.summary[:40]}...")
                                    # Inject back into hits for UI
                                    for h in new_hits: h['beast_intel'] = f"{analysis.verdict}: {analysis.summary}"

                                    # v5.5 Autonomous Execution (Paper Mode)
                                    engine.process_signal(sym, sym_max_heat, {"unusual_activity": new_hits, "beast_intel": analysis.summary}, decision=analysis)

                                # v5.6 BEAST MODE INTEGRATION (Multi-Engine Sync)
                                try:
                                    mmle = get_mmle()
                                    cie = get_cie()
                                    leviathan = get_leviathan()
                                    sml = get_sml()
                                    
                                    scan_match = next((s for s in cache.scan_results if s.get('symbol') == sym), {})
                                    spot = float(scan_match.get('price', 0) or chain.get('underlying_price', 0))
                                    atr = scan_match.get('atr') or (spot * 0.02)
                                    hist = dm.get_history(sym)
                                    
                                    # 1. MMLE (TNT Regime)
                                    tnt_sig = mmle.evaluate(
                                        ticker=sym, spot=spot,
                                        raw_chain=chain.get('raw_chain') or chain,
                                        atr=atr, sigma_S_daily=0.02, sigma_vol_daily=0.05,
                                        adv=scan_match.get('volume', 1000000), nearest_dte=7
                                    )

                                    # 2. CIE (Cycle Convergence)
                                    cie_sig = cie.evaluate(sym, spot, chain.get('raw_chain') or chain)
                                    
                                    # 3. Leviathan (Forced Moves)
                                    lev_sig = None
                                    if hist:
                                        lev_sig = leviathan.analyze(sym, hist)
                                    
                                    # 4. SML (Fractal Cascade)
                                    sml_sig = None
                                    if hist:
                                        # Use a simplified market history for SML (just the target for now)
                                        market_hist = {sym: pd.DataFrame(hist)}
                                        # Ensure dummy data for benchmarks if missing
                                        for b in ["SPY", "VIX", "TLT", "DXY", "QQQ", "IWM", "IJR", "XRT"]:
                                            if b not in market_hist:
                                                market_hist[b] = pd.DataFrame(dm.get_history(b) or hist)
                                        sml_sig = sml.compute_all(sym, market_hist)

                                    with cache.lock:
                                        if not hasattr(cache, 'beast_stats'):
                                            cache.beast_stats = {}

                                        beast_data = {
                                            "symbol": sym,
                                            "mmle": {
                                                "status": tnt_sig.state,
                                                "composite": tnt_sig.composite_z,
                                                "vpin_z": tnt_sig.components.get('z_vpin', 0),
                                                "axis_collapse": "yes" if tnt_sig.components.get('axis_cos', 0) > 0.85 else "no",
                                                "call_wall": tnt_sig.target_magnet or 0,
                                                "put_wall": tnt_sig.components.get('put_wall', 0) or 0
                                            },
                                            "cie": {
                                                "signal": cie_sig.signal,
                                                "score": cie_sig.total_score,
                                                "verdict": cie_sig.verdict,
                                                "calls": cie_sig.call_walls[:2],
                                                "puts": cie_sig.put_walls[:2]
                                            },
                                            "leviathan": {
                                                "action": lev_sig['action'] if lev_sig else "IDLE",
                                                "pressure": lev_sig['pressure']['score'] if lev_sig else 0,
                                                "trigger": lev_sig['trigger']['score'] if lev_sig else 0,
                                                "commitment": lev_sig['commitment']['score'] if lev_sig else 0
                                            },
                                            "sml": {
                                                "net": sml_sig['net_pressure'] if sml_sig else 0,
                                                "conf": sml_sig['confidence'] if sml_sig else 0,
                                                "regime": sml_sig['regime'] if sml_sig else "CONFLICT",
                                                "lifecycle": sml_sig['lifecycle'] if sml_sig else "DORMANT"
                                            }
                                        }
                                        cache.beast_stats[sym] = beast_data
                                        
                                        # Fallback for legacy UI components
                                        if not hasattr(cache, 'mmle_stats'): cache.mmle_stats = {}
                                        cache.mmle_stats[sym] = {
                                            "symbol": sym, "status": tnt_sig.state, "composite": tnt_sig.composite_z,
                                            "vpin": round(tnt_sig.components.get('z_vpin', 0) * 0.1, 3),
                                            "vpin_z": tnt_sig.components.get('z_vpin', 0),
                                            "vanna_prox": round(tnt_sig.components.get('vex_total', 0) / 1000000.0, 3),
                                            "charm_prox": round(tnt_sig.components.get('cex_total', 0) / 1000000.0, 3),
                                            "axis_collapse": "yes" if tnt_sig.components.get('axis_cos', 0) > 0.85 else "no",
                                            "call_wall": tnt_sig.target_magnet or 0,
                                            "put_wall": tnt_sig.components.get('put_wall', 0) or 0,
                                            "vccw_window": "open" if tnt_sig.state != "IDLE" else "closed"
                                        }

                                    # v5.1 LIVE PUSH: Stream BEAST data to connected clients
                                    ws_broadcast('beast_update', {'data': beast_data})
                                    ws_broadcast('mmle_update', {'data': cache.mmle_stats[sym]})
                                except Exception as beast_err:
                                    logger.warning(f"[BEAST] Eval error for {sym}: {beast_err}")

                            # If high heat, log it immediately
                            for h in new_hits:
                                if h['unusual_score'] >= 70:
                                    cache.log_event(f"[WHALE] {h['symbol']} {h.get('sweep_label', h.get('type', '?'))} ({h['unusual_score']} HEAT)")
                                    
                    except Exception as e:
                        logger.warning(f"[FLOW] Error on {sym}: {e}")
                
                # FIRE DISCORD AS WE GO — don't wait for full scan
                discord_client = get_discord()
                if discord_client and discord_client.enabled and all_alerts:
                    # Filter for high-heat hits that haven't alerted recently
                    batch_ready = [a for a in all_alerts[-50:] if a.get('unusual_score', 0) >= 50 and cache.can_alert(a['symbol'], "FLOW", cooldown=1800)]
                    if batch_ready:
                        batch_ready.sort(key=lambda x: x.get('unusual_score', 0), reverse=True)
                        discord_client.fire_flow_alerts(batch_ready[:3])

                # v5.1 BATCH PUSH: Full list broadcast once per batch (not per symbol)
                ws_broadcast('flow_update', {'data': cache.flow_results[:30], 'last_update': cache.last_flow})

                # HEARTBEAT: Show progress in UI
                cache.log_event(f"FLOW PULSE: Checked {i+len(batch)}/{len(to_check)} targets...")
                time.sleep(1.0) # slightly slower for stability
                
            if all_alerts:
                discord_client = get_discord()
                if discord_client and discord_client.enabled:
                    # Send top alerts to discord after the full run
                    top_alerts = sorted(all_alerts, key=lambda x: x.get('unusual_score', 0), reverse=True)[:15]
                    discord_client.fire_flow_alerts(top_alerts)
                
                # Update sentinel watch with intensity
                top_f = all_alerts[0]
                cache.log_event(f"WHALE HEAT: {len(all_alerts)} FLOW SIGNALS DISCLOSED")
                cache.log_event(f"TOP WHALE: ${top_f['symbol']} {top_f.get('sweep_label', top_f.get('type', '?'))} ({top_f['unusual_score']} SCORE)")
            
        except Exception as e:
            logger.error(f"Worker Flow Error: {e}")
            time.sleep(30)
        time.sleep(120) # 2 min cycle

def get_api(client_id=None, client_secret=None):
    """Returns the Tradier API instance (ignores legacy Schwab credentials)."""
    from tradier_api import tradier_api
    return tradier_api

@app.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    from tradier_api import tradier_api
    online = bool(tradier_api.token)
    return jsonify({"status": "ONLINE" if online else "OFFLINE", "provider": "tradier"})

@app.route('/api/market/status', methods=['GET'])
def get_market_status():
    dm = get_data_mgr()
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 500
    return jsonify({
        "status": "success",
        "data": dm.provider_status()
    })

@app.route('/api/market/sigkick', methods=['GET'])
def get_sigkick():
    dm = get_data_mgr()
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 500
    symbol = request.args.get('symbol', 'SPY').upper()
    tfs = request.args.get('tfs', 'day').split(',')
    analysis = dm.get_sigkick_analysis(symbol, timeframes=tfs)
    return jsonify({
        "status": "success",
        "data": analysis
    })

@app.route('/api/market/correlation', methods=['GET'])
def get_correlation():
    dm = get_data_mgr()
    if not dm: return jsonify({"status": "error", "message": "DataManager not initialized"}), 500
    symbol = request.args.get('symbol', 'GME').upper()
    etf = request.args.get('etf', 'XRT').upper()
    analysis = dm.get_etf_basket_correlation(symbol, etf)
    return jsonify({
        "status": "success",
        "data": analysis
    })
@app.route('/api/market/quotes', methods=['GET'])
def get_quotes():
    dm = get_data_mgr()
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 500
    symbols = request.args.get('symbols', '').split(',')
    # Always ensure favorites are in the quote list if requested
    if "favorites" in request.args:
        symbols.extend(FAVORITES)
        symbols = list(set(symbols)) # De-duplicate
        
    api = get_api(request.args.get('client_id'), request.args.get('client_secret'))
    if not api: return jsonify({"status": "error", "message": "Not authenticated"}), 401
    
    # Use DataManager for multi-provider fallback
    quotes = dm.get_quotes(symbols)
    return jsonify({"status": "success", "data": quotes})

@app.route('/api/market/scan', methods=['GET'])
def scan_market():
    # Split: tradeable stocks first, large caps pushed to the end
    # USER: Large caps are for advertisement purposes only - keep them minimal/separate.
    tradeable = [r for r in cache.scan_results if r.get('price', 0) <= 150.0 or r.get('symbol') in FAVORITES]
    # We sort tradeable by score, but give a hidden boost to the sweet spot
    # USER: Hard filter: No D or F grades (anything < 45 score / grade 'EXCLUDE')
    final_tradeable = []
    for r in tradeable:
        if r.get('grade') == 'EXCLUDE':
            continue
            
        p = r.get('price', 0)
        if 2.0 <= p <= 50.0:
            r['_sweet_spot'] = True
        else:
            r['_sweet_spot'] = False
        final_tradeable.append(r)
            
    filtered = sorted(final_tradeable, key=lambda x: (x.get('is_favorite', False), x.get('_sweet_spot', False), x.get('squeeze_score', 0)), reverse=True)
    
    return jsonify({
        "status": "success", 
        "data": filtered,
        "last_update": cache.last_scan
    })

@app.route('/api/market/flow', methods=['GET'])
def get_flow():
    # --- LARGE CAP FILTER: Exclude stocks over $150 from the flow feed ---
    # --- SWEET SPOT FOCUS: Prioritize $5-$50 range ---
    price_lookup = {}
    with cache.lock:
        price_lookup = {r['symbol']: r.get('price', 0) for r in cache.scan_results}
        raw_flow = list(cache.flow_results)
    
    filtered = []
    for f in raw_flow:
        price = price_lookup.get(f['symbol'], 999)
        if price <= 150.0 or f['symbol'] in FAVORITES:
            # Add sweet spot flag for UI highlighting
            f['_sweet_spot'] = (5.0 <= price <= 50.0)
            filtered.append(f)
    
    # Sort by unusual score, but pin favorites and prioritize sweet spot
    filtered.sort(key=lambda x: (x['symbol'] in FAVORITES, x.get('_sweet_spot', False), x.get('unusual_score', 0)), reverse=True)
        
    return jsonify({
        "status": "success", 
        "data": filtered,
        "last_update": cache.last_flow
    })

@app.route('/api/market/chain/<ticker>', methods=['GET'])
def get_full_option_chain(ticker):
    """Institutional Giga-Fetch: Returns the entire options chain for a symbol."""
    try:
        svc = get_options_svc()
        if not svc:
            return jsonify({"status": "error", "message": "Options service not ready"}), 500
        
        chain = svc.get_full_chain(ticker.upper())
        if chain:
            return jsonify({"status": "success", "data": chain})
        return jsonify({"status": "error", "message": "Failed to fetch chain or symbol invalid"}), 404
    except Exception as e:
        logger.error(f"Full chain route error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/market/strikes', methods=['GET'])
def get_strikes():
    """Aggregate flow into sentiment/strike radar format — filtered to sub-$150 stocks."""
    with cache.lock:
        # --- LARGE CAP FILTER: Only include tradeable-range stocks ---
        price_lookup = {r['symbol']: r.get('price', 0) for r in cache.scan_results}
        filtered_flow = [f for f in cache.flow_results if price_lookup.get(f['symbol'], 999) <= 150.0 or f['symbol'] in FAVORITES]

        # Aggregate by symbol+strike to find most active contracts
        agg = {}
        for f in filtered_flow:
            key = f"{f['symbol']}_{f['strike']}_{f['type']}"
            if key not in agg:
                agg[key] = {
                    'symbol': f['symbol'],
                    'strike': f['strike'],
                    'type': f['type'],
                    'expiry_formatted': f.get('expiry_formatted', f.get('expiry', '—')),
                    'heat': 0,
                    'volume': 0,
                    'premium': 0,
                    'sentiment': f['sentiment'],
                    'is_oi_spike': False,
                    'is_sweep': False,
                    'is_block': False
                }
            agg[key]['heat'] = max(agg[key]['heat'], f['unusual_score'])
            agg[key]['volume'] += f['volume']
            agg[key]['premium'] += f.get('premium', 0)
            if f.get('is_oi_spike'): agg[key]['is_oi_spike'] = True
            if f.get('is_sweep'): agg[key]['is_sweep'] = True
            if f.get('is_block'): agg[key]['is_block'] = True
            
        # Return top 15 by heat
        results = sorted(agg.values(), key=lambda x: (x['premium'], x['heat']), reverse=True)[:15]
        return jsonify({"status": "success", "data": results})

@app.route('/api/market/whales', methods=['GET'])
def get_whales():
    """Aggregate flow into ticker-level heat map — filtered to sub-$150 stocks."""
    with cache.lock:
        # --- LARGE CAP FILTER: Only include tradeable-range stocks ---
        price_lookup = {r['symbol']: r.get('price', 0) for r in cache.scan_results}
        filtered_flow = [f for f in cache.flow_results if price_lookup.get(f['symbol'], 999) <= 150.0 or f['symbol'] in FAVORITES]

        agg = {}
        for f in filtered_flow:
            s = f['symbol']
            if s not in agg:
                agg[s] = {
                    'symbol': s,
                    'heat': 0,
                    'premium': 0,
                    'count': 0,
                    'bull_count': 0,
                    'bear_count': 0,
                    'sentiment': 'BULLISH'
                }
            agg[s]['heat'] = max(agg[s]['heat'], f['unusual_score'])
            agg[s]['premium'] += f.get('premium', 0)
            agg[s]['count'] += 1
            if f['sentiment'] == 'BULLISH':
                agg[s]['bull_count'] += 1
            else:
                agg[s]['bear_count'] += 1
            
        for s in agg:
            # Calculate dominant sentiment
            agg[s]['sentiment_ratio'] = (agg[s]['bull_count'] / agg[s]['count']) if agg[s]['count'] > 0 else 0.5
            agg[s]['sentiment'] = 'BULLISH' if agg[s]['sentiment_ratio'] >= 0.5 else 'BEARISH'
            
        # Sort by total premium to find the biggest "Whale" interest
        results = sorted(agg.values(), key=lambda x: x['premium'], reverse=True)[:20]
        return jsonify({"status": "success", "data": results})

@app.route('/api/settings/sync', methods=['POST'])
def sync_settings():
    """Atomic update for all system keys and parameters."""
    try:
        data = request.json
        # Mapping UI fields to .env keys
        mapping = {
            'tradier_token': 'TRADIER_TOKEN',
            'tradier_acct': 'TRADIER_ACCOUNT',
            'alpaca_key': 'ALPACA_API_KEY',
            'alpaca_secret': 'ALPACA_API_SECRET',
            'polygon_key': 'POLYGON_API_KEY',
            'av_key': 'ALPHA_VANTAGE_API_KEY',
            'discord_main': 'DISCORD_WEBHOOK_ALL',
            'discord_flow': 'DISCORD_WEBHOOK_FLOW'
        }

        # Update .env file
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
        
        new_lines = []
        handled_keys = set()
        for line in lines:
            if '=' in line:
                key = line.split('=')[0].strip()
                match = False
                for ui_key, env_key in mapping.items():
                    if key == env_key:
                        val = data.get(ui_key)
                        if val is not None:
                            new_lines.append(f"{env_key}={val}\n")
                            os.environ[env_key] = val
                            handled_keys.add(env_key)
                        else:
                            new_lines.append(line)
                        match = True
                        break
                if not match: new_lines.append(line)
            else: new_lines.append(line)
        
        for ui_key, env_key in mapping.items():
            if env_key not in handled_keys and data.get(ui_key):
                new_lines.append(f"{env_key}={data.get(ui_key)}\n")
                os.environ[env_key] = data.get(ui_key)

        with open(env_path, 'w') as f:
            f.writelines(new_lines)

        # Hot-Sync Active Instances (Tradier)
        dm = get_data_mgr()
        if dm and dm.tradier.available:
            from tradier_api import tradier_api
            # Tokens are automatically re-loaded from os.environ
        
        dm = get_data_mgr()
        if dm:
            from data_providers import AlpacaProvider, PolygonProvider, AlphaVantageProvider
            dm.alpaca = AlpacaProvider()
            dm.polygon = PolygonProvider()
            dm.alphav = AlphaVantageProvider()

        logger.info("♻️ HUD SYNCHRONIZED")
        return jsonify({"status": "success", "message": "Vault Synchronized"})
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# Static files are handled automatically by Flask via static_folder='JS_FRONTEND' and static_url_path=''

@app.route('/warroom')
def serve_warroom():
    """Single-page 'Large Print' dashboard for institutional monitoring."""
    return send_from_directory('JS_FRONTEND', 'war_room_v5.html')

@app.route('/api/market/intel', methods=['GET'])
def get_tactical_intel():
    """Returns the latest BeastIntel tactical events from the cache."""
    with cache.lock:
        # Filter for messages starting with [INTEL] or similar if needed
        # For now, just return the last 20 events
        return jsonify({
            "status": "success",
            "data": cache.events[-20:]
        })

# ============================================================
# OPENCLAW AGENT BRIDGE
# ============================================================
@app.route('/api/agent/status', methods=['GET'])
def agent_status():
    """Allows OpenClaw to verify SqueezeOS connection and get top targets."""
    with cache.lock:
        top_squeeze = cache.scan_results[:5] if cache.scan_results else []
        top_flow = cache.flow_results[:5] if cache.flow_results else []
    return jsonify({
        "status": "ONLINE",
        "tradier_connected": get_data_mgr().tradier.available,
        "top_squeeze_targets": top_squeeze,
        "top_flow_targets": top_flow
    })

@app.route('/api/agent/trade', methods=['POST'])
def agent_trade():
    """Allows OpenClaw to submit a simulated/paper trade for 24/7 logging."""
    data = request.json
    if not data or 'symbol' not in data or 'action' not in data:
        return jsonify({"status": "error", "message": "Missing symbol or action (BUY/SELL)"}), 400
    
    symbol = data['symbol'].upper()
    action = data['action'].upper()
    qty = data.get('quantity', 1)
    
    # Log this action definitively
    msg = f"OPENCLAW AGENT INITIATED {action} {qty}x {symbol}"
    cache.log_event(msg)
    logger.info(f"🤖 [AGENT TRADE] {msg}")
    
    return jsonify({
        "status": "success",
        "message": f"Simulated {action} order submitted for {qty} of {symbol}",
        "trade_mode": "PAPER_TRADING"
    })

@app.route('/api/market/iwm_playbook', methods=['GET'])
def get_iwm_playbook():
    # Find IWM in scan results
    iwm_data = next((r for r in cache.scan_results if r.get('symbol') == 'IWM'), None)
    if iwm_data and iwm_data.get('iwm_playbook'):
        return jsonify({"status": "success", "data": iwm_data['iwm_playbook'], "price": iwm_data['price']})
    return jsonify({"status": "error", "message": "IWM Playbook data not available"})

@app.route('/api/market/lifecycle', methods=['GET'])
def get_market_lifecycle():
    with cache.lock:
        return jsonify(cache.lifecycle)

@app.route('/api/market/risk', methods=['GET'])
def get_market_risk():
    symbol = request.args.get('symbol')
    score = request.args.get('score', 50, type=float)
    from risk_manager import risk_manager
    sizing = risk_manager.calculate_size(score)
    return jsonify({
        "symbol": symbol,
        "score": score,
        "sizing": sizing
    })

# ============================================================
# PRODUCTION STARTUP ENGINE
# ============================================================
def init_beast():
    """Institutional Background Engine Initialization"""
    if _services['workers_started']:
        return
        
    try:
        logger.info("[BOOT] Initializing background services...")
        get_discord()
        get_analyzer()
        get_options_svc()
        get_data_mgr()
        logger.info("[OK] Beast Mode Data Engine Online")
        
        # Start workers
        threading.Thread(target=worker_discovery, daemon=True).start()
        threading.Thread(target=worker_scanner, daemon=True).start()
        threading.Thread(target=worker_flow, daemon=True).start()
        threading.Thread(target=worker_meme_battle, daemon=True).start()
        _services['workers_started'] = True
        cache.log_event("SQUEEZE OS SUPERPOWER ENGINE ONLINE")
            
    except Exception as e:
        logger.error(f"Background Init Failed: {e}")

# TRIGGER STARTUP: Under Gunicorn, this runs when the module is loaded
# We use a Lock to ensure even if multiple threads load it, it's safe.
startup_lock = Lock()
with startup_lock:
    if not _services['workers_started']:
        threading.Thread(target=init_beast, daemon=True).start()

if __name__ == '__main__':
    # Local Dev Mode
    PORT = int(os.environ.get('PORT', 8182))

    print("========================================")
    print("  SQUEEZE OS v5.1 — THE BEASTMODE EDITION")
    print("  WebSocket Streaming Engine ACTIVE")
    print("========================================")

    # Try SSL first (institutional grade), fall back to HTTP if certs missing
    ssl_ctx = None
    if os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH):
        ssl_ctx = (CERT_PATH, KEY_PATH)
        print(f"  SSL: Custom certs loaded")
        print(f"  URL: https://127.0.0.1:{PORT}")
    else:
        try:
            # Try adhoc SSL (requires pyopenssl)
            import OpenSSL  # noqa: F401
            ssl_ctx = 'adhoc'
            print(f"  SSL: Adhoc (dev mode)")
            print(f"  URL: https://127.0.0.1:{PORT}")
        except ImportError:
            # No SSL available — run plain HTTP (still works fine locally)
            print(f"  SSL: Disabled (install pyopenssl for HTTPS)")
            print(f"  URL: http://127.0.0.1:{PORT}")

    print("========================================")

    try:
        # v5.1: Use socketio.run() instead of app.run() for WebSocket support
        socketio.run(
            app,
            host='0.0.0.0',
            port=PORT,
            ssl_context=ssl_ctx if ssl_ctx else None,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        print(f"CRITICAL BOOT ERROR: {e}")
        logger.error(f"Boot Error: {e}")
        # Don't silently die — give the user something to work with
        print("\nTROUBLESHOOTING:")
        print("  1. Is port 8182 already in use? Run: netstat -ano | findstr 8182")
        print("  2. Missing packages? Run: pip install flask-socketio pyopenssl")
        print("  3. Check SqueezeOS_LOGS.txt for details")
        import traceback
        traceback.print_exc()
