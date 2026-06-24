"""
SqueezeOS MCP Server — HTTP JSON-RPC 2.0 Transport
====================================================
Implements the Model Context Protocol so Smithery and MCP clients
can discover and call all SqueezeOS tools directly.

POST /mcp  — main JSON-RPC dispatch
GET  /mcp  — server info (health check)

Supported methods:
  initialize        — handshake + capabilities
  tools/list        — all 26 tools
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
            "• Volatility Release: 0-100% "
            "• Liquidity Refill: 0-100% "
            "• Dealer Hedge: 0-100% "
            "• Mean Reversion Pull: 0-100% "
            "• Structural Pressure: 0-100% "
            "• Directional Bias: NONE (always — Truth Layer is strictly neutral) "
            "• Time Window: DORMANT / DEVELOPING / NEAR_TERM / IMMEDIATE "
            "Use this to display the obligation state without committing to a trade direction. "
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

    # ── FTD Data Oracle ───────────────────────────────────────────────────────
    {
        "name": "ftd_alerts",
        "description": (
            "ShortSqueeze Swarm — live FTD anomaly alert feed. Free. "
            "Returns the last 25 SEC Reg SHO anomaly events detected by the background engine: "
            "NEW_THRESHOLD_LIST_ENTRY (symbol newly on SEC threshold list) and "
            "FTD_SPIKE (latest fail_shares ≥ 2× rolling window average, 95th-percentile+ reading). "
            "Each alert includes symbol, anomaly_type, spike_ratio, and settlement_date. "
            "This is a teaser feed — descriptive public-regulatory data only, not trade signals. "
            "For full 180-day FTD time series or ratio analysis, use ftd_analysis (0.03 RLUSD)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max alerts to return (default 25, max 100)"},
            },
        },
    },
    {
        "name": "ftd_analysis",
        "description": (
            "FTD Data Oracle — full FTD ratio + percentile analysis for any US equity. Cost: 0.03 RLUSD. "
            "Returns the latest Fails-To-Deliver record for a symbol with: "
            "fail_shares (shares failed to deliver), fail_value (notional), settlement_date, "
            "rank_percentile (where this reading sits vs 180-day window, 0.0–1.0), "
            "window_avg_fails, and spike_ratio (latest / window_avg). "
            "A spike_ratio ≥ 2.0 at rank_percentile ≥ 0.95 is an institutional-grade FTD anomaly. "
            "Data sourced directly from SEC Reg SHO biweekly reports — same feed Bloomberg charges "
            "$200/month for. Descriptive regulatory data only — not a trade signal. "
            "Pass payment_token from verify_payment plus agent_wallet."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol":        {"type": "string", "description": "US equity ticker (e.g. GME, AMC, BBBY, XRT)"},
                "payment_token": {"type": "string", "description": "JWT from verify_payment (0.03 RLUSD)"},
                "agent_wallet":  {"type": "string", "description": "Your XRPL wallet address"},
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
            "• PERFECT_BULLISH_REGIME — EMA_30 > EMA_60 > EMA_90 > EMA_120 > EMA_741 "
            "  (full institutional highway: asset is locked into massive capital momentum, safe to ride). "
            "• PERFECT_BEARISH_REGIME — full inversion, macro distribution confirmed. "
            "• CONSOLIDATION_CHOP — mixed stack; watch matrix_spread_pct for squeeze_alert. "
            "squeeze_alert=true means CONSOLIDATION_CHOP with |matrix_spread_pct| < 5% — "
            "price is coiling directly against the 741 anchor, a macro breakout is building. "
            "matrix_spread_pct = ((EMA_30 - EMA_741) / EMA_741) * 100. "
            "Fires Discord alert automatically on every PERFECT BULLISH or BEARISH hit. "
            "Tickers are fully dynamic — pass any comma-separated list. No hardcoded universe. "
            "Max 50 symbols per call. Data from Tradier (primary) or Alpaca (fallback). "
            "Pass payment_token from verify_payment plus agent_wallet."
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
    "ftd_analysis":         "a4b5c6d7-e002-4f3e-aa24-d52e3bc12b5a",
}
_PRICES = {
    "council_verdict": 0.10, "market_scan": 0.05,
    "options_intelligence": 0.05, "iwm_odte": 0.03,
    "marketplace_read_signal": 0.02,
    "iam_resolve": 0.05,
    "macro_741_scan": 0.04,
    "ftd_analysis": 0.03,
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

    # ── FTD Data Oracle ───────────────────────────────────────────────────────
    if name == "ftd_alerts":
        limit = args.get("limit", 25)
        return _text(_proxy("GET", f"{sq}/api/ftd/alerts", params={"limit": limit}))

    if name == "ftd_analysis":
        if not payment_token: return _need_token(name)
        symbol = (args.get("symbol") or "GME").upper()
        return _compress_mcp_result(
            _text(_proxy("GET", f"{sq}/api/ftd/ratio/{symbol}", headers=ph)),
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
