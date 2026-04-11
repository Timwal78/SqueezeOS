import os
import json
import time
import threading
import logging
import math
import random
import typing
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from threading import Lock
from data_providers import load_env_file, DataManager
from schwab_api import schwab_api
from discord_alerts import DiscordAlerts
from options_intelligence import OptionsIntelligence
from forced_move_engine import ForcedMoveEngine
from mean_reversion_engine import MeanReversionEngine

# --- INITIALIZATION ---
load_env_file()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SqueezeOS-v5")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- MANIFESTO LAWS ---
FAVORITES = ["AMC", "GME", "PLTR", "AMD", "NIO", "SOFI", "RIOT", "MARA"]
MEGA_CAPS = {
    'AAPL', 'MSFT', 'GOOG', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'LLY', 'V', 'MA', 'AVGO', 'HD', 'COST',
    'JPM', 'UNH', 'WMT', 'BAC', 'XOM', 'CVX', 'PG', 'ORCL', 'ABBV', 'CRM', 'ADBE', 'NFLX', 'AMD', 'INTC', 'DIS',
    'PFE', 'KO', 'PEP', 'CSCO', 'TMO', 'AZN', 'NKE', 'ABT', 'LIN', 'DHR', 'WFC', 'MRK', 'VZ', 'T', 'NVR', 'BKNG'
}
RULE_3_LIMIT = 3

# Broad Liquid Universe for Discovery
LIQUID_MID_CAPS = [
    "AMD", "PLTR", "SOFI", "RIOT", "MARA", "NIO", "AMC", "GME", "DKNG", "SNAP", "UBER", "PYPL", "SQ", "AFRM", "COIN",
    "AAL", "CCL", "DAL", "UAL", "XOM", "CVX", "OXY", "SLB", "HAL", "RIVN", "LCID", "F", "GM", "BAC", "WFC", "JPM", "C",
    "T", "VZ", "VZ", "PFE", "MRNA", "ABBV", "PINS", "OPEN", "CHPT", "LUV", "SAVE", "JBLU", "MU", "TXL", "KVUE"
]

# --- GLOBAL STATE ---
class GlobalState:
    def __init__(self):
        self.lock = Lock()
        self.universe = {}
        self.quotes = {}
        self.scan_results: list[dict] = []
        self.flow_results: list[dict] = []
        self.terminal_feed: list[dict] = [] 
        self.last_scan_ts: float = 0.0
        self.last_flow_ts: float = 0.0
        self.alert_history: dict[str, float] = {}
        self.heartbeats: dict[str, float] = {"scanner": 0.0, "flow": 0.0, "discovery": 0.0}
        self.beast_signals: list[dict] = []
        self.discovery_results: list[dict] = []
        self.last_discovery_ts: float = 0.0
        self.audit = {
            "universe_size": 0,
            "mega_caps_filtered": 0,
            "uptime_start": time.time(),
            "trading_mode": "SHADOW"
        }

    def push_terminal(self, event_type: str, msg: str, symbol: str = '', score: float = 0.0, extra: typing.Optional[dict] = None):
        with self.lock:
            entry = {
                'type': event_type, 
                'msg': msg, 
                'symbol': symbol, 
                'score': score, 
                'ts': time.time(),
                'time_str': time.strftime('%H:%M:%S')
            }
            if extra: entry.update(extra)
            self.terminal_feed.insert(0, entry)
            if len(self.terminal_feed) > 200:
                self.terminal_feed = self.terminal_feed[:200]

    def push_flow(self, flow_data: dict):
        with self.lock:
            key = f"{flow_data['symbol']}_{flow_data['strike']}_{flow_data['type']}_{flow_data.get('expiry_formatted','')}"
            now = time.time()
            self.flow_results = [f for f in self.flow_results if now - f.get('seen_time', 0) < 3600]
            for existing in self.flow_results:
                existing_key = f"{existing['symbol']}_{existing['strike']}_{existing['type']}_{existing.get('expiry_formatted','')}"
                if existing_key == key:
                    return
            flow_data['seen_time'] = now
            self.flow_results.insert(0, flow_data)
            if len(self.flow_results) > 500:
                self.flow_results = self.flow_results[:500]

    def can_alert(self, key, cooldown=3600):
        with self.lock:
            now = time.time()
            if key in self.alert_history and (now - self.alert_history[key] < cooldown):
                return False
            self.alert_history[key] = now
            return True

