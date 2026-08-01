"""
SML Quad-Score Explosive Breakout Finder Scanner — background Python loop,
no TradingView required. Every QUAD_SCORE_SCAN_INTERVAL seconds (default
300), pulls real DAILY bars via DataManager and runs quad_score_engine. A
fresh ENTER_CALL on the latest bar routes to iam_executor.execute_async()
with system tag "SML_QUAD_SCORE" — the full safety stack applies there
(paper mode, stop-losses, daily-loss breaker, primary-system gate). This
module places no orders itself.

This engine is long-only (see quad_score_engine.py's module docstring) —
only BUY ever fires here. An EXIT_TARGET/EXIT_STOP closing that long also
emits a SELL, matching every other engine's "close via _close_equity_
position" convention.

Needs REAL, DEEP daily history (~4+ years) for the weekly-macro-regime
filter's Weekly EMA_200 to ever validate — QUAD_SCORE_BARS_LIMIT defaults
to 1100 daily bars (~4.4 years) accordingly, well above every other daily
scanner's default window in this codebase.

Env vars:
  QUAD_SCORE_SCAN_ENABLED   = true    — master switch
  QUAD_SCORE_SCAN_INTERVAL  = 300     — seconds between passes
  QUAD_SCORE_SCAN_SYMBOLS   = ""      — comma override; empty -> dynamic
                                        universe (IAM_SYMBOL_ALLOWLIST ->
                                        market-scanner candidates -> quoted
                                        universe; never hardcoded)
  QUAD_SCORE_SCAN_TOP_N     = 10      — dynamic-universe size cap
  QUAD_SCORE_BARS_LIMIT     = 1100    — daily bars requested per symbol
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("QUAD-SCORE-SCANNER")

_ENABLED    = os.environ.get("QUAD_SCORE_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("QUAD_SCORE_SCAN_INTERVAL", "300")))
_TIMEFRAME  = "1D"
_BARS_LIMIT = int(os.environ.get("QUAD_SCORE_BARS_LIMIT", "1100"))

_SCAN_TOP_N = int(os.environ.get("QUAD_SCORE_SCAN_TOP_N", "10"))

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
    order as breakout_scanner.py/sovereign_squeeze_scanner.py:
      1. QUAD_SCORE_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("QUAD_SCORE_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    from quad_score_engine import compute_series, QuadScoreParams, _bar_key

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = QuadScoreParams.from_env()
    min_bars = max(p.pctile_window + p.hv_length, p.ema_slow, p.weekly_ema_len * 5) + p.atr_length + 5
    fired = 0
    syms = _symbols()
    if not syms:
        logger.info("[QUAD-SCORE-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars or len(bars) < min_bars:
                logger.info(f"[QUAD-SCORE-SCANNER] {sym}: insufficient daily bars ({len(bars)}/{min_bars}) — skipping")
                continue

            out = compute_series(bars, p)
            last = len(bars) - 1
            action = out["live_signal"][last]

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "QUAD_SCORE_SCAN", {
                    "event": out["events"][last],
                    "composite": out["composite"][last],
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
            event_label = out["events"][last]
            setup = out["scores"][last] or {}
            resolution = {
                "action":                action,
                "system":                "SML_QUAD_SCORE",
                "rationale":             f"QUAD-SCORE {action}: {event_label} @ {price} (composite {setup.get('composite')})",
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
            logger.info(f"[QUAD-SCORE-SCANNER] ⚡ {sym} {action} ({event_label}) → executor")
        except Exception as e:
            logger.warning(f"[QUAD-SCORE-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    return fired


def _loop():
    logger.info(f"[QUAD-SCORE-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[QUAD-SCORE-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from quad_score_engine import QuadScoreParams
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME, "bars_limit": _BARS_LIMIT,
            "symbols": _symbols(), "params": QuadScoreParams.from_env().__dict__}


def start_quad_score_scanner():
    global _started
    if not _ENABLED:
        logger.info("[QUAD-SCORE-SCANNER] QUAD_SCORE_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="quad-score-scanner").start()
