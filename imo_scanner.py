"""
SML-IMO Background Scanner — pure Python signal loop, no TradingView required.
==============================================================================
Every IMO_SCAN_INTERVAL seconds, pulls real daily bars for the configured
symbols via DataManager (Tradier → Alpaca → Polygon priority) and runs
imo_engine on them. A NEW signal on the latest bar is routed to
iam_executor.execute_async() — where the full safety stack applies (arm
switch, paper mode, symbol allowlist, confidence gate, daily caps, hard
stops, daily-loss breaker). This module makes no orders itself.

Env vars:
  IMO_SCAN_ENABLED   = true    — master switch for this loop
  IMO_SCAN_INTERVAL  = 300     — seconds between passes
  IMO_SCAN_SYMBOLS   = ""      — comma list; empty → IAM_SYMBOL_ALLOWLIST if
                                 set, else SPY,IWM,QQQ,NVDA,HOOD (the symbols
                                 that earned an edge in
                                 docs/ENGINE_SCOREBOARD_2026-07-17.md)
  IMO_MIN_BARS       = 160     — refuse to signal on thinner history
  IMO_BARS_LIMIT     = 420     — daily bars requested per symbol

De-dup: a signal is fired once per (symbol, bar, action) — rescanning the
same still-open daily bar never re-fires. If bars are unavailable the
symbol is skipped with a real log line, never guessed (Prime Directive).
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("IMO-SCANNER")

_ENABLED   = os.environ.get("IMO_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL  = int(float(os.environ.get("IMO_SCAN_INTERVAL", "300")))
_MIN_BARS  = int(os.environ.get("IMO_MIN_BARS", "160"))
_BARS_LIMIT = int(os.environ.get("IMO_BARS_LIMIT", "420"))

_DEFAULT_SYMBOLS = "SPY,IWM,QQQ,NVDA,HOOD"  # scoreboard-backed default

_started = False
_lock = threading.Lock()
_last_fired: dict = {}   # symbol → "barkey|action"
_status = {
    "running": False,
    "last_pass_ts": None,
    "last_pass_symbols": 0,
    "signals_fired_total": 0,
    "last_signal": None,
    "last_error": None,
}


def _symbols() -> list:
    raw = os.environ.get("IMO_SCAN_SYMBOLS", "").strip()
    if not raw:
        raw = os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip() or _DEFAULT_SYMBOLS
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _confidence(state: dict) -> float:
    """Map oscillator state → executor confidence. Base clears the default
    IAM_MIN_CONFIDENCE=70 gate; regime/volume alignment adds conviction."""
    conf = 75.0
    if state.get("regime") == "TREND":
        conf += 10.0
    if state.get("rel_volume", 0) >= 1.5:
        conf += 5.0
    if state.get("vol_accelerating"):
        conf += 2.0
    return min(conf, 92.0)


def scan_once() -> int:
    """One pass over the symbol list. Returns number of signals fired."""
    from core.legacy import get_service
    from imo_engine import analyze, ImoParams

    dm = get_service("dm")
    if not dm:
        _status["last_error"] = "DataManager not initialized"
        return 0

    p = ImoParams.from_env()
    fired = 0
    syms = _symbols()
    for sym in syms:
        try:
            bars = dm.get_bars(sym, "1D", _BARS_LIMIT) or []
            if len(bars) < _MIN_BARS:
                logger.info(f"[IMO-SCANNER] {sym}: only {len(bars)} real bars (<{_MIN_BARS}) — skipping")
                continue
            result = analyze(sym, bars, p)
            if result.get("status") != "success":
                continue

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "IMO_SCAN", {
                    "oscillator": result["oscillator"],
                    "regime":     result["regime"],
                    "z_score":    result["z_score"],
                    "signal":     result.get("signal"),
                    "detail":     result.get("signal_detail"),
                })
            except Exception:
                pass

            action = result.get("signal")
            if action not in ("BUY", "SELL"):
                continue

            key = f"{result.get('bar_key')}|{action}"
            with _lock:
                if _last_fired.get(sym) == key:
                    continue  # already fired for this bar
                _last_fired[sym] = key

            conf = _confidence(result)
            resolution = {
                "action":                action,
                "system":                "SML_IMO",
                "rationale":             f"SML-IMO {result.get('signal_detail')} | osc={result['oscillator']} "
                                         f"z={result['z_score']} regime={result['regime']} relVol={result['rel_volume']}x",
                "vehicle":               sym,
                "resolution_confidence": conf,
                "invalidation":          "",
                "review_trigger":        "",
            }
            from iam_executor import execute_async
            execute_async(sym, resolution, "NEAR_TERM", conf, float(result.get("price") or 0.0))
            fired += 1
            _status["signals_fired_total"] += 1
            _status["last_signal"] = {
                "symbol": sym, "action": action,
                "detail": result.get("signal_detail"),
                "confidence": conf, "ts": time.time(),
            }
            logger.info(f"[IMO-SCANNER] 🎯 {sym} {action} ({result.get('signal_detail')}) conf={conf:.0f}% → executor")
        except Exception as e:
            logger.warning(f"[IMO-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    _status["last_pass_symbols"] = len(syms)
    _status["last_error"] = None
    return fired


def _loop():
    logger.info(f"[IMO-SCANNER] Online — {_symbols()} every {_INTERVAL}s (pure Python, no TradingView)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[IMO-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    from imo_engine import ImoParams
    return {
        **_status,
        "enabled": _ENABLED,
        "running": _started,
        "interval_s": _INTERVAL,
        "symbols": _symbols(),
        "params": ImoParams.from_env().__dict__,
    }


def start_imo_scanner():
    global _started
    if not _ENABLED:
        logger.info("[IMO-SCANNER] IMO_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    t = threading.Thread(target=_loop, daemon=True, name="imo-scanner")
    t.start()
