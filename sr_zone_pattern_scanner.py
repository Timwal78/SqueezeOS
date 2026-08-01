"""
SML S/R Zone + Candlestick Pattern Scanner — background Python loop, no
TradingView required. Every SR_ZONE_PATTERN_SCAN_INTERVAL seconds (default
300), pulls real DAILY bars via DataManager and runs sr_zone_pattern_engine.
A NEW ENTER_UP / EXIT signal on the latest bar routes to
iam_executor.execute_async() with system tag "SML_SR_ZONE_PATTERN" — the full
safety stack applies there (paper mode, stop-losses, daily-loss breaker,
primary-system gate). This module places no orders itself.

Honest evidence status (see docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md):
this engine's real backtest is THIN — 12 trades across 7 symbols / 4.5 years
at default params (zone_buffer_pct=3.0, exit_mode=atr_target), aggregate
PF 1.186, mixed per-symbol (NVDA lost, AMC weak, GME strong on only 4 trades).
This is NOT the same evidence bar CASCADE/Breakout/S/R-Matrix cleared. It is
wired to PAPER trading (IAM_PAPER_MODE=true default, same as every other
scanner here) so it starts accumulating real Paper Trade Ledger evidence
going forward -- it is explicitly NOT recommended for IAM_PRIMARY_SYSTEM
based on current evidence, same caveat class as Gamma Pin/Squeeze Fuel.

Daily bars mean this works out-of-the-box on a Tradier-only deployment
(unlike ORB/DRUCK's intraday feeds) — same as breakout_scanner.py/
sr_matrix_scanner.py.

live_signal mapping mirrors sr_matrix_scanner.py exactly: ENTER_UP -> BUY,
any EXIT_* -> SELL (closes the long, matching _close_equity_position).

Env vars:
  SR_ZONE_PATTERN_SCAN_ENABLED   = true    — master switch
  SR_ZONE_PATTERN_SCAN_INTERVAL  = 300     — seconds between passes
  SR_ZONE_PATTERN_SCAN_SYMBOLS   = ""      — comma override; empty -> dynamic
                                              universe (IAM_SYMBOL_ALLOWLIST ->
                                              market-scanner candidates ->
                                              quoted universe; never hardcoded)
  SR_ZONE_PATTERN_SCAN_TOP_N     = 10      — dynamic-universe size cap
  SR_ZONE_PATTERN_BARS_LIMIT     = 300     — daily bars requested per symbol
  (engine params: SR_ZONE_PATTERN_BARS / _NO_OF_PIVOTS / _ZONE_EXPIRY /
   _EXIT_MODE / _ATR_STOP_MULT / _ATR_TARGET_MULT / _ZONE_BUFFER_PCT —
   see sr_zone_pattern_engine.ZonePatternParams.from_env())
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("SR-ZONE-PATTERN-SCANNER")

_ENABLED    = os.environ.get("SR_ZONE_PATTERN_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("SR_ZONE_PATTERN_SCAN_INTERVAL", "300")))
_TIMEFRAME  = "1D"
_BARS_LIMIT = int(os.environ.get("SR_ZONE_PATTERN_BARS_LIMIT", "300"))

# 25 (raised from 10, 2026-08-01) -- see breakout_scanner.py's identical
# comment: tradier_api.py's global 1.05s/call rate limiter makes an actual
# violation impossible regardless of this value; 25 across 5 Tradier-daily
# scanners (+ CASCADE's 40) keeps worst-case queue-drain comfortably under
# the shared 300s SCAN_INTERVAL. Full math in CLAUDE.md's scan-width section.
_SCAN_TOP_N = int(os.environ.get("SR_ZONE_PATTERN_SCAN_TOP_N", "25"))

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
    order as breakout_scanner.py/sr_matrix_scanner.py:
      1. SR_ZONE_PATTERN_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("SR_ZONE_PATTERN_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    from sr_zone_pattern_engine import compute_series, ZonePatternParams, _bar_key

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = ZonePatternParams.from_env()
    fired = 0
    syms = _symbols()
    if not syms:
        logger.info("[SR-ZONE-PATTERN-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars or len(bars) < p.bars * 2 + 2:
                logger.info(f"[SR-ZONE-PATTERN-SCANNER] {sym}: insufficient daily bars ({len(bars)}) — skipping")
                continue

            out = compute_series(bars, p)
            last = len(bars) - 1
            action = out["live_signal"][last]

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "SR_ZONE_PATTERN_SCAN", {"event": out["events"][last]})
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

            event = out["events"][last]
            price = float(bars[-1].get("close") or bars[-1].get("c") or 0.0)
            resolution = {
                "action":                action,
                "system":                "SML_SR_ZONE_PATTERN",
                "rationale":             f"SR ZONE+PATTERN {event}: zone+candlestick confluence @ {price}",
                "vehicle":               sym,
                "resolution_confidence": 75.0,  # must clear IAM_MIN_CONFIDENCE (75) -- kept at the floor given thin backtest evidence
                "invalidation":          "",
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "IMMEDIATE", 75.0, price)
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {"symbol": sym, "action": action, "event": event, "ts": time.time()}
            logger.info(f"[SR-ZONE-PATTERN-SCANNER] ⚡ {sym} {action} ({event}) → executor")
        except Exception as e:
            logger.warning(f"[SR-ZONE-PATTERN-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    return fired


def _loop():
    logger.info(f"[SR-ZONE-PATTERN-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[SR-ZONE-PATTERN-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from sr_zone_pattern_engine import ZonePatternParams
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "symbols": _symbols(), "params": ZonePatternParams.from_env().__dict__,
            "evidence_status": "THIN — 12 trades / 7 symbols / 4.5yr backtest, PF 1.186, mixed per-symbol. "
                                "Not recommended for IAM_PRIMARY_SYSTEM. See docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md"}


def start_sr_zone_pattern_scanner():
    global _started
    if not _ENABLED:
        logger.info("[SR-ZONE-PATTERN-SCANNER] SR_ZONE_PATTERN_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="sr-zone-pattern-scanner").start()
