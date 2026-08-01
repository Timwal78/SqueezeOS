"""
SML Market Maker Intelligence v4 Scanner — intraday Python loop, no
TradingView required. Same pattern as druck_scanner.py.

Every MM_INTEL_SCAN_INTERVAL seconds (default 300), pulls real intraday bars
via DataManager and runs mm_intel_engine. A NEW live_signal event on the
latest bar routes to iam_executor.execute_async() with system tag
"SML_MM_V4" -- the full safety stack applies there (paper mode,
stop-losses, daily-loss breaker, primary-system gate). This module places
no orders itself.

Live-signal mapping (deliberately narrower than the full backtest state
machine -- same reasoning class as breakout_engine.py's ENTER-only design,
see that module's docstring):
  - "BUY"  -> BUY  (opens a long thesis)
  - "SELL" -> SELL (opens a bearish/put thesis -- iam_executor's SELL action
                    already has this compound "close long + open a fresh
                    put" meaning for every other engine here)
  - "EXIT_STOP"/"EXIT_RESOLVED" while exit_direction == 1 (closing a LONG)
        -> SELL (closes the long, matching _close_equity_position, same
           "exits never blocked" convention as every other engine)
  - "EXIT_STOP"/"EXIT_RESOLVED" while exit_direction == -1 (closing a
        SHORT/put thesis) -> NO live signal. iam_executor has no "close an
        existing put" mechanism (same gap breakout_engine.py's docstring
        already documents) -- inventing one here would add an un-backtested
        action. Downside on live LONG positions still comes from
        iam_executor's own real stop-loss order (IAM_STOP_LOSS_PCT).

Backtest verdict (docs/MM_INTEL_BACKTEST_2026-07-25.md): PROMISING, not
proven -- 4 of 5 symbols profit factor > 1.0 on real 5-minute bars, but NO
options/theta modeled despite this being a labeled 0DTE tool. This scanner
feeds the exact same paper-first safety stack as every other engine --
IAM_PAPER_MODE=true is still the default, and nobody has added
SML_MM_V4 to IAM_PRIMARY_SYSTEM. That is a separate, explicit, future
decision -- not made here.

Data reality (documented, not papered over): DataManager's intraday bars
come from Polygon or Alpaca (Tradier path is daily-only). On a Tradier-only
deployment this scanner finds no intraday bars and logs exactly that every
pass -- it never invents bars, same as DRUCK/ORB.

Env vars:
  MM_INTEL_SCAN_ENABLED   = true   -- master switch
  MM_INTEL_SCAN_INTERVAL  = 300    -- seconds between passes
  MM_INTEL_SCAN_SYMBOLS   = ""     -- comma override; empty -> dynamic
                                     universe (IAM_SYMBOL_ALLOWLIST ->
                                     market-scanner candidates -> quoted
                                     universe; never hardcoded)
  MM_INTEL_SCAN_TOP_N     = 10     -- dynamic-universe size cap
  MM_INTEL_TIMEFRAME      = 5MIN   -- bar size fed to dm.get_bars, matches
                                     the real backtest's granularity
  MM_INTEL_BARS_LIMIT     = 300    -- bars requested per symbol (covers the
                                     engine's largest rolling window,
                                     inv_lookback=75, with real buffer)
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("MM-INTEL-SCANNER")

_ENABLED    = os.environ.get("MM_INTEL_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("MM_INTEL_SCAN_INTERVAL", "300")))
_TIMEFRAME  = os.environ.get("MM_INTEL_TIMEFRAME", "5MIN").strip()
_BARS_LIMIT = int(os.environ.get("MM_INTEL_BARS_LIMIT", "300"))

# 15 (raised modestly from 10, 2026-08-01) -- deliberately NOT widened as
# aggressively as the Tradier-daily scanners (breakout/sr_matrix/sr_zone_
# pattern/sovereign_squeeze/quad_score, now 25 each). This engine's 5MIN
# bars route through DataManager.get_bars() -> Polygon FIRST (data_providers.py),
# which has a much tighter shared global limiter (PolygonRateGuard, 12s/call
# = 5/min, real free-tier ceiling) than Tradier's 1.05s/call -- and that
# quota is also shared with the market-scanner's own Polygon grouped-daily
# discovery call. 15*12s=180s worst case still comfortably fits the 300s
# SCAN_INTERVAL, without eating deeply into a much scarcer shared budget.
_SCAN_TOP_N = int(os.environ.get("MM_INTEL_SCAN_TOP_N", "15"))

_started = False
_lock = threading.Lock()
_last_fired: dict = {}
_status = {
    "running": False,
    "last_pass_ts": None,
    "signals_fired_total": 0,
    "last_signal": None,
    "intraday_data_available": None,
    "last_error": None,
}


def _symbols() -> list:
    """
    Universe resolution -- DYNAMIC by default, never a hardcoded list
    (operator directive 2026-07-19 + Prime Directive #1), same resolution
    order as druck_scanner.py/orb_scanner.py/imo_scanner.py:
      1. MM_INTEL_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet -- the pass skips honestly.
    """
    raw = os.environ.get("MM_INTEL_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    from mm_intel_engine import analyze, MMIntelParams

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = MMIntelParams.from_env()
    fired = 0
    got_data = False
    syms = _symbols()
    if not syms:
        logger.info("[MM-INTEL-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars:
                logger.info(f"[MM-INTEL-SCANNER] {sym}: no {_TIMEFRAME} bars from any provider "
                            f"(Tradier is daily-only — needs Polygon or Alpaca key) — skipping")
                continue
            got_data = True
            result = analyze(sym, bars, p)
            if result.get("status") != "success":
                continue

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "MM_INTEL_SCAN", {
                    "inv_z": result.get("inv_z"), "gamma_pressure": result.get("gamma_pressure"),
                    "signal": result.get("signal"),
                })
            except Exception:
                pass

            raw_signal = result.get("signal")
            action = None
            if raw_signal in ("BUY", "SELL"):
                action = raw_signal
            elif raw_signal in ("EXIT_STOP", "EXIT_RESOLVED") and result.get("exit_direction") == 1:
                action = "SELL"
            if not action:
                continue

            bars_used = len(bars)
            bar_key = str(bars[-1].get("date") or bars[-1].get("t") or bars[-1].get("timestamp") or bars_used)
            key = f"{bar_key}|{raw_signal}"
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            conf = float(result.get("confidence") or 0.0)
            resolution = {
                "action":                action,
                "system":                "SML_MM_V4",  # IAM_PRIMARY_SYSTEM name (was SML_MM_INTEL)
                "rationale":             f"MM Intel v4 {raw_signal}: inv_z={result.get('inv_z'):.2f} "
                                         f"gamma_pressure={result.get('gamma_pressure'):.2f} "
                                         f"conf={conf:.0f}% -- underlying %-move proxy only, "
                                         f"no options/theta modeled (see docs/MM_INTEL_BACKTEST_2026-07-25.md)",
                "vehicle":               sym,
                "resolution_confidence": conf,
                "invalidation":          str(result.get("active_invalidation") or ""),
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "IMMEDIATE", conf, float(result.get("price") or 0.0))
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {"symbol": sym, "action": action, "raw_signal": raw_signal,
                                      "inv_z": result.get("inv_z"), "confidence": conf, "ts": time.time()}
            logger.info(f"[MM-INTEL-SCANNER] ⚡ {sym} {action} (raw={raw_signal}) "
                        f"inv_z={result.get('inv_z'):.2f} conf={conf:.0f}% → executor")
        except Exception as e:
            logger.warning(f"[MM-INTEL-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    _status["intraday_data_available"] = got_data
    return fired


def _loop():
    logger.info(f"[MM-INTEL-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[MM-INTEL-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from mm_intel_engine import MMIntelParams
    p = MMIntelParams.from_env()
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "symbols": _symbols(),
            "params": {"z_critical": p.z_critical, "gamma_thresh": p.gamma_thresh, "sensitivity": p.sensitivity}}


def start_mm_intel_scanner():
    global _started
    if not _ENABLED:
        logger.info("[MM-INTEL-SCANNER] MM_INTEL_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="mm-intel-scanner").start()
