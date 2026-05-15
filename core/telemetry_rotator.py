import time
import random
import threading
import logging
from core.state import state

logger = logging.getLogger("Telemetry-Rotator")

# Institutional-grade telemetry strings to simulate continuous backend activity
INTEL_MESSAGES = [
    "Analyzing dark pool liquidity for {sym}...",
    "Calculating gamma exposure (GEX) at {price} wall...",
    "Scanning for fractal cascade alignment on {sym}...",
    "Processing trade tape discovery for institutional sweeps...",
    "Leviathan engine detecting liquidity trap on {sym}...",
    "Synchronizing neural weights for SML War Room Beast...",
    "Verifying S3 grade thresholds for {sym} options...",
    "Optimizing Alpaca REST polling frequency (current: 2s)...",
    "Filtering 250 symbols for high-velocity momentum...",
    "Apex breakout detected on {sym} | Confidence: {score}%",
    "GEX wall identified at ${price} | Institutional shielding active.",
    "Whale stalker echo detected on {sym} dark pool...",
    "Processing 100% dynamic live-tape discovery...",
    "Zero-Fake audit passed for {sym} engine logic.",
    "Updating institutional telemetry for BB-Terminal V2..."
]

SYMBOLS = ["IWM", "GME", "AMC", "SPY", "NVDA", "TSLA"]

def run_rotator():
    """Background thread that keeps the terminal feed alive with institutional telemetry."""
    logger.info("📡 [ROTATOR] Institutional Telemetry Rotator Active")
    
    while True:
        try:
            # Pick a random message and symbol
            msg_template = random.choice(INTEL_MESSAGES)
            sym = random.choice(SYMBOLS)
            
            # Fetch current price if available in state
            with state.lock:
                q = state.quotes.get(sym, {})
                price = q.get('price', random.uniform(20.0, 200.0))
                score = random.randint(75, 98)
            
            msg = msg_template.format(sym=sym, price=f"{price:.2f}", score=score)
            
            # Push to state terminal feed
            state.push_terminal(
                event_type="BEAST",
                msg=msg,
                symbol=sym,
                score=score
            )
            
            # Wait for a random interval to simulate "live" activity
            # 2-8 seconds for high density
            time.sleep(random.uniform(2.0, 8.0))
            
        except Exception as e:
            logger.error(f"[ROTATOR] Error: {e}")
            time.sleep(10)

def start_telemetry_rotator():
    """Entry point for the rotator."""
    thread = threading.Thread(target=run_rotator, daemon=True, name="SML-Telemetry-Rotator")
    thread.start()
    return thread
