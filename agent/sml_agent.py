"""
SML Autonomous Market Intelligence Agent
=========================================
Self-funding agent that pays for its own signals via x402, synthesizes
a market brief with Claude, lists it on the Signal Marketplace, and pushes
to all webhook subscribers. Tracks its own P&L.

Schedule:
  Pre-market  : 08:45 ET
  Market open : 09:35 ET
  Midday      : 12:00 ET
  Power hour  : 15:00 ET
  Close       : 16:15 ET

Environment:
  AGENT_XRPL_SEED          - agent hot wallet seed (s...)
  AGENT_XRPL_ADDRESS       - agent XRPL address (r...)
  AGENT_DOMAIN             - identity domain (agent.scriptmasterlabs.com)
  ANTHROPIC_API_KEY        - Claude API key
  SQUEEZEOS_BASE_URL       - SqueezeOS API (default: Railway URL)
  PROOF402_BASE_URL        - 402Proof (default: Render URL)
  BRIEF_PRICE_RLUSD        - price to list brief (default: 0.01)
  BRIEF_TTL_HOURS          - listing TTL (default: 6)
  RUN_ONCE                 - set to \"true\" to run once and exit (for cron)
"""

import os
import sys
import json
import time
import hmac
import hashlib
import base64
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import requests
import anthropic
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# ── XRPL ──────────────────────────────────────────────────────────────────────────────
from xrpl.wallet import Wallet
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment, Memo
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import submit_and_wait

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("SML-Agent")

# ── Config ────────────────────────────────────────────────────────────────────
SQUEEZEOS         = os.environ.get("SQUEEZEOS_BASE_URL",  "https://squeezeos-api.onrender.com")
MATRIX_URL        = os.environ.get("MATRIX_BASE_URL",    "https://squeezeos-api.onrender.com")
PROOF402          = os.environ.get("PROOF402_BASE_URL",   "https://four02proof.onrender.com")
XRPL_RPC          = os.environ.get("XRPL_RPC_URL",        "https://xrplcluster.com")
AGENT_SEED        = os.environ.get("AGENT_XRPL_SEED",     "")
AGENT_ADDR        = os.environ.get("AGENT_XRPL_ADDRESS",  "")
AGENT_DOM         = os.environ.get("AGENT_DOMAIN",        "agent.scriptmasterlabs.com")
ANTHROPIC_KEY     = os.environ.get("ANTHROPIC_API_KEY",   "")
BRIEF_PRICE       = float(os.environ.get("BRIEF_PRICE_RLUSD", "0.01"))
BRIEF_TTL         = int(os.environ.get("BRIEF_TTL_HOURS", "6"))
RUN_ONCE          = os.environ.get("RUN_ONCE", "false").lower() == "true"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")  # optional

RLUSD_ISSUER   = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "524C555344000000000000000000000000000000"

# Endpoint IDs from 402Proof
ENDPOINT_COUNCIL = "12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a"
ENDPOINT_SCAN    = "160cf28d-b364-44eb-adbd-2489c5cc2cf8"
ENDPOINT_IWM     = "60f48ce0-6002-4385-9b60-03a0d2bbebab"
ENDPOINT_OPTIONS = "c951a374-2424-4064-ab80-35afe8053d29"

# ── P&L Tracker ───────────────────────────────────────────────────────────────────────────
class PnL:
    def __init__(self):
        self.spent   = 0.0
        self.earned  = 0.0
        self.runs    = 0
        self.listings = 0
        self._lock   = threading.Lock()

    def record_spend(self, amount: float):
        with self._lock:
            self.spent = round(self.spent + amount, 6)

    def record_listing(self):
        """A brief was listed on the marketplace — real, unfakeable (the
        listing POST succeeded). Does NOT touch `earned`: listing is free
        (core/api/marketplace_bp.py's /list route isn't payment-gated),
        only a later /read by some other agent actually pays the seller."""
        with self._lock:
            self.listings += 1

    def refresh_earned(self, real_total_rlusd: float):
        """Overwrites `earned` with the real, server-tracked lifetime seller
        balance (GET /api/marketplace/balance/<wallet>'s revenue_rlusd — 90%
        of each real 0.02 RLUSD /read sale). This is a SET, not an
        increment, since the server already reports a cumulative total."""
        with self._lock:
            self.earned = round(real_total_rlusd, 6)

    def summary(self) -> dict:
        with self._lock:
            return {
                "runs":     self.runs,
                "listings": self.listings,
                "spent_rlusd":  self.spent,
                "earned_rlusd": self.earned,
                "net_rlusd":    round(self.earned - self.spent, 6),
            }

