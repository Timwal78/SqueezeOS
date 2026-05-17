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
    app.register_blueprint(v2_bp, url_prefix='/api')
    app.register_blueprint(v2_bp, url_prefix='/api/v1', name='v2_bridge_v1')
    
    # Start background market scanner
    start_market_scanner()
    
    # Start institutional telemetry rotator (Goal 3)
    start_telemetry_rotator()
    
    @app.after_request
    def add_no_cache(response):
        if 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    @app.route('/')
    def serve_index():
        return send_from_directory(app.static_folder, 'SML_Command_Center_ORACLE.html')

    @app.route('/legacy')
    def serve_legacy():
        return send_from_directory(app.static_folder, 'index.html')

    @app.route('/terminal')
    def serve_terminal():
        return send_from_directory(app.static_folder, 'SML_Command_Center_ORACLE.html')

    @app.route('/api/beast/events')
    def legacy_beast_events():
        """Alias for legacy frontend support."""
        return redirect('/api/events')

    @app.route('/api/telemetry', methods=['POST'])
    def root_telemetry():
        """Root-level telemetry bridge (legacy support)."""
        return redirect('/api/left-wing/telemetry', code=307)

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