state = GlobalState()

# --- SERVICE LAYER ---
_services = {}
def get_service(name):
    with state.lock:
        return _services.get(name)

def init_services():
    try:
        from squeeze_analyzer import SqueezeAnalyzer
        from options_service import OptionsProService
        from gamma_flow_engine import GammaFlowEngine
        from rmre_bridge import rmre_bridge
        from execution_engine import ExecutionEngine, SignalEmitter
        from performance_tracker import PerformanceTracker
        from delta_neutrality import DeltaNeutralityEngine
        from sr_patterns_engine import SRPatternsEngine
        
        dm = DataManager(schwab_api)
        analyzer = SqueezeAnalyzer()
        options_svc = OptionsProService()
        perf = PerformanceTracker()
        exec_eng = ExecutionEngine(schwab_api, rmre_bridge, perf)
        delta_mgr = DeltaNeutralityEngine(exec_eng)
        
        watchlist = []
        if os.path.exists('watchlist.json'):
            try:
                with open('watchlist.json', 'r') as f:
                    raw = json.load(f)
                    watchlist = raw if isinstance(raw, list) else raw.get('symbols', [])
            except Exception as e:
                logger.warning(f"[WATCHLIST] Failed to load watchlist.json: {e}")
        
        gamma_eng = GammaFlowEngine(dm.polygon, watchlist + FAVORITES)
        options_intel = OptionsIntelligence()
        forced_move = ForcedMoveEngine()
        discord = DiscordAlerts()
        signals = SignalEmitter(gamma_eng, gamma_eng)
        
        with state.lock:
            _services.update({
                "dm": dm, "analyzer": analyzer, "options": options_svc,
                "rmre": rmre_bridge, "exec": exec_eng, "perf": perf,
                "gamma": gamma_eng, "delta": delta_mgr, "discord": discord,
                "signals": signals, "options_intel": options_intel, "forced_move": forced_move,
                "mre": MeanReversionEngine(bb_period=20, bb_std=2.0, rsi_period=14, max_price=100.0),
                "sr_patterns": SRPatternsEngine()
            })
        
        def preload_task():
            rmre_bridge.set_data_provider(dm)
            for sym in rmre_bridge.REGIME_SYMBOLS:
                rmre_bridge.pre_load_history(sym)
            
            try:
                provider_info = f"POLYGON (MTF) | SCHWAB ({'LIVE' if schwab_api.authenticated else 'OFFLINE'})"
                discord.fire_startup_alert(provider_info, len(watchlist) + len(FAVORITES))
                logger.info("[DISCORD] Startup alert dispatched.")
            except Exception as e:
                logger.error(f"[DISCORD] Startup alert failed: {e}")

        threading.Thread(target=preload_task, daemon=True).start()
        logger.info("[OK] v5 Institutional Services Online")
    except Exception as e:
        logger.error(f"[CRITICAL] Service Init Failure: {e}")

# --- WORKERS ---