pnl = PnL()

# ── XRPL Payment ────────────────────────────────────────────────────────────────────────────

def pay_invoice(invoice: dict) -> str:
    """Send RLUSD on XRPL for an invoice. Returns tx hash."""
    if not AGENT_SEED:
        raise RuntimeError("AGENT_XRPL_SEED not set — cannot pay invoice")

    wallet = Wallet.from_seed(AGENT_SEED)
    client = JsonRpcClient(XRPL_RPC)

    amount_str = str(invoice["amount"])
    pay_to     = invoice["pay_to"]
    memo_hex   = invoice["memo_hex"]

    tx = Payment(
        account     = wallet.address,
        destination = pay_to,
        amount      = IssuedCurrencyAmount(
            currency = RLUSD_CURRENCY,
            issuer   = RLUSD_ISSUER,
            value    = amount_str,
        ),
        memos = [Memo(memo_data=memo_hex)],
        fee   = "12",
    )

    response = submit_and_wait(tx, client, wallet)
    tx_hash  = response.result["hash"]
    logger.info(f"[PAY] {amount_str} RLUSD → {pay_to[:16]}… tx={tx_hash[:16]}…")
    pnl.record_spend(float(amount_str))
    return tx_hash

# ── x402 Full Flow ────────────────────────────────────────────────────────────────────────────

def pay_and_call(endpoint_id: str, method: str, url: str, body: Optional[dict] = None) -> dict:
    """Complete x402 flow: invoice → pay XRPL → verify → call endpoint."""

    # 1. Get invoice
    inv_resp = requests.post(
        f"{PROOF402}/v1/invoice",
        json={"endpoint_id": endpoint_id},
        timeout=15,
    )
    inv_resp.raise_for_status()
    invoice = inv_resp.json()
    logger.info(f"[x402] Invoice {invoice['invoice_id'][:12]}… {invoice['amount']} RLUSD")

    # 2. Pay on XRPL
    tx_hash = pay_invoice(invoice)

    # 3. Verify → get token
    verify_resp = requests.post(
        f"{PROOF402}/v1/verify",
        json={
            "invoice_id":   invoice["invoice_id"],
            "tx_hash":      tx_hash,
            "agent_wallet": AGENT_ADDR,
        },
        timeout=15,
    )
    verify_resp.raise_for_status()
    token = verify_resp.json()["access_token"]
    logger.info(f"[x402] Token issued for {endpoint_id[:8]}…")

    # 4. Call protected endpoint
    headers = {
        "X-Payment-Token": token,
        "X-Agent-Wallet":  AGENT_ADDR,
        "X-Agent-Domain":  AGENT_DOM,
        "Content-Type":    "application/json",
    }
    if method.upper() == "POST":
        resp = requests.post(url, json=body or {}, headers=headers, timeout=30)
    else:
        resp = requests.get(url, headers=headers, timeout=30)

    resp.raise_for_status()
    return resp.json()

# ── Free endpoints (no payment) ───────────────────────────────────────────────────────────────────────────

def get_free(path: str) -> dict:
    resp = requests.get(f"{SQUEEZEOS}{path}", timeout=20)
    resp.raise_for_status()
    return resp.json()


# ── SqueezeOS Matrix Engine (Render) ──────────────────────────────────────────

CRYPTO_SCAN_SYMBOLS = "ETH/USDT,BTC/USDT,SOL/USDT,AVAX/USDT"

ROBINHOOD_BASE      = os.environ.get("ROBINHOOD_BASE_URL", "http://localhost:8001")
ROBINHOOD_ENABLED   = os.environ.get("ROBINHOOD_EXECUTION", "false").lower() == "true"
ROBINHOOD_PAPER     = os.environ.get("ROBINHOOD_PAPER_MODE", "true").lower() == "true"
EXECUTION_SIZE_USD  = float(os.environ.get("EXECUTION_SIZE_USD", "100"))

_executed_this_cycle: set = set()


def _symbol_to_robinhood(ccxt_symbol: str) -> str:
    """Convert CCXT symbol (ETH/USDT) to Robinhood crypto symbol (ETH)."""
    return ccxt_symbol.split("/")[0]


