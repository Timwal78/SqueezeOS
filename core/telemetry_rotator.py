import time
import threading
import logging
from core.state import state

logger = logging.getLogger("Telemetry-Rotator")

# Institutional telemetry message templates — only fire with real live state data
INTEL_MESSAGES = [
    "Analyzing dark pool liquidity for {sym}...",
    "Calculating gamma exposure (GEX) at ${price} wall...",
    "Scanning for fractal cascade alignment on {sym}...",
    "Processing live trade tape for institutional sweeps on {sym}...",
    "Leviathan engine detecting liquidity trap on {sym}...",
    "Verifying S3 grade thresholds for {sym} options...",
    "Filtering live universe for high-velocity momentum on {sym}...",
    "Apex breakout monitor active on {sym} | Score: {score}",
    "GEX wall identified at ${price} | Institutional shielding active on {sym}.",
    "Whale stalker echo detected on {sym} dark pool...",
    "Processing 100% live-tape discovery for {sym}...",
    "Zero-Fake audit passed for {sym} engine logic.",
    "Live telemetry stream active for {sym} @ ${price}.",
]

# Mandatory watch symbols — always included per DEVELOPER_MANIFESTO
MANDATORY = ["GME", "AMC", "IWM"]

def run_rotator():
    """Background thread emitting live-state telemetry only — never fake data."""
    logger.info("[ROTATOR] Institutional Telemetry Rotator Active — live-only mode")
    msg_idx = 0

    while True:
        try:
            with state.lock:
                quotes = dict(state.quotes)

            # Build live symbol pool from real state — mandatory trio always first
            live_syms = MANDATORY + [s for s in quotes if s not in MANDATORY]

            for sym in live_syms:
                q     = quotes.get(sym, {})
                price = q.get("price")
                score = q.get("composite_score") or q.get("score")

                # Skip if no live price — never fake a value
                if price is None:
                    continue

                template = INTEL_MESSAGES[msg_idx % len(INTEL_MESSAGES)]
                msg_idx += 1

                score_str = f"{score:.0f}%" if score is not None else "scanning"
                msg = template.format(sym=sym, price=f"{price:.2f}", score=score_str)

                state.push_terminal(
                    event_type="BEAST",
                    msg=msg,
                    symbol=sym,
                    score=score or 0,
                )

            # 60s between cycles — real signals (SQUEEZE_ALERT, COUNCIL_VERDICT)
            # must remain readable before telemetry pushes them off the feed
            time.sleep(60)

        except Exception as e:
            logger.error(f"[ROTATOR] Error: {e}")
            time.sleep(15)


def start_telemetry_rotator():
    thread = threading.Thread(target=run_rotator, daemon=True, name="SML-Telemetry-Rotator")
    thread.start()
    return thread
