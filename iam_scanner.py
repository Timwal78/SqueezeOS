"""
IAM Background Scanner — proactive obligation surveillance.

Pulls a dynamic symbol list from state.scan_results (top squeeze candidates,
already ranked by score and sourced from Tradier/Alpaca/Polygon by the market
scanner) and falls back to state.quotes when scan_results is still warming up.

Resolves IAM for each symbol and fires the Discord beast-channel embed +
broker execution on any BUY/SELL + IMMEDIATE/NEAR_TERM combination.

Environment variables:
  IAM_SCAN_ENABLED     = true   — master switch for background scanning
  IAM_SCAN_TOP_N       = 50     — max symbols per pass
  IAM_SCAN_INTERVAL    = 300    — seconds to wait between full scan passes
  IAM_SCAN_INTER_DELAY = 2.0    — seconds between symbols (engine is data-fetch heavy)
"""
import os
import time
import threading
import logging

logger = logging.getLogger("IAM-SCANNER")

_SCAN_ENABLED   = os.environ.get("IAM_SCAN_ENABLED", "true").lower() == "true"
_SCAN_TOP_N     = int(os.environ.get("IAM_SCAN_TOP_N", "50"))
_SCAN_INTERVAL  = int(float(os.environ.get("IAM_SCAN_INTERVAL", "300")))
_INTER_DELAY    = float(os.environ.get("IAM_SCAN_INTER_DELAY", "2.0"))
_URGENT_WINDOWS = {"IMMEDIATE", "NEAR_TERM"}
_INITIAL_DELAY  = 120   # wait for market scanner to warm up before first pass


def _get_symbols() -> list:
    """
    Dynamically pull symbol list from live state — no hardcoded tickers.
    Primary: state.scan_results (market scanner top candidates, ranked by squeeze score).
    Fallback: state.quotes universe (all live-quoted symbols).
    """
    from core.state import state

    with state.lock:
        candidates = list(state.scan_results)

    if candidates:
        return [r.get("symbol") for r in candidates[:_SCAN_TOP_N] if r.get("symbol")]

    with state.lock:
        fallback = list(state.quotes.keys())

    return fallback[:_SCAN_TOP_N]


def _scan_pass():
    """One full pass: resolve IAM for each symbol, alert on actionable obligations."""
    from core.api.iam_bp import _get_iam_engine, _fire_iam_discord
    import core.signal_history as signal_history

    symbols = _get_symbols()
    if not symbols:
        logger.info("[IAM-SCANNER] Symbol universe empty — market scanner still warming up")
        return

    logger.info(f"[IAM-SCANNER] Pass starting — {len(symbols)} symbols")
    engine = _get_iam_engine()
    alerts = 0

    for sym in symbols:
        try:
            result = engine.resolve(sym)
            if "error" in result:
                time.sleep(_INTER_DELAY)
                continue

            truth      = result.get("truth_layer", {})
            resolution = result.get("resolution", {})
            action     = resolution.get("action", "HOLD")
            window     = truth.get("time_window", "DORMANT")
            confidence = resolution.get("resolution_confidence", 0.0)
            stress     = truth.get("total_system_stress", 0.0)

            try:
                signal_history.record(sym, "IAM_SCAN", {
                    "action":     action,
                    "stress":     stress,
                    "window":     window,
                    "confidence": confidence,
                })
            except Exception:
                pass

            if action in ("BUY", "SELL") and window in _URGENT_WINDOWS:
                _fire_iam_discord(sym, result)
                try:
                    from iam_executor import execute_async
                    price = float(result.get("price") or 0.0)
                    execute_async(sym, resolution, window, confidence, price)
                except Exception:
                    pass
                alerts += 1

        except Exception as e:
            logger.warning(f"[IAM-SCANNER] {sym}: {e}")

        time.sleep(_INTER_DELAY)

    logger.info(f"[IAM-SCANNER] Pass complete — {len(symbols)} resolved, {alerts} obligations fired")


def _scanner_loop():
    time.sleep(_INITIAL_DELAY)
    while True:
        try:
            _scan_pass()
        except Exception as e:
            logger.error(f"[IAM-SCANNER] Pass error: {e}")
        time.sleep(_SCAN_INTERVAL)


def start_iam_scanner():
    if not _SCAN_ENABLED:
        logger.info("[IAM-SCANNER] Disabled via IAM_SCAN_ENABLED=false")
        return
    t = threading.Thread(target=_scanner_loop, daemon=True, name="iam-scanner")
    t.start()
    logger.info(
        "[IAM-SCANNER] Started — interval=%ds, top_n=%d, inter_delay=%.1fs, initial_delay=%ds",
        _SCAN_INTERVAL, _SCAN_TOP_N, _INTER_DELAY, _INITIAL_DELAY,
    )
