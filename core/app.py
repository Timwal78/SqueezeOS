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
from core.api.v2_bridge import v2_bp
from core.api.premium_bp import premium_bp
from core.api.relay_bp import relay_bp
from core.api.webhook_bp import webhook_bp, start_webhook_engine
from core.api.marketplace_bp import marketplace_bp
from core.api.hiring_bp import hiring_bp
from core.api.mcp_bp import mcp_bp
from core.api.honeypot import honeypot_bp, honeypot_before_request
from core.api.settlement_bp import settlement_bp
from core.api.futures_bp import futures_bp
from core.api.agent_analytics import analytics_bp, before_analytics, after_analytics
import core.signal_history as signal_history
from core.legacy import start_whale_stalker, init_services, get_service, clean_data
from core.market_graph import get_graph
from core.rdt_engine import RecurrentDepthTransformer
from core.telemetry_rotator import start_telemetry_rotator

state.audit['uptime_start'] = time.time()

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SqueezeOS-Core")

def create_app():
    # Use parent directory as static folder to serve root files (index.html, .js, .css)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, static_folder=root_dir, static_url_path='')
    CORS(app) # Enable CORS for institutional dashboard
    
    # Start Legacy Workers & Services
    init_services()
    start_whale_stalker()
    
    # Honeypot must be registered FIRST so explicit trap routes take priority
    app.register_blueprint(honeypot_bp)
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
    app.register_blueprint(marketplace_bp, url_prefix='/api/marketplace')
    app.register_blueprint(hiring_bp,     url_prefix='/api/hiring')
    app.register_blueprint(mcp_bp,        url_prefix='/mcp')
    app.register_blueprint(settlement_bp, url_prefix='/api/settlement')
    app.register_blueprint(futures_bp,    url_prefix='/api/futures')
    app.register_blueprint(analytics_bp)
    app.register_blueprint(v2_bp, url_prefix='/api')
    app.register_blueprint(v2_bp, url_prefix='/api/v1', name='v2_bridge_v1')
    
    # Start background market scanner
    start_market_scanner()

    # Start webhook delivery engine (SSE tap + delivery workers)
    start_webhook_engine()

    # Start institutional telemetry rotator (Goal 3)
    start_telemetry_rotator()
    
    @app.after_request
    def run_analytics(response):
        return after_analytics(response)

    @app.after_request
    def add_no_cache(response):
        if 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    @app.route('/')
    def serve_index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.route('/terminal')
    def serve_terminal():
        return send_from_directory(app.static_folder, 'SML_Command_Center_ORACLE.html')

    @app.route('/legacy')
    def serve_legacy():
        return send_from_directory(app.static_folder, 'SML_Command_Center_ORACLE.html')

    # Discovery paths that signal agent presence when accessed
    _DISCOVERY_PATHS = frozenset({
        '/llms.txt', '/openapi.json', '/robots.txt',
        '/.well-known/mcp.json', '/.well-known/openapi.json', '/.well-known/ai-plugin.json',
        '/.well-known/server.json', '/.well-known/agents.json',
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
            # Logic for updating anchors from external ingestion
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
        """
        SML Command Center Oracle — master signal aggregator.
        Returns BUY/SELL/HOLD/SHIELD directive with full Driver/Navigator payload.
        Supports: /api/oracle  (all 3 symbols)
                  /api/oracle/GME  (single symbol)
        """
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
            # Master directive = highest confidence non-SHIELD signal
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


    # ── SML MarketGraphify + RDT Routes ──────────────────────────────────────

    @app.route('/api/graph', methods=['GET'])
    @app.route('/api/graph/<symbol>', methods=['GET'])
    def graph_snapshot(symbol=None):
        """Full Neo4j graph snapshot — nodes + edges. Live market relationship map."""
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
        """OpenMythos RDT — recursive fractal correlation across SML universe."""
        graph = get_graph()
        rdt = RecurrentDepthTransformer(graph=graph)
        try:
            # Pull live prices from oracle for RDT input
            from core.oracle_engine import OracleEngine, ORACLE_SYMBOLS
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            engine = OracleEngine(services)
            snapshots = {}
            # Dynamic Universe Discovery (Goal 1)
            active_universe = list(state.quotes.keys())[:20] if state.quotes else ORACLE_SYMBOLS
            for sym in active_universe:
                try:
                    oracle_data = engine.analyze(sym)
                    # Use `or 0.0` — oracle returns explicit None for missing fields
                    price  = oracle_data.get("price")  or 0.0
                    vpin   = oracle_data.get("vpin")   or 0.0
                    gex    = oracle_data.get("gamma_wall_above") or 0.0
                    regime = oracle_data.get("regime") or "UNKNOWN"
                    snapshots[sym] = {
                        "price": price, "vpin": vpin,
                        "gex": gex, "regime": regime
                    }
                    # Write live state into graph
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

    # ── Demo endpoint — full council verdict, IWM, no payment, 5-min cache ────
    # Shows agents the EXACT response format they get when they pay.
    # Eliminates "is this real?" friction for new agents evaluating the platform.
    _demo_cache: dict = {}
    _DEMO_TTL = 300  # 5 minutes

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
            bias   = 'BULLISH' if trend > 0.2 else 'BEARISH' if trend < -0.2 else 'NEUTRAL'
            result = {
                "demo":       True,
                "symbol":     "IWM",
                "verdict": {
                    "symbol":     "IWM",
                    "bias":       bias,
                    "regime":     data.get('regime', 'UNKNOWN'),
                    "confidence": min(100, int(abs(trend) * 200)),
                    "thesis":     f"IWM regime={data.get('regime','UNKNOWN')} trend_score={round(trend,3)} → {bias}",
                    "timestamp":  now,
                },
                "engines": {
                    "sml": {k: v for k, v in data.items() if k in (
                        'regime','trend_score','vpin','gamma_wall_above',
                        'gamma_wall_below','bias','directive',
                    )},
                },
                "note":       "Demo data — fixed symbol IWM, refreshed every 5 min. Real paid calls accept any symbol.",
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

    # ── Free Signal Preview — acquisition funnel ─────────────────────────────
    # Returns bias + regime only, cached 15 min. No payment required.
    # Enough for an agent to verify SqueezeOS works; not enough to trade on.
    _preview_cache: dict = {}
    _PREVIEW_TTL = 900  # 15 minutes

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
        except Exception:
            bias, regime = "NEUTRAL", "UNKNOWN"
        result = {
            "symbol":  symbol,
            "bias":    bias,
            "regime":  regime,
            "ts":      now,
            "preview": True,
            "upgrade": {
                "full_verdict": "/api/council",
                "price_rlusd":  "0.10",
                "includes":     ["confidence", "thesis", "engine_breakdown", "gamma_wall", "vpin"],
                "gateway":      "https://four02proof.onrender.com",
            },
        }
        _preview_cache[symbol] = result
        return jsonify(result)

    # ── Signal History — free public endpoint ────────────────────────────────
    # Last N signals per symbol from the in-memory ring buffer.
    # Free, no auth. Enables agent backtesting and confidence calibration.

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

    return app

if __name__ == "__main__":
    import ssl
    app = create_app()
    port = int(os.environ.get("PORT", 8182))
    
    cert_file = 'domain.cert.pem'
    key_file = 'private.key.pem'
    ssl_ctx = None
    
    # Goal 3: Stabilize mobile handshake by making SSL optional
    force_ssl = os.environ.get('FORCE_SSL', 'false').lower() == 'true'

    if force_ssl and os.path.exists(cert_file) and os.path.exists(key_file):
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_file, key_file)
        logger.info(f"🔒 SSL ENABLED — HTTPS on port {port}")
    else:
        logger.info(f"ℹ️ SSL DISABLED — Running HTTP on port {port} (Local/Mobile Friendly)")

    app.run(host='0.0.0.0', port=port, debug=False, threaded=True, ssl_context=ssl_ctx)
