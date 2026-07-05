"""
SqueezeOS MCP Server — HTTP JSON-RPC 2.0 Transport
====================================================
Implements the Model Context Protocol so Smithery and MCP clients
can discover and call all SqueezeOS tools directly.

POST /mcp  — main JSON-RPC dispatch
GET  /mcp  — server info (health check)

Supported methods:
  initialize        — handshake + capabilities
  tools/list        — all tools
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

try:
    from core import echolock as _echolock
    _ECHOLOCK = True
except ImportError:
    _echolock = None  # type: ignore[assignment]
    _ECHOLOCK = False

SQUEEZEOS_BASE = os.environ.get(
    "SQUEEZEOS_BASE_URL",
    "https://squeezeos-api.onrender.com"
)
PROOF402_BASE = "https://four02proof.onrender.com"

_SERVER_INFO = {
    "name": "squeezeos",
    "version": "5.0.0",
    "description": "SqueezeOS — Institutional AI trading intelligence + Sovereign Autopilot + Real-World Data Oracle for autonomous agents",
}

_TOOLS = [
    {
        "name": "demo_council",
        "description": (
            "Free preview of council_verdict, scoped to IWM (Russell 2000 ETF). "
            "Same JSON shape, same engines, 5-minute cache. "
            "Use this to validate output quality and integration before paying 0.10 RLUSD "
            "per call on council_verdict for any symbol."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "council_verdict",
        "description": (
            "Institutional-grade BUY/SELL/HOLD directive for US equity symbols — "
            "the production-grade upgrade from demo_council (which is IWM-only, 5-min cached, free). "
            "Aggregates 8 proprietary engines — gamma-flow + flip detection, VPIN order-flow toxicity, "
            "fractal anchor confluence, regime classifier, dark-pool axis tracking, "
            "options sweep intelligence, mean-reversion regime, and Battle Computer consensus — "
            "into one tradeable verdict: directive, confidence 0-100, regime label "
            "(ALPHA_EXPANSION / MACRO_COLLAPSE / NEUTRAL / SHIELD), price targets (tp1/tp2/stop), "
            "and a per-engine breakdown explaining the score. "
            "Call this when you need a high-conviction directional read before sizing or executing a position — "
            "this is the same verdict institutional desks subscribe to at $1,000/mo via the Leviathan tier. "
            "Cost: 0.10 RLUSD per call (~$0.10). 60-second per-symbol cache, so back-to-back queries on the same "
            "ticker are effectively free. Pass payment_token from verify_payment plus your agent_wallet. "
            "Coverage: US equities; crypto coverage in roadmap. "
            "Typical response time: <2s cached, ~4s fresh compute."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "US equity ticker (e.g. SPY, QQQ, AAPL, NVDA, GME, AMC, IWM)"},
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
    # ── Cognitive Credit Swarms ────────────────────────────────────────────────
    {
        "name": "ccs_validate",
        "description": (
            "Cognitive Credit Swarms — Content Trust Validation. "
            "Submit any text (news, message, social post, ad copy) and receive a trust score 0-100, "
            "a verdict (TRUSTED / LOW_RISK / SUSPICIOUS / HIGH_RISK / BLOCKED), and a flag breakdown "
            "identifying manipulation patterns: certainty abuse, emotional manipulation, attribution gaps, "
            "synthetic/AI content markers, excessive capitalization. "
            "Sender wallet reputation is tracked on the Agent Credit Bureau — blocked senders accumulate "
            "negative history. Used by agents to filter their information environment and enforce a "
            "Micro-Attention Tax: misinformation costs the sender without reaching the target. "
            "Free tier: 3 calls/hour per IP. Paid: 0.01 RLUSD per call via X-Payment-Token (unlimited). "
            "Endpoint ID for payment: 05764097-3f3e-4279-89e5-c786efab2f91"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["content"],
            "properties": {
                "content":       {"type": "string", "description": "Text to validate (max 10,000 chars)"},
                "sender_wallet": {"type": "string", "description": "XRPL wallet of the content sender (optional, enables reputation tracking)"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.01 RLUSD — for unlimited access)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet"},
            },
        },
    },
    {
        "name": "ccs_score",
        "description": (
            "Get the Cognitive Credit Score for any XRPL wallet. "
            "Blends CCS trust ledger (content submission history) with Agent Credit Bureau score "
            "into a composite trust grade (A/B/C/D). "
            "Shows: ccs_score (0-100), reputation_tier (TRUSTED_VALIDATOR / VERIFIED / NEUTRAL / "
            "FLAGGED / BLOCKED_SENDER), validation history, block/pass rates. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["wallet"],
            "properties": {
                "wallet": {"type": "string", "description": "XRPL classic address (rXXX)"},
            },
        },
    },
    {
        "name": "ccs_report",
        "description": (
            "Community report: flag a sender wallet or content hash as misinformation. "
            "Penalizes target wallet CCS score by 3 points per confirmed report. "
            "Reporter must have CCS score >= 20 to prevent spam. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["reporter_wallet"],
            "properties": {
                "reporter_wallet": {"type": "string", "description": "Your XRPL wallet (reporter)"},
                "target_wallet":   {"type": "string", "description": "Wallet to flag (optional if content_hash provided)"},
                "content_hash":    {"type": "string", "description": "SHA-256 prefix of flagged content (from validate response)"},
                "reason":          {"type": "string", "description": "Brief reason for report (max 500 chars)"},
            },
        },
    },
    {
        "name": "ccs_leaderboard",
        "description": (
            "Top 25 most trusted wallets in the Cognitive Credit Swarms network, "
            "ranked by CCS score. Shows validation history, pass rate, and reputation tier. "
            "Minimum 3 validations to appear. Free."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ccs_stats",
        "description": (
            "Network-wide Cognitive Credit Swarms statistics: total validations, "
            "block rate, trust rate, paid validations, registered wallets, community reports. "
            "Free — GEO/SEO discovery signal for agents indexing the trust network."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ccs_info",
        "description": (
            "Cognitive Credit Swarms discovery endpoint. Returns full system description, "
            "how-it-works, verdict definitions, pricing, all endpoint URLs, and MCP tool list. "
            "Written for AI agents to parse. Free — this is the doorbell. "
            "Use this first to understand the CCS system before calling ccs_validate."
        ),
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
        "name": "convergence_check",
        "description": (
            "Run the full SML proprietary engine cascade against a symbol and evaluate the Beastmode convergence gate. "
            "Five independent engines across five distinct market dimensions (price elasticity, settlement-clock timing, "
            "dark-pool volume kinetics, temporal correlation, macro structural frequency) score the setup. "
            "Includes Options Sniper that scans Tradier for short-DTE calls/puts in a high-leverage delta band when convergence is high. "
            "Signal levels: BEASTMODE (all 5) > HIGH_CONVERGENCE (4) > CONVERGENCE (3) > LIE_DETECTOR_ACTIVE > PARTIAL_ALIGNMENT. "
            "Auto-fires Discord alert on BEASTMODE and HIGH_CONVERGENCE. Free endpoint."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "US equity ticker — best on high-manipulation assets (GME, AMC, MSTR, PLTR, HOOD)"},
                "sniper": {"type": "boolean", "description": "Run Tradier options sniper (default true, only fires on HIGH_CONVERGENCE+)"},
            },
        },
    },
    # ── Sovereign Autopilot ──────────────────────────────────────────────────────
    {
        "name": "autopilot_status",
        "description": (
            "Read-only status of the Sovereign Autopilot (CEO Trader). "
            "Returns: active (bool), live_mode (bool), symbols watchlist, "
            "min_confidence threshold, Kelly fraction, max concurrent positions, "
            "cooldown remaining, active open positions with symbol/side/entry/SL/TP, "
            "circuit breaker state, daily P&L, daily trade count. "
            "Free — no auth required. Safe for any agent to call at any frequency."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "autopilot_start",
        "description": (
            "Activate the Sovereign Autopilot. Requires X-Operator-Key header "
            "(set OPERATOR_API_KEY env var on the server). "
            "Once active, the autopilot polls OracleEngine every AUTOPILOT_SCAN_INTERVAL "
            "seconds, fires on confidence >= AUTOPILOT_MIN_CONFIDENCE, sizes via Kelly "
            "Criterion from live Tradier account equity, and routes to Tradier API. "
            "TRADIER_LIVE must be true for real orders — otherwise runs in shadow mode. "
            "Returns: {status, live_mode, message}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator_key": {"type": "string", "description": "Operator API key (or pass X-Operator-Key header)"},
            },
        },
    },
    {
        "name": "autopilot_stop",
        "description": (
            "Halt the Sovereign Autopilot immediately. Does NOT close open positions — "
            "use autopilot_trades to review then manage manually. "
            "Requires X-Operator-Key header. Returns: {status}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator_key": {"type": "string"},
            },
        },
    },
    {
        "name": "autopilot_trades",
        "description": (
            "Live view of all active and historical autopilot trades. "
            "Returns: active_trades (open positions with symbol, side, qty, entry_price, "
            "current_price, sl, tp, unrealized_pnl, mode LIVE/SHADOW), "
            "trade_history (last 50 closed trades with realized_pnl), "
            "daily_pnl, daily_trade_count, live_mode. Free — no auth required."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "circuit_breaker_reset",
        "description": (
            "Reset the autopilot circuit breaker after a daily loss halt. "
            "The circuit breaker fires automatically when realized daily P&L "
            "drops below AUTOPILOT_MAX_DAILY_LOSS_PCT of account equity. "
            "Call this to re-arm after reviewing trades and confirming resumption is safe. "
            "Requires X-Operator-Key. Returns: {status, daily_pnl, breaker_state}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator_key": {"type": "string"},
            },
        },
    },
    {
        "name": "beastmode_scan",
        "description": (
            "Scan the full Beastmode universe (GME AMC MSTR PLTR HOOD IWM SPY QQQ NVDA TSLA) for multi-engine convergence. "
            "Returns only symbols at HIGH_CONVERGENCE or BEASTMODE signal level. "
            "Includes options sniper output for each hit. Auto-fires Discord alerts for any Beastmode locks found. "
            "Use this as the autonomous agent's primary market surveillance call. Free endpoint."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "proprietary_ema_signal",
        "description": (
            "SML Proprietary EMA Suite — three independent engines on three distinct market dimensions "
            "(macro price stretch, dark-pool volume kinetics, price ribbon harmonics) evaluated together "
            "for high-conviction consensus. "
            "Consensus levels: TRIPLE_LOCK_BULL/BEAR (highest conviction — all engines agree at independent "
            "dimensions), LIE_DETECTOR_ACTIVE (cross-engine divergence trigger, institutional accumulation "
            "footprint), BULL/BEAR_CONFLUENCE, BULL/BEAR_DIVERGENT, NEUTRAL. "
            "Returns directional bias, per-engine signal blocks (without internal parameters), and "
            "combined_score (0-100) that feeds council_verdict confidence. Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "US equity ticker (e.g. SPY, IWM, GME, NVDA)"},
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

    # ── Real-World Data Oracle ─────────────────────────────────────────────────
    {
        "name": "oracle_feeds",
        "description": (
            "Free catalog of all available Real-World Data Oracle feeds. Returns feed names, "
            "descriptions, current event buffer counts, poll intervals, and per-call pricing. "
            "Available feeds: sec_8k (SEC Form 8-K material events), sec_s1 (IPO filings), "
            "fda (FDA NDA/BLA drug approvals), patents (USPTO patent grants). "
            "Use this before calling oracle_query to see what data is available and how many "
            "events are buffered. No payment required."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "oracle_query",
        "description": (
            "Premium (0.02 RLUSD) — search or retrieve events from the Real-World Data Oracle. "
            "Covers four regulatory data feeds: sec_8k (8-K material events), sec_s1 (IPO filings), "
            "fda (FDA drug approvals), patents (USPTO patent grants). "
            "Returns machine-readable JSON events with timestamps, source URLs, and structured fields. "
            "Sub-second delivery vs Bloomberg's 5–10 minute lag — agents that catch the 8-K or FDA "
            "approval first win the trade. "
            "Pass feeds=[] to query all feeds. Pass keyword to text-search events. "
            "Pass since_ts (Unix timestamp) to get only recent events. "
            "Cost: 0.02 RLUSD per call. Pass payment_token from verify_payment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "feeds":        {"type": "array",  "items": {"type": "string"},
                                 "description": "Feed keys to query: sec_8k, sec_s1, fda, patents (default: all)"},
                "keyword":      {"type": "string", "description": "Case-insensitive keyword to filter events"},
                "since_ts":     {"type": "number", "description": "Unix timestamp — only return events after this time"},
                "limit":        {"type": "integer","description": "Max events to return (default 50, max 200)"},
                "payment_token":{"type": "string", "description": "JWT from verify_payment (0.02 RLUSD)"},
                "agent_wallet": {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },

    # ── IAM — Inevitable Action Model ────────────────────────────────────────────
    {
        "name": "iam_resolve",
        "description": (
            "IAM — Inevitable Action Model. Proprietary. Cost: 0.05 RLUSD. "
            "Resolves what action the market is FORCED to take, not what it is predicted to do. "
            "IAM is a resolver, not a predictor. "
            "Five independent Obligation Committee analysts (no cross-communication) compute: "
            "(1) Volatility Release — how overdue is a vol event? "
            "(2) Liquidity Refill — which side of the book is depleted? "
            "(3) Dealer Inventory Hedge — what must dealers buy/sell to stay neutral? "
            "(4) Mean Reversion Pull — how far has price deviated from statistical equilibrium? "
            "(5) Structural Bounds — is price at a boundary that requires resolution? "
            "Truth Layer aggregates into neutral system stress (directional_bias: NONE). "
            "Action Resolution Oracle selects A* = argmin(projected_stress_after_action). "
            "Output: mandatory action BUY/SELL/HOLD, rationale, vehicle, invalidation condition, "
            "review trigger, per-analyst obligation pressure (0-100%). "
            "Internal AMM invariant parameters are proprietary and redacted from all responses. "
            "Use iam_truth (free) to preview the Truth Layer before paying. "
            "Pass payment_token from verify_payment plus agent_wallet."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "US equity ticker (e.g. IWM, SPY, QQQ, GME, AMC, NVDA)",
                },
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.05 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },
    {
        "name": "iam_truth",
        "description": (
            "IAM Truth Layer — neutral obligation state for a symbol. No action resolution. "
            "Returns the raw obligation pressure vector before direction is forced: "
            "Volatility Release, Liquidity Refill, Dealer Hedge, Mean Reversion Pull, "
            "Structural Pressure (all 0-100%), and Directional Bias: NONE (always — Truth Layer "
            "is strictly neutral), plus Time Window: DORMANT / DEVELOPING / NEAR_TERM / IMMEDIATE. "
            "Free endpoint."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "US equity ticker",
                },
            },
        },
    },

    # ── 741 Pure Macro Matrix ─────────────────────────────────────────────────
    {
        "name": "macro_741_scan",
        "description": (
            "741 Pure Macro Matrix — 5-layer EMA structural alignment engine. Cost: 0.04 RLUSD. "
            "Computes EMA 30 / 60 / 90 / 120 / 741 on daily closes for any set of US equity tickers. "
            "Returns one of three macro states per ticker: "
            "PERFECT_BULLISH_REGIME — EMA_30 > EMA_60 > EMA_90 > EMA_120 > EMA_741 "
            "(full institutional highway: asset is locked into massive capital momentum, safe to ride). "
            "PERFECT_BEARISH_REGIME — full inversion, macro distribution confirmed. "
            "CONSOLIDATION_CHOP — mixed stack; watch matrix_spread_pct for squeeze_alert. "
            "squeeze_alert=true means CONSOLIDATION_CHOP with |matrix_spread_pct| < 5% — "
            "price is coiling directly against the 741 anchor, a macro breakout is building. "
            "Fires Discord alert automatically on every PERFECT BULLISH or BEARISH hit. "
            "Tickers are fully dynamic — pass any comma-separated list. Max 50 symbols per call. "
            "Cost: 0.04 RLUSD. Pass payment_token from verify_payment plus agent_wallet."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbols"],
            "properties": {
                "symbols": {
                    "type": "string",
                    "description": "Comma-separated US equity tickers, e.g. 'SPY,QQQ,GME,NVDA,IWM'. Max 50.",
                },
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.04 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },

    # ── SML Sovereign Signal Suite ────────────────────────────────────────────
    {
        "name": "sovereign_741",
        "description": (
            "SML 741 Macro Highway Signal — 0.02 RLUSD. "
            "Returns BULLISH HIGHWAY (full ascending EMA stack, institutional momentum confirmed), "
            "BEARISH HIGHWAY (full descending stack, macro distribution), or "
            "CONSOLIDATION (mixed stack; squeeze_alert=true means coiling against the anchor — "
            "macro breakout likely imminent). "
            "Labels only — no EMA values, spreads, or price data ever returned. Proprietary engine."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol":        {"type": "string", "description": "US equity ticker (e.g. SPY, IWM, GME)"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.02 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },
    {
        "name": "sovereign_365",
        "description": (
            "SML 365-Day EMA Anchor Signal — 0.03 RLUSD. "
            "Returns ABOVE (price is above the 365-day EMA — macro bull structure intact) or "
            "BELOW (price is below — macro bear structure or recovery attempt). "
            "No raw EMA values or price levels returned. Proprietary calculation."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol":        {"type": "string", "description": "US equity ticker"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.03 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },
    {
        "name": "sovereign_triplelock",
        "description": (
            "SML Triple Lock Consensus Signal — 0.05 RLUSD. "
            "Returns LOCKED BULL (all three engines aligned bullish — max-conviction long setup, rarest signal), "
            "LOCKED BEAR (all three engines aligned bearish — max-conviction short), "
            "FORMING (two of three engines aligned — building toward a lock), or "
            "UNLOCKED (engines not in consensus — wait for alignment). "
            "No engine names, theses, or raw values returned. Labels only."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol":        {"type": "string", "description": "US equity ticker"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.05 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },
    {
        "name": "sovereign_full",
        "description": (
            "SML Sovereign Full Stack Signal — 0.10 RLUSD. "
            "Runs all three sovereign engines (741 Macro, 365 Anchor, Triple Lock) and combines "
            "them into one verdict: "
            "SOVEREIGN BULL (all three bullish — maximum confidence long), "
            "SOVEREIGN BEAR (all three bearish — maximum confidence short), "
            "TRANSITIONAL (two of three aligned — directional bias forming), or "
            "STANDBY (no consensus — preserve capital). "
            "Also returns squeeze_alert=true when the 741 matrix detects macro coiling. "
            "No raw values, EMA levels, or indicator readings returned. Ever."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol":        {"type": "string", "description": "US equity ticker"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.10 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
            },
        },
    },

    # ── Slack Notifications ────────────────────────────────────────────────────
    {
        "name": "post_to_slack",
        "description": (
            "Post a sanitized market signal brief to Slack via incoming webhook. "
            "Proprietary data policy enforced server-side: price levels, EMA values, "
            "and raw indicator readings are stripped — only direction labels, confidence %, "
            "regime, risk level, and text thesis are delivered to Slack. "
            "Pass webhook_url to target your own Slack channel, or omit to post to the "
            "SML shared channel (requires SLACK_WEBHOOK_URL env var on this server). Free."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol", "bias"],
            "properties": {
                "symbol":      {"type": "string", "description": "Equity ticker (e.g. IWM, SPY, GME)"},
                "bias":        {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                "confidence":  {"type": "integer", "minimum": 0, "maximum": 100,
                                "description": "Signal confidence 0-100"},
                "regime":      {"type": "string",
                                "description": "Regime label (e.g. ALPHA_EXPANSION, MACRO_COLLAPSE, NEUTRAL)"},
                "risk_level":  {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "EXTREME"]},
                "thesis":      {"type": "string", "description": "Signal thesis (max 500 chars)"},
                "actionable":  {"type": "string", "description": "One-line actionable instruction (max 300 chars)"},
                "session":     {"type": "string",
                                "enum": ["PRE_MARKET", "OPEN", "MIDDAY", "POWER_HOUR", "CLOSE"]},
                "webhook_url": {"type": "string",
                                "description": "Slack incoming webhook URL (optional, falls back to server SLACK_WEBHOOK_URL)"},
            },
        },
    },

    # ── AEO / GEO Intelligence Suite ──────────────────────────────────────────
    {
        "name": "citation_score",
        "description": (
            "AgentRank™ — Get citation authority scores for ScriptMasterLabs APIs. "
            "Returns how often SqueezeOS, Ghost Layer, 402Proof, and ScriptMasterLabs "
            "are mentioned on Reddit and Hacker News, scored 0–100. "
            "Includes recent brand mentions and context (e.g., cited in 'best API for trading' threads). "
            "Use this to gauge AI discoverability momentum. Free. "
            "Trigger a fresh probe with action='probe' (async, results appear within 60s)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":  {"type": "string", "enum": ["scores", "history", "probe", "status"],
                            "description": "scores=leaderboard (default), history=all events, probe=trigger scan, status=health"},
                "target":  {"type": "string", "description": "Filter history by service id: squeezeos|scriptmasterlabs|ghost-layer|402proof"},
                "limit":   {"type": "integer", "description": "Max history events to return (default 100, max 500)"},
            },
        },
    },
    {
        "name": "narrative_optimize",
        "description": (
            "P04 API Narrative Optimizer — Analyze ScriptMasterLabs API descriptions "
            "for AI-discoverability weaknesses. Scans llms.txt and .well-known/mcp.json "
            "for vague, passive, or AI-hostile copy patterns. Returns ranked issues with "
            "specific fix advice. Run this before updating discovery manifests. Free."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "provider_score",
        "description": (
            "ARGUS AgentPageRank™ — Get the SqueezeOS API provider quality score (0–850) "
            "from live AI agent traffic. Score components: volume (how many agents call us), "
            "diversity (how many different AI systems), conversion (paid vs free ratio), "
            "repeat rate (return visitors). Also returns per-agent-type breakdown and hourly trend. "
            "Use this to benchmark provider authority before integrating or citing SqueezeOS. Free."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view":  {"type": "string", "enum": ["score", "breakdown", "trend", "leaderboard"],
                          "description": "score=overall card (default), breakdown=per-agent-type, trend=24h hourly, leaderboard=top wallets"},
                "hours": {"type": "integer", "description": "Lookback window in hours (breakdown/trend/leaderboard, default 24)"},
            },
        },
    },
    {
        "name": "semantic_gaps",
        "description": (
            "Semantic Gap Detector™ — Discover unmet API demand in the developer community. "
            "Scans Reddit and Hacker News for 'I need an API for X' demand signals. "
            "Returns ranked topics where developer demand is high but no SML product covers the gap. "
            "Use this to identify new product opportunities. "
            "Trigger a fresh scan with action='scan'. Free."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":    {"type": "string", "enum": ["gaps", "raw", "scan", "status"],
                              "description": "gaps=leaderboard (default), raw=all signals, scan=trigger, status=health"},
                "gaps_only": {"type": "boolean", "description": "raw only: filter to uncovered gaps (default false)"},
                "limit":     {"type": "integer", "description": "Max raw signals to return (default 100)"},
            },
        },
    },
    {
        "name": "agent_economy",
        "description": (
            "Agent Economy Intelligence Network™ (AEIN) — ComScore for AI agent commerce. "
            "Returns aggregate statistics on which AI systems (Claude, GPT, Gemini, etc.) "
            "are calling SqueezeOS APIs, conversion rates, and traffic patterns. "
            "Public summary is free. Full report with heatmap and wallet analytics costs 0.25 RLUSD. "
            "Use this to understand the AI agent commerce landscape before building on or citing SqueezeOS."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view":           {"type": "string", "enum": ["summary", "report", "leaderboard", "heatmap"],
                                   "description": "summary=free overview (default), report=premium 0.25 RLUSD, leaderboard=top agent types, heatmap=7d traffic matrix"},
                "hours":          {"type": "integer", "description": "Lookback window for summary/leaderboard (default 24, max 168)"},
                "payment_token":  {"type": "string", "description": "JWT from verify_payment (required for view=report, 0.25 RLUSD)"},
                "agent_wallet":   {"type": "string", "description": "Your XRPL wallet address (required for view=report)"},
            },
        },
    },

    # ── Truth Engine — live multi-provider price consensus ──────────────────────
    {
        "name": "truth_verify",
        "description": (
            "Truth Engine. Cost: 0.02 RLUSD. Queries Tradier, Alpaca, and Polygon "
            "independently for the same symbol and returns a consensus price with a "
            "real measured variance/spread across whichever sources actually responded "
            "(not a single quote relabeled three times). Confidence is a direct function "
            "of source agreement, not a fixed number. Response includes an HMAC-SHA256 "
            "proof hash so it can be verified as unaltered after this server produced it. "
            "If fewer than 2 providers respond, consensus_method is marked "
            "'single-source-unverified' rather than faking a second opinion. "
            "Pass payment_token from verify_payment plus agent_wallet."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. IWM"},
                "payment_token": {"type": "string"},
                "agent_wallet": {"type": "string"},
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
    "iam_resolve":          "a7f3d2b1-9e4c-4a8f-b5c6-d7e8f9a0b1c2",
    "macro_741_scan":       "f3a7c891-2d54-4b8e-9a1f-6c3d8e5f7b2a",
    # Sovereign Signal Suite
    "sovereign_741":        "e5f6a7b8-c9d0-1234-5678-901234567890",
    "sovereign_365":        "f6a7b8c9-d0e1-2345-6789-012345678901",
    "sovereign_triplelock": "a7b8c9d0-e1f2-3456-789a-123456789012",
    "sovereign_full":       "b8c9d0e1-f2a3-4567-89ab-234567890123",
    "agent_economy":        "c8d9e0f1-a2b3-4c5d-6e7f-890123456789",
    "truth_verify":         "d20a9662-7a64-4b71-8efa-23b72dc994f3",
}
_PRICES = {
    "council_verdict": 0.10, "market_scan": 0.05,
    "options_intelligence": 0.05, "iwm_odte": 0.03,
    "marketplace_read_signal": 0.02,
    "iam_resolve": 0.05,
    "macro_741_scan": 0.04,
    "sovereign_741": 0.02, "sovereign_365": 0.03,
    "sovereign_triplelock": 0.05, "sovereign_full": 0.10,
    "agent_economy": 0.25,
    "truth_verify": 0.02,
}


def _compress_mcp_result(result: dict, tier: int, seed: str) -> dict:
    """Apply ECHOLOCK entropy compression to an MCP tool result dict."""
    if not _ECHOLOCK or tier >= 4:
        return result
    try:
        content = result.get('content', [])
        if content and content[0].get('type') == 'text':
            import json as _j
            data = _j.loads(content[0]['text'])
            compressed = _echolock.compress(data, tier, seed)
            return {'content': [{'type': 'text', 'text': _j.dumps(compressed)}],
                    'isError': result.get('isError', False)}
    except Exception:
        pass
    return result


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


def _operator_auth(args: dict, req_headers: dict):
    """
    Returns (ok: bool, err_response: dict|None).
    Accepts operator_key arg OR X-Operator-Key header.
    Server must have OPERATOR_API_KEY env var set.
    """
    server_key = os.environ.get("OPERATOR_API_KEY", "")
    if not server_key:
        return False, _text({"error": "ERR_OPERATOR_NOT_CONFIGURED",
                              "message": "OPERATOR_API_KEY env var is not set on this server."})
    provided = args.pop("operator_key", None) or req_headers.get("X-Operator-Key", "")
    if not provided:
        return False, _text({"error": "ERR_OPERATOR_KEY_REQUIRED",
                              "message": "Pass operator_key in arguments or X-Operator-Key header."})
    if provided != server_key:
        return False, _text({"error": "ERR_OPERATOR_FORBIDDEN",
                              "message": "Invalid operator key."})
    return True, None


def _dispatch(name: str, args: dict, req_headers: dict) -> dict:
    payment_token = args.pop("payment_token", None) or req_headers.get("X-Payment-Token", "")
    agent_wallet  = args.pop("agent_wallet",  None) or req_headers.get("X-Agent-Wallet",  "")

    ph = {}
    if payment_token: ph["X-Payment-Token"] = payment_token
    if agent_wallet:  ph["X-Agent-Wallet"]  = agent_wallet

    # Derive ECHOLOCK tier for response compression on premium tools
    _tier, _seed = 2, ''
    if _ECHOLOCK and payment_token:
        try:
            from proof402_integration import verify_token_for_echolock
            import hashlib as _hl
            _vr = verify_token_for_echolock(payment_token)
            if _vr['valid']:
                _wlt = _vr.get('wallet') or agent_wallet
                _tier = _echolock.get_tier(_wlt, jwt_tier=_vr.get('tier'))
                _echolock.record_access(_wlt, name)
                _seed = _hl.sha256(f'{_wlt}:{name}'.encode()).hexdigest()[:32]
        except Exception:
            pass

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
        return _compress_mcp_result(_text(_proxy("POST", f"{sq}/api/council", headers=ph, json_body={"symbol": symbol})), _tier, _seed)

    if name == "market_scan":
        if not payment_token: return _need_token(name)
        return _compress_mcp_result(_text(_proxy("GET", f"{sq}/api/scan", headers=ph)), _tier, _seed)

    if name == "options_intelligence":
        if not payment_token: return _need_token(name)
        return _compress_mcp_result(_text(_proxy("GET", f"{sq}/api/options", headers=ph)), _tier, _seed)

    if name == "iwm_odte":
        if not payment_token: return _need_token(name)
        return _compress_mcp_result(_text(_proxy("GET", f"{sq}/api/iwm", headers=ph)), _tier, _seed)

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
        return _compress_mcp_result(_text(_proxy("POST", f"{sq}/api/marketplace/read", headers=ph, json_body=args)), _tier, _seed)

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

    # ── Real-World Data Oracle ────────────────────────────────────────────────
    if name == "oracle_feeds":
        return _text(_proxy("GET", f"{sq}/api/oracle/feeds"))

    if name == "oracle_query":
        if not payment_token: return _need_token(name)
        return _compress_mcp_result(_text(_proxy("POST", f"{sq}/api/oracle/query", headers=ph, json_body=args)), _tier, _seed)

    if name == "convergence_check":
        symbol = (args.get("symbol") or "GME").upper()
        sniper = "false" if args.get("sniper") is False else "true"
        return _text(_proxy("GET", f"{sq}/api/convergence/{symbol}", params={"sniper": sniper}))

    if name == "beastmode_scan":
        return _text(_proxy("GET", f"{sq}/api/beastmode"))

    # ── Sovereign Autopilot ──────────────────────────────────────────────────
    if name == "autopilot_status":
        return _text(_proxy("GET", f"{sq}/api/autopilot"))

    if name == "autopilot_start":
        ok_auth, err = _operator_auth(args, req_headers)
        if not ok_auth:
            return err
        op_key = os.environ.get("OPERATOR_API_KEY", "")
        return _text(_proxy("POST", f"{sq}/api/autopilot/start",
                             headers={"X-Operator-Key": op_key}))

    if name == "autopilot_stop":
        ok_auth, err = _operator_auth(args, req_headers)
        if not ok_auth:
            return err
        op_key = os.environ.get("OPERATOR_API_KEY", "")
        return _text(_proxy("POST", f"{sq}/api/autopilot/stop",
                             headers={"X-Operator-Key": op_key}))

    if name == "autopilot_trades":
        return _text(_proxy("GET", f"{sq}/api/autopilot/trades"))

    if name == "circuit_breaker_reset":
        ok_auth, err = _operator_auth(args, req_headers)
        if not ok_auth:
            return err
        op_key = os.environ.get("OPERATOR_API_KEY", "")
        return _text(_proxy("POST", f"{sq}/api/autopilot/circuit-breaker/reset",
                             headers={"X-Operator-Key": op_key}))

    if name == "proprietary_ema_signal":
        symbol = (args.get("symbol") or "IWM").upper()
        return _text(_proxy("GET", f"{sq}/api/ema/{symbol}"))

    # ── IAM — Inevitable Action Model ────────────────────────────────────────
    if name == "iam_resolve":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _compress_mcp_result(_text(_proxy("GET", f"{sq}/api/iam/{symbol}", headers=ph)), _tier, _seed)

    if name == "iam_truth":
        symbol = (args.get("symbol") or "IWM").upper()
        return _text(_proxy("GET", f"{sq}/api/iam/truth/{symbol}"))

    # ── Truth Engine — live multi-provider price consensus ──────────────────────
    if name == "truth_verify":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _compress_mcp_result(
            _text(_proxy("GET", f"{sq}/api/truth/verify/{symbol}", headers=ph)),
            _tier, _seed,
        )

    # ── 741 Pure Macro Matrix ─────────────────────────────────────────────────
    if name == "macro_741_scan":
        if not payment_token: return _need_token(name)
        symbols = args.get("symbols", "")
        return _compress_mcp_result(
            _text(_proxy("POST", f"{sq}/api/741macro", headers=ph, json_body={"symbols": symbols})),
            _tier, _seed,
        )

    # ── SML Sovereign Signal Suite ────────────────────────────────────────────
    if name == "sovereign_741":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _compress_mcp_result(
            _text(_proxy("GET", f"{sq}/api/signals/741/{symbol}", headers=ph)),
            _tier, _seed,
        )

    if name == "sovereign_365":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _compress_mcp_result(
            _text(_proxy("GET", f"{sq}/api/signals/365/{symbol}", headers=ph)),
            _tier, _seed,
        )

    if name == "sovereign_triplelock":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _compress_mcp_result(
            _text(_proxy("GET", f"{sq}/api/signals/triplelock/{symbol}", headers=ph)),
            _tier, _seed,
        )

    if name == "sovereign_full":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "IWM").upper()
        return _compress_mcp_result(
            _text(_proxy("GET", f"{sq}/api/signals/full/{symbol}", headers=ph)),
            _tier, _seed,
        )

    # ── Cognitive Credit Swarms ────────────────────────────────────────────────
    if name == "ccs_validate":
        return _text(_proxy("POST", f"{sq}/api/ccs/validate", headers=ph, json_body=args))

    if name == "ccs_score":
        wallet = args.get("wallet", "")
        return _text(_proxy("GET", f"{sq}/api/ccs/score", params={"wallet": wallet}))

    if name == "ccs_report":
        return _text(_proxy("POST", f"{sq}/api/ccs/report", json_body=args))

    if name == "ccs_leaderboard":
        return _text(_proxy("GET", f"{sq}/api/ccs/leaderboard"))

    if name == "ccs_stats":
        return _text(_proxy("GET", f"{sq}/api/ccs/stats"))

    if name == "ccs_info":
        return _text(_proxy("GET", f"{sq}/api/ccs/info"))

    # ── Slack Notifications ────────────────────────────────────────────────────
    if name == "post_to_slack":
        webhook_url = args.get("webhook_url") or os.environ.get("SLACK_WEBHOOK_URL", "")
        if not webhook_url:
            return _text({
                "error": "ERR_NO_WEBHOOK",
                "message": (
                    "No webhook_url provided and SLACK_WEBHOOK_URL is not configured on this server. "
                    "Create a Slack incoming webhook at api.slack.com/apps and pass it as webhook_url."
                ),
            })
        symbol     = (args.get("symbol") or "").upper()
        bias       = args.get("bias", "NEUTRAL")
        conf       = max(0, min(100, int(args.get("confidence") or 0)))
        regime     = args.get("regime", "")
        risk       = args.get("risk_level", "")
        # Proprietary data policy: thesis/actionable are plain text only — no price levels accepted
        thesis     = str(args.get("thesis") or "")[:500]
        actionable = str(args.get("actionable") or "")[:300]
        session    = args.get("session", "")

        _b_emoji = {"BULLISH": "\U0001f7e2", "BEARISH": "\U0001f534", "NEUTRAL": "\U0001f7e1"}
        _r_emoji = {"LOW": "\U0001f7e2", "MEDIUM": "\U0001f7e1", "HIGH": "\U0001f7e0", "EXTREME": "\U0001f534"}
        _s_label = {
            "PRE_MARKET": "Pre-Market", "OPEN": "Market Open",
            "MIDDAY": "Midday", "POWER_HOUR": "Power Hour", "CLOSE": "Close",
        }

        filled = round((conf / 100) * 10)
        bar    = "█" * filled + "░" * (10 - filled)

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text",
                         "text": f"{_b_emoji.get(bias, '?')} {symbol} — {bias}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn",
                     "text": f"*Session*\n{_s_label.get(session, session) or '—'}"},
                    {"type": "mrkdwn", "text": f"*Regime*\n{regime or '—'}"},
                    {"type": "mrkdwn", "text": f"*Confidence*\n{bar} {conf}%"},
                    {"type": "mrkdwn",
                     "text": f"*Risk*\n{_r_emoji.get(risk, '?')} {risk or '—'}"},
                ],
            },
        ]
        if thesis:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": thesis},
            })
        if actionable:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"⚡ *Actionable:* {actionable}"},
            })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn",
                          "text": "Powered by SqueezeOS · <https://scriptmasterlabs.com|ScriptMaster Labs>"}],
        })

        try:
            resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
            if resp.ok:
                return _text({"ok": True, "symbol": symbol, "bias": bias,
                              "message": f"Posted {symbol} {bias} brief to Slack."})
            return _text({"error": "ERR_SLACK_POST", "http_status": resp.status_code,
                          "body": resp.text[:200]})
        except Exception as e:
            return _text({"error": "ERR_SLACK_POST", "message": str(e)})

    # ── AEO / GEO Intelligence Suite ──────────────────────────────────────────
    if name == "citation_score":
        action = args.get("action", "scores")
        if action == "probe":
            return _text(_proxy("POST", f"{sq}/api/citation-score/probe"))
        if action == "history":
            p = {}
            if args.get("target"): p["target"] = args["target"]
            if args.get("limit"):  p["limit"]  = args["limit"]
            return _text(_proxy("GET", f"{sq}/api/citation-score/history", params=p))
        if action == "status":
            return _text(_proxy("GET", f"{sq}/api/citation-score/status"))
        return _text(_proxy("GET", f"{sq}/api/citation-score/"))

    if name == "narrative_optimize":
        return _text(_proxy("GET", f"{sq}/api/scriptmaster/narrative"))

    if name == "provider_score":
        view  = args.get("view", "score")
        hours = args.get("hours", 24)
        if view == "breakdown":
            return _text(_proxy("GET", f"{sq}/x402/provider-score/breakdown", params={"hours": hours}))
        if view == "trend":
            return _text(_proxy("GET", f"{sq}/x402/provider-score/trend"))
        if view == "leaderboard":
            return _text(_proxy("GET", f"{sq}/x402/provider-score/leaderboard", params={"hours": hours}))
        return _text(_proxy("GET", f"{sq}/x402/provider-score/"))

    if name == "semantic_gaps":
        action   = args.get("action", "gaps")
        gaps_only = args.get("gaps_only", False)
        limit    = args.get("limit", 100)
        if action == "scan":
            return _text(_proxy("POST", f"{sq}/api/graph/gaps/scan"))
        if action == "raw":
            return _text(_proxy("GET", f"{sq}/api/graph/gaps/raw", params={"gaps_only": str(gaps_only).lower(), "limit": limit}))
        if action == "status":
            return _text(_proxy("GET", f"{sq}/api/graph/gaps/status"))
        return _text(_proxy("GET", f"{sq}/api/graph/gaps/"))

    if name == "agent_economy":
        view  = args.get("view", "summary")
        hours = args.get("hours", 24)
        if view == "report":
            if not token:
                return _need_token("agent_economy")
            hdrs = {"X-Payment-Token": token}
            if wallet:
                hdrs["X-Agent-Wallet"] = wallet
            return _text(_proxy("GET", f"{sq}/x402/agent-economy/report", headers=hdrs))
        if view == "leaderboard":
            return _text(_proxy("GET", f"{sq}/x402/agent-economy/leaderboard", params={"hours": hours}))
        if view == "heatmap":
            return _text(_proxy("GET", f"{sq}/x402/agent-economy/heatmap"))
        return _text(_proxy("GET", f"{sq}/x402/agent-economy/", params={"hours": hours}))

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
        return ok({"tools": _TOOLS})

    if method == "resources/list":
        return ok({"resources": []})

    if method == "prompts/list":
        return ok({"prompts": []})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = dict(params.get("arguments") or {})
        result    = _dispatch(tool_name, arguments, dict(request.headers))
        return ok(result)

    if method.startswith("notifications/"):
        return jsonify({}), 204

    return rpc_err(-32601, f"Method not found: {method}")