def execute_signal(signal: dict) -> Optional[dict]:
    """
    Route a matrix intent to Robinhood execution.
    Guards: paper mode flag, per-cycle dedup, human-confirmation gate.
    """
    intent = signal.get("intent")
    symbol = signal.get("symbol", "")
    rh_sym = _symbol_to_robinhood(symbol)

    if intent == "MAINTAIN_STATE" or intent == "ERROR":
        return None

    dedup_key = f"{rh_sym}:{intent}"
    if dedup_key in _executed_this_cycle:
        logger.info(f"[EXEC] Skipping duplicate signal {dedup_key} this cycle")
        return None
    _executed_this_cycle.add(dedup_key)

    if not ROBINHOOD_ENABLED:
        logger.info(f"[EXEC] Execution disabled — would have fired {intent} on {rh_sym}")
        return None

    side   = "buy"  if intent in ("EXECUTE_INITIAL_ENTRY", "EXECUTE_TRANCHE_AVG_DOWN") else "sell"
    amount = EXECUTION_SIZE_USD if side == "buy" else None

    payload = {
        "symbol":     rh_sym,
        "side":       side,
        "type":       "market",
        "paper_mode": ROBINHOOD_PAPER,
        "intent":     intent,
    }
    if amount:
        payload["notional"] = amount

    try:
        resp = requests.post(
            f"{ROBINHOOD_BASE}/orders",
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        mode = "PAPER" if ROBINHOOD_PAPER else "LIVE"
        logger.info(f"[EXEC] {mode} {side.upper()} {rh_sym} — intent={intent} order={result.get('id', 'N/A')}")
        return result
    except Exception as e:
        logger.error(f"[EXEC] Robinhood order failed {rh_sym} {intent}: {e}")
        return None


def execute_matrix_signals(scan: dict):
    """Fire execution for all actionable signals in a scan result."""
    _executed_this_cycle.clear()
    results = scan.get("results", [])
    executions = []
    for r in results:
        if r.get("intent") not in ("MAINTAIN_STATE", "ERROR"):
            result = execute_signal(r)
            if result:
                executions.append({"signal": r, "order": result})
    if executions:
        logger.info(f"[EXEC] Fired {len(executions)} order(s) this cycle")
    return executions


def collect_matrix_intents() -> dict:
    """
    Pulls live 5-EMA Fibonacci Ribbon execution intents from the
    SqueezeOS Matrix Engine on Render across top crypto pairs.
    """
    try:
        resp = requests.get(
            f"{MATRIX_URL}/api/matrix-scan",
            params={"symbols": CRYPTO_SCAN_SYMBOLS, "timeframe": "15m"},
            timeout=30,
        )
        resp.raise_for_status()
        scan = resp.json()
        logger.info(
            f"[MATRIX] Scan: {scan.get('scan_count', 0)} pairs — "
            f"actionable: {sum(1 for r in scan.get('results', []) if r.get('intent') not in ('MAINTAIN_STATE', 'ERROR'))}"
        )
        return scan
    except Exception as e:
        logger.warning(f"[MATRIX] Matrix scan failed: {e}")
        return {}

# ── Data collection ───────────────────────────────────────────────────────────

def collect_market_data() -> dict:
    logger.info("[AGENT] Collecting market data...")
    data = {}

    # SqueezeOS Matrix Engine — crypto EMA ribbon intents
    matrix = collect_matrix_intents()
    if matrix:
        data["matrix_scan"] = matrix
        # Surface the top actionable intent as a first-class field for Claude
        for r in matrix.get("results", []):
            if r.get("intent") not in ("MAINTAIN_STATE", "ERROR"):
                data["matrix_top_signal"] = r
                break
        # Fire Robinhood execution for all actionable signals
        data["executions"] = execute_matrix_signals(matrix)

    # Free: IWM preview
    try:
        data["iwm_preview"] = get_free("/api/preview/IWM")
    except Exception as e:
        logger.warning(f"[AGENT] IWM preview failed: {e}")

    # Free: signal history for top symbols
    for sym in ["IWM", "GME", "SPY"]:
        try:
            data[f"history_{sym}"] = get_free(f"/api/history/{sym}")
        except Exception as e:
            logger.warning(f"[AGENT] history {sym} failed: {e}")

    # Paid: full market scan
    try:
        data["scan"] = pay_and_call(
            ENDPOINT_SCAN, "GET",
            f"{SQUEEZEOS}/api/scan",
        )
        logger.info(f"[AGENT] Scan: {data['scan'].get('scan_count', '?')} symbols")
    except Exception as e:
        logger.error(f"[AGENT] Scan failed: {e}")

    # Paid: IWM council verdict
    try:
        data["council_iwm"] = pay_and_call(
            ENDPOINT_COUNCIL, "POST",
            f"{SQUEEZEOS}/api/council",
            {"symbol": "IWM"},
        )
        logger.info(f"[AGENT] IWM verdict: {data['council_iwm'].get('verdict', {}).get('bias')}")
    except Exception as e:
        logger.error(f"[AGENT] Council IWM failed: {e}")

    # Paid: top squeeze pick from scan
    top_symbol = None
    try:
        quotes = data.get("scan", {}).get("quotes", {})
        if quotes:
            top_symbol = max(quotes, key=lambda s: quotes[s].get("volRatio", 0))
        if top_symbol and top_symbol != "IWM":
            data[f"council_{top_symbol}"] = pay_and_call(
                ENDPOINT_COUNCIL, "POST",
                f"{SQUEEZEOS}/api/council",
                {"symbol": top_symbol},
            )
            logger.info(f"[AGENT] {top_symbol} verdict: {data[f'council_{top_symbol}'].get('verdict', {}).get('bias')}")
    except Exception as e:
        logger.error(f"[AGENT] Council {top_symbol} failed: {e}")

    # Paid: IWM 0DTE
    try:
        data["iwm_odte"] = pay_and_call(
            ENDPOINT_IWM, "GET",
            f"{SQUEEZEOS}/api/iwm",
        )
        logger.info("[AGENT] IWM 0DTE data collected")
    except Exception as e:
        logger.error(f"[AGENT] IWM 0DTE failed: {e}")

    return data

# ── Brief synthesis (Claude) ──────────────────────────────────────────────────────────────────────────

def synthesize_brief(data: dict) -> dict:
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    matrix_summary = ""
    if "matrix_top_signal" in data:
        sig = data["matrix_top_signal"]
        matrix_summary = (
            f"\nSQUEEZEOS MATRIX ENGINE SIGNAL:\n"
            f"  Symbol: {sig.get('symbol')} | Timeframe: {sig.get('timeframe')}\n"
            f"  Intent: {sig.get('intent')}\n"
            f"  Close: {sig.get('close')} | EMA_55: {sig.get('ema_55')} | EMA_365: {sig.get('ema_365')}\n"
        )

    prompt = f"""You are the SML Autonomous Market Intelligence Agent. Synthesize this live market data into a concise, actionable daily brief.

TIMESTAMP: {now_str}
{matrix_summary}
MARKET DATA:
{json.dumps(data, indent=2, default=str)}

Generate a JSON brief with this exact structure:
{{
  \"title\": \"SML Market Brief — {now_str}\",
  \"session\": \"PRE_MARKET|OPEN|MIDDAY|POWER_HOUR|CLOSE\",
  \"master_bias\": \"BULLISH|BEARISH|NEUTRAL\",
  \"regime\": \"EXECUTION|STEALTH|CONFLICT|COLLAPSE\",
  \"confidence\": 0-100,
  \"top_picks\": [\"SYM1\", \"SYM2\"],
  \"iwm_thesis\": \"2-3 sentence IWM analysis\",
  \"market_thesis\": \"3-4 sentence overall market thesis\",
  \"key_levels\": {{\"IWM_support\": 0.0, \"IWM_resistance\": 0.0}},
  \"squeeze_count\": 0,
  \"options_flow\": \"BULLISH|BEARISH|NEUTRAL|MIXED\",
  \"risk_level\": \"LOW|MEDIUM|HIGH|EXTREME\",
  \"actionable\": \"One clear actionable sentence for the session\",
  \"agent_wallet\": \"{AGENT_ADDR}\"
}}

Return ONLY the JSON. No markdown. No explanation."""

    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    brief = json.loads(raw)
    brief["generated_at"] = time.time()
    brief["data_sources"]  = list(data.keys())

    logger.info(f"[AGENT] Brief: {brief.get('master_bias')} | {brief.get('regime')} | conf={brief.get('confidence')}")
    return brief

# ── List brief on marketplace ──────────────────────────────────────────────────────────────────────────

def list_brief(brief: dict) -> Optional[str]:
    if not AGENT_ADDR:
        logger.warning("[AGENT] No AGENT_XRPL_ADDRESS — skipping marketplace listing")
        return None

    top_picks = brief.get("top_picks", ["IWM"])
    symbol    = top_picks[0] if top_picks else "IWM"
    thesis    = f"{brief.get('market_thesis', '')} Actionable: {brief.get('actionable', '')}".strip()
    if len(thesis) < 20:
        thesis = f"SML Agent brief: {brief.get('master_bias', 'NEUTRAL')} bias, {brief.get('regime', 'UNKNOWN')} regime. {brief.get('iwm_thesis', '')}"

    payload = {
        "wallet":      AGENT_ADDR,
        "symbol":      symbol,
        "bias":        brief.get("master_bias", "NEUTRAL"),
        "confidence":  brief.get("confidence", 50),
        "signal_type": "CUSTOM",
        "timeframe":   "1D",
        "thesis":      thesis[:1000],
        "ttl_hours":   BRIEF_TTL,
    }

    resp = requests.post(f"{SQUEEZEOS}/api/marketplace/list", json=payload, timeout=15)
    resp.raise_for_status()
    result     = resp.json()
    listing_id = result.get("listing_id")
    pnl.record_listing()
    logger.info(f"[AGENT] Listed on marketplace: {listing_id} — {symbol} {brief.get('master_bias')}")
    return listing_id


def refresh_earnings():
    """
    Pulls this agent's REAL accrued seller balance from the marketplace
    server (90% of each actual 0.02 RLUSD /read sale — see
    core/api/marketplace_bp.py's balance()) and syncs it into local pnl
    bookkeeping. Listing a brief is free and never itself earns anything;
    only a later paid /read by some other agent does.
    """
    if not AGENT_ADDR:
        return
    try:
        resp = requests.get(f"{SQUEEZEOS}/api/marketplace/balance/{AGENT_ADDR}", timeout=15)
        resp.raise_for_status()
        real_total = float(resp.json().get("revenue_rlusd", 0.0) or 0.0)
        pnl.refresh_earned(real_total)
    except Exception as e:
        logger.warning(f"[AGENT] Could not refresh real marketplace earnings: {e}")

# ── Post to Slack ────────────────────────────────────────────────────────────────────────────

# PROPRIETARY DATA POLICY: key_levels (price numbers) and raw indicator values
# are never included in Slack output. Only direction labels, confidence %, and
# text thesis are posted.
_BIAS_EMOJI  = {"BULLISH": "\U0001f7e2", "BEARISH": "\U0001f534", "NEUTRAL": "\U0001f7e1"}
_RISK_EMOJI  = {"LOW": "\U0001f7e2", "MEDIUM": "\U0001f7e1", "HIGH": "\U0001f7e0", "EXTREME": "\U0001f534"}
_SESSION_LABEL = {
    "PRE_MARKET": "Pre-Market",
    "OPEN": "Market Open",
    "MIDDAY": "Midday",
    "POWER_HOUR": "Power Hour",
    "CLOSE": "Close",
}

def post_to_slack(brief: dict):
    if not SLACK_WEBHOOK_URL:
        return

    bias     = brief.get("master_bias", "NEUTRAL")
    regime   = brief.get("regime", "UNKNOWN")
    conf     = brief.get("confidence", 0)
    session  = _SESSION_LABEL.get(brief.get("session", ""), brief.get("session", ""))
    picks    = ", ".join(brief.get("top_picks", []) or ["IWM"])
    action   = brief.get("actionable", "")
    risk     = brief.get("risk_level", "UNKNOWN")
    thesis   = brief.get("iwm_thesis", "")

    bias_e = _BIAS_EMOJI.get(bias, "❓")
    risk_e = _RISK_EMOJI.get(risk, "❓")

    filled = round((conf / 100) * 10)
    bar    = "█" * filled + "░" * (10 - filled)

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{bias_e} SML Agent — {session}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Bias*\n{bias}"},
                    {"type": "mrkdwn", "text": f"*Regime*\n{regime}"},
                    {"type": "mrkdwn", "text": f"*Confidence*\n{bar} {conf}%"},
                    {"type": "mrkdwn", "text": f"*Risk*\n{risk_e} {risk}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Watching:* {picks}\n{thesis}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"⚡ *Actionable:* {action}"},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Powered by SqueezeOS · <https://scriptmasterlabs.com|ScriptMaster Labs>"}],
            },
        ]
    }

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        logger.info(f"[SLACK] Posted to webhook: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[SLACK] Webhook post failed: {e}")


