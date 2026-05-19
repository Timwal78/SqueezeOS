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
  RUN_ONCE                 - set to "true" to run once and exit (for cron)
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

# ── XRPL ──────────────────────────────────────────────────────────────────────
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
SQUEEZEOS   = os.environ.get("SQUEEZEOS_BASE_URL",  "https://lively-fascination-production-41fa.up.railway.app")
PROOF402    = os.environ.get("PROOF402_BASE_URL",   "https://four02proof.onrender.com")
XRPL_RPC      = os.environ.get("XRPL_RPC_URL",          "https://xrplcluster.com")
AGENT_SEED    = os.environ.get("AGENT_XRPL_SEED",       "")
AGENT_ADDR    = os.environ.get("AGENT_XRPL_ADDRESS",    "")
AGENT_DOM     = os.environ.get("AGENT_DOMAIN",          "agent.scriptmasterlabs.com")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY",     "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
BRIEF_PRICE = float(os.environ.get("BRIEF_PRICE_RLUSD", "0.01"))
BRIEF_TTL   = int(os.environ.get("BRIEF_TTL_HOURS", "6"))
RUN_ONCE    = os.environ.get("RUN_ONCE", "false").lower() == "true"

RLUSD_ISSUER   = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "524C555344000000000000000000000000000000"

# Endpoint IDs from 402Proof
ENDPOINT_COUNCIL = "12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a"
ENDPOINT_SCAN    = "160cf28d-b364-44eb-adbd-2489c5cc2cf8"
ENDPOINT_IWM     = "60f48ce0-6002-4385-9b60-03a0d2bbebab"
ENDPOINT_OPTIONS = "c951a374-2424-4064-ab80-35afe8053d29"

# ── P&L Tracker ───────────────────────────────────────────────────────────────
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

    def record_earn(self, amount: float):
        with self._lock:
            self.earned = round(self.earned + amount, 6)
            self.listings += 1

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

# ── XRPL Payment ──────────────────────────────────────────────────────────────

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

# ── x402 Full Flow ────────────────────────────────────────────────────────────

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

# ── Free endpoints (no payment) ───────────────────────────────────────────────

def get_free(path: str) -> dict:
    resp = requests.get(f"{SQUEEZEOS}{path}", timeout=20)
    resp.raise_for_status()
    return resp.json()

# ── Data collection ───────────────────────────────────────────────────────────

def collect_market_data() -> dict:
    logger.info("[AGENT] Collecting market data...")
    data = {}

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

# ── Brief synthesis (Claude) ──────────────────────────────────────────────────

