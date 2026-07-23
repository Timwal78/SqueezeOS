"""
CIE Scanner — Daily/Weekly Python loop, no TradingView required.
=================================================================
Every CIE_SCAN_INTERVAL seconds (default 900), pulls real Daily bars via
DataManager for the dynamic universe (or aggregates them into Weekly bars
when CIE_TIMEFRAME=1W), runs cycle_intelligence_engine.analyze() with real
SEC FTD/threshold-list data from core.ftd_data, and routes CIE_FIRE signals
with a resolved direction to iam_executor.execute_async() tagged system
"SML_CIE" — the full safety stack applies there. This module places no
orders itself.

Data reality (documented, not papered over):
  * Settlement layer  — REAL SEC FTD + Reg SHO threshold-list data
    (core/ftd_data.py, same feed that powers /api/ftd). Cost-to-borrow has
    no real data source in this codebase, so that sub-component stays at 0.
  * Dark-pool layer   — NEVER fed here. No real dark-pool print feed exists
    anywhere in this codebase. Stays at 0.0/"dark_flow_unavailable" — future
    work, not simulated.
  * Fractal layer     — self-mines a signature library from the SAME real
    Daily/Weekly bars pulled per symbol (see cycle_intelligence_engine.analyze()).
  * Meme-cycle layer  — real volume ratio; "iv_atm" is a realized ATR%
    volatility proxy, NOT options-chain implied volatility (no per-bar
    options-chain pull is wired here).

Because dark-pool never fires, CIE_FIRE in production requires settlement
+ fractal + meme axes to converge (2 of the remaining 3 at >=0.5 plus
composite_z >= 3.0) — a real, if narrower, bar than the 4-axis synthetic
test scenario. No backtest evidence exists for this narrower live
configuration until tests/backtest_cie.py is run and its results are
written up — do not claim profitability before that.

Env vars:
  CIE_SCAN_ENABLED   = true      — master switch
  CIE_SCAN_INTERVAL  = 900       — seconds between passes (Daily/Weekly data
                                   changes slowly; no need to poll like ORB's 120s)
  CIE_SCAN_SYMBOLS   = ""        — comma override; empty -> dynamic universe
                                   (IAM_SYMBOL_ALLOWLIST -> market-scanner
                                   candidates -> quoted universe; never hardcoded)
  CIE_SCAN_TOP_N     = 10        — dynamic-universe size cap
  CIE_TIMEFRAME      = 1D        — "1D" (Daily) or "1W" (Weekly, aggregated
                                   client-side from Daily bars — DataManager
                                   has no native weekly timeframe)
  CIE_BARS_LIMIT     = 300       — Daily bars requested per symbol (Weekly
                                   aggregates from this same pull)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime

logger = logging.getLogger("CIE-SCANNER")

_ENABLED = os.environ.get("CIE_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL = int(float(os.environ.get("CIE_SCAN_INTERVAL", "900")))
_TIMEFRAME = os.environ.get("CIE_TIMEFRAME", "1D").strip().upper()
_BARS_LIMIT = int(os.environ.get("CIE_BARS_LIMIT", "300"))
_SCAN_TOP_N = int(os.environ.get("CIE_SCAN_TOP_N", "10"))

_started = False
_lock = threading.Lock()
_last_fired: dict = {}
_status = {
    "running": False,
    "last_pass_ts": None,
    "signals_fired_total": 0,
    "last_signal": None,
    "data_available": None,
    "last_error": None,
}


def _symbols() -> list:
    """DYNAMIC universe resolution — same convention as orb_scanner/druck_scanner
    (operator directive 2026-07-19 + Prime Directive #1): never a hardcoded list.
      1. CIE_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("CIE_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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


def _aggregate_weekly(daily_bars: list) -> list:
    """Group real Daily bars into Weekly bars (ISO week). DataManager has no
    native weekly timeframe, so this aggregates client-side from real Daily
    data — never fabricates a bar."""
    weeks: dict = {}
    order: list = []
    for b in daily_bars:
        raw_date = b.get("date") or b.get("t")
        if not raw_date:
            continue
        try:
            d = datetime.fromisoformat(str(raw_date)[:10]).date()
        except ValueError:
            continue
        key = (d.isocalendar()[0], d.isocalendar()[1])
        if key not in weeks:
            weeks[key] = {"date": d.isoformat(), "o": b.get("o", b.get("open")),
                          "h": b.get("h", b.get("high")), "l": b.get("l", b.get("low")),
                          "c": b.get("c", b.get("close")), "v": 0.0}
            order.append(key)
        wk = weeks[key]
        h = b.get("h", b.get("high"))
        l = b.get("l", b.get("low"))
        if h is not None and (wk["h"] is None or h > wk["h"]):
            wk["h"] = h
        if l is not None and (wk["l"] is None or l < wk["l"]):
            wk["l"] = l
        wk["c"] = b.get("c", b.get("close"))
        wk["date"] = d.isoformat()
        wk["v"] += float(b.get("v", b.get("volume", 0)) or 0.0)
    return [weeks[k] for k in order]


def scan_once() -> int:
    from core.legacy import get_service
    from cycle_intelligence_engine import analyze
    from core.ftd_data import get_store

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    store = get_store()
    fired = 0
    got_data = False
    syms = _symbols()
    if not syms:
        logger.info("[CIE-SCANNER] no live universe yet (market scanner warming up) — pass skipped")

    for sym in syms:
        try:
            daily = dm.get_bars(sym, "1D", _BARS_LIMIT) or []
            if not daily:
                logger.info(f"[CIE-SCANNER] {sym}: no daily bars from any provider — skipping")
                continue
            bars = _aggregate_weekly(daily) if _TIMEFRAME == "1W" else daily
            if len(bars) < 30:
                logger.info(f"[CIE-SCANNER] {sym}: only {len(bars)} {_TIMEFRAME} bars — too few, skipping")
                continue
            got_data = True

            recs = store.series_for(sym, limit=180)
            # FTDDataStore has no shares-outstanding/float feed anywhere in this
            # codebase (confirmed by search), so the engine's designed
            # fail_shares/float_shares ratio can't be computed for real. Rather
            # than fabricate a float number, derive a real, self-referential
            # severity proxy instead: float_shares_proxy is scaled so that a
            # fail count AT this symbol's own real 180-day peak lands exactly
            # on the engine's "high" threshold (sett_ftd_high_pct) — every
            # other reading scales proportionally below that. 100% real fail
            # counts in, no invented float data.
            if recs:
                from cycle_intelligence_engine import CIE_CONFIG as _CIECFG
                window_max = max(r.fail_shares for r in recs) or 1
                float_proxy = max(1, round(window_max / _CIECFG["sett_ftd_high_pct"]))
                ftd_recs = [(r.settlement_date, r.fail_shares, float_proxy) for r in recs]
            else:
                ftd_recs = []
            on_list = store.is_on_threshold_list(sym)
            since = store.threshold_entry_date(sym) if on_list else None

            result = analyze(sym, bars, ftd_records=ftd_recs, on_threshold_list=on_list,
                              threshold_since=since, today=date.today())
            if result.get("status") != "success":
                continue

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "CIE_SCAN", {
                    "state": result.get("state"), "composite_z": result.get("composite_z"),
                    "signal": result.get("signal"), "timeframe": _TIMEFRAME,
                })
            except Exception:
                pass

            action = result.get("signal")
            if action not in ("BUY", "SELL"):
                continue
            key = f"{result.get('bar_key')}|{action}|{_TIMEFRAME}"
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            conf = min(80.0 + (5.0 if result.get("composite_z", 0) >= 4.0 else 0.0), 90.0)
            resolution = {
                "action": action,
                "system": "SML_CIE",
                "rationale": f"CIE {result.get('state')} on {_TIMEFRAME}: composite_z={result.get('composite_z')} "
                             f"components={result.get('components')}",
                "vehicle": sym,
                "resolution_confidence": conf,
                "invalidation": "",
                "review_trigger": "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "NEAR_TERM", conf, float(result.get("price") or 0.0))
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {"symbol": sym, "action": action,
                                      "state": result.get("state"),
                                      "composite_z": result.get("composite_z"),
                                      "confidence": conf, "ts": time.time()}
            logger.info(f"[CIE-SCANNER] ⚡ {sym} {action} state={result.get('state')} "
                        f"z={result.get('composite_z')} conf={conf:.0f}% -> executor")
        except Exception as e:
            logger.warning(f"[CIE-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    _status["data_available"] = got_data
    return fired


def _loop():
    logger.info(f"[CIE-SCANNER] Online — {_symbols()} every {_INTERVAL}s on {_TIMEFRAME} bars (pure Python)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[CIE-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "timeframe": _TIMEFRAME,
            "bars_limit": _BARS_LIMIT, "symbols": _symbols()}


def start_cie_scanner():
    global _started
    if not _ENABLED:
        logger.info("[CIE-SCANNER] CIE_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="cie-scanner").start()