def worker_scanner():
    logger.info("📡 [SENTINEL] Scanner Awakened")
    while True:
        try:
            state.heartbeats["scanner"] = time.time()
            dm = get_service("dm")
            analyzer = get_service("analyzer")
            exec_eng = get_service("exec")
            if not dm or not analyzer: 
                time.sleep(5)
                continue
            
            u_map = dm.discover_universe(limit=2000)
            with state.lock:
                state.universe = u_map
                universe_list = list(u_map.keys())
            
            if not universe_list:
                time.sleep(10)
                continue
            
            regime_syms = ["SPY", "QQQ", "IWM"] 
            high_priority = list(set(FAVORITES) | set(regime_syms))
            standard_priority = [s for s in universe_list if s not in high_priority]
            
            idx = int((time.time() // 60) % 5) * 400
            targets = high_priority + standard_priority[idx : idx + 400]
            
            # Rate Limit Protection: Jitter before batch request
            time.sleep(random.uniform(1, 3))
            
            quotes = dm.get_quotes(targets, fast_only=True)
            results = analyzer.analyze_batch(quotes)
            
            with state.lock:
                state.quotes.update(quotes)
                current_map = {r['symbol']: r for r in state.scan_results}
                for r in results: 
                    r['is_mega'] = r['symbol'] in MEGA_CAPS
                    current_map[r['symbol']] = r
                state.scan_results = sorted(current_map.values(), key=lambda x: -x.get('squeeze_score', 0))
                state.last_scan_ts = time.time()

            for r in results:
                if r.get('squeeze_score', 0) >= 50:
                    icon = '🟢' if r.get('direction') == 'BULLISH' else '🔴'
                    state.push_terminal('SCAN', f"{icon} {r['symbol']} SQZ:{r['squeeze_score']:.0f} ${r.get('price',0):.2f}", symbol=r['symbol'], score=r['squeeze_score'])

            discord = get_service("discord")
            if discord:
                discord.fire_squeeze_alerts(results)

            if exec_eng:
                exec_eng.update_live_prices(quotes)

            time.sleep(10)
        except Exception as e:
            logger.error(f"[SCANNER FAIL] {e}")
            time.sleep(30)

def worker_flow():
    logger.info("🌊 [SENTINEL] Flow Monitoring Active")
    while True:
        try:
            state.heartbeats["flow"] = time.time()
            options = get_service("options")
            if not options:
                time.sleep(10)
                continue
                
            with state.lock:
                limit = min(50, len(state.scan_results))
                to_check = list(set([r['symbol'] for r in state.scan_results[:limit]] + FAVORITES))
            
            # Slice universe to avoid hitting Schwab too hard in one burst
            for sym in to_check[:20]:
                chain = options.get_options_chain(sym)
                if chain and 'unusual_activity' in chain:
                    hits = chain['unusual_activity']
                    for h in hits:
                        if h.get('unusual_score', 0) >= 40:
                            h['is_mega'] = sym in MEGA_CAPS
                            if h['is_mega'] and h.get('unusual_score', 0) < 70: continue
                            state.push_flow(h)
                            icon = '🟢' if h.get('sentiment') == 'BULLISH' else '🔴'
                            state.push_terminal('FLOW', f"{icon} {sym} ${h['strike']} {h['type']} | {h['unusual_score']} HEAT", symbol=sym, score=h['unusual_score'])
                    
                    discord = get_service("discord")
                    if discord: discord.fire_flow_alerts(hits)
                
                time.sleep(random.uniform(0.5, 1.5)) # Inter-symbol jitter

            time.sleep(30)
        except Exception as e:
            logger.error(f"[FLOW FAIL] {e}")
            time.sleep(30)

def worker_discovery():
    logger.info("🔭 [SENTINEL] Discovery Engine Awakened")
    while True:
        try:
            state.heartbeats["discovery"] = time.time()
            dm = get_service("dm")
            mre = get_service("mre")
            if not dm or not mre:
                time.sleep(10)
                continue
                
            logger.info("[DISCOVERY] Scanning liquid mid-caps for Mean Reversion setups...")
            
            # We use a curated liquid list for discovery to ensure high-conviction setups
            scan_list = LIQUID_MID_CAPS + FAVORITES
            
            # Incremental Loading: Consume the generator and update state symbol-by-symbol
            with state.lock:
                state.discovery_results = [] # Clear for new cycle
                
            for opp in mre.scan_universe(scan_list):
                with state.lock:
                    # Update or add
                    existing = {o['symbol']: i for i, o in enumerate(state.discovery_results)}
                    if opp['symbol'] in existing:
                        state.discovery_results[existing[opp['symbol']]] = opp
                    else:
                        state.discovery_results.append(opp)
                    
                    # Keep sorted by confidence
                    state.discovery_results.sort(key=lambda x: (x.get('triggered', False), x.get('confidence', 0)), reverse=True)
                    state.last_discovery_ts = time.time()
                
                # Push top hit to terminal as they come
                icon = '📈' if 'OVERSOLD' in opp['status'] else '📉'
                state.push_terminal('DISCOVERY', f"{icon} {opp['symbol']} {opp['status']} (Conf: {opp['confidence']}%)", symbol=opp['symbol'])
                
                # Small breathe to allow polling
                time.sleep(0.1)
                
            logger.info(f"💓 [HEARTBEAT] Discovery Sync Cycle Complete — {len(state.discovery_results)} results live")
            time.sleep(60)
        except Exception as e:
            logger.error(f"[DISCOVERY FAIL] {e}")
            time.sleep(60)
def worker_autopilot():
    logger.info("🤖 [AUTO-PILOT] Autonomous Entry Sentinel Armed")
    while True:
        try:
            exec_eng = get_service("exec")
            if not exec_eng:
                time.sleep(10)
                continue
                
            # Phase 1: Check Cooldown & Portfolio Limits
            now = time.time()
            cooldown_remains = exec_eng.autopilot_cooldown - (now - exec_eng.last_autopilot_entry)
            if cooldown_remains > 0:
                time.sleep(30)
                continue
                
            active_count = len(exec_eng.active_trades)
            if active_count >= exec_eng.max_autopilot_trades:
                # Still manage exits even if we can't enter new ones
                time.sleep(60)
                continue
            
            # Phase 2: Identify High-Conviction Triggers
            trigger = None
            
            # --- CHECK A: Discovery Mean Reversion (90%+ Confidence) ---
            with state.lock:
                # Prefer exact triggers over 'near' setups
                reversion_hits = [d for d in state.discovery_results if d.get('triggered', False) and d.get('confidence', 0) >= 90]
            
            if reversion_hits:
                hit = reversion_hits[0] # Take the top confidence hit
                symbol = hit['symbol']
                # Ensure we aren't already trading this symbol
                if not any(t['symbol'] == symbol for t in exec_eng.active_trades.values()):
                    side = 'BUY' if 'OVERSOLD' in hit['status'] else 'SELL'
                    trigger = {'symbol': symbol, 'side': side, 'price': hit['price'], 'reason': f"REVERSION {hit['confidence']}%"}

            # --- CHECK B: Squeeze (Beast Score 85+) ---
            if not trigger:
                with state.lock:
                    squeeze_hits = [s for s in state.scan_results[:10] if s.get('squeeze_score', 0) >= 85]
                
                if squeeze_hits:
                    hit = squeeze_hits[0]
                    symbol = hit['symbol']
                    if not any(t['symbol'] == symbol for t in exec_eng.active_trades.values()):
                        side = hit.get('direction', 'BULLISH')
                        side = 'BUY' if side == 'BULLISH' else 'SELL'
                        trigger = {'symbol': symbol, 'side': side, 'price': hit['price'], 'reason': f"BEAST SQZ {hit['squeeze_score']}"}

            # Phase 3: Execute
            if trigger:
                symbol, side, price = trigger['symbol'], trigger['side'], trigger['price']
                # Determine Qty (Safety Default: Maintain < $500 total value)
                qty = max(1, int(450 / price))
                
                msg = f"🤖 [AUTOPILOT] Triggering {side} {qty} {symbol} @ {price} | Reason: {trigger['reason']}"
                state.push_terminal('SYSTEM', msg, symbol=symbol)
                logger.info(msg)
                
                if exec_eng.live_mode:
                    exec_eng.execute_live_trade(symbol, side, qty, price)
                else:
                    exec_eng.execute_shadow_trade(symbol, side, qty, price)
                
                exec_eng.last_autopilot_entry = time.time()

            time.sleep(30) # Poll frequency
        except Exception as e:
            logger.error(f"[AUTOPILOT FAIL] {e}")
            time.sleep(30)

def worker_sr_patterns():
    logger.info("📐 [SENTINEL] S&R Patterns Awakened")
    while True:
        try:
            state.heartbeats["sr_patterns"] = time.time()
            sr_eng = get_service("sr_patterns")
            discord = get_service("discord")
            if not sr_eng or not discord:
                time.sleep(10)
                continue
            
            # Merged with meme/low float runners as requested
            custom_targets = ["AMC", "GME", "HOLO", "FFIE", "YYAI"]
            scan_list = list(set(LIQUID_MID_CAPS + FAVORITES + custom_targets))
            
            time.sleep(random.uniform(2, 5))
            
            hits = sr_eng.scan_universe(scan_list)
            if hits:
                discord.fire_sr_pattern_alerts(hits)
                for h in hits:
                     icon = '🟢' if h['action'] == 'BUY' else '🔴'
                     state.push_terminal('PATTERN', f"{icon} {h['symbol']} {h['pattern']} @ ${h['price']:.2f}", symbol=h['symbol'])

            time.sleep(120)
        except Exception as e:
            logger.error(f"[SR PATTERNS FAIL] {e}")
            time.sleep(60)


# --- ROUTES ---

@app.route('/')
def index_v5():
    return send_from_directory('.', 'index.html')

@app.route('/api/auth/url')
def get_auth_url():
    return jsonify({"status": "success", "url": schwab_api.get_auth_url()})

@app.route('/api/auth/status')
def get_auth_status():
    # Fast local check — don't attempt a slow token refresh here
    if schwab_api.access_token and time.time() < schwab_api.token_expires_at:
        return jsonify({"status": "ONLINE", "message": "Connected"})
    elif schwab_api.refresh_token:
        return jsonify({"status": "AUTH_EXPIRED", "message": "Token expired — click SAVE & AUTHENTICATE to re-login"})
    return jsonify({"status": "OFFLINE", "message": "Not authenticated"})

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"})

@app.route('/api/market/discovery')
def get_discovery():
    with state.lock:
        return jsonify({
            "status": "success", 
            "data": state.discovery_results or [], 
            "ts": state.last_discovery_ts
        })

@app.route('/api/market/scan')
def get_scan():
    final = []
    seen = set()
    with state.lock:
        mega_count = 0
        for r in state.scan_results:
            sym = r['symbol']
            if sym in seen: continue
            seen.add(sym)
            if r.get('is_mega'):
                if mega_count < RULE_3_LIMIT:
                    final.append(r)
                    mega_count += 1
            elif r.get('price', 0) >= 0.50:
                final.append(r)
    return jsonify({"status": "success", "data": final})

@app.route('/api/market/quotes')
def get_quotes():
    symbols = request.args.get('symbols', '').split(',')
    with state.lock:
        res = {s: state.quotes[s] for s in symbols if s in state.quotes}
    return jsonify({"status": "success", "data": res})

@app.route('/api/market/flow')
def get_market_flow():
    with state.lock: return jsonify({"status": "success", "data": state.flow_results})

@app.route('/api/terminal/feed')
def get_terminal():
    with state.lock: return jsonify({"status": "success", "data": state.terminal_feed})

@app.route('/api/search')
def api_search():
    """Search for a symbol — add it to quotes if found in universe or try to fetch a quote."""
    q = request.args.get('q', '').strip().upper()
    if not q:
        return jsonify({"status": "error", "message": "No query"}), 400
    
    dm = get_service("dm")
    
    # Check if we already have it
    with state.lock:
        if q in state.quotes or q in state.universe:
            return jsonify({"status": "success", "symbol": q})
    
    # Try to fetch a live quote for it
    if dm:
        try:
            quotes = dm.get_quotes([q], fast_only=True)
            if quotes and q in quotes:
                with state.lock:
                    state.quotes.update(quotes)
                return jsonify({"status": "success", "symbol": q})
        except Exception as e:
            logger.warning(f"[SEARCH] Failed to fetch quote for {q}: {e}")
    
    return jsonify({"status": "success", "symbol": q, "note": "Symbol accepted — awaiting data"})

@app.route('/api/market/alarms')
def get_market_alarms():
    """Aggregate options flow into clustered alarms per symbol (heat clusters)."""
    with state.lock:
        flow = list(state.flow_results)
    
    if not flow:
        return jsonify({"status": "success", "data": []})
    
    # Group flow by symbol and build alarm clusters
    from collections import defaultdict
    clusters = defaultdict(list)
    for f in flow:
        clusters[f['symbol']].append(f)
    
    alarms = []
    for symbol, entries in clusters.items():
        max_heat = max(e.get('unusual_score', 0) for e in entries)
        sentiment = 'BULLISH' if sum(1 for e in entries if e.get('sentiment') == 'BULLISH') >= len(entries) / 2 else 'BEARISH'
        strikes = sorted(set(e.get('strike', 0) for e in entries))
        latest_time = max(e.get('seen_time', 0) for e in entries)
        
        alarms.append({
            'symbol': symbol,
            'sentiment': sentiment,
            'max_heat': max_heat,
            'contracts': len(entries),
            'strikes': strikes[:5],
            'cluster_count': len(strikes),
            'seen_time': latest_time
        })
    
    # Sort by heat descending
    alarms.sort(key=lambda x: -x['max_heat'])
    return jsonify({"status": "success", "data": alarms})

@app.route('/api/market/intel')
def get_market_intel():
    """Return combined intel feed from flow + scan highlights."""
    with state.lock:
        flow = list(state.flow_results)
        scan = list(state.scan_results[:20])
    
    intel = []
    
    # Flow-based intel entries
    for f in flow[:30]:
        intel.append({
            'type': 'FLOW',
            'symbol': f.get('symbol', ''),
            'sentiment': f.get('sentiment', 'NEUTRAL'),
            'strike': f.get('strike', 0),
            'expiry': f.get('expiry_formatted', ''),
            'premium': f.get('premium', 0),
            'label': f"{'🐳 WHALE' if f.get('unusual_score', 0) >= 70 else '⚡SWEEP'} {f.get('type', 'CALL')}",
            'seen_time': f.get('seen_time', 0)
        })
    
    return jsonify({"status": "success", "data": intel})

@app.route('/api/beast/signals')
def get_beast_signals():
    """Return top squeeze candidates as beast-mode signals."""
    with state.lock:
        scan = list(state.scan_results)
    
    signals = []
    for s in scan:
        score = s.get('squeeze_score', 0)
        if score >= 50:
            signals.append({
                'symbol': s['symbol'],
                'action': s.get('direction', 'NEUTRAL'),
                'score': score,
                'price': s.get('price', 0),
                'ts': s.get('ts', time.time()),
                'is_mega': s.get('is_mega', False)
            })
    
    return jsonify({"status": "ok", "data": signals[:20]})

@app.route('/api/options/intelligence/<symbol>')
def api_options_intelligence(symbol):
    try:
        intel = get_service("options_intel")
        chain = schwab_api.get_option_chains(symbol.upper())
        if not chain: return jsonify({"status": "error"}), 404
        with state.lock: quote = state.quotes.get(symbol.upper(), {})
        return jsonify(intel.scan_symbol(symbol.upper(), chain, quote))
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/forced-move/<symbol>')
def api_forced_move(symbol):
    try:
        fm = get_service("forced_move")
        dm = get_service("dm")
        history = dm.get_price_history(symbol.upper(), period_type='month', period=3)
        if not history or 'candles' not in history: return jsonify({"error": "No history"}), 404
        bars = [{'date': c['datetime'], 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close'], 'volume': c['volume']} for c in history['candles']]
        vix = state.quotes.get('VIX', {}).get('price', 20.0)
        return jsonify(fm.analyze(symbol.upper(), bars, vix))
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/settings')
def get_settings():
    return jsonify({
        'schwabKey': os.environ.get('SCHWAB_CLIENT_ID', ''),
        'schwabSecret': os.environ.get('SCHWAB_CLIENT_SECRET', ''),
        'alpacaKey': os.environ.get('ALPACA_API_KEY', ''),
        'polyKey': os.environ.get('POLYGON_API_KEY', ''),
        'webhook': os.environ.get('DISCORD_WEBHOOK_ALL', '')
    })

def _update_env_key(key, value):
    os.environ[key] = value
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r') as f: lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(key + '='):
            lines[i] = f"{key}={value}\n"; found = True; break
    if not found: lines.append(f"{key}={value}\n")
    with open(env_path, 'w') as f: f.writelines(lines)

@app.route('/api/settings/schwab', methods=['POST'])
def save_schwab_settings():
    data = request.json
    _update_env_key('SCHWAB_CLIENT_ID', data.get('key',''))
    _update_env_key('SCHWAB_CLIENT_SECRET', data.get('secret',''))
    # Hot-reload the global schwab_api instance with new credentials
    schwab_api.client_id = data.get('key', '') or schwab_api.client_id
    schwab_api.client_secret = data.get('secret', '') or schwab_api.client_secret
    return jsonify({"status": "success"})

@app.route('/api/auth/exchange', methods=['POST'])
def exchange_auth_code():
    """Exchange Schwab OAuth authorization code for access + refresh tokens."""
    data = request.json or {}
    code = data.get('code', '')
    if not code:
        return jsonify({"status": "error", "message": "No auth code provided"}), 400

    # Hot-swap credentials if the frontend sends them
    client_id = data.get('client_id')
    client_secret = data.get('client_secret')
    redirect_uri = data.get('redirect_uri')
    if client_id:
        schwab_api.client_id = client_id
        _update_env_key('SCHWAB_CLIENT_ID', client_id)
    if client_secret:
        schwab_api.client_secret = client_secret
        _update_env_key('SCHWAB_CLIENT_SECRET', client_secret)
    if redirect_uri:
        schwab_api.redirect_uri = redirect_uri
        if not schwab_api.redirect_uri.endswith('/'):
            schwab_api.redirect_uri += '/'
        _update_env_key('SCHWAB_REDIRECT_URI', redirect_uri)

    result = schwab_api.exchange_code(code)
    if result.get('status') == 'success':
        state.push_terminal('SYSTEM', '🔑 Schwab OAuth: Session Established')
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": result.get('message', 'Token exchange failed')})

@app.route('/api/settings/backups', methods=['POST'])
def save_backup_settings():
    """Save Alpaca, Polygon, and Alpha Vantage keys."""
    data = request.json or {}
    if data.get('alpacaKey'):
        _update_env_key('ALPACA_API_KEY', data['alpacaKey'])
    if data.get('alpacaSecret'):
        _update_env_key('ALPACA_API_SECRET', data['alpacaSecret'])
    if data.get('polyKey'):
        _update_env_key('POLYGON_API_KEY', data['polyKey'])
    if data.get('avKey'):
        _update_env_key('ALPHA_VANTAGE_API_KEY', data['avKey'])
    return jsonify({"status": "success"})

@app.route('/api/settings/discord', methods=['POST'])
def save_discord_settings():
    """Save Discord webhook URLs and optionally send a test alert."""
    data = request.json or {}
    webhook = data.get('webhook', '')
    flow_webhook = data.get('flow_webhook', '')
    is_test = data.get('test', False)

    if webhook:
        _update_env_key('DISCORD_WEBHOOK_ALL', webhook)
        _update_env_key('DISCORD_WEBHOOK_SQUEEZE', webhook)
    if flow_webhook:
        _update_env_key('DISCORD_WEBHOOK_FLOW', flow_webhook)

    if is_test and webhook:
        try:
            import requests as req
            payload = {
                "content": "🧪 **SQUEEZE OS v4.1** — Test alert received! Your webhook is active.",
                "username": "SqueezeOS"
            }
            r = req.post(webhook, json=payload, timeout=10)
            if r.status_code in (200, 204):
                return jsonify({"status": "success", "message": "Test alert sent"})
            else:
                return jsonify({"status": "error", "message": f"Discord returned {r.status_code}"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    return jsonify({"status": "success"})

# --- TRADING CONTROL ---
@app.route('/api/trading/status')
def get_trading_status():
    exec_eng = get_service("exec")
    if not exec_eng: return jsonify({"status": "error"}), 503
    return jsonify({
        "status": "success", "live_mode": exec_eng.live_mode,
        "max_order_value": exec_eng.max_order_value,
        "active_trades_count": len(exec_eng.active_trades)
    })

@app.route('/api/trading/toggle', methods=['POST'])
def toggle_trading_mode():
    exec_eng = get_service("exec")
    if not exec_eng: return jsonify({"status": "error"}), 503
    live = request.json.get('live', False)
    exec_eng.live_mode = live
    state.push_terminal("SYSTEM", f"Trading mode switched to {'LIVE' if live else 'SHADOW'}")
    return jsonify({"status": "success", "live_mode": live})

@app.route('/api/trading/balances')
def get_trading_balances():
    dm = get_service("dm")
    if not dm: return jsonify({"status": "error"}), 503
    bal = {"alpaca": {}, "schwab": {}}
    try:
        acc = dm.alpaca.get_account()
        bal["alpaca"] = {"equity": acc.get("equity"), "buying_power": acc.get("buying_power")}
    except: pass
    try:
        accs = dm.schwab.schwab.get_balances()
        if accs:
            acc = accs[0]
            bal["schwab"] = {"equity": acc.get("currentBalances", {}).get("liquidationValue"), "buying_power": acc.get("currentBalances", {}).get("buyingPower")}
    except: pass
    return jsonify({"status": "success", "balances": bal})

if __name__ == "__main__":
    init_services()
    threading.Thread(target=worker_scanner, daemon=True).start()
    threading.Thread(target=worker_flow, daemon=True).start()
    threading.Thread(target=worker_discovery, daemon=True).start()
    threading.Thread(target=worker_autopilot, daemon=True).start()
    threading.Thread(target=worker_sr_patterns, daemon=True).start()
    port = int(os.environ.get("PORT", 8182))
    app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True)
