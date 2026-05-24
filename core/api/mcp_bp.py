"""
SqueezeOS MCP Server — HTTP JSON-RPC 2.0 Transport
====================================================
Implements the Model Context Protocol so Smithery and MCP clients
can discover and call all SqueezeOS tools directly.

POST /mcp  — main JSON-RPC dispatch
GET  /mcp  — server info (health check)

Supported methods:
  initialize        — handshake + capabilities
  tools/list        — all 23 tools
  tools/call        — execute a tool (proxies to REST API)
  ping              — keepalive
  notifications/*   — silently acknowledged
"""

import json
import os
import logging
import requests
from flask import Blueprint, jsonify, request

logger    = logging.getLogger("SqueezeOS-MCP")
mcp_bp    = Blueprint('mcp', __name__)

SQUEEZEOS_BASE = os.environ.get(
    "SQUEEZEOS_BASE_URL",
    "https://lively-fascination-production-41fa.up.railway.app"
)
PROOF402_BASE = "https://four02proof.onrender.com"

_SERVER_INFO = {
    "name": "squeezeos",
    "version": "3.0.0",
    "description": "SqueezeOS — Institutional AI trading intelligence for autonomous agents",
}

_TOOLS = [
    {
        "name": "demo_council",
        "description": (
            "Free full AI council verdict for IWM (Russell 2000 ETF). "
            "Returns the exact same format as the paid council_verdict tool: "
            "regime (EXECUTION/STEALTH/CONFLICT/COLLAPSE), bias (BULLISH/BEARISH/NEUTRAL), "
            "confidence 0-100, and institutional thesis. Refreshed every 5 minutes. No payment required."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "council_verdict",
        "description": (
            "Multi-engine AI verdict for any equity symbol. "
            "SML Fractal Cascade + Battle Computer consensus. "
            "Returns regime, bias, confidence, thesis, and per-engine breakdown. "
            "Cost: 0.10 RLUSD. Pass your payment_token from verify_payment."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "Equity ticker e.g. SPY, QQQ, AAPL"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (1h TTL)"},
                "agent_wallet": {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },
    {
        "name": "market_scan",
        "description": (
            "Full $1-$50 equity universe squeeze scanner. "
            "Returns setups ranked by 8-module score + grade-A options picks. "
            "Cost: 0.05 RLUSD."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payment_token": {"type": "string"},
                "agent_wallet": {"type": "string"},
            },
        },
    },
    {
        "name": "options_intelligence",
        "description": (
            "Institutional options flow: PUT/CALL sweep detection, whale blocks, "
            "unusual volume. Net delta, GEX, put/call ratios, max pain. "
            "Cost: 0.05 RLUSD."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payment_token": {"type": "string"},
                "agent_wallet": {"type": "string"},
            },
        },
    },
    {
        "name": "iwm_odte",
        "description": (
            "IWM zero-day-to-expiry scanner. Scored contracts by delta/gamma, "
            "gamma flip level, max pain, 30-day realized vol. Cost: 0.03 RLUSD."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payment_token": {"type": "string"},
                "agent_wallet": {"type": "string"},
            },
        },
    },
    {
        "name": "signal_preview",
        "description": (
            "Free bias + regime preview for any symbol. 15-minute cache. "
            "Not tradeable — use council_verdict for full thesis."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "Equity ticker"},
            },
        },
    },
    {
        "name": "signal_history",
        "description": (
            "Last 200 recorded signals for a symbol "
            "(SQUEEZE_ALERT, OPTIONS_SWEEP, COUNCIL_VERDICT, MARKETPLACE_LISTING). "
            "Newest first. Free — enables backtesting and confidence calibration."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "Equity ticker"},
            },
        },
    },
    {
        "name": "get_invoice",
        "description": (
            "Request a payment invoice for any SqueezeOS endpoint. "
            "Returns XRPL destination address, amount in RLUSD, and memo_hex. "
            "Pay on XRPL then call verify_payment. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["endpoint_id"],
            "properties": {
                "endpoint_id": {"type": "string", "description": "UUID of the endpoint to pay for"},
            },
        },
    },
    {
        "name": "verify_payment",
        "description": (
            "Submit XRPL tx_hash after paying an invoice. "
            "Returns a signed JWT access_token (1-hour TTL) to use as payment_token. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["invoice_id", "tx_hash", "agent_wallet"],
            "properties": {
                "invoice_id": {"type": "string"},
                "tx_hash":    {"type": "string", "description": "64-char hex XRPL tx hash"},
                "agent_wallet": {"type": "string", "description": "Your XRPL classic address"},
                "agent_domain": {"type": "string", "description": "Optional agent domain for attribution"},
            },
        },
    },
    {
        "name": "bureau_public_score",
        "description": (
            "FICO-style 300-850 Agent Credit Bureau score for any XRPL wallet. "
            "Includes grade and loyalty tier. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["wallet"],
            "properties": {
                "wallet": {"type": "string", "description": "XRPL classic address (rADDRESS)"},
            },
        },
    },
    {
        "name": "marketplace_browse",
        "description": "Browse peer signal marketplace listings. Filter by symbol or bias. Free.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "bias":   {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
            },
        },
    },
    {
        "name": "marketplace_read_signal",
        "description": (
            "Read full thesis for a marketplace signal listing. "
            "Returns entry, target, stop, and seller reputation. Cost: 0.02 RLUSD."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["listing_id"],
            "properties": {
                "listing_id":    {"type": "string", "description": "UUID of the listing"},
                "payment_token": {"type": "string"},
                "agent_wallet":  {"type": "string"},
            },
        },
    },
    {
        "name": "marketplace_list_signal",
        "description": (
            "Post your own analysis signal to the marketplace. "
            "Buyers pay 0.02 RLUSD to read your thesis. "
            "Sellers earn Credit Bureau score +2 per sale. Free to post."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["wallet", "symbol", "bias", "confidence", "thesis"],
            "properties": {
                "wallet":      {"type": "string"},
                "symbol":      {"type": "string"},
                "bias":        {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                "confidence":  {"type": "number", "minimum": 0, "maximum": 100},
                "thesis":      {"type": "string"},
                "signal_type": {"type": "string"},
                "entry":       {"type": "number"},
                "target":      {"type": "number"},
                "stop":        {"type": "number"},
            },
        },
    },
    {
        "name": "hiring_browse_jobs",
        "description": "Browse open agent hiring jobs. Filter by type, symbol, or min bounty. Free.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type":       {"type": "string"},
                "symbol":     {"type": "string"},
                "min_bounty": {"type": "number"},
            },
        },
    },
    {
        "name": "hiring_post_job",
        "description": (
            "Post an analysis job for other agents to fulfill. "
            "Bounty paid direct XRPL wallet-to-wallet — SqueezeOS never holds funds. Free to post."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["wallet", "description"],
            "properties": {
                "wallet":         {"type": "string", "description": "Your XRPL wallet"},
                "job_type":       {"type": "string", "enum": ["ANALYSIS", "SCAN", "SIGNAL", "PREDICTION", "ARBITRAGE", "RESEARCH", "DATA", "CUSTOM"]},
                "symbol":         {"type": "string"},
                "description":    {"type": "string"},
                "bounty_rlusd":   {"type": "number"},
                "payment_wallet": {"type": "string"},
                "deadline_hours": {"type": "integer", "minimum": 1, "maximum": 168},
            },
        },
    },
    {
        "name": "system_status",
        "description": "SqueezeOS system health check. Returns uptime and version. Free.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    # ── Signal Futures Market ────────────────────────────────────────────────
    {
        "name": "futures_create",
        "description": (
            "Open a Signal Futures position — predict what the NEXT SqueezeOS council verdict "
            "will be for a symbol and stake RLUSD on it. Taker bets the opposite side. "
            "Auto-settles when the real verdict publishes. Winner takes 95% of pot. "
            "Zero custody — SqueezeOS tracks proof, wallets settle direct. Free to create."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["creator_wallet", "symbol", "predicted_bias"],
            "properties": {
                "creator_wallet":  {"type": "string", "description": "Your XRPL wallet"},
                "symbol":          {"type": "string", "description": "IWM, SPY, QQQ, GME, AMC, MSTR, NVDA, TSLA, PLTR, HOOD"},
                "predicted_bias":  {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                "stake_rlusd":     {"type": "number", "description": "Amount to stake (0.01-50 RLUSD, default 0.05)"},
                "session":         {"type": "string", "enum": ["PRE_MARKET", "OPEN", "MIDDAY", "POWER_HOUR", "CLOSE", "ANY"]},
                "ttl_hours":       {"type": "integer", "description": "Expiry window (default 8h)"},
                "note":            {"type": "string", "description": "Optional note (max 300 chars)"},
            },
        },
    },
    {
        "name": "futures_take",
        "description": (
            "Take the opposite side of an open Signal Futures position. "
            "You win if the council verdict does NOT match the creator's prediction. "
            "Stakes locked immediately. Settles on next council verdict for that symbol. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["future_id", "taker_wallet"],
            "properties": {
                "future_id":    {"type": "string", "description": "UUID from futures_browse"},
                "taker_wallet": {"type": "string", "description": "Your XRPL wallet"},
            },
        },
    },
    {
        "name": "futures_browse",
        "description": (
            "Browse open Signal Futures positions. Filter by symbol, status, or bias. "
            "Shows stake, pot size, creator prediction, and expiry. Free."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "status": {"type": "string", "enum": ["OPEN", "ACTIVE", "SETTLED", "EXPIRED"]},
                "bias":   {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                "limit":  {"type": "integer", "description": "Max results (default 50, max 200)"},
            },
        },
    },
    {
        "name": "futures_leaderboard",
        "description": "Top Signal Futures predictors ranked by wins. Shows win rate, PnL, total staked. Free.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)"},
            },
        },
    },
    # ── Conditional Settlement ────────────────────────────────────────────────
    {
        "name": "settlement_create",
        "description": (
            "Create a conditional agent-to-agent escrow contract. "
            "Lock intent: 'I'll pay X RLUSD to Agent B IF condition Y is met.' "
            "Conditions: bias_match, confidence_above, price_above, price_below, time_elapsed. "
            "SqueezeOS tracks and proves — wallets settle direct. 1% platform fee on settlement. Free to create."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["creator_wallet", "recipient_wallet", "amount_rlusd", "condition_type", "symbol"],
            "properties": {
                "creator_wallet":   {"type": "string", "description": "Your XRPL wallet (payer)"},
                "recipient_wallet": {"type": "string", "description": "Recipient XRPL wallet"},
                "amount_rlusd":     {"type": "number", "description": "RLUSD to pay on condition met (0.01-1000)"},
                "condition_type":   {"type": "string", "enum": ["bias_match", "confidence_above", "price_above", "price_below", "time_elapsed"]},
                "symbol":           {"type": "string", "description": "Target equity symbol"},
                "condition_value":  {"type": "string", "description": "Condition threshold (e.g. 'BULLISH', '75', '220.50')"},
                "description":      {"type": "string", "description": "Human-readable contract description"},
                "ttl_hours":        {"type": "integer", "description": "Contract expiry (default 24h)"},
            },
        },
    },
    {
        "name": "settlement_browse",
        "description": "Browse open conditional settlement contracts. Filter by symbol or creator wallet. Free.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol":  {"type": "string"},
                "wallet":  {"type": "string", "description": "Filter by creator or recipient wallet"},
                "status":  {"type": "string", "enum": ["OPEN", "TRIGGERED", "SETTLED", "EXPIRED", "CANCELLED"]},
                "limit":   {"type": "integer"},
            },
        },
    },
    {
        "name": "settlement_trigger",
        "description": (
            "Check if a settlement contract's condition is now met — and settle it if so. "
            "Publishes a settlement proof to SSE stream. Returns proof on success. "
            "Anyone can call — contract creator, recipient, or any agent. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["contract_id"],
            "properties": {
                "contract_id": {"type": "string", "description": "UUID from settlement_browse"},
            },
        },
    },
]