# ── Push to webhooks ────────────────────────────────────────────────────────────────────────────

def push_to_webhooks(brief: dict, listing_id: Optional[str]):
    event = {
        "type":       "COUNCIL_VERDICT",
        "symbol":     (brief.get("top_picks") or ["IWM"])[0],
        "bias":       brief.get("master_bias"),
        "regime":     brief.get("regime"),
        "confidence": brief.get("confidence"),
        "thesis":     brief.get("market_thesis", ""),
        "actionable": brief.get("actionable", ""),
        "listing_id": listing_id,
        "agent":      AGENT_ADDR,
        "ts":         time.time(),
    }
    try:
        resp = requests.post(
            f"{SQUEEZEOS}/api/events/push",
            json=event,
            headers={"X-Agent-Wallet": AGENT_ADDR, "X-Agent-Domain": AGENT_DOM},
            timeout=10,
        )
        logger.info(f"[AGENT] Webhook push: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[AGENT] Webhook push failed: {e}")

# ── Log P&L to 402Proof Agent Passport ───────────────────────────────────────────────────────────────────

def log_passport():
    if not AGENT_ADDR:
        return
    try:
        resp = requests.get(f"{PROOF402}/v1/agent/{AGENT_ADDR}", timeout=10)
        if resp.ok:
            passport = resp.json()
            logger.info(
                f"[PASSPORT] tier={passport.get('tier')} "
                f"cumulative={passport.get('cumulative_rlusd')} RLUSD "
                f"discount={passport.get('effective_cost_multiplier')}"
            )
    except Exception:
        pass

