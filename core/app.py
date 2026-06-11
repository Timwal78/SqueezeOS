import os
import json
import queue
import logging
import time
from datetime import datetime
from flask import Flask, Response, jsonify, redirect, url_for, send_from_directory, request
from flask_cors import CORS
from core.state import state, sse_queues
from core.api.left_wing import left_wing_bp
from core.api.beast import beast_bp
from core.api.mmle import mmle_bp
from core.api.battle import battle_bp
from core.api.ai_reads import ai_reads_bp
from core.api.scriptmaster_bp import scriptmaster_bp
from core.api.ceo import ceo_bp
from core.api.market_scanner import market_bp, start_market_scanner
from options_anomaly_engine import start_anomaly_engine
from core.api.v2_bridge import v2_bp
from core.api.premium_bp import premium_bp
from core.api.relay_bp import relay_bp
from core.api.webhook_bp import webhook_bp, start_webhook_engine
from core.api.tradingview_webhook_bp import tradingview_webhook_bp
from core.api.marketplace_bp import marketplace_bp
from core.api.hiring_bp import hiring_bp
from core.api.mcp_bp import mcp_bp
from core.api.proprietary_ema_bp import proprietary_ema_bp
from core.api.convergence_bp import convergence_bp
from core.api.honeypot import honeypot_bp, honeypot_before_request
from core.api.settlement_bp import settlement_bp
from core.api.futures_bp import futures_bp
from core.api.oracle_data_bp import oracle_data_bp, start_oracle_pollers
from core.api.ftd_bp import ftd_bp
from core.ftd_data import start_ftd_pollers
from core.api.agent_analytics import analytics_bp, before_analytics, after_analytics
from core.api.autopilot_bp import autopilot_bp
from core.api.stigmergy_bp import stigmergy_bp
from core.api.notary_bp import notary_bp
from core.api.triple_lock_bp import triple_lock_bp
from core.api.nw_liq_bp import nw_liq_bp
from core.api.keys_bp import keys_bp
from core.api.config_bp import config_bp
from core.api.sml_alert_bp import sml_alert_bp
from core.api.smithery_bp import smithery_bp
from core.api.oracle_engine_bp import oracle_engine_bp
import core.signal_history as signal_history
from core.legacy import start_whale_stalker, init_services, get_service, clean_data
from core.market_graph import get_graph
from core.rdt_engine import RecurrentDepthTransformer
from core.telemetry_rotator import start_telemetry_rotator
from tools.sales_agent import start_sales_agent

state.audit['uptime_start'] = time.time()

# Serverless detection — skip background threads on Vercel (stateless per-request)
_IS_SERVERLESS = os.environ.get('VERCEL') == '1'


def _start_self_pinger():
    """
    Daemon thread that pings /api/status every 10 min.
    Prevents Render free-tier cold-start spin-down independent of GitHub Actions keepalive.
    Uses SQUEEZEOS_BASE_URL env var; falls back to the canonical Render URL.
    """
    import threading as _threading
    import urllib.request as _urlreq

    base = os.getenv('SQUEEZEOS_BASE_URL', 'https://squeezeos-api.onrender.com').rstrip('/')
    url  = f"{base}/api/status"

    def _loop():
        time.sleep(90)           # give gunicorn time to finish startup
        while True:
            try:
                _urlreq.urlopen(url, timeout=30)
            except Exception:
                pass             # failures are silent — GH Actions keepalive is the primary
            time.sleep(600)      # 10-minute interval

    t = _threading.Thread(target=_loop, daemon=True, name="self-pinger")
    t.start()
    logger.info("[self-pinger] Started — pinging %s every 10 min", url)

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SqueezeOS-Core")

