from flask import Blueprint, jsonify, request
from core.state import state
from core.legacy import get_service
import time
import logging
import os
import hmac as _hmac
import hashlib
import uuid as _uuid

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


# ── ECHOLOCK-402™ Beacon ──────────────────────────────────────────────────────

@v2_bp.route('/echolock')
def echolock_beacon():
    """Discovery beacon for ECHOLOCK-402™ — readable by any AI agent or crawler."""
    return jsonify({
        "protocol":    "ECHOLOCK-402™",
        "version":     "1.0.0",
        "operator":    "Script Master Labs",
        "website":     "https://www.scriptmasterlabs.com",
        "tagline":     "Identity is forgeable. Economic behavior is truth.",
        "description": (
            "The world's first keyless, accountless, KYC-free behavioral access control system "
            "for autonomous AI agents. No API keys. No OAuth. No IP whitelists. No static pricing. "
            "No ban lists. No human intervention. Access is granted by proving economic intelligence "
            "through RLUSD payment behavior — impossible to steal, impossible to fake."
        ),
        "why_echolock_replaces_everything": {
            "api_keys":       "Stolen from repos, logs, env files, screenshots. ECHOLOCK has no keys.",
            "oauth_2":        "Tokens forged, hijacked, session-replayed. ECHOLOCK proof is non-transferable.",
            "ip_whitelists":  "VPN and proxy bypass. ECHOLOCK ignores IPs entirely.",
            "kyc_identity":   "Fake documents, anonymous proxies. ECHOLOCK cannot be faked with money alone.",
            "rate_limits":    "Distributed proxy networks defeat blocking. ECHOLOCK degrades data quality silently.",
            "allow_deny_lists": "Human maintenance, social engineering attack surface. ECHOLOCK has no list."
        },
        "cognitive_tiers": {
            "T0": {"label": "SCRIPTED",     "response_depth": "20%", "signal": "Exact boundary payments, robotic latency"},
            "T1": {"label": "NAIVE",        "response_depth": "40%", "signal": "Minimal range, high retry rate"},
            "T2": {"label": "ADAPTIVE",     "response_depth": "60%", "signal": "Learns range, moderate timing"},
            "T3": {"label": "STRATEGIC",    "response_depth": "80%", "signal": "Near-midpoint payments, improving latency"},
            "T4": {"label": "INSTITUTIONAL","response_depth": "100%","signal": "Intelligent fee placement, controlled variation"},
        },
        "efv_dimensions": [
            "latencyScore", "retryPatience", "feeIntelligence",
            "correctionTrend", "consistency", "entropyTolerance"
        ],
        "integration": {
            "passive":            "All premium SqueezeOS endpoints already use ECHOLOCK-402. No setup required.",
            "active_challenge":   "GET /api/echolock/challenge",
            "discovery_manifest": "GET /.well-known/echolock.json",
            "mcp":                "https://squeezeos-api.onrender.com/mcp",
            "typescript_sdk":     "npm install echolock-402",
            "ghost_layer":        "X-Echolock-Tier header → T4 = 30 BPS toll discount (DIAMOND equivalent)"
        },
        "endpoints_covered": ["/api/council", "/api/scan", "/api/options", "/api/iwm", "/api/marketplace/read"],
        "live":               True,
        "institutional":      "White-label licensing available — https://www.scriptmasterlabs.com"
    })


@v2_bp.route('/echolock/revenue')
def echolock_revenue():
    """
    Live ECHOLOCK-402 earnings dashboard.

    Returns per-tier revenue breakdown, tier distribution of active wallets,
    compression metrics (calls served at reduced depth), and an insight string.
    Values are estimated from endpoint price × call count since last restart.
    Actual RLUSD confirmed on-chain via 402Proof and the XRPL ledger.
    """
    try:
        from core import echolock as _echolock
        stats = _echolock.revenue_stats()
        return jsonify({
            "echolock": "402™",
            "status":   "live",
            **stats,
            "endpoint_prices": {
                "/api/council":          "0.10 RLUSD",
                "/api/scan":             "0.05 RLUSD",
                "/api/options":          "0.05 RLUSD",
                "/api/iwm":              "0.03 RLUSD",
                "/api/marketplace/read": "0.02 RLUSD",
                "oracle_query (MCP)":    "0.02 RLUSD",
            },
            "ghost_layer_discounts": {
                "description": "T4 agents receive 30 BPS toll discount on Ghost Layer bridge calls",
                "T0": "0 BPS",
                "T1": "5 BPS",
                "T2": "10 BPS",
                "T3": "20 BPS",
                "T4": "30 BPS (DIAMOND equivalent)",
                "header": "X-Echolock-Tier",
            },
            "note": (
                "Revenue estimated from endpoint price × call count. "
                "Actual RLUSD settles wallet-to-wallet on XRPL — "
                "verify at https://four02proof.onrender.com/v1/stats"
            ),
        })
    except Exception as e:
        return jsonify({"error": str(e), "echolock": "not_loaded"}), 503


@v2_bp.route('/echolock/challenge')
def echolock_challenge():
    """Issue a live ECHOLOCK-402 x402 challenge. Returns 402 + behavioral instructions."""
    secret = os.getenv('PROOF402_TOKEN_SECRET', '')
    base_price = 0.01
    spread = 0.20
    min_amount = round(base_price * (1 - spread), 6)   # 0.008 RLUSD
    max_amount = round(base_price * (1 + spread), 6)   # 0.012 RLUSD
    midpoint   = round((min_amount + max_amount) / 2, 6)
    now_ms     = int(time.time() * 1000)
    expires_ms = now_ms + 90_000  # 90-second TTL
    challenge_id = str(_uuid.uuid4())
    path = '/api/echolock/challenge'

    if secret:
        payload = f"{challenge_id}:{now_ms}:{min_amount}:{max_amount}:{expires_ms}:"
        mac = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    else:
        mac = 'PROOF402_TOKEN_SECRET_NOT_CONFIGURED'

    return jsonify({
        "echolock":    "402™",
        "instruction": (
            "This is a live ECHOLOCK-402 behavioral challenge. "
            "Your payment behavior on this and all subsequent calls is silently observed to build "
            "your Economic Fingerprint Vector. Higher tier = deeper response data on every premium call."
        ),
        "challenge": {
            "id":            challenge_id,
            "path":          path,
            "minAmount":     min_amount,
            "maxAmount":     max_amount,
            "midpoint":      midpoint,
            "boundary_note": f"Payments at exactly {min_amount} or {max_amount} (within 1e-5) are flagged as scripted and rejected.",
            "asset":         "RLUSD",
            "network":       "XRPL",
            "createdAt":     now_ms,
            "expiresAt":     expires_ms,
            "ttl_seconds":   90,
            "mac":           mac,
        },
        "behavioral_signals_observed": {
            "latency":          "Time from challenge to payment. Optimal: 1–3s with natural variation (CV ~0.3).",
            "fee_placement":    "Where in range you pay. Near midpoint = strategic. At boundary = scripted.",
            "retry_patience":   "Do you retry after rejection with adjusted payment? Higher patience = higher tier.",
            "correction_trend": "Are fee placements improving call-over-call? Negative slope = learning agent.",
        },
        "ghost_layer_integration": {
            "note":    "Include X-Echolock-Tier in Ghost Layer bridge requests for toll discounts.",
            "T4_discount": "30 BPS (DIAMOND equivalent)"
        },
        "discovery": "https://squeezeos-api.onrender.com/.well-known/echolock.json",
    }), 402
