"""
SML-DRUCK Scanner — intraday Python loop, no TradingView required.
=====================================================================
Every DRUCK_SCAN_INTERVAL seconds (default 300), pulls real bars via
DataManager and runs druck_engine. A NEW signal on the latest bar routes to
iam_executor.execute_async() with system tag "SML_DRUCK" — the full safety
stack applies there (paper mode, stop-losses, daily-loss breaker, primary-
system gate). This module places no orders itself.

Data reality (documented, not papered over): DataManager's intraday bars
come from Polygon or Alpaca (Tradier path is daily-only). On a Tradier-only
deployment this scanner finds no intraday bars and logs exactly that every
pass — it never invents bars. The TradingView webhook path in the Pine twin
(system "SML_DRUCK") works regardless — same dual-path pattern as ORB/IMO.

DRUCK-LB is a multi-bar SWING strategy by design (unlike ORB's one-shot
opening-range breakout) — a fired signal is a fresh entry condition on that
bar, not a same-bar-only event, so the per-bar dedup key below is keyed on
bar timestamp + action, same convention as orb_scanner.py.

Env vars:
  DRUCK_SCAN_ENABLED   = true       — master switch
  DRUCK_SCAN_INTERVAL  = 300        — seconds between passes
  DRUCK_SCAN_SYMBOLS   = ""         — comma override; empty → dynamic universe
                                      (IAM_SYMBOL_ALLOWLIST → market-scanner
                                      candidates → quoted universe; never hardcoded)
  DRUCK_SCAN_TOP_N     = 10         — dynamic-universe size cap
  DRUCK_TIMEFRAME      = 15MIN      — bar size fed to dm.get_bars (matches the
                                      Pine script's typical base-chart resolution
                                      paired with its 2H default HTF filter)
  DRUCK_BARS_LIMIT     = 500        — bars requested per symbol (DRUCK's
                                      atr_pctile_len=100 default needs real
                                      history, not a cold-start window)
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("DRUCK-SCANNER")

_ENABLED    = os.environ.get("DRUCK_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("DRUCK_SCAN_INTERVAL", "300")))
_TIMEFRAME  = os.environ.get("DRUCK_TIMEFRAME", "15MIN").strip()
_BARS_LIMIT = int(os.environ.get("DRUCK_BARS_LIMIT", "500"))

_SCAN_TOP_N = int(os.environ.get("DRUCK_SCAN_TOP_N", "10"))

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
    Universe resolution — DYNAMIC by default, never a hardcoded list
    (operator directive 2026-07-19 + Prime Directive #1), same resolution
    order as orb_scanner.py/imo_scanner.py:
      1. DRUCK_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("DRUCK_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    from druck_engine import analyze, DruckParams

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = DruckParams.from_env()
    fired = 0
    got_data = False
    syms = _symbols()
    if not syms:
        logger.info("[DRUCK-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars:
                logger.info(f"[DRUCK-SCANNER] {sym}: no {_TIMEFRAME} bars from any provider "
                            f"(Tradier is daily-only — needs Polygon or Alpaca key) — skipping")
                continue
            got_data = True
            result = analyze(sym, bars, p)
            if result.get("status") != "success":
                continue

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "DRUCK_SCAN", {
                    "regime": result.get("regime"), "adx": result.get("adx"),
                    "atr_pctile": result.get("atr_pctile"), "signal": result.get("signal"),
                })
            except Exception:
                pass

            action = result.get("signal")
            if action not in ("BUY", "SELL"):
                continue
            bars_used = len(bars)
            bar_key = str(bars[-1].get("date") or bars[-1].get("t") or bars[-1].get("timestamp") or bars_used)
            key = f"{bar_key}|{action}"
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            jugular = bool(result.get("jugular"))
            conf = min(80.0 + (10.0 if jugular else 0.0), 90.0)
            resolution = {
                "action":                action,
                "system":                "SML_DRUCK",
                "rationale":             f"DRUCK-LB {action}: regime={result.get('regime')} "
                                         f"adx={result.get('adx')} atr_pctile={result.get('atr_pctile')}"
                                         f"{' [JUGULAR]' if jugular else ''}",
                "vehicle":               sym,
                "resolution_confidence": conf,
                "invalidation":          "",
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "IMMEDIATE", conf, float(result.get("price") or 0.0))
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {"symbol": sym, "action": action,
                                      "regime": result.get("regime"), "jugular": jugular,
                                      "confidence": conf, "ts": time.time()}
            logger.info(f"[DRUCK-SCANNER] ⚡ {sym} {action} regime={result.get('regime')} "
                        f"jugular={jugular} conf={conf:.0f}% → executor")
        except Exception as e:
            logger.warning(f"[DRUCK-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    _status["intraday_data_available"] = got_data
    return fired


def _loop():
    logger.info(f"[DRUCK-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[DRUCK-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from druck_engine import DruckParams
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "symbols": _symbols(), "params": DruckParams.from_env().__dict__}


def start_druck_scanner():
    global _started
    if not _ENABLED:
        logger.info("[DRUCK-SCANNER] DRUCK_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="druck-scanner").start()