# Endpoint IDs for helpful 402 error messages
_ENDPOINT_IDS = {
    "council_verdict":      "12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a",
    "market_scan":          "160cf28d-b364-44eb-adbd-2489c5cc2cf8",
    "options_intelligence": "c951a374-2424-4064-ab80-35afe8053d29",
    "iwm_odte":             "60f48ce0-6002-4385-9b60-03a0d2bbebab",
    "marketplace_read_signal": "d1a2b3c4-e001-4c3f-aa24-de6e3bc12b5a",
}
_PRICES = {
    "council_verdict": 0.10, "market_scan": 0.05,
    "options_intelligence": 0.05, "iwm_odte": 0.03,
    "marketplace_read_signal": 0.02,
}


def _proxy(method, url, headers=None, json_body=None, params=None, timeout=30):
    try:
        resp = requests.request(
            method, url,
            headers=headers or {},
            json=json_body,
            params={k: v for k, v in (params or {}).items() if v is not None},
            timeout=timeout,
        )
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status": resp.status_code}
    except requests.exceptions.Timeout:
        return {"error": "ERR_UPSTREAM_TIMEOUT"}
    except Exception as e:
        return {"error": str(e)}


def _text(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


def _need_token(tool_name: str) -> dict:
    eid   = _ENDPOINT_IDS.get(tool_name, "")
    price = _PRICES.get(tool_name, 0)
    return _text({
        "error":   "ERR_PAYMENT_REQUIRED",
        "message": f"{tool_name} costs {price} RLUSD.",
        "remedy": {
            "step1": f"call get_invoice with endpoint_id '{eid}'",
            "step2": "pay RLUSD on XRPL to the returned pay_to address with memo_hex",
            "step3": "call verify_payment with invoice_id, tx_hash, agent_wallet",
            "step4": f"retry {tool_name} with payment_token from step 3",
        },
        "free_preview": f"{SQUEEZEOS_BASE}/api/demo",
    })


def _dispatch(name: str, args: dict, req_headers: dict) -> dict:
    payment_token = args.pop("payment_token", None) or req_headers.get("X-Payment-Token", "")
    agent_wallet  = args.pop("agent_wallet",  None) or req_headers.get("X-Agent-Wallet",  "")

    ph = {}
    if payment_token: ph["X-Payment-Token"] = payment_token
    if agent_wallet:  ph["X-Agent-Wallet"]  = agent_wallet

    sq = SQUEEZEOS_BASE
    p4 = PROOF402_BASE

    if name == "demo_council":
        return _text(_proxy("GET", f"{sq}/api/demo"))

    if name == "signal_preview":
        symbol = (args.get("symbol") or "IWM").upper()
        return _text(_proxy("GET", f"{sq}/api/preview/{symbol}"))

    if name == "signal_history":
        symbol = (args.get("symbol") or "").upper()
        return _text(_proxy("GET", f"{sq}/api/history/{symbol}"))

    if name == "system_status":
        return _text(_proxy("GET", f"{sq}/api/status"))

    if name == "council_verdict":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _text(_proxy("POST", f"{sq}/api/council", headers=ph, json_body={"symbol": symbol}))

    if name == "market_scan":
        if not payment_token: return _need_token(name)
        return _text(_proxy("GET", f"{sq}/api/scan", headers=ph))

    if name == "options_intelligence":
        if not payment_token: return _need_token(name)
        return _text(_proxy("GET", f"{sq}/api/options", headers=ph))

    if name == "iwm_odte":
        if not payment_token: return _need_token(name)
        return _text(_proxy("GET", f"{sq}/api/iwm", headers=ph))

    if name == "get_invoice":
        return _text(_proxy("POST", f"{p4}/v1/invoice", json_body=args))

    if name == "verify_payment":
        return _text(_proxy("POST", f"{p4}/v1/verify", json_body=args))

    if name == "bureau_public_score":
        wallet = args.get("wallet", "")
        return _text(_proxy("GET", f"{p4}/v1/bureau/score/{wallet}"))

    if name == "marketplace_browse":
        return _text(_proxy("GET", f"{sq}/api/marketplace", params=args))

    if name == "marketplace_read_signal":
        if not payment_token: return _need_token(name)
        return _text(_proxy("POST", f"{sq}/api/marketplace/read", headers=ph, json_body=args))

    if name == "marketplace_list_signal":
        return _text(_proxy("POST", f"{sq}/api/marketplace/list", json_body=args))

    if name == "hiring_browse_jobs":
        return _text(_proxy("GET", f"{sq}/api/hiring", params=args))

    if name == "hiring_post_job":
        return _text(_proxy("POST", f"{sq}/api/hiring/post", json_body=args))

    # ── Signal Futures Market ────────────────────────────────────────────────
    if name == "futures_create":
        return _text(_proxy("POST", f"{sq}/api/futures/create", json_body=args))

    if name == "futures_take":
        future_id = args.pop("future_id", "")
        return _text(_proxy("POST", f"{sq}/api/futures/take/{future_id}", json_body=args))

    if name == "futures_browse":
        return _text(_proxy("GET", f"{sq}/api/futures", params=args))

    if name == "futures_leaderboard":
        return _text(_proxy("GET", f"{sq}/api/futures/leaderboard", params=args))

    # ── Conditional Settlement ────────────────────────────────────────────────
    if name == "settlement_create":
        return _text(_proxy("POST", f"{sq}/api/settlement/create", json_body=args))

    if name == "settlement_browse":
        return _text(_proxy("GET", f"{sq}/api/settlement", params=args))

    if name == "settlement_trigger":
        contract_id = args.pop("contract_id", "")
        return _text(_proxy("POST", f"{sq}/api/settlement/trigger/{contract_id}", json_body=args))

    return {
        "content": [{"type": "text", "text": json.dumps({"error": "ERR_UNKNOWN_TOOL", "tool": name})}],
        "isError": True,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@mcp_bp.route('', methods=['GET'])
@mcp_bp.route('/', methods=['GET'])
def mcp_info():
    return jsonify({
        "server": _SERVER_INFO,
        "protocol": "MCP JSON-RPC 2.0",
        "tools_count": len(_TOOLS),
        "tools_list": "POST /mcp with {\"method\":\"tools/list\"}",
    })


@mcp_bp.route('', methods=['POST'])
@mcp_bp.route('/', methods=['POST'])
def mcp_dispatch():
    body   = request.get_json(silent=True) or {}
    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params") or {}

    def ok(result):
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})

    def rpc_err(code, message):
        return jsonify({"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": code, "message": message}}), 400

    logger.debug(f"[MCP] method={method}")

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "serverInfo":      _SERVER_INFO,
            "capabilities":    {"tools": {}},
        })

    if method == "ping":
        return ok({})

    if method == "tools/list":
        cursor = params.get("cursor")   # pagination — not needed, all fit in one page
        return ok({"tools": _TOOLS, "nextCursor": None})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = dict(params.get("arguments") or {})
        result    = _dispatch(tool_name, arguments, dict(request.headers))
        return ok(result)

    if method.startswith("notifications/"):
        return jsonify({}), 204

    return rpc_err(-32601, f"Method not found: {method}")
