"""
SML Squeeze Fuel Scanner — background loop feeding squeeze_fuel_engine.py's
composite score to the live executor.

Every SQUEEZE_FUEL_SCAN_INTERVAL seconds (default 300), pulls each
candidate's live quote (state.quotes, the same real data squeeze_analyzer
already reads), an optional live Tradier option chain (same call
gamma_pin_scanner.py already makes), computes the composite via
squeeze_fuel_engine.analyze(), and on a resolved BUY (composite score >=
ENTRY_THRESHOLD AND bullish price/volume direction) routes to
iam_executor.execute_async() tagged "SML_SQUEEZE_FUEL". This module places
no orders itself — the full existing safety stack applies there (paper
mode, stop-losses, daily-loss breaker, primary-system gate).

NO BACKTEST EVIDENCE EXISTS FOR THIS ENGINE — see squeeze_fuel_engine.py's
module docstring for why. This build does NOT flip anything live by
itself: IAM_PAPER_MODE=true is still the default, and nobody has added
SML_SQUEEZE_FUEL to IAM_PRIMARY_SYSTEM. Do not add it there or represent
this as a proven signal.
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("SQUEEZE-FUEL-SCANNER")

_ENABLED         = os.environ.get("SQUEEZE_FUEL_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL        = int(float(os.environ.get("SQUEEZE_FUEL_SCAN_INTERVAL", "300")))
_SCAN_TOP_N      = int(os.environ.get("SQUEEZE_FUEL_SCAN_TOP_N", "10"))
_MAX_EXPIRATIONS = int(os.environ.get("SQUEEZE_FUEL_MAX_EXPIRATIONS", "8"))
_PULL_CHAIN      = os.environ.get("SQUEEZE_FUEL_PULL_CHAIN", "true").strip().lower() == "true"

_started = False
_lock = threading.Lock()
_last_fired: dict = {}
_status = {
    "running": False,
    "last_pass_ts": None,
    "signals_fired_total": 0,
    "last_signal": None,
    "last_error": None,
}


def _symbols() -> list:
    """
    Dynamic universe resolution -- same order as every other scanner here
    (gamma_pin_scanner.py/druck_scanner.py/orb_scanner.py/imo_scanner.py):
      1. SQUEEZE_FUEL_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Never a hardcoded list (operator directive 2026-07-19, Prime Directive #1).
    """
    raw = os.environ.get("SQUEEZE_FUEL_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
    if raw and raw != "*":
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    try:
        from core.state import state
        with state.lock:
            candidates = list(state.scan_results)
            quotes = list(state.quotes.keys())
        if candidates:
            return [r.get("symbol") for r in candidates[:_SCAN_TOP_N] if r.get("symbol")]
        return [s for s in quotes[:_SCAN_TOP_N]]
    except Exception:
        return []


def _fetch_chain(symbol: str):
    if not _PULL_CHAIN:
        return None
    try:
        import tradier_api
        return tradier_api.get_option_chain_schwab_format(symbol, max_expirations=_MAX_EXPIRATIONS)
    except Exception:
        return None


def scan_once() -> int:
    from squeeze_fuel_engine import analyze
    from core.state import state

    fired = 0
    syms = _symbols()
    if not syms:
        logger.info("[SQUEEZE-FUEL-SCANNER] no live universe yet (market scanner warming up) — pass skipped")

    for sym in syms:
        try:
            with state.lock:
                quote = dict(state.quotes.get(sym, {}))
            if not quote:
                continue

            raw_chain = _fetch_chain(sym)
            result = analyze(sym, quote_data=quote, raw_chain=raw_chain)

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "SQUEEZE_FUEL_SCAN", {
                    "composite_score": result["composite_score"],
                    "direction": result["direction"],
                })
            except Exception:
                pass

            if result.get("action") != "BUY":
                continue

            score_bucket = int(result["composite_score"] // 5) * 5  # dedup on ~5pt score buckets
            key = f'BUY|{score_bucket}'
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            conf = min(result["composite_score"], 99.0)
            spot = float(quote.get("price", 0) or 0)
            resolution = {
                "action":                "BUY",
                "system":                "SML_SQUEEZE_FUEL",
                "rationale":             f"Squeeze fuel composite {result['composite_score']}/100 "
                                         f"(ignition {result['ignition']['score']}/40, "
                                         f"FTD fuel {result['ftd_fuel']['score']}/20"
                                         f"{' [ON THRESHOLD LIST]' if result['ftd_fuel']['on_reg_sho_threshold_list'] else ''}, "
                                         f"short-vol pressure {result['short_volume_fuel']['score']}/20, "
                                         f"gamma amp {result['gamma_amplifier']['score']}/20 "
                                         f"[{result['gamma_amplifier']['regime'] or 'no chain'}]) — "
                                         f"NO BACKTEST EVIDENCE, see squeeze_fuel_engine.py docstring",
                "vehicle":               sym,
                "resolution_confidence": conf,
                "invalidation":          "",
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "IMMEDIATE", conf, spot)
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {
                "symbol": sym, "composite_score": result["composite_score"],
                "confidence": conf, "ts": time.time(),
            }
            logger.info(f"[SQUEEZE-FUEL-SCANNER] ⚡ {sym} BUY composite={result['composite_score']} → executor")
        except Exception as e:
            logger.warning(f"[SQUEEZE-FUEL-SCANNER] {sym}: {e}")
        time.sleep(0.3)

    _status["last_pass_ts"] = time.time()
    return fired


def _loop():
    logger.info(f"[SQUEEZE-FUEL-SCANNER] Online — {_symbols()} every {_INTERVAL}s "
                f"(NO BACKTEST EVIDENCE — see squeeze_fuel_engine.py docstring)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[SQUEEZE-FUEL-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from squeeze_fuel_engine import ENTRY_THRESHOLD
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "symbols": _symbols(),
            "entry_threshold": ENTRY_THRESHOLD}


def start_squeeze_fuel_scanner():
    global _started
    if not _ENABLED:
        logger.info("[SQUEEZE-FUEL-SCANNER] SQUEEZE_FUEL_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="squeeze-fuel-scanner").start()
