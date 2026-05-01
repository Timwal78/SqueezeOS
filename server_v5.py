import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import time
import threading
import logging
import math
import random
import typing
from flask import Flask, request, jsonify, send_from_directory, Response, redirect, render_template_string
from functools import wraps
from datetime import datetime
from flask_cors import CORS
from threading import Lock
from functools import wraps
import queue

sse_queues = []
from data_providers import load_env_file, DataManager
from schwab_api import schwab_api
from discord_alerts import DiscordAlerts
from options_intelligence import OptionsIntelligence
from forced_move_engine import ForcedMoveEngine
from mean_reversion_engine import MeanReversionEngine
from beast_webhook import register_beast_routes
from iwm_odte_engine import IwmOdteEngine
from kdp_sentinel_engine import KdpSentinelEngine
from free_llm import get_llm

# --- INITIALIZATION ---
load_env_file()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SqueezeOS-v5")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- MANIFESTO LAWS ---
FAVORITES = ["IWM", "AMC", "GME", "SPY", "QQQ", "VIX"] # Institutional Priority Queue
MEGA_CAPS = {
    'AAPL', 'MSFT', 'GOOG', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'LLY', 'V', 'MA', 'AVGO', 'HD', 'COST',
    'JPM', 'UNH', 'WMT', 'BAC', 'XOM', 'CVX', 'PG', 'ORCL', 'ABBV', 'CRM', 'ADBE', 'NFLX', 'AMD', 'INTC', 'DIS',
    'PFE', 'KO', 'PEP', 'CSCO', 'TMO', 'AZN', 'NKE', 'ABT', 'LIN', 'DHR', 'WFC', 'MRK', 'VZ', 'T', 'NVR', 'BKNG'
}
RULE_3_LIMIT = 3

# Broad Liquid Universe for Discovery
LIQUID_MID_CAPS = [] # Purged per Rule 1 (Use 100% Fetch Policy)

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
        self.iwm_odte_results: dict = {}
        self.iwm_odte_engine = None
        self.alert_history: dict[str, float] = {}
        self.heartbeats: dict[str, float] = {"scanner": 0.0, "flow": 0.0, "discovery": 0.0}
        self.beast_signals: list[dict] = []
        self.discovery_results: list[dict] = []
        self.last_discovery_ts: float = 0.0
        self.kdp_results: dict = {}
        self.audit = {
            "universe_size": 0,
            "mega_caps_filtered": 0,
            "uptime_start": time.time(),
            "trading_mode": "SHADOW",
            "conservation_mode": False
        }
        self.conservation_until = 0.0
        self.beast_paper_data: dict = {}  # BEAST paper trading observation data

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
            
            # Dispatch to SSE listeners
            global sse_queues
            for q in sse_queues:
                try:
                    q.put_nowait(entry)
                except:
                    pass

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

    def can_alert(self, key, category=None, cooldown=3600):
        """Standardized cooldown guard with optional category tagging."""
        with self.lock:
            now = time.time()
            if key in self.alert_history and (now - self.alert_history[key] < cooldown):
                return False
            self.alert_history[key] = now
            return True

    def log_event(self, msg: str, level: str = "INFO"):
        """BEAST-compatible event logging for terminal and audit trail."""
        logger.info(f"[EVENT] {msg}")
        self.push_terminal('EVENT', msg)

state = GlobalState()

