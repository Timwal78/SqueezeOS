"""
SML Support/Resistance Matrix Scanner — background Python loop, no
TradingView required. Every SR_MATRIX_SCAN_INTERVAL seconds (default 300),
pulls real DAILY bars via DataManager and runs sr_matrix_engine. A NEW pivot
confirmation on the latest bar routes to iam_executor.execute_async() with
system tag "SML_SR_MATRIX" — the full safety stack applies there (paper
mode, stop-losses, daily-loss breaker, primary-system gate). This module
places no orders itself.

Daily bars mean this works out-of-the-box on a Tradier-only deployment
(unlike ORB/DRUCK's intraday feeds) — same as imo_scanner.py/
breakout_scanner.py/cie_scanner.py.

Env vars:
  SR_MATRIX_SCAN_ENABLED   = true    — master switch
  SR_MATRIX_SCAN_INTERVAL  = 300     — seconds between passes
  SR_MATRIX_SCAN_SYMBOLS   = ""      — comma override; empty -> dynamic universe
                                       (IAM_SYMBOL_ALLOWLIST -> market-scanner
                                       candidates -> quoted universe; never hardcoded)
  SR_MATRIX_SCAN_TOP_N     = 10      — dynamic-universe size cap
  SR_MATRIX_BARS_LIMIT     = 300     — daily bars requested per symbol
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("SR-MATRIX-SCANNER")

_ENABLED    = os.environ.get("SR_MATRIX_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("SR_MATRIX_SCAN_INTERVAL", "300")))
_TIMEFRAME  = "1D"
_BARS_LIMIT = int(os.environ.get("SR_MATRIX_BARS_LIMIT", "300"))

# Dynamic (2026-08-01) -- see breakout_scanner.py's identical comment and
# scan_budget.py's module docstring: this scanner's share of the safe
# shared Tradier queue budget is computed live across whichever secondary
# scanners are actually enabled; SR_MATRIX_SCAN_TOP_N, if set, always wins.
from scan_budget import dynamic_top_n
_SCAN_TOP_N = dynamic_top_n("SR_MATRIX", "SR_MATRIX_SCAN_TOP_N")

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
    Universe resolution — DYNAMIC by default, never a hardcoded list
    (operator directive 2026-07-19 + Prime Directive #1), same resolution
    order as orb_scanner.py/druck_scanner.py/breakout_scanner.py:
      1. SR_MATRIX_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("SR_MATRIX_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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


def scan_once() -> int:
    from core.legacy import get_service
    from sr_matrix_engine import compute_series, SrMatrixParams, _bar_key

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = SrMatrixParams.from_env()
    fired = 0
    syms = _symbols()
    if not syms:
        logger.info("[SR-MATRIX-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars or len(bars) < p.bars * 2 + 2:
                logger.info(f"[SR-MATRIX-SCANNER] {sym}: insufficient daily bars ({len(bars)}) — skipping")
                continue

            out = compute_series(bars, p)
            last = len(bars) - 1
            action = out["live_signal"][last]

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "SR_MATRIX_SCAN", {
                    "pivot_high_confirmed": out["confirmed_high"][last],
                    "pivot_low_confirmed": out["confirmed_low"][last],
                })
            except Exception:
                pass

            if action not in ("BUY", "SELL"):
                continue

            bar_key = _bar_key(bars[-1], last)
            key = f"{bar_key}|{action}"
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            price = float(bars[-1].get("close") or bars[-1].get("c") or 0.0)
            pivot_label = "pivot low" if action == "BUY" else "pivot high"
            resolution = {
                "action":                action,
                "system":                "SML_SR_MATRIX",
                "rationale":             f"S/R MATRIX {action}: confirmed {pivot_label} ({p.bars}-bar) @ {price}",
                "vehicle":               sym,
                "resolution_confidence": 78.0,  # must clear IAM_MIN_CONFIDENCE (75)
                "invalidation":          "",
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "IMMEDIATE", 78.0, price)
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {"symbol": sym, "action": action, "ts": time.time()}
            logger.info(f"[SR-MATRIX-SCANNER] ⚡ {sym} {action} ({pivot_label}) → executor")
        except Exception as e:
            logger.warning(f"[SR-MATRIX-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    return fired


def _loop():
    logger.info(f"[SR-MATRIX-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[SR-MATRIX-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from sr_matrix_engine import SrMatrixParams
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "symbols": _symbols(), "params": SrMatrixParams.from_env().__dict__}


def start_sr_matrix_scanner():
    global _started
    if not _ENABLED:
        logger.info("[SR-MATRIX-SCANNER] SR_MATRIX_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="sr-matrix-scanner").start()
