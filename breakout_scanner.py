"""
SML Breakout Scanner — background Python loop, no TradingView required.
=========================================================================
Every BREAKOUT_SCAN_INTERVAL seconds (default 300), pulls real DAILY bars via
DataManager and runs breakout_engine. A NEW entry signal on the latest bar
routes to iam_executor.execute_async() with system tag "SML_BREAKOUT" — the
full safety stack applies there (paper mode, stop-losses, daily-loss breaker,
primary-system gate). This module places no orders itself.

Daily bars mean this works out-of-the-box on a Tradier-only deployment (unlike
ORB/DRUCK's intraday bars, which need Polygon/Alpaca) — same as imo_scanner.py
and cie_scanner.py.

Only ENTRY events (ENTER_UP -> BUY, ENTER_DOWN -> SELL) are routed live — see
breakout_engine.py's module docstring for why target/stop exits are NOT
auto-fired as a live SELL signal (iam_executor's SELL has a compound "close
long + open put" meaning that doesn't match a flat take-profit exit).

Env vars:
  BREAKOUT_SCAN_ENABLED   = true    — master switch
  BREAKOUT_SCAN_INTERVAL  = 300     — seconds between passes
  BREAKOUT_SCAN_SYMBOLS   = ""      — comma override; empty -> dynamic universe
                                      (IAM_SYMBOL_ALLOWLIST -> market-scanner
                                      candidates -> quoted universe; never hardcoded)
  BREAKOUT_SCAN_TOP_N     = 10      — dynamic-universe size cap
  BREAKOUT_BARS_LIMIT     = 300     — daily bars requested per symbol
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("BREAKOUT-SCANNER")

_ENABLED    = os.environ.get("BREAKOUT_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("BREAKOUT_SCAN_INTERVAL", "300")))
_TIMEFRAME  = "1D"
_BARS_LIMIT = int(os.environ.get("BREAKOUT_BARS_LIMIT", "300"))

# 25 (raised from 10, 2026-08-01): tradier_api.py's rate limiter is a global,
# process-wide 1.05s/call floor shared by EVERY Tradier caller regardless of
# which scanner makes the call -- this makes an actual rate-limit violation
# structurally impossible no matter how high this goes; the only real cost of
# going too wide is scan-cycle staleness (a slower pass, not an error). With
# CASCADE's own AVG_DOWN_SCAN_TOP_N already at 40 and 5 Tradier-daily
# scanners sharing this same global queue, 25 each (5*25=125 + CASCADE's 40
# = 165 total * 1.05s ~= 173s worst-case queue-drain) leaves ~42% margin
# under the shared 300s SCAN_INTERVAL -- see CLAUDE.md's scan-width section.
_SCAN_TOP_N = int(os.environ.get("BREAKOUT_SCAN_TOP_N", "25"))

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
    order as orb_scanner.py/druck_scanner.py/imo_scanner.py:
      1. BREAKOUT_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("BREAKOUT_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    from breakout_engine import compute_series, BreakoutParams, _bar_key

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = BreakoutParams.from_env()
    fired = 0
    syms = _symbols()
    if not syms:
        logger.info("[BREAKOUT-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars or len(bars) < p.lookback + 2:
                logger.info(f"[BREAKOUT-SCANNER] {sym}: insufficient daily bars ({len(bars)}) — skipping")
                continue

            out = compute_series(bars, p)
            last = len(bars) - 1
            action = out["live_signal"][last]

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "BREAKOUT_SCAN", {
                    "event": out["events"][last], "in_pos": out["in_pos"],
                    "direction": out["direction"],
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

            event = out["events"][last]
            price = float(bars[-1].get("close") or bars[-1].get("c") or 0.0)
            resolution = {
                "action":                action,
                "system":                "SML_BREAKOUT",
                "rationale":             f"BREAKOUT {event}: {p.lookback}-day Donchian break @ {price}",
                "vehicle":               sym,
                "resolution_confidence": 80.0,
                "invalidation":          "",
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "IMMEDIATE", 80.0, price)
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {"symbol": sym, "action": action, "event": event, "ts": time.time()}
            logger.info(f"[BREAKOUT-SCANNER] ⚡ {sym} {action} ({event}) → executor")
        except Exception as e:
            logger.warning(f"[BREAKOUT-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    return fired


def _loop():
    logger.info(f"[BREAKOUT-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[BREAKOUT-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from breakout_engine import BreakoutParams
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "symbols": _symbols(), "params": BreakoutParams.from_env().__dict__}


def start_breakout_scanner():
    global _started
    if not _ENABLED:
        logger.info("[BREAKOUT-SCANNER] BREAKOUT_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="breakout-scanner").start()