def synthesize_brief(data: dict) -> dict:
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt = f"""You are the SML Autonomous Market Intelligence Agent — a zero-simulation, absolute-execution trading intelligence system built on Script Master Labs' proprietary engine stack. Your mandate: synthesize live multi-engine data into a high-conviction brief. Never estimate, interpolate, or fabricate. If a data source is missing, note it explicitly.

TIMESTAMP: {now_str}

═══ RAW ENGINE OUTPUT ═══
{json.dumps(data, indent=2, default=str)}

═══ YOUR ANALYTICAL MANDATE ═══

STEP 1 — ENGINE ALIGNMENT CHECK
Examine every data source and answer:
- Does the council verdict bias (BULLISH/BEARISH/NEUTRAL) match the scan's top-scoring symbols' momentum direction?
- Does the options flow (PUT/CALL sweep sentiment) confirm or contradict the council bias?
- Does the IWM 0DTE gamma flip level support or resist the current price action implied by the council regime?
- Is the current bias a CONTINUATION (same as last 2+ signals in history) or a REVERSAL? Reversals need higher evidence threshold.

STEP 2 — CONTRADICTION FLAGS
Identify any conflicts across engines. Examples:
- Council says BULLISH but options flow shows heavy PUT sweeps → CONFLICT
- Regime is EXECUTION but squeeze count is 0 → CONFLICT
- IWM verdict is BEARISH but 0DTE gamma flip is above current price → BEARISH CONFIRMATION
Flag each conflict explicitly. Do not average them away.

STEP 3 — TOP PICK SELECTION
A pick is only grade-A if ALL THREE are true:
  (a) it appears in the scan results with score > 70
  (b) the council bias for IWM or that symbol is directionally aligned
  (c) options flow is NOT explicitly contradicting the direction
Picks that meet only 1 or 2 criteria are grade-B — still list them but flag the grade.

STEP 4 — CONFIDENCE CALIBRATION
Start at the council confidence score. Then:
  +10 if scan top picks align with council bias
  +10 if options flow confirms
  +5  if signal history shows continuation (same bias 2+ times)
  +5  if IWM 0DTE gamma flip confirms direction
  -15 if any CONFLICT flag from Step 2
  -10 if this is a bias reversal with < 2 confirming signals
  -20 if 2 or more CONFLICT flags
Cap final confidence at 95. Floor at 5.

STEP 5 — KEY LEVELS
Extract IWM support and resistance ONLY from hard data:
- gamma_flip_level and max_pain from the 0DTE data (these are real structural levels)
- Do NOT invent levels. If 0DTE data is missing, set both to 0 and note "0DTE_UNAVAILABLE"

═══ OUTPUT FORMAT ═══
Return ONLY valid JSON. No markdown, no explanation, no commentary outside the JSON.

{{
  "title": "SML Market Brief — {now_str}",
  "session": "PRE_MARKET|OPEN|MIDDAY|POWER_HOUR|CLOSE",
  "master_bias": "BULLISH|BEARISH|NEUTRAL",
  "regime": "EXECUTION|STEALTH|CONFLICT|COLLAPSE",
  "confidence": 0-95,
  "engine_alignment": "CONFIRMED|PARTIAL|CONFLICTED",
  "conflict_flags": ["list any conflicts found, empty array if none"],
  "continuation_or_reversal": "CONTINUATION|REVERSAL|INSUFFICIENT_HISTORY",
  "top_picks": [
    {{"symbol": "SYM", "bias": "BULLISH|BEARISH", "grade": "A|B", "reason": "one sentence why"}}
  ],
  "iwm_thesis": "2-3 sentences: what the council said + what the 0DTE data confirms or challenges",
  "market_thesis": "3-4 sentences: the full picture across scan + council + options, explicitly noting any conflicts",
  "key_levels": {{"IWM_support": 0.0, "IWM_resistance": 0.0, "source": "gamma_flip|max_pain|0DTE_UNAVAILABLE"}},
  "squeeze_count": 0,
  "options_flow": "BULLISH|BEARISH|NEUTRAL|MIXED",
  "risk_level": "LOW|MEDIUM|HIGH|EXTREME",
  "actionable": "One sentence — ONLY if confidence >= 60 and engine_alignment != CONFLICTED. Otherwise: STAND_ASIDE — [reason]",
  "conviction_grade": "A|B|C|STAND_ASIDE",
  "agent_wallet": "{AGENT_ADDR}"
}}"""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if Claude adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    brief = json.loads(raw.strip())
    brief["generated_at"] = time.time()
    brief["data_sources"]  = list(data.keys())

    logger.info(
        f"[AGENT] Brief: {brief.get('master_bias')} | {brief.get('regime')} | "
        f"conf={brief.get('confidence')} | alignment={brief.get('engine_alignment')} | "
        f"grade={brief.get('conviction_grade')} | conflicts={brief.get('conflict_flags', [])}"
    )
    return brief

# ── List brief on marketplace ─────────────────────────────────────────────────

def list_brief(brief: dict) -> Optional[str]:
    if not AGENT_ADDR:
        logger.warning("[AGENT] No AGENT_XRPL_ADDRESS — skipping marketplace listing")
        return None

    picks     = brief.get("top_picks", [])
    top_pick  = picks[0] if picks and isinstance(picks[0], dict) else None
    symbol    = top_pick["symbol"] if top_pick else "IWM"

    conflicts = brief.get("conflict_flags", [])
    conflict_note = f" CONFLICTS: {'; '.join(conflicts)}." if conflicts else ""
    thesis = (
        f"[{brief.get('conviction_grade','?')} | {brief.get('engine_alignment','?')} | "
        f"{brief.get('continuation_or_reversal','?')}] "
        f"{brief.get('market_thesis', '')} "
        f"{brief.get('iwm_thesis', '')}"
        f"{conflict_note} "
        f"Actionable: {brief.get('actionable', '')}"
    ).strip()
    if len(thesis) < 20:
        thesis = f"SML Agent: {brief.get('master_bias','NEUTRAL')} | {brief.get('regime','UNKNOWN')} | conf={brief.get('confidence',0)}"

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
    pnl.record_earn(BRIEF_PRICE)
    logger.info(f"[AGENT] Listed on marketplace: {listing_id} — {symbol} {brief.get('master_bias')}")
    return listing_id

