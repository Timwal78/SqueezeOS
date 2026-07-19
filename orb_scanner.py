"""
ORB v6 BEASTMODE Scanner — intraday Python loop, no TradingView required.
=========================================================================
Every ORB_SCAN_INTERVAL seconds (default 120) during scanning, pulls real
intraday bars via DataManager and runs orb_engine. A NEW signal on the
latest bar routes to iam_executor.execute_async() with system tag
"SML_ORB_MM" — the full safety stack applies there. This module places no
orders itself.

Data reality (documented, not papered over): DataManager's intraday bars
come from Polygon or Alpaca (Tradier path is daily-only). On a
Tradier-only deployment this scanner finds no intraday bars and logs
exactly that every pass — it never invents bars. The TradingView webhook
path in the Pine twin works regardless.

Env vars:
  ORB_SCAN_ENABLED   = true      — master switch
  ORB_SCAN_INTERVAL  = 120       — seconds between passes
  ORB_SCAN_SYMBOLS   = ""        — comma override; empty → dynamic universe
                                   (IAM_SYMBOL_ALLOWLIST → market-scanner
                                   candidates → quoted universe; never hardcoded)
  ORB_SCAN_TOP_N     = 10        — dynamic-universe size cap
  ORB_TIMEFRAME      = 5MIN      — intraday bar size fed to dm.get_bars
  ORB_BARS_LIMIT     = 400       — bars requested per symbol
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("ORB-SCANNER")

_ENABLED    = os.environ.get("ORB_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL   = int(float(os.environ.get("ORB_SCAN_INTERVAL", "120")))
_TIMEFRAME  = os.environ.get("ORB_TIMEFRAME", "5MIN").strip()
_BARS_LIMIT = int(os.environ.get("ORB_BARS_LIMIT", "400"))

_SCAN_TOP_N = int(os.environ.get("ORB_SCAN_TOP_N", "10"))

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
    (operator directive 2026-07-19 + Prime Directive #1):
      1. ORB_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("ORB_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    from orb_engine import analyze, OrbParams

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = OrbParams.from_env()
    fired = 0
    got_data = False
    syms = _symbols()
    if not syms:
        logger.info("[ORB-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            bars = dm.get_bars(sym, _TIMEFRAME, _BARS_LIMIT) or []
            if not bars:
                logger.info(f"[ORB-SCANNER] {sym}: no intraday {_TIMEFRAME} bars from any provider "
                            f"(Tradier is daily-only — needs Polygon or Alpaca key) — skipping")
                continue
            got_data = True
            result = analyze(sym, bars, p)
            if result.get("status") != "success":
                continue

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "ORB_SCAN", {
                    "or_high": result.get("or_high"), "or_low": result.get("or_low"),
                    "inventory_z": result.get("inventory_z"),
                    "signal": result.get("signal"),
                })
            except Exception:
                pass

            action = result.get("signal")
            if action not in ("BUY", "SELL"):
                continue
            key = f"{result.get('bar_key')}|{action}"
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            z = abs(result.get("inventory_z") or 0.0)
            conf = min(80.0 + (5.0 if z >= 2.0 else 0.0), 90.0)
            resolution = {
                "action":                action,
                "system":                "SML_ORB_MM",
                "rationale":             f"ORB BEASTMODE {action}: OR breakout with trapped MM inventory "
                                         f"z={result.get('inventory_z')} (OR {result.get('or_low')}–{result.get('or_high')})",
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
                                      "inventory_z": result.get("inventory_z"),
                                      "confidence": conf, "ts": time.time()}
            logger.info(f"[ORB-SCANNER] ⚡ {sym} {action} z={result.get('inventory_z')} conf={conf:.0f}% → executor")
        except Exception as e:
            logger.warning(f"[ORB-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    _status["intraday_data_available"] = got_data
    return fired


def _loop():
    logger.info(f"[ORB-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[ORB-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from orb_engine import OrbParams
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "symbols": _symbols(), "params": OrbParams.from_env().__dict__}


def start_orb_scanner():
    global _started
    if not _ENABLED:
        logger.info("[ORB-SCANNER] ORB_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="orb-scanner").start()