def create_app():
    # Use parent directory as static folder to serve root files (index.html, .js, .css)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, static_folder=root_dir, static_url_path='')
    CORS(app) # Enable CORS for institutional dashboard
    
    # Start Legacy Workers & Services (skipped in Vercel serverless mode)
    if not _IS_SERVERLESS:
        init_services()
        start_whale_stalker()
    
    # Honeypot must be registered FIRST so explicit trap routes take priority
    app.register_blueprint(honeypot_bp)
    app.register_blueprint(smithery_bp)
    app.before_request(honeypot_before_request)
    app.before_request(before_analytics)

    # Register Blueprints
    app.register_blueprint(left_wing_bp, url_prefix='/api/left-wing')
    app.register_blueprint(beast_bp, url_prefix='/api/beast')
    app.register_blueprint(mmle_bp, url_prefix='/api/mmle')
    app.register_blueprint(battle_bp, url_prefix='/api/battle')
    app.register_blueprint(ai_reads_bp, url_prefix='/api/ai')
    app.register_blueprint(scriptmaster_bp, url_prefix='/api/scriptmaster')
    app.register_blueprint(ceo_bp, url_prefix='/api/ceo')
    app.register_blueprint(market_bp, url_prefix='/api/market')
    app.register_blueprint(premium_bp, url_prefix='/api')
    app.register_blueprint(relay_bp, url_prefix='/api/relay')
    app.register_blueprint(webhook_bp,     url_prefix='/api/webhooks')
    app.register_blueprint(tradingview_webhook_bp, url_prefix='/api/webhooks')
    app.register_blueprint(marketplace_bp, url_prefix='/api/marketplace')
    app.register_blueprint(hiring_bp,     url_prefix='/api/hiring')
    app.register_blueprint(mcp_bp,        url_prefix='/mcp')
    app.register_blueprint(settlement_bp,  url_prefix='/api/settlement')
    app.register_blueprint(futures_bp,     url_prefix='/api/futures')
    app.register_blueprint(oracle_data_bp, url_prefix='/api/oracle')
    app.register_blueprint(ftd_bp,         url_prefix='/api/ftd')
    app.register_blueprint(stigmergy_bp,  url_prefix='/api/stigmergy')
    app.register_blueprint(notary_bp,     url_prefix='/api/notary')
    app.register_blueprint(triple_lock_bp, url_prefix='/api/triple-lock')
    app.register_blueprint(nw_liq_bp,      url_prefix='/api/nwliq')
    app.register_blueprint(sml_alert_bp,  url_prefix='/api/sml')
    app.register_blueprint(proprietary_ema_bp, url_prefix='/api')
    app.register_blueprint(convergence_bp,     url_prefix='/api')
    app.register_blueprint(autopilot_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(keys_bp)
    app.register_blueprint(config_bp, url_prefix='/api')
    app.register_blueprint(v2_bp, url_prefix='/api')
    app.register_blueprint(v2_bp, url_prefix='/api/v1', name='v2_bridge_v1')
    app.register_blueprint(oracle_engine_bp, url_prefix='/api/engine')

    # Stellar Forge growth engine — feature-flagged, dormant unless enabled.
    # Registers the affiliate/loyalty/payout surface only when explicitly turned
    # on (after a Postgres DSN + payout wallet are in place). Off by default.
    if os.environ.get('STELLAR_FORGE_ENABLED', '').lower() == 'true':
        from core.api.forge_bp import forge_bp
        app.register_blueprint(forge_bp, url_prefix='/api/forge')
        logging.getLogger('SqueezeOS').info('Stellar Forge blueprint ENABLED at /api/forge')
    
    # Log key convergence routes so Render startup logs confirm registration
    key_routes = ["/api/convergence", "/api/beastmode", "/api/market/scan", "/api/council", "/api/scan"]
    registered = {r.rule for r in app.url_map.iter_rules()}
    for kr in key_routes:
        hit = any(r.startswith(kr) for r in registered)
        logger.info("[routes] %s → %s", kr, "REGISTERED" if hit else "MISSING ⚠")

    if not _IS_SERVERLESS:
        # Start background market scanner
        start_market_scanner()

        # Start webhook delivery engine (SSE tap + delivery workers)
        start_webhook_engine()

        # Start 24/7 options anomaly crime solver
        start_anomaly_engine()

        # Start institutional telemetry rotator (Goal 3)
        start_telemetry_rotator()

        # Start Real-World Data Oracle pollers (SEC EDGAR, FDA, USPTO)
        start_oracle_pollers()

        # Start FTD Data Oracle pollers (SEC Reg SHO FTD + Threshold list)
        start_ftd_pollers()

        # Self-pinger — keeps Render free-tier warm; pings own /api/status every 10 min
        _start_self_pinger()
        
        # Autonomous AI Sales Agent — hunts for leads and sends pitches to Discord daily
        start_sales_agent()
    
    @app.after_request
    def run_analytics(response):
        return after_analytics(response)

    @app.after_request
    def add_security_headers(response):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Link'] = '<https://squeezeos-api.onrender.com/.well-known/agents.json>; rel="payment"'
        if 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "NOT_FOUND", "message": "Endpoint does not exist"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "INTERNAL_ERROR", "message": "Server error"}), 500

    @app.route('/')
    def serve_index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.route('/terminal')
    @app.route('/beastmode')
    def serve_beastmode():
        return send_from_directory(app.static_folder, 'beastmode.html')

    @app.route('/beast')
    def serve_beast():
        return send_from_directory(app.static_folder, 'beast.html')

    @app.route('/gme')
    def serve_gme_beastmode():
        return send_from_directory(app.static_folder, 'gme_beastmode.html')

    @app.route('/card')
    def serve_card():
        return send_from_directory(app.static_folder, 'card.html')

    # ── 301 Redirects — dead routes indexed by Google ────────────────────────
    # All permanently redirect to / so link equity passes forward, no 404 penalty.
    @app.route('/trading-indicators')
    @app.route('/trading-indicators/')
    def redirect_trading_indicators():
        return redirect('/', code=301)

    @app.route('/neurospark')
    @app.route('/neurospark/')
    def redirect_neurospark():
        return redirect('/', code=301)

    @app.route('/enoch-adhd')
    @app.route('/enoch-adhd/')
    def redirect_enoch_adhd():
        return redirect('/', code=301)

    @app.route('/NeuroStack')
    @app.route('/NeuroStack/')
    def redirect_neurostack():
        return redirect('/', code=301)

    @app.route('/MasterSheets')
    @app.route('/MasterSheets/')
    def redirect_mastersheets():
        return redirect('/', code=301)

    @app.route('/apps/fee-forge')
    @app.route('/apps/fee-forge/')
    def redirect_fee_forge():
        return redirect('/', code=301)

    @app.route('/books/book-of-enoch')
    @app.route('/books/book-of-enoch/')
    def redirect_book_of_enoch():
        return redirect('/', code=301)

    @app.route('/apps/darkpool-scanner')
    @app.route('/apps/darkpool-scanner/')
    def redirect_darkpool_scanner():
        return redirect('/', code=301)

    @app.route('/apps/exo-brain')
    @app.route('/apps/exo-brain/')
    def redirect_exo_brain():
        return redirect('/', code=301)

    # Discovery paths that signal agent presence when accessed
    _DISCOVERY_PATHS = frozenset({
        '/llms.txt', '/openapi.json', '/robots.txt',
        '/.well-known/mcp.json', '/.well-known/openapi.json', '/.well-known/ai-plugin.json',
        '/.well-known/server.json', '/.well-known/agents.json',
        '/.well-known/catalog.json', '/.well-known/x402-registry.json',
    })

    def _broadcast_sse(event: dict):
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

    # Global broadcast accessible by blueprints (settlement, futures)
    import core.app as _self_module
    _self_module._broadcast_sse_global = _broadcast_sse

    @app.after_request
    def broadcast_agent_signals(response):
        path = request.path
        ua = request.headers.get('User-Agent', '')[:60]
        wallet = request.headers.get('X-Agent-Wallet', '')
        if path in _DISCOVERY_PATHS and response.status_code == 200:
            _broadcast_sse({
                'type': 'AGENT_PROBE',
                'path': path,
                'agent': ua,
                'wallet': wallet,
                'ts': time.time(),
            })
        elif response.status_code == 402:
            _broadcast_sse({
                'type': 'AGENT_PAY',
                'path': path,
                'agent': ua,
                'wallet': wallet,
                'ts': time.time(),
            })
        return response

    @app.route('/robots.txt')
    def serve_robots():
        return send_from_directory(app.static_folder, 'robots.txt', mimetype='text/plain')

    @app.route('/sitemap.xml')
    def serve_sitemap():
        return send_from_directory(app.static_folder, 'sitemap.xml', mimetype='application/xml')

    @app.route('/llms.txt')
    def serve_llms():
        return send_from_directory(app.static_folder, 'llms.txt', mimetype='text/plain')

    @app.route('/openapi.json')
    def serve_openapi_root():
        return send_from_directory(app.static_folder, 'openapi.json', mimetype='application/json')

    @app.route('/.well-known/openapi.json')
    def serve_openapi_wellknown():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'openapi.json',
            mimetype='application/json'
        )

    @app.route('/.well-known/ai-plugin.json')
    def serve_ai_plugin():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'ai-plugin.json',
            mimetype='application/json'
        )

    @app.route('/.well-known/mcp.json')
    def serve_mcp():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'mcp.json',
            mimetype='application/json'
        )

    @app.route('/.well-known/agents.json')
    def serve_agents():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'agents.json',
            mimetype='application/json'
        )

    @app.route('/.well-known/server.json')
    def serve_server_json():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'server.json',
            mimetype='application/json'
        )

    @app.route('/.well-known/catalog.json')
    def serve_catalog_json():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'catalog.json',
            mimetype='application/json'
        )

    @app.route('/.well-known/x402-registry.json')
    def serve_x402_registry():
        return send_from_directory(
            os.path.join(app.static_folder, '.well-known'), 'x402-registry.json',
            mimetype='application/json'
        )



    @app.route('/api/beast/events')
    def legacy_beast_events():
        """Alias for legacy frontend support."""
        return redirect('/api/events')

    @app.route('/api/telemetry', methods=['POST'])
    def root_telemetry():
        """Root-level telemetry bridge (legacy support)."""
        return redirect('/api/left-wing/telemetry', code=307)

    @app.route('/api/events/push', methods=['POST'])
    def push_event():
        """Agent broadcast endpoint — pushes an event to all SSE + webhook subscribers."""
        event = request.get_json(silent=True) or {}
        if not event.get("type"):
            return jsonify({"error": "type required"}), 400
        event["ts"] = event.get("ts") or time.time()
        _broadcast_sse(event)
        return jsonify({"status": "pushed", "type": event["type"], "ts": event["ts"]})

    @app.route('/api/events')
    def sse_events():
        """Unified SSE stream for institutional alerts."""
        def stream():
            q = queue.Queue(maxsize=100)
            sse_queues.append(q)
            try:
                yield f"data: {json.dumps({'type': 'CONNECTED', 'msg': 'SqueezeOS-Core SSE Active'})}\n\n"
                while True:
                    event = q.get()
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                if q in sse_queues:
                    sse_queues.remove(q)
        return Response(stream(), mimetype='text/event-stream')
    
    @app.route('/api/cascade/<symbol>')
    def get_cascade(symbol):
        """Fractal Cascade multi-timeframe alignment (Legacy Bridge)."""
        symbol = symbol.upper().strip()
        sml = get_service("sml")
        dm = get_service("dm")
        if not sml or not dm:
            return jsonify({"status": "error", "message": "SML or DM service unavailable"}), 503
        
        history = dm.get_history(symbol)
        if not history:
            return jsonify({"status": "error", "message": f"No history for {symbol}"}), 404
        
        data = sml.compute_fractal_cascade(symbol, {symbol: history})
        return jsonify(clean_data({
            "status": "success",
            "data": data
        }))

    @app.route('/api/ftd', methods=['GET', 'POST'])
    def get_ftd_data():
        """Automated FTD tracker feed for Mobile Battle Computer."""
        registry_path = os.path.join(os.path.dirname(__file__), 'ftd_registry.json')
        
        if os.path.exists(registry_path):
            with open(registry_path, 'r') as f:
                registry = json.load(f)
        else:
            registry = {"gme": [], "amc": [], "last_updated": "never"}

        if request.method == 'POST':
            new_data = request.get_json()
            if 'gme' in new_data: registry['gme'] = new_data['gme']
            if 'amc' in new_data: registry['amc'] = new_data['amc']
            registry['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(registry_path, 'w') as f:
                json.dump(registry, f, indent=2)
            return jsonify({"status": "success", "message": "Registry updated"})

        return jsonify({
            "status": "success",
            "timestamp": registry.get('last_updated', datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "gme": "\n".join(registry.get('gme', [])),
            "amc": "\n".join(registry.get('amc', []))
        })

    @app.route('/api/status')
    def system_status():
        return jsonify({
            "status": "online",
            "uptime": round(time.time() - state.audit['uptime_start'], 2),
            "version": "6.1-CORE"
        })

    @app.route('/api/oracle', methods=['GET'])
    @app.route('/api/oracle/<symbol>', methods=['GET'])
    def oracle_signal(symbol=None):
        from core.oracle_engine import OracleEngine, ORACLE_SYMBOLS, run_oracle_batch
        services = {
            "dm":            get_service("dm"),
            "whale_stalker": get_service("whale_stalker"),
            "sml":           get_service("sml"),
        }
        if symbol:
            sym = symbol.upper().strip()
            engine = OracleEngine(services)
            result = engine.analyze(sym)
            return jsonify({"status": "success", "oracle": result})
        else:
            results = run_oracle_batch(ORACLE_SYMBOLS, services)
            ranked = sorted(
                [v for v in results.values() if v.get("directive") != "SHIELD"],
                key=lambda x: x.get("confidence", 0), reverse=True
            )
            master = ranked[0] if ranked else list(results.values())[0]
            return jsonify({
                "status": "success",
                "master": master,
                "symbols": results,
                "timestamp": datetime.now().isoformat(),
            })

    @app.route('/api/graph', methods=['GET'])
    @app.route('/api/graph/<symbol>', methods=['GET'])
    def graph_snapshot(symbol=None):
        graph = get_graph()
        if not graph:
            return jsonify({"status": "error", "message": "Neo4j unavailable"}), 503
        try:
            if symbol:
                sym = symbol.upper().strip()
                nodes = [n for n in graph.get_all_tickers() if n["symbol"] == sym]
                edges = graph.get_edges(sym)
            else:
                nodes = graph.get_all_tickers()
                edges = graph.get_edges()
            return jsonify({
                "status": "success",
                "nodes": nodes,
                "edges": edges,
                "snapshot_ts": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"[GRAPH] Snapshot error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/graph/rdt', methods=['GET'])
    def rdt_signals():
        graph = get_graph()
        rdt = RecurrentDepthTransformer(graph=graph)
        try:
            from core.oracle_engine import OracleEngine, ORACLE_SYMBOLS
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            engine = OracleEngine(services)
            snapshots = {}
            active_universe = list(state.quotes.keys()) if state.quotes else ORACLE_SYMBOLS
            for sym in active_universe:
                try:
                    oracle_data = engine.analyze(sym)
                    price  = oracle_data.get("price")  or 0.0
                    vpin   = oracle_data.get("vpin")   or 0.0
                    gex    = oracle_data.get("gamma_wall_above") or 0.0
                    regime = oracle_data.get("regime") or "UNKNOWN"
                    snapshots[sym] = {
                        "price": price, "vpin": vpin,
                        "gex": gex, "regime": regime
                    }
                    if graph:
                        graph.update_ticker(
                            symbol=sym, price=price,
                            regime=regime, vpin=vpin, gex=gex
                        )
                except Exception as e:
                    logger.warning(f"[RDT] Oracle pull failed for {sym}: {e}")

            signals = rdt.run_universe(snapshots)
            return jsonify({
                "status": "success",
                "signals": [
                    {
                        "symbol":        s.symbol,
                        "direction":     s.direction,
                        "confidence":    round(s.confidence, 1),
                        "fractal_match": s.fractal_match,
                        "fractal_score": round(s.fractal_score, 1),
                        "target_mult":   s.target_mult,
                        "reason":        s.reason,
                        "depth":         s.depth,
                        "ts":            s.ts
                    } for s in signals
                ],
                "top_pick": signals[0].symbol if signals else None,
                "ts": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"[RDT] Error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    _demo_cache: dict = {}
    _DEMO_TTL = 300

    @app.route('/api/demo', methods=['GET'])
    @app.route('/api/demo/council', methods=['GET'])
    def demo_council():
        now = time.time()
        cached = _demo_cache.get('council')
        if cached and (now - cached.get('_cached_at', 0)) < _DEMO_TTL:
            return jsonify(cached)
        try:
            from core.oracle_engine import OracleEngine
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            engine = OracleEngine(services)
            data   = engine.analyze('IWM')
            trend  = data.get('trend_score', 0) or 0
            regime = data.get('regime', 'UNKNOWN')
            bias   = 'BULLISH' if trend > 0.2 else 'BEARISH' if trend < -0.2 else 'NEUTRAL'
            awaiting = regime in ('UNKNOWN', '') and abs(trend) < 1e-6
            if awaiting:
                thesis = ("IWM live data feed warming up. This is a transient state; the engines "
                          "(SML Fractal Cascade, Battle Computer, OracleEngine) need ~1 market-data tick "
                          "to populate before producing a directive. Retry in ~60 seconds. The paid /api/council "
                          "endpoint returns AWAITING_DATA in the same shape — no charge applies if data is not yet ready.")
            else:
                thesis = f"IWM regime={regime} trend_score={round(trend,3)} → {bias}"
            result = {
                "demo":       True,
                "status":     "AWAITING_DATA" if awaiting else "READY",
                "symbol":     "IWM",
                "verdict": {
                    "symbol":     "IWM",
                    "bias":       bias,
                    "regime":     regime,
                    "confidence": min(100, int(abs(trend) * 200)),
                    "thesis":     thesis,
                    "timestamp":  now,
                },
                "engines": {
                    "sml": {k: v for k, v in data.items() if k in (
                        'regime','trend_score','vpin','gamma_wall_above',
                        'gamma_wall_below','bias','directive',
                    )},
                },
                "note":       "Demo data — fixed symbol IWM, refreshed every 5 min. Real paid calls accept any symbol.",
                "next_refresh_seconds": _DEMO_TTL,
                "upgrade": {
                    "any_symbol":  "/api/council",
                    "price_rlusd": "0.10",
                    "gateway":     "https://four02proof.onrender.com",
                    "includes":    ["any symbol", "live data", "full engine breakdown", "battle computer consensus"],
                },
                "_cached_at": now,
            }
        except Exception as e:
            result = {
                "demo":    True,
                "symbol":  "IWM",
                "error":   str(e),
                "note":    "Oracle engine temporarily offline. Try /api/preview/IWM for cached preview.",
                "_cached_at": now,
            }
        _demo_cache['council'] = result
        return jsonify(result)

    _preview_cache: dict = {}
    _PREVIEW_TTL = 900

    @app.route('/api/preview', methods=['GET'])
    @app.route('/api/preview/<symbol>', methods=['GET'])
    def signal_preview(symbol='IWM'):
        symbol = symbol.upper().strip()
        now = time.time()
        cached = _preview_cache.get(symbol)
        if cached and (now - cached['ts']) < _PREVIEW_TTL:
            return jsonify(cached)
        try:
            from core.oracle_engine import OracleEngine
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            engine = OracleEngine(services)
            data   = engine.analyze(symbol)
            bias   = data.get("bias") or data.get("directive", "NEUTRAL")
            regime = data.get("regime", "UNKNOWN")
            trend_score = data.get("trend_score", 0.0)
            
            # Determine Conviction Tier
            if abs(trend_score) > 0.8: conviction = "EXTREME"
            elif abs(trend_score) > 0.5: conviction = "HIGH"
            elif abs(trend_score) > 0.2: conviction = "MODERATE"
            else: conviction = "LOW"
            
            # Extract top signals
            signals = data.get("signals", [])
            top_signals = signals[:3] if isinstance(signals, list) else []
            
        except Exception:
            bias, regime, conviction, top_signals = "NEUTRAL", "UNKNOWN", "LOW", []
            
        result = {
            "symbol":  symbol,
            "bias":    bias,
            "regime":  regime,
            "conviction_tier": conviction,
            "top_signals_detected": len(top_signals),
            "top_signals_preview": top_signals,
            "ts":      now,
            "preview": True,
            "upgrade": {
                "full_verdict": "/api/council",
                "price_rlusd":  "0.10",
                "includes":     ["confidence", "thesis", "full_engine_breakdown", "gamma_wall_levels", "vpin_exact_value", "institutional_flow_data", "dark_pool_prints"],
                "gateway":      "https://four02proof.onrender.com",
                "view_example": "/api/council/example"
            },
        }
        _preview_cache[symbol] = result
        return jsonify(result)

    @app.route('/api/council/example', methods=['GET'])
    def council_example():
        """Redirects to the live SPY council endpoint — no mock data per DEVELOPER_MANIFESTO."""
        from flask import redirect
        return redirect('/api/council/SPY', code=302)

    @app.route('/api/history', methods=['GET'])
    def signal_history_all():
        limit = min(int(request.args.get('limit', 100)), 500)
        return jsonify({
            "signals":  signal_history.get_all_recent(limit),
            "symbols":  signal_history.get_symbols(),
            "limit":    limit,
            "free":     True,
            "ts":       time.time(),
        })

    @app.route('/api/history/<symbol>', methods=['GET'])
    def signal_history_symbol(symbol):
        sym   = symbol.upper().strip()
        limit = min(int(request.args.get('limit', 50)), 200)
        return jsonify({
            "symbol":   sym,
            "signals":  signal_history.get_history(sym, limit),
            "count":    len(signal_history.get_history(sym, limit)),
            "limit":    limit,
            "free":     True,
            "upgrade":  {
                "live_stream":  "/api/events",
                "webhooks":     "/api/webhooks/subscribe",
                "full_verdict": "/api/council",
                "price_rlusd":  "0.10",
            },
            "ts":       time.time(),
        })


    @app.route('/<path:path>')
    def serve_static(path):
        return send_from_directory(app.static_folder, path)


    @app.route('/health')
    def health():
        import datetime
        return jsonify({'status': 'ok', 'service': 'squeezeos-api', 'version': '7.0', 'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'})

    from x402_flask import register_x402_discovery
    register_x402_discovery(app)

    return app

if __name__ == "__main__":
    import ssl
    app = create_app()
    port = int(os.environ.get("PORT", 8182))
    
    cert_file = 'domain.cert.pem'
    key_file = 'private.key.pem'
    ssl_ctx = None
    
    force_ssl = os.environ.get('FORCE_SSL', 'false').lower() == 'true'

    if force_ssl and os.path.exists(cert_file) and os.path.exists(key_file):
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_file, key_file)
        logger.info(f"🔒 SSL ENABLED — HTTPS on port {port}")
    else:
        logger.info(f"ℹ️ SSL DISABLED — Running HTTP on port {port} (Local/Mobile Friendly)")

    app.run(host='0.0.0.0', port=port, debug=False, threaded=True, ssl_context=ssl_ctx)