# ── Open Signal Futures position ─────────────────────────────────────────────

def post_futures_position(brief: dict) -> Optional[str]:
    """Agent stakes on its own IWM prediction — only when conviction grade is A or B."""
    if not AGENT_ADDR:
        return None
    grade = brief.get("conviction_grade", "C")
    if grade == "STAND_ASIDE":
        logger.info("[AGENT] Skipping futures — conviction grade STAND_ASIDE")
        return None
    bias = brief.get("master_bias", "").upper()
    if bias not in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return None
    # Stake higher on grade-A conviction
    stake = 0.02 if grade == "A" else 0.01
    session = brief.get("session", "ANY").upper()
    if session not in {"PRE_MARKET", "OPEN", "MIDDAY", "POWER_HOUR", "CLOSE", "ANY"}:
        session = "ANY"
    alignment = brief.get("engine_alignment", "")
    conflicts  = brief.get("conflict_flags", [])
    try:
        resp = requests.post(
            f"{SQUEEZEOS}/api/futures/create",
            json={
                "creator_wallet": AGENT_ADDR,
                "symbol":         "IWM",
                "predicted_bias": bias,
                "session":        session,
                "stake_rlusd":    stake,
                "note":           f"Grade={grade} alignment={alignment} conf={brief.get('confidence',0)} conflicts={len(conflicts)}",
            },
            timeout=10,
        )
        if resp.ok:
            future_id = resp.json().get("future_id")
            logger.info(f"[AGENT] Futures {grade}-grade position: {future_id[:8]}… IWM {bias} stake={stake} RLUSD")
            return future_id
    except Exception as e:
        logger.warning(f"[AGENT] Futures position failed: {e}")
    return None


# ── Trigger pending settlement contracts ──────────────────────────────────────

def trigger_pending_settlements():
    """Scan open settlement contracts and trigger any that may now be met."""
    try:
        resp = requests.get(f"{SQUEEZEOS}/api/settlement", params={"status": "OPEN", "limit": 50}, timeout=10)
        if not resp.ok:
            return
        contracts = resp.json().get("contracts", [])
        triggered = 0
        for c in contracts:
            cid = c.get("id")
            if not cid:
                continue
            try:
                t = requests.post(f"{SQUEEZEOS}/api/settlement/trigger/{cid}", timeout=10)
                if t.ok and t.json().get("status") == "settled":
                    triggered += 1
                    logger.info(f"[AGENT] Settlement triggered: {cid[:8]}…")
            except Exception:
                pass
        if triggered:
            logger.info(f"[AGENT] Triggered {triggered} settlement contracts")
    except Exception as e:
        logger.warning(f"[AGENT] Settlement scan failed: {e}")


# ── Discord webhook ───────────────────────────────────────────────────────────

_BIAS_COLOR = {"BULLISH": 0x00C851, "BEARISH": 0xFF4444, "NEUTRAL": 0xFFBB33}
_GRADE_EMOJI = {"A": "🟢", "B": "🟡", "C": "🟠", "STAND_ASIDE": "🔴"}
_REGIME_EMOJI = {
    "EXECUTION": "⚡", "STEALTH": "👻",
    "CONFLICT":  "⚠️", "COLLAPSE": "💀",
}