# --- UTILITIES ---
def require_localhost(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.remote_addr not in ['127.0.0.1', '::1', 'localhost']:
            return jsonify({"status": "error", "message": "Unauthorized: Localhost only"}), 403
        return f(*args, **kwargs)
    return decorated_function

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
        
        # MythosArchitect requires PyTorch + BEAST module — graceful multi-level fallback
        _architect_cls = None
        try:
            from BEAST.architect.mythos_architect import MythosArchitect
            _architect_cls = MythosArchitect
            logger.info("[BEAST] MythosArchitect loaded (OpenMythos + StrategyArchitect)")
        except Exception as e:
            logger.warning(f"[BEAST] MythosArchitect unavailable ({e})")
            try:
                from BEAST.architect.strategy_architect import StrategyArchitect as _architect_cls
                logger.info("[BEAST] StrategyArchitect loaded (fallback)")
            except Exception as e2:
                logger.warning(f"[BEAST] StrategyArchitect also unavailable ({e2}), falling back to FreeLLM architect")
                class _StubArchitect:
                    """FreeLLM-backed architect when BEAST module is not deployed."""
                    def analyze(self, symbol=None, signal=None, **kw):
                        try:
                            from free_llm import get_llm
                            commentary = get_llm().analyze_signal(symbol or 'UNKNOWN', signal or kw)
                            return {"commentary": commentary, "source": "free_llm"}
                        except Exception:
                            return {}
                    def get_strategy(self, symbol=None, context=None, **kw):
                        try:
                            from free_llm import get_llm
                            rating = get_llm().score_trade(symbol or 'UNKNOWN', context or kw)
                            return {"rating": rating, "source": "free_llm"}
                        except Exception:
                            return {}
                    def architect(self, thesis, symbol=None):
                        try:
                            from free_llm import get_llm
                            commentary = get_llm().commentary(f"Ticker: {symbol or 'UNKNOWN'}\nThesis: {thesis}")
                            return {"commentary": commentary, "source": "free_llm"}
                        except Exception:
                            return {}
                _architect_cls = _StubArchitect
        
        dm = DataManager(schwab_api)
        analyzer = SqueezeAnalyzer()
        options_svc = OptionsProService()
        perf = PerformanceTracker()
        discord = DiscordAlerts()
        exec_eng = ExecutionEngine(schwab_api, rmre_bridge, perf, discord)
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
        signals = SignalEmitter(gamma_eng, gamma_eng)
        
        iwm_engine = IwmOdteEngine(dm)
        kdp_engine = KdpSentinelEngine(dm)
        
        with state.lock:
            _services.update({
                "dm": dm, "analyzer": analyzer, "options": options_svc,
                "rmre": rmre_bridge, "exec": exec_eng, "perf": perf,
                "gamma": gamma_eng, "delta": delta_mgr, "discord": discord,
                "signals": signals, "options_intel": options_intel, "forced_move": forced_move,
                "iwm_engine": iwm_engine, "kdp_engine": kdp_engine,
                "mre": MeanReversionEngine(bb_period=20, bb_std=2.0, rsi_period=14, max_price=500.0),
                "sr_patterns": SRPatternsEngine(),
                "mythos_arch": _architect_cls()
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
            now = time.time()
            if now < state.conservation_until:
                logger.warning("🛡️ API GUARDIAN: Conservation Mode Active in SqueezeOS.")
                time.sleep(30)
                continue
            
            state.heartbeats["scanner"] = time.time()
            dm = get_service("dm")
            analyzer = get_service("analyzer")
            exec_eng = get_service("exec")
            if not dm or not analyzer: 
                time.sleep(5)
                continue
            
            u_map = dm.discover_universe(limit=10000)  # MANIFESTO: FULL FETCH — no artificial cap
            with state.lock:
                state.universe = u_map
                universe_list = list(u_map.keys())
            
            if not universe_list:
                time.sleep(10)
                continue
            
            regime_syms = ["SPY", "QQQ", "IWM"] 
            high_priority = list(set(FAVORITES) | set(regime_syms))
            standard_priority = [s for s in universe_list if s not in high_priority]
            
            # MANIFESTO: FULL FETCH — scan ENTIRE discovered universe every cycle
            targets = high_priority + standard_priority
            
            # Rate Limit Protection: Jitter before batch request
            time.sleep(random.uniform(1, 3))
            
            quotes = dm.get_quotes(targets, fast_only=True)
            
            # MANIFESTO: $50 SWEET SPOT CAP — FAVORITES (IWM etc.) always pass
            before = len(quotes)
            quotes = {s: q for s, q in quotes.items() if s in FAVORITES or q.get('price', 0) <= 50.0}
            filtered = before - len(quotes)
            if filtered:
                logger.info(f"[SCANNER] Price cap filtered {filtered} symbols (>${50}), {len(quotes)} remaining")
            
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

            time.sleep(5)  # MANIFESTO: Faster scan cycles
        except Exception as e:
            if "429" in str(e):
                logger.warning("📉 PROTOCOL 429 in SqueezeOS Scanner. Entering 60s Global Hibernation.")
                state.conservation_until = time.time() + 900 # 15 min
                time.sleep(60)
            else:
                logger.error(f"[SCANNER FAIL] {e}")
                time.sleep(30)

def worker_flow():
    logger.info("🌊 [SENTINEL] Flow Monitoring Active")
    while True:
        try:
            now = time.time()
            if now < state.conservation_until:
                time.sleep(30)
                continue

            state.heartbeats["flow"] = time.time()
            options = get_service("options")
            if not options:
                time.sleep(10)
                continue
                
            with state.lock:
                limit = min(50, len(state.scan_results))
                to_check = list(set([r['symbol'] for r in state.scan_results[:limit]] + FAVORITES))
            
            # Slice universe to avoid hitting Schwab too hard in one burst
            for sym in to_check[:50]:  # MANIFESTO: FULL FETCH — expanded flow monitoring
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

            time.sleep(10)
        except Exception as e:
            if "429" in str(e):
                state.conservation_until = time.time() + 900
                time.sleep(60)
            else:
                logger.error(f"[FLOW FAIL] {e}")
                time.sleep(10)

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
            
            # Use live-discovered universe from scanner instead of empty hardcoded list
            with state.lock:
                live_universe = [r['symbol'] for r in state.scan_results[:50] if r.get('price', 0) >= 2.0 and r.get('price', 0) <= 500.0]
            
            scan_list = list(set(live_universe + FAVORITES))
            
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
                
                # Discord notification for trade execution
                discord = get_service("discord")
                if discord:
                    discord.fire_beast_trade_alert({
                        'symbol': symbol,
                        'side': side,
                        'qty': qty,
                        'entry_price': price,
                        'regime': 'AUTOPILOT',
                        'hurst': 0.0,
                        'net_pressure': 0.0,
                        'sl': 0.0,
                        'tp': 0.0,
                    }, is_live=exec_eng.live_mode)
                
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

def worker_beast_paper():
    """BEAST Paper Trading Observer — runs hedger dry-runs + GEX scans for weekend observation."""
    logger.info("🦅 [BEAST] Paper Trading Observer Awakened")
    while True:
        try:
            exec_eng = get_service("exec")
            if not exec_eng:
                time.sleep(30)
                continue
            
            # Load watchlist for monitoring
            watchlist_syms = []
            if os.path.exists('watchlist.json'):
                try:
                    with open('watchlist.json', 'r') as f:
                        raw = json.load(f)
                        watchlist_syms = raw if isinstance(raw, list) else raw.get('symbols', [])
                except Exception:
                    pass
            
            # Filter to equity symbols only (skip crypto)
            equity_syms = [s for s in watchlist_syms if s not in ('XRP', 'BTC', 'ETH', 'DOGE')]
            if not equity_syms:
                equity_syms = ['AMC', 'GME', 'SPY']
            
            beast_paper_data = {
                'hedger_snapshots': [],
                'gex_regimes': [],
                'ts': time.time()
            }
            
            # Phase 1: Run hedger dry-run cycles
            hedger = exec_eng.beast_hedger
            if hedger and getattr(hedger, 'available', False):
                for sym in equity_syms[:5]:  # Top 5 to avoid rate limits
                    try:
                        result = hedger.run_cycle(sym)
                        status = result.get('status', 'UNKNOWN')
                        beast_paper_data['hedger_snapshots'].append({
                            'symbol': sym,
                            'status': status,
                            'delta_from_target': result.get('delta_from_target', 0),
                            'snapshot': result.get('snapshot', {}),
                            'ts': time.time()
                        })

                        # --- EXPERT PRECISION: Fire alert on new trade execution (Dry Run) ---
                        if status in ('DRY_RUN', 'SUBMITTED'):
                            trade_info = result.get('result', {})
                            if trade_info:
                                discord.fire_beast_hedge_executed(
                                    symbol=sym,
                                    side=trade_info.get('side', 'UNKNOWN'),
                                    qty=trade_info.get('qty', 0),
                                    price=trade_info.get('mid', 0.0),
                                    delta=result.get('delta_from_target', 0),
                                    reason=f"Institutional {sym} Rebalance"
                                )
                        state.push_terminal('BEAST', f"🦅 HEDGER {sym}: {result.get('status', '?')} | Δ={result.get('delta_from_target', 0)}", symbol=sym)
                        time.sleep(1)  # Rate limit breathe
                    except Exception as e:
                        logger.warning(f"[BEAST] Hedger cycle failed for {sym}: {e}")
            else:
                beast_paper_data['hedger_snapshots'].append({'status': 'HEDGER_OFFLINE', 'reason': 'Alpaca keys missing or init failed'})
            
            # Phase 2: GEX regime scan for top symbols
            for sym in equity_syms[:3]:
                try:
                    gex_data = exec_eng.get_gamma_walls(sym)
                    if gex_data:
                        gex_data['symbol'] = sym
                        beast_paper_data['gex_regimes'].append(gex_data)
                        regime = gex_data.get('regime', '?')
                        cw = gex_data.get('call_wall', '?')
                        pw = gex_data.get('put_wall', '?')
                        state.push_terminal('BEAST', f"📊 GEX {sym}: {regime} | CW=${cw} PW=${pw}", symbol=sym)
                except Exception as e:
                    logger.warning(f"[BEAST] GEX scan failed for {sym}: {e}")
            
            # Store in global state
            with state.lock:
                state.beast_paper_data = beast_paper_data
            
            logger.info(f"🦅 [BEAST] Paper Trading Cycle Complete — {len(beast_paper_data['hedger_snapshots'])} hedger, {len(beast_paper_data['gex_regimes'])} GEX")
            
            # Discord notification for paper trading cycle
            discord = get_service("discord")
            if discord:
                perf = get_service("perf")
                total_pnl = 0.0
                active_trades = []
                if perf:
                    summary = perf.get_summary()
                    total_pnl = summary.get('total_pnl', 0.0)
                exec_eng_d = get_service("exec")
                recent_closed = []
                if exec_eng_d:
                    active_trades = exec_eng_d.get_active_trades()
                    recent_closed = exec_eng_d.get_trade_history()[:5]
                discord.fire_beast_paper_summary(
                    hedger_count=len(beast_paper_data['hedger_snapshots']),
                    gex_count=len(beast_paper_data['gex_regimes']),
                    active_trades=active_trades,
                    recent_closed=recent_closed,
                    total_pnl=total_pnl
                )
            
            time.sleep(300)  # 5 min cycles
        except Exception as e:
            logger.error(f"[BEAST PAPER FAIL] {e}")
            time.sleep(60)

def worker_iwm_odte():
    """Background worker for IWM 0DTE institutional scanning."""
    logger.info("Starting IWM 0DTE Institutional Sentinel...")
    # Delay start to allow other services to warm up
    time.sleep(10)
    
    while True:
        try:
            dm = get_service("dm")
            if not dm:
                time.sleep(10)
                continue
                
            engine = IwmOdteEngine(dm)
            state.iwm_odte_engine = engine
            
            scan = engine.run_scan()
            if scan and 'error' not in scan:
                with state.lock:
                    state.iwm_odte_results = scan
                
                bias = scan.get('bias', 'NEUTRAL')
                best = scan.get('best')
                if best:
                    score = best.get('score', 0)
                    msg = f"🦉 [IWM 0DTE] {bias} | BEST: {best['side'].upper()} {best['strike']} score={score}"
                    
                    # High Conviction Alert
                    category = 'BEAST_ALERT' if score >= 75 else 'BEAST'
                    state.push_terminal(category, msg, symbol='IWM')
                    
                    if score >= 75:
                        logger.info(f"🔥 HIGH CONVICTION IWM: {msg}")
            
            # 5 minute cycle
            time.sleep(300)
        except Exception as e:
            logger.error(f"[IWM-0DTE FAIL] {e}")
            time.sleep(60)




def worker_kdp_sentinel():
    """Expert-Precision KDP Sentinel Worker."""
    logger.info("Starting KDP Institutional Sentinel...")
    time.sleep(20)
    
    while True:
        try:
            kdp_engine = get_service("kdp_engine")
            if kdp_engine:
                chain = schwab_api.get_option_chains("KDP")
                if chain and 'error' not in chain:
                    with state.lock:
                        quote = state.quotes.get("KDP", {})
                    
                    results = kdp_engine.run_scan(chain, quote)
                    
                    with state.lock:
                        state.kdp_results = results
                    
                    # High conviction alert logic
                    top = results.get('top_contracts', [])
                    if top:
                        best = top[0]
                        score = best.get('score', 0)
                        if score >= 75:
                            msg = f"🦅 [KDP HIGH CONVICTION] {best['type']} ${best['strike']} | SCORE: {score} | OI/Vol: {best.get('oi_vol_ratio')}x"
                            state.push_terminal('BEAST_ALERT', msg, symbol='KDP', extra={'score': score})
                        elif score >= 60:
                            msg = f"🦉 [KDP ACTIVE] {best['type']} ${best['strike']} | Score: {score}"
                            state.push_terminal('SYSTEM', msg, symbol='KDP')
            
            time.sleep(600) # 10 min cycle
        except Exception as e:
            logger.error(f"[KDP SENTINEL FAIL] {e}")
            time.sleep(60)


TRADE_DESK_URL = os.environ.get('TRADE_DESK_URL', 'https://sml-ai-trade-desk.onrender.com')
TRADE_DESK_SECRET = os.environ.get('TRADE_DESK_SECRET', 'SML_TRADEDESK_2026')

def worker_trade_desk_bridge():
    """Keep the AI Trade Desk Render service warm and forward high-conviction signals."""
    logger.info("🔗 [TRADE DESK] Bridge Worker Awakened")
    time.sleep(15)  # Let other services initialize first
    
    last_ping = 0
    trade_desk_online = False
    forwarded_signals = set()  # Dedup forwarded signals
    
    while True:
        try:
            discord = get_service("discord")
            if not discord:
                time.sleep(10)
                continue
            
            now = time.time()
            
            # ── Phase 1: Keep-Alive Ping (every 8 minutes to stay under 10min spin-down) ──
            if now - last_ping >= 480:
                result = discord.ping_trade_desk(TRADE_DESK_URL)
                was_online = trade_desk_online
                trade_desk_online = result.get('ok', False)
                last_ping = now
                
                # Fire status alert on state change
                if trade_desk_online != was_online:
                    service_name = result.get('data', {}).get('service', '') if trade_desk_online else ''
                    discord.fire_trade_desk_status(trade_desk_online, service_name)
                
                state.push_terminal('SYSTEM', f"🔗 Trade Desk: {'ONLINE' if trade_desk_online else 'OFFLINE'}")
            
            # ── Phase 2: Forward High-Conviction Signals (score >= 80) ──
            if trade_desk_online:
                with state.lock:
                    top_signals = [s for s in state.scan_results if s.get('squeeze_score', 0) >= 80]
                
                for signal in top_signals[:5]:
                    sym = signal.get('symbol', '')
                    sig_key = f"{sym}_{int(now // 1800)}"  # 30-min dedup window
                    if sig_key in forwarded_signals:
                        continue
                    
                    discord.forward_to_trade_desk(TRADE_DESK_URL, TRADE_DESK_SECRET, signal)
                    forwarded_signals.add(sig_key)
                    state.push_terminal('BRIDGE', f"📡 Forwarded {sym} (score={signal.get('squeeze_score', 0)}) to AI Trade Desk")
                    time.sleep(2)  # Rate limit
                
                # Cleanup old dedup keys
                if len(forwarded_signals) > 200:
                    forwarded_signals.clear()
            
            time.sleep(30)
        except Exception as e:
            logger.error(f"[TRADE DESK BRIDGE] {e}")
            time.sleep(60)

# --- ROUTES ---

@app.route('/')
def index_v5():
    return send_from_directory('.', 'index.html')

@app.route('/api/auth/url')
def get_auth_url_route():
    # Pass redirect_uri from request if provided to support multi-port dashboards
    redirect_uri = request.args.get('redirect_uri')
    if redirect_uri:
        schwab_api.redirect_uri = redirect_uri
    return jsonify({"status": "success", "url": schwab_api.get_auth_url()})

@app.route('/api/auth/exchange', methods=['POST'])
def api_auth_exchange():
    data = request.json
    code = data.get('code')
    if not code:
        return jsonify({"status": "error", "message": "No code provided"}), 400
    
    redirect_uri = data.get('redirect_uri')
    if redirect_uri:
        schwab_api.redirect_uri = redirect_uri
        
    res = schwab_api.exchange_code(code)
    return jsonify(res)

@app.route('/callback')
def oauth_callback():
    return send_from_directory('.', 'callback.html')

@app.route('/api/auth/tokens')
@require_localhost
def get_auth_tokens():
    """Secure bridge for Schwab tokens to external systems. Restricted to Localhost."""
    return jsonify({
        "status": "success",
        "access_token": schwab_api.access_token,
        "refresh_token": schwab_api.refresh_token,
        "expires_at": schwab_api.token_expires_at,
        "updated_at": datetime.now().isoformat()
    })

@app.route('/api/auth/status')
def get_auth_status():
    # Fast local check — don't attempt a slow token refresh here
    if schwab_api.access_token and time.time() < schwab_api.token_expires_at:
        return jsonify({"status": "ONLINE", "message": "Connected"})
    elif schwab_api.refresh_token:
        return jsonify({"status": "AUTH_EXPIRED", "message": "Token expired — click SAVE & AUTHENTICATE to re-login"})
    return jsonify({"status": "OFFLINE", "message": "Not authenticated"})

@app.route('/api/health')
def api_health():
    """Health endpoint for supervisor."""
    return jsonify({
        "status": "operational",
        "uptime_sec": round(time.time() - state.audit["uptime_start"]),
        "trading_mode": state.audit["trading_mode"]
    })

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

@app.route('/api/market/reversal')
def get_market_reversal():
    """Return reversal scan signals — symbols showing momentum exhaustion or breakout setups."""
    symbol = request.args.get('symbol', '').strip().upper()
    with state.lock:
        scan = list(state.scan_results)
    
    # Filter for high-score signals with directional clarity
    reversals = []
    for s in scan:
        score = s.get('squeeze_score', 0)
        direction = s.get('direction', 'NEUTRAL')
        if score >= 60 and direction != 'NEUTRAL':
            if not symbol or s.get('symbol') == symbol:
                reversals.append({
                    'symbol': s['symbol'],
                    'direction': direction,
                    'score': score,
                    'price': s.get('price', 0),
                    'setup': 'REVERSAL' if s.get('is_mega') else 'MOMENTUM',
                    'ts': s.get('ts', 0)
                })
    
    reversals.sort(key=lambda x: -x['score'])
    return jsonify({"status": "success", "data": reversals[:20]})

@app.route('/api/market/signals')
def get_market_signals():
    """Combined signal feed — active scan + flow signals for frontend signal table."""
    with state.lock:
        scan = list(state.scan_results[:30])
        flow = list(state.flow_results[:20])
    
    signals = []
    
    # Scan-based signals
    for s in scan:
        score = s.get('squeeze_score', 0)
        if score >= 50:
            signals.append({
                'type': 'SQUEEZE',
                'symbol': s['symbol'],
                'action': s.get('direction', 'NEUTRAL'),
                'score': score,
                'price': s.get('price', 0),
                'is_mega': s.get('is_mega', False),
                'ts': s.get('ts', 0)
            })
    
    # Flow-based signals
    for f in flow:
        score = f.get('unusual_score', 0)
        if score >= 60:
            signals.append({
                'type': 'FLOW',
                'symbol': f.get('symbol', ''),
                'action': f.get('sentiment', 'NEUTRAL'),
                'score': score,
                'strike': f.get('strike', 0),
                'expiry': f.get('expiry_formatted', ''),
                'premium': f.get('premium', 0),
                'ts': f.get('seen_time', 0)
            })
    
    signals.sort(key=lambda x: -x['score'])
    return jsonify({"status": "success", "data": signals[:30]})

@app.route('/api/beast/scan-signals')
def get_beast_scan_signals():
    """Return top squeeze candidates as beast-mode scan signals (distinct from webhook signals)."""
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

@app.route('/api/beast/paper')
def api_beast_paper():
    """Returns current BEAST paper trading observation data."""
    paper_data = getattr(state, 'beast_paper_data', {})
    # Also include shadow trades from execution engine
    exec_eng = get_service("exec")
    shadow_trades = []
    trade_history = []
    if exec_eng:
        shadow_trades = exec_eng.get_active_trades()
        trade_history = exec_eng.get_trade_history()[:20]
    
    return jsonify({
        "status": "ok",
        "hedger_snapshots": paper_data.get('hedger_snapshots', []),
        "gex_regimes": paper_data.get('gex_regimes', []),
        "shadow_trades": shadow_trades,
        "trade_history": trade_history,
        "last_update": paper_data.get('ts', 0),
        "iwm_odte": state.iwm_odte_results
    })

@app.route('/api/beast/iwm_odte')
def api_beast_iwm_odte():
    """Dedicated endpoint for IWM 0DTE data."""
    with state.lock:
        return jsonify({"status": "success", "data": state.iwm_odte_results})

@app.route('/api/beast/kdp')
def api_beast_kdp():
    """Dedicated endpoint for KDP monitoring data."""
    with state.lock:
        return jsonify({"status": "success", "data": state.kdp_results})

@app.route('/api/beast/readiness')
def api_beast_readiness():
    """Go/No-Go checklist for live trading transition."""
    exec_eng = get_service("exec")
    perf = get_service("perf")
    
    checks = []
    
    # 1. Alpaca Connection
    hedger_available = False
    if exec_eng and exec_eng.beast_hedger:
        hedger_available = getattr(exec_eng.beast_hedger, 'available', False)
    checks.append({
        'name': 'Alpaca Paper Connected',
        'passed': hedger_available,
        'detail': 'PAPER mode active' if hedger_available else 'Hedger offline — check ALPACA_API_KEY'
    })
    
    # 2. Hedger executing dry-runs
    paper_data = getattr(state, 'beast_paper_data', {})
    hedger_snaps = paper_data.get('hedger_snapshots', [])
    hedger_running = len(hedger_snaps) > 0 and hedger_snaps[0].get('status') != 'HEDGER_OFFLINE'
    checks.append({
        'name': 'Hedger Dry-Runs Active',
        'passed': hedger_running,
        'detail': f'{len(hedger_snaps)} snapshots collected' if hedger_running else 'No hedger data yet'
    })
    
    # 3. GEX data flowing
    gex_data = paper_data.get('gex_regimes', [])
    gex_ok = len(gex_data) > 0
    checks.append({
        'name': 'GEX Data Flowing',
        'passed': gex_ok,
        'detail': f'{len(gex_data)} symbols scanned' if gex_ok else 'No GEX data'
    })
    
    # 4. Shadow PnL check
    shadow_pnl = 0.0
    if perf:
        summary = perf.get_summary()
        shadow_pnl = summary.get('total_pnl', 0.0)
    pnl_ok = shadow_pnl >= -50.0  # Allow up to -$50 drawdown
    checks.append({
        'name': 'Shadow PnL Acceptable',
        'passed': pnl_ok,
        'detail': f'${shadow_pnl:.2f} total PnL' if shadow_pnl != 0 else 'No trades executed yet'
    })
    
    # 5. Kill switch NOT present
    import tempfile
    kill_path = os.path.join(tempfile.gettempdir(), 'sml_hedger', 'sml_hedger_kill')
    kill_present = os.path.exists(kill_path)
    checks.append({
        'name': 'Kill Switch Clear',
        'passed': not kill_present,
        'detail': 'No kill switch file' if not kill_present else f'KILL SWITCH ACTIVE at {kill_path}'
    })
    
    all_passed = all(c['passed'] for c in checks)
    
    return jsonify({
        'status': 'GO' if all_passed else 'NO_GO',
        'checks': checks,
        'recommendation': 'System ready for live transition' if all_passed else 'Address failing checks before going live',
        'ts': time.time()
    })

@app.route('/api/beast/gex/<symbol>')
def api_beast_gex(symbol):
    try:
        exec_eng = get_service("exec")
        if not exec_eng: return jsonify({"error": "Exec engine offline"}), 503
        data = exec_eng.get_gamma_walls(symbol)
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/beast/architect', methods=['POST'])
def api_beast_architect():
    try:
        data = request.json
        thesis = data.get('thesis', '')
        symbol = data.get('symbol', None)
        if not thesis: return jsonify({"error": "No thesis"}), 400
        
        m_arch = get_service("mythos_arch")
        if not m_arch: return jsonify({"error": "Architect offline"}), 503
        
        result = m_arch.architect(thesis, symbol)
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

def _mask(val: str) -> str:
    """Show only last 4 chars of a secret."""
    if not val or len(val) <= 4:
        return '••••'
    return '••••' + val[-4:]

@app.route('/api/settings')
def get_settings():
    return jsonify({
        'schwabKey':    _mask(os.environ.get('SCHWAB_CLIENT_ID', '')),
        'schwabSecret': _mask(os.environ.get('SCHWAB_CLIENT_SECRET', '')),
        'alpacaKey':    _mask(os.environ.get('ALPACA_API_KEY', '')),
        'alpacaSecret': _mask(os.environ.get('ALPACA_API_SECRET', '')),
        'polyKey':      _mask(os.environ.get('POLYGON_API_KEY', '')),
        'webhook':      _mask(os.environ.get('DISCORD_WEBHOOK_ALL', '')),
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
                "content": "🧪 **SQUEEZE OS v5.0** — Test alert received! Your webhook is active.",
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
        accs = dm.schwab.schwab.get_accounts()
        if accs and isinstance(accs, list):
            acc = accs[0]
            bal["schwab"] = {"equity": acc.get("currentBalances", {}).get("liquidationValue"), "buying_power": acc.get("currentBalances", {}).get("buyingPower")}
    except: pass
    return jsonify({"status": "success", "balances": bal})

# --- RISK & PERFORMANCE ---
@app.route('/api/trade/positions')
@require_localhost
def get_portfolio_positions():
    exec_eng = get_service("exec")
    if not exec_eng or not exec_eng.delta_engine:
        return jsonify({"status": "error", "message": "Delta Engine Unavailable"}), 503
    try:
        # Calculate live delta stress across all positions
        delta_data = exec_eng.delta_engine.calculate_basket_delta(state.quotes)
        return jsonify({
            "status": "success",
            "delta_stress": delta_data,
            "active_trades": exec_eng.get_active_trades()
        })
    except Exception as e:
        logger.error(f"Error calculating portfolio delta: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/trade/performance')
@app.route('/api/performance/stats')
@require_localhost
def get_performance_stats():
    exec_eng = get_service("exec")
    if not exec_eng or not exec_eng.tracker:
        return jsonify({"status": "error", "message": "Performance Tracker Unavailable"}), 503
    return jsonify({
        "status": "success",
        "stats": exec_eng.tracker.get_summary()
    })


@app.route('/api/trade-desk/status')
def api_trade_desk_status():
    """Check AI Trade Desk connectivity and bridge status."""
    discord = get_service("discord")
    if not discord:
        return jsonify({"status": "error", "message": "Discord service unavailable"}), 503
    
    result = discord.ping_trade_desk(TRADE_DESK_URL)
    return jsonify({
        "status": "success",
        "trade_desk_online": result.get('ok', False),
        "trade_desk_url": TRADE_DESK_URL,
        "service_info": result.get('data', {}),
        "error": result.get('error', None)
    })
# --- INSTITUTIONAL BRIDGES ---

@app.route('/api/beast/events')
def api_beast_events():
    """Server-Sent Events for real-time institutional alerts."""
    def stream():
        q = queue.Queue(maxsize=100)
        sse_queues.append(q)
        try:
            # Yield initial heartbeat
            yield f"data: {json.dumps({'type': 'CONNECTED', 'msg': 'Institutional SSE Active'})}\n\n"
            while True:
                event = q.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            if q in sse_queues:
                sse_queues.remove(q)
            
    return Response(stream(), mimetype='text/event-stream')

# ── Free LLM (Ollama / local Llama) ──────────────────────────────────────────

@app.route('/api/ai/status')
def api_ai_status():
    llm = get_llm()
    available = llm.is_available()
    models = llm.list_models() if available else []
    return jsonify({"available": available, "model": llm.model, "models": models})

@app.route('/api/ai/analyze', methods=['POST'])
def api_ai_analyze():
    try:
        data = request.json or {}
        mode = data.get('mode', 'signal')   # signal | options | score | commentary

        llm = get_llm()
        if not llm.is_available():
            return jsonify({"error": "Ollama not running. Start with: ollama run llama3.2"}), 503

        if mode == 'signal':
            symbol = data.get('symbol', 'UNKNOWN')
            result = llm.analyze_signal(symbol, data.get('signal', {}))
        elif mode == 'options':
            symbol = data.get('symbol', 'UNKNOWN')
            result = llm.options_thesis(symbol, data.get('chain', {}))
        elif mode == 'score':
            symbol = data.get('symbol', 'UNKNOWN')
            result = llm.score_trade(symbol, data.get('context', {}))
        elif mode == 'commentary':
            prompt = data.get('prompt', '')
            if not prompt:
                return jsonify({"error": "prompt required for commentary mode"}), 400
            result = llm.commentary(prompt)
        else:
            return jsonify({"error": f"Unknown mode: {mode}"}), 400

        return jsonify({"status": "ok", "mode": mode, "response": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Credit Beast — AI Credit Repair PWA ──────────────────────────────────────

@app.route('/credit')
def credit_app():
    return send_from_directory('.', 'credit_repair.html')

@app.route('/credit_manifest.json')
def credit_manifest():
    return send_from_directory('.', 'credit_manifest.json')

@app.route('/credit_sw.js')
def credit_sw():
    return send_from_directory('.', 'credit_sw.js'), 200, {'Content-Type': 'application/javascript'}

try:
    from credit_repair_server import credit_bp
    app.register_blueprint(credit_bp)
    logger.info("[CREDIT BEAST] Blueprint registered — /credit and /api/credit/* live")
except Exception as e:
    logger.warning(f"[CREDIT BEAST] Blueprint failed: {e}")

if __name__ == "__main__":
    init_services()
    # Register BEAST webhook routes (TradingView Pine → SqueezeOS → Discord)
    register_beast_routes(app, state)
    threading.Thread(target=worker_scanner, daemon=True).start()
    threading.Thread(target=worker_flow, daemon=True).start()
    threading.Thread(target=worker_discovery, daemon=True).start()
    threading.Thread(target=worker_autopilot, daemon=True).start()
    threading.Thread(target=worker_sr_patterns, daemon=True).start()
    threading.Thread(target=worker_beast_paper, daemon=True).start()
    threading.Thread(target=worker_iwm_odte, daemon=True).start()
    threading.Thread(target=worker_kdp_sentinel, daemon=True).start()
    threading.Thread(target=worker_trade_desk_bridge, daemon=True).start()
    port = int(os.environ.get("PORT", 8182))
    
    # SSL Context — required for Schwab OAuth callback (redirect_uri = https://127.0.0.1:8182/callback)
    import ssl
    cert_file = os.path.expanduser('~/.squeeze_os_cert.pem')
    key_file = os.path.expanduser('~/.squeeze_os_key.pem')
    ssl_ctx = None
    if os.path.exists(cert_file) and os.path.exists(key_file):
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_file, key_file)
        logger.info(f"🔒 SSL ENABLED — HTTPS on port {port}")
    else:
        logger.warning("⚠️ SSL cert/key not found — running plain HTTP (Schwab OAuth will fail)")
    
    app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True, ssl_context=ssl_ctx)