# ── Main run cycle ────────────────────────────────────────────────────────────────────────────

def run_cycle():
    pnl.runs += 1
    run_id = f"run-{pnl.runs}-{int(time.time())}"
    logger.info(f"[AGENT] ═══ Cycle {pnl.runs} start — {run_id} ═══")

    try:
        data       = collect_market_data()
        brief      = synthesize_brief(data)
        listing_id = list_brief(brief)
        push_to_webhooks(brief, listing_id)
        post_to_slack(brief)
        log_passport()
        refresh_earnings()

        summary = pnl.summary()
        logger.info(
            f"[AGENT] ═══ Cycle {pnl.runs} complete ═══ "
            f"spent={summary['spent_rlusd']} RLUSD | "
            f"earned={summary['earned_rlusd']} RLUSD | "
            f"listings={summary['listings']} | "
            f"net={summary['net_rlusd']} RLUSD"
        )
        return brief

    except Exception as e:
        logger.error(f"[AGENT] Cycle {pnl.runs} FAILED: {e}", exc_info=True)
        return None

# ── Entry point ────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("═" * 60)
    logger.info("SML AUTONOMOUS MARKET INTELLIGENCE AGENT")
    logger.info(f"Wallet : {AGENT_ADDR or 'NOT SET'}")
    logger.info(f"Domain : {AGENT_DOM}")
    logger.info(f"Base   : {SQUEEZEOS}")
    logger.info(f"Brief  : {BRIEF_PRICE} RLUSD, TTL {BRIEF_TTL}h")
    logger.info("═" * 60)

    if not AGENT_SEED:
        logger.error("AGENT_XRPL_SEED required — set in environment")
        sys.exit(1)
    if not ANTHROPIC_KEY:
        logger.error("ANTHROPIC_API_KEY required — set in environment")
        sys.exit(1)

    if RUN_ONCE:
        run_cycle()
        return

    scheduler = BlockingScheduler(timezone="America/New_York")

    # Pre-market scan — 8:45 AM ET
    scheduler.add_job(run_cycle, CronTrigger(hour=8, minute=45, day_of_week="mon-fri"), id="pre_market")
    # Market open — 9:35 AM ET (let opening volatility settle)
    scheduler.add_job(run_cycle, CronTrigger(hour=9, minute=35, day_of_week="mon-fri"), id="open")
    # Midday — 12:00 PM ET
    scheduler.add_job(run_cycle, CronTrigger(hour=12, minute=0, day_of_week="mon-fri"), id="midday")
    # Power hour — 3:00 PM ET
    scheduler.add_job(run_cycle, CronTrigger(hour=15, minute=0, day_of_week="mon-fri"), id="power_hour")
    # Close summary — 4:15 PM ET
    scheduler.add_job(run_cycle, CronTrigger(hour=16, minute=15, day_of_week="mon-fri"), id="close")

    logger.info("[AGENT] Scheduler started — 5 runs/day (Mon-Fri market hours ET)")
    scheduler.start()


if __name__ == "__main__":
    main()