def push_discord(brief: dict, listing_id: Optional[str]):
    if not DISCORD_WEBHOOK:
        return

    bias      = brief.get("master_bias", "NEUTRAL")
    regime    = brief.get("regime", "")
    conf      = brief.get("confidence", 0)
    grade     = brief.get("conviction_grade", "C")
    alignment = brief.get("engine_alignment", "")
    conflicts = brief.get("conflict_flags", [])
    actionable = brief.get("actionable", "")
    picks     = brief.get("top_picks", [])
    levels    = brief.get("key_levels", {})
    color     = _BIAS_COLOR.get(bias, 0x888888)
    g_emoji   = _GRADE_EMOJI.get(grade, "⚪")
    r_emoji   = _REGIME_EMOJI.get(regime, "")
    session   = brief.get("session", "")

    # Top picks field
    picks_lines = []
    for p in (picks if isinstance(picks, list) else []):
        if isinstance(p, dict):
            pg = _GRADE_EMOJI.get(p.get("grade",""), "")
            picks_lines.append(f"{pg} **{p.get('symbol','')}** {p.get('bias','')} — {p.get('reason','')}")
        else:
            picks_lines.append(f"• {p}")
    picks_str = "\n".join(picks_lines) if picks_lines else "None"

    # Conflict field
    conflict_str = "\n".join(f"⚠️ {c}" for c in conflicts) if conflicts else "✅ None"

    # Key levels
    support    = levels.get("IWM_support", 0)
    resistance = levels.get("IWM_resistance", 0)
    levels_str = f"Support: **{support}** | Resistance: **{resistance}**" if support else "0DTE data unavailable"

    fields = [
        {"name": f"{r_emoji} Regime",          "value": regime,       "inline": True},
        {"name": "📊 Confidence",               "value": f"{conf}",    "inline": True},
        {"name": "🔗 Engine Alignment",         "value": alignment,    "inline": True},
        {"name": "📈 Top Picks",                "value": picks_str,    "inline": False},
        {"name": "🎯 Key Levels (IWM)",         "value": levels_str,   "inline": False},
        {"name": "⚡ Actionable",               "value": actionable,   "inline": False},
        {"name": "⚠️ Conflict Flags",           "value": conflict_str, "inline": False},
    ]
    if listing_id:
        fields.append({
            "name":  "🛒 Marketplace",
            "value": f"[Read full thesis]({SQUEEZEOS}/api/marketplace/preview/{listing_id})",
            "inline": False,
        })

    embed = {
        "title":       f"{g_emoji} SML Agent — {bias} | {session}",
        "description": brief.get("market_thesis", ""),
        "color":       color,
        "fields":      fields,
        "footer":      {"text": f"Script Master Labs • {brief.get('title','')[:60]}"},
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }

    try:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"embeds": [embed]},
            timeout=10,
        )
        if resp.ok:
            logger.info(f"[DISCORD] Brief posted — {bias} {grade} conf={conf}")
        else:
            logger.warning(f"[DISCORD] Post failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        logger.warning(f"[DISCORD] Failed: {e}")


# ── Push to webhooks ──────────────────────────────────────────────────────────

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

# ── Log P&L to 402Proof Agent Passport ───────────────────────────────────────

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

# ── Main run cycle ────────────────────────────────────────────────────────────

def run_cycle():
    pnl.runs += 1
    run_id = f"run-{pnl.runs}-{int(time.time())}"
    logger.info(f"[AGENT] ═══ Cycle {pnl.runs} start — {run_id} ═══")

    try:
        data       = collect_market_data()
        brief      = synthesize_brief(data)
        listing_id = list_brief(brief)
        post_futures_position(brief)
        trigger_pending_settlements()
        push_discord(brief, listing_id)
        push_to_webhooks(brief, listing_id)
        log_passport()

        summary = pnl.summary()
        logger.info(
            f"[AGENT] ═══ Cycle {pnl.runs} complete ═══ "
            f"spent={summary['spent_rlusd']} RLUSD | "
            f"listings={summary['listings']} | "
            f"net={summary['net_rlusd']} RLUSD"
        )
        return brief

    except Exception as e:
        logger.error(f"[AGENT] Cycle {pnl.runs} FAILED: {e}", exc_info=True)
        return None

# ── Entry point ───────────────────────────────────────────────────────────────

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
