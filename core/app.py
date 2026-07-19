import os
import json
import queue
import logging
import time
import threading
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
from core.api.convergence_bp import convergence_bp, start_beastmode_scanner
from core.api.honeypot import honeypot_bp, honeypot_before_request
from core.api.settlement_bp import settlement_bp
from core.api.futures_bp import futures_bp
from core.api.oracle_data_bp import oracle_data_bp, start_oracle_pollers
from core.oracle_engine import start_oracle_batch_scanner
from core.api.ftd_bp import ftd_bp
from core.api.passport_bp import passport_bp
from core.ftd_data import start_ftd_pollers
from core.api.agent_analytics import analytics_bp, before_analytics, after_analytics
from core.api.agent_interceptor import add_discovery_headers
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
from core.api.iam_bp import iam_bp
from core.api.imo_bp import imo_bp
from core.api.orb_bp import orb_bp
from core.api.vapl_bp import vapl_bp
from core.vapl.middleware import install_vapl_middleware
from core.api.macro741_bp import macro741_bp
from core.api.macro_bp import macro_bp
from core.api.signal_products_bp import signal_products_bp
from core.api.avg_down_bp import avg_down_bp
from core.api.vault_bp import vault_bp
from core.api.cascade_bp import cascade_bp
from core.api.slack_bp import slack_bp
from core.api.ccs_bp import ccs_bp
from core.api.compliance_bp import compliance_bp
from core.api.citation_scout_bp import citation_scout_bp, start_citation_scout
from core.api.provider_score_bp import provider_score_bp
from core.api.gap_detector_bp import gap_detector_bp, start_gap_detector
from core.api.agent_economy_bp import agent_economy_bp
from core.api.aeo_stripe_bp import aeo_stripe_bp
from core.api.aeo_treasury_bp import aeo_treasury_bp
from core.api.trade_desk_stripe_bp import trade_desk_stripe_bp
from core.api.marketing_activity_bp import marketing_activity_bp
from core.api.truth_bp import truth_bp
from core.api.memory_bp import memory_bp
from core.api.fred_bp import fred_bp
from core.api.aws_marketplace_bp import aws_marketplace_bp, run_entitlements_self_check
from core.api.grants_bp import grants_bp
from core.api.gap_proposals_bp import gap_proposals_bp
from core.api.settlement_router_bp import settlement_router_bp
from core.api.delta_explosion_bp import delta_explosion_bp
from core.api.deltaforge_bp import deltaforge_bp
import core.signal_history as signal_history
from core.legacy import start_whale_stalker, init_services, get_service, clean_data
from core.market_graph import get_graph
from core.rdt_engine import RecurrentDepthTransformer
from core.telemetry_rotator import start_telemetry_rotator

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
    # CORS — restrict to known frontends in production.
    # CORS_ORIGINS env var accepts a comma-separated list; defaults to the
    # canonical dashboard origins.  Set to "*" locally if needed for dev.
    _cors_origins_env = os.environ.get(
        "CORS_ORIGINS",
        "https://scriptmasterlabs.com,https://www.scriptmasterlabs.com,"
        "https://signal-auction-loom.vercel.app,https://squeezeos-api.onrender.com",
    )
    _cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    CORS(app, origins=_cors_origins, supports_credentials=False)
    
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
    app.register_blueprint(passport_bp,    url_prefix='/api/passport')
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
    app.register_blueprint(iam_bp,           url_prefix='/api/iam')
    app.register_blueprint(imo_bp,           url_prefix='/api/imo')
    app.register_blueprint(orb_bp,           url_prefix='/api/orb')
    app.register_blueprint(vapl_bp)
    app.register_blueprint(macro741_bp,        url_prefix='/api')
    app.register_blueprint(macro_bp,           url_prefix='/api')
    app.register_blueprint(avg_down_bp,        url_prefix='/api/avg-down')
    app.register_blueprint(vault_bp,           url_prefix='/api/vault')
    app.register_blueprint(cascade_bp,         url_prefix='/api/cascade')
    app.register_blueprint(signal_products_bp, url_prefix='/api/signals')
    app.register_blueprint(slack_bp,           url_prefix='/api/slack')
    app.register_blueprint(ccs_bp,             url_prefix='/api/ccs')
    app.register_blueprint(compliance_bp,      url_prefix='/api/compliance')
    # AEO/SEO/GEO Intelligence Suite
    app.register_blueprint(citation_scout_bp,  url_prefix='/api/citation-score')
    app.register_blueprint(provider_score_bp,  url_prefix='/x402/provider-score')
    app.register_blueprint(gap_detector_bp,    url_prefix='/api/graph/gaps')
    app.register_blueprint(agent_economy_bp,   url_prefix='/x402/agent-economy')
    app.register_blueprint(aeo_stripe_bp)
    app.register_blueprint(aeo_treasury_bp,    url_prefix='/api/aeo')
    app.register_blueprint(trade_desk_stripe_bp)
    app.register_blueprint(marketing_activity_bp, url_prefix='/api/marketing')
    app.register_blueprint(truth_bp,           url_prefix='/api/truth')
    app.register_blueprint(memory_bp,          url_prefix='/api/memory')
    app.register_blueprint(fred_bp,            url_prefix='/api/fred')
    app.register_blueprint(aws_marketplace_bp, url_prefix='/api/aws-marketplace')
    app.register_blueprint(grants_bp,          url_prefix='/api/grants')
    app.register_blueprint(gap_proposals_bp,   url_prefix='/api/gap-proposals')
    app.register_blueprint(settlement_router_bp, url_prefix='/api/settlement-router')
    app.register_blueprint(delta_explosion_bp, url_prefix='/api/delta-explosion')
    app.register_blueprint(deltaforge_bp, url_prefix='/api/deltaforge')

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

    # One-shot AWS Marketplace Entitlements self-check — fires a real
    # GetEntitlements call at boot (once credentials are configured) so the
    # first deploy after adding them produces the CloudTrail-visible
    # successful call AWS's listing audit requires. No-ops (with a logged
    # reason) until AWS_MARKETPLACE_* env vars are set. Runs in a background
    # thread so a slow/unreachable AWS call never blocks startup.
    threading.Thread(target=run_entitlements_self_check, daemon=True).start()

    if not _IS_SERVERLESS:
        # Start background market scanner
        start_market_scanner()

        # Start background beastmode convergence scanner (cached, non-blocking)
        start_beastmode_scanner()

        # Start background oracle batch scanner (cached, non-blocking — see
        # core/oracle_engine.py for why /api/oracle needs this same treatment)
        start_oracle_batch_scanner()

        # Start IAM background obligation scanner — dynamic top-N from market scanner
        from iam_scanner import start_iam_scanner
        start_iam_scanner()

        # Start SML-IMO pure-Python signal scanner (no TradingView required)
        from imo_scanner import start_imo_scanner
        start_imo_scanner()

        # Start ORB v6 BEASTMODE intraday scanner (pure Python; needs
        # Polygon/Alpaca for intraday bars — logs and idles without them)
        from orb_scanner import start_orb_scanner
        start_orb_scanner()

        # Start webhook delivery engine (SSE tap + delivery workers)
        start_webhook_engine()

        # Start 24/7 options anomaly crime solver
        start_anomaly_engine()

        # Start institutional telemetry rotator (Goal 3)
        start_telemetry_rotator()

        # AEO/GEO background engines
        start_citation_scout()
        start_gap_detector()

        # Start Real-World Data Oracle pollers (SEC EDGAR, FDA, USPTO)
        start_oracle_pollers()

        # Start FTD Data Oracle pollers (SEC Reg SHO FTD + Threshold list)
        start_ftd_pollers()

        # Start ShortSqueeze Swarm — FTD/Reg SHO anomaly detection + Discord alerts
        from ftd_anomaly_engine import start_ftd_anomaly_engine
        try:
            from discord_alerts import DiscordAlerts
            _discord_for_ftd = DiscordAlerts()
        except Exception:
            _discord_for_ftd = None
        start_ftd_anomaly_engine(_discord_for_ftd)

        # SML Triple Lock Scanner — market-wide 15-min bar scanner (GEO/ARI/MAC stacks)
        from core.sml_tl_scanner import start_tl_scanner
        start_tl_scanner()

        # SML Avg-Down Engine — automated pyramid builder on 5-layer EMA ribbon
        from avg_down_engine import start_avg_down_engine
        start_avg_down_engine()

        # SML Vault Engine — same pyramid strategy on crypto via CCXT, zero
        # custody (operator's own exchange account only). No-ops with a log
        # line if SML_EMA_PERIODS / SML_VAULT_SYMBOLS aren't configured.
        from sml_vault_engine import start_vault_engine
        start_vault_engine()

        # Self-pinger — keeps Render free-tier warm; pings own /api/status every 10 min
        _start_self_pinger()
    
    @app.after_request
    def run_analytics(response):
        return after_analytics(response)

    @app.after_request
    def run_agent_interceptor(response):
        return add_discovery_headers(response)

    @app.after_request
    def add_security_headers(response):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # style-src allows 'unsafe-inline' because the FTD dashboard and Agent
        # Passport pages both use a single embedded <style> block rather than
        # an external stylesheet -- default-src 'self' alone silently drops
        # inline <style> tags per the CSP spec (confirmed live: the HTML
        # structure rendered correctly but zero CSS applied). img-src allows
        # data: because both pages' apple-touch-icon is an inline data-URI
        # SVG, which default-src 'self' also blocks. Script sources remain
        # restricted to 'self' only -- this does not affect XSS protection
        # against injected scripts.
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
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

    # ── 301 Redirects — dead routes indexed by Google ───────────────────────────────────
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
        '/api/ccs/info',
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
    
    @app.route('/api/fractal-cascade/<symbol>')
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

    _oracle_symbol_cache: dict = {}
    _ORACLE_SYMBOL_TTL = 20

    @app.route('/api/oracle', methods=['GET'])
    @app.route('/api/oracle/<symbol>', methods=['GET'])
    def oracle_signal(symbol=None):
        from core.oracle_engine import OracleEngine, ORACLE_SYMBOLS, get_oracle_batch_cache
        if symbol:
            sym = symbol.upper().strip()
            now = time.time()
            cached = _oracle_symbol_cache.get(sym)
            if cached and (now - cached['ts']) < _ORACLE_SYMBOL_TTL:
                return jsonify({"status": "success", "oracle": cached['data'], "cache_age_s": round(now - cached['ts'], 1)})

            # A fresh OracleEngine() is instantiated per request, so its internal
            # per-field _cached() TTLs (core/oracle_engine.py) never actually persist
            # across requests — this route-level cache is what makes repeated polls
            # for the same symbol (dashboards typically poll every 10-15s) cheap.
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            engine = OracleEngine(services)
            result = engine.analyze(sym)
            _oracle_symbol_cache[sym] = {"ts": now, "data": result}
            return jsonify({"status": "success", "oracle": result})
        else:
            # Cached — see core/oracle_engine.py's background batch scanner. This used
            # to run run_oracle_batch() live on every request against the full dynamic
            # universe (hundreds-to-thousands of tickers post Law-2 discovery), which
            # blew past callers' read timeouts (e.g. the Robinhood executor's 20s) on
            # every single poll. Now it just serves the last background-refreshed scan.
            cache = get_oracle_batch_cache()
            results = cache["results"]
            batch_size = cache["universe_size"] or len(ORACLE_SYMBOLS)
            ranked = sorted(
                [v for v in results.values() if v.get("directive") != "SHIELD"],
                key=lambda x: x.get("confidence", 0), reverse=True
            )
            master = ranked[0] if ranked else (list(results.values())[0] if results else {})
            return jsonify({
                "status": "success",
                "master": master,
                "symbols": results,
                "universe_size": batch_size,
                "cache_age_s": round(time.time() - cache["ts"], 1) if cache["ts"] else None,
                "stale": cache["stale"],
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
            # 100% FETCH — live scan universe; ORACLE_SYMBOLS is emergency fallback only
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
    _DEMO_RETRY_TTL = 20   # short cache for the timeout-fallback path, so we retry soon instead of waiting a full 5 min
    _DEMO_BUDGET_SEC = 15  # OracleEngine.analyze() shares a single rate-limited Tradier
                            # client with the background market scanner (up to ~160 calls
                            # per scan cycle, ~0.5s apart) — under contention analyze() can
                            # block 60-120s+. The free demo endpoint must stay responsive
                            # regardless, so it never waits past this budget.
    import concurrent.futures
    _demo_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="demo-council")

    @app.route('/api/demo', methods=['GET'])
    @app.route('/api/demo/council', methods=['GET'])
    def demo_council():
        now = time.time()
        cached = _demo_cache.get('council')
        if cached:
            cache_ttl = cached.get('_cache_ttl_override', _DEMO_TTL)
            if (now - cached.get('_cached_at', 0)) < cache_ttl:
                return jsonify(cached)
        try:
            from core.oracle_engine import OracleEngine
            services = {
                "dm":            get_service("dm"),
                "whale_stalker": get_service("whale_stalker"),
                "sml":           get_service("sml"),
            }
            engine = OracleEngine(services)
            try:
                data = _demo_executor.submit(engine.analyze, 'IWM').result(timeout=_DEMO_BUDGET_SEC)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    f"[DEMO] OracleEngine.analyze('IWM') exceeded {_DEMO_BUDGET_SEC}s budget "
                    "(likely queued behind the background scanner's Tradier calls) — "
                    "returning AWAITING_DATA instead of blocking the demo endpoint"
                )
                result = {
                    "demo":       True,
                    "status":     "AWAITING_DATA",
                    "symbol":     "IWM",
                    "verdict": {
                        "symbol":     "IWM",
                        "bias":       "NEUTRAL",
                        "regime":     "UNKNOWN",
                        "confidence": 0,
                        "thesis":     ("Live engines are busy refreshing full-universe market data right now. "
                                       "This is a transient state, not an outage — retry in ~20 seconds. The paid "
                                       "/api/council endpoint returns AWAITING_DATA in the same shape — no charge "
                                       "applies if data is not yet ready."),
                        "timestamp":  now,
                    },
                    "engines": {},
                    "note":       "Demo data — fixed symbol IWM, refreshed every 5 min. Real paid calls accept any symbol.",
                    "next_refresh_seconds": _DEMO_RETRY_TTL,
                    "upgrade": {
                        "any_symbol":  "/api/council",
                        "price_rlusd": "0.10",
                        "gateway":     "https://four02proof.onrender.com",
                        "includes":    ["any symbol", "live data", "full engine breakdown", "battle computer consensus"],
                    },
                    "_cached_at": now,
                    "_cache_ttl_override": _DEMO_RETRY_TTL,
                }
                _demo_cache['council'] = result
                return jsonify(result)
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

    install_vapl_middleware(app)

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
