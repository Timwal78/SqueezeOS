"""
SML Gamma Pin Scanner — real Tradier options-chain constraint scanner.
=====================================================================
Every GAMMA_PIN_SCAN_INTERVAL seconds (default 300), pulls a real Tradier
options chain per symbol via tradier_api.get_option_chain_schwab_format(),
reuses gamma_flow_engine.calculate_gex_profile() (the same GEX math already
live in production via core/oracle_engine.py's gamma-flow read) and
gamma_flow_engine.detect_pin_risk() (a synchronous restatement of
GammaFlowEngine._check_pin_risk()'s real thresholds — 0-2 DTE + spot within
0.5% of the max-OI strike). A resolved BUY/SELL routes to
iam_executor.execute_async() with system tag "SML_GAMMA_PIN" — the full
safety stack applies there (paper mode, stop-losses, daily-loss breaker,
primary-system gate). This module places no orders itself.

Chain-based, not bar-based — works out of the box on a Tradier-only
deployment (no Polygon/Alpaca dependency), unlike ORB/DRUCK's intraday
feeds. Idles honestly and logs why when TRADIER_API_KEY is unset.

NO BACKTEST EVIDENCE EXISTS FOR THIS CONSTRAINT, and none is added here.
Unlike Breakout/SR-Matrix (which shipped with a real historical backtest
before going live), a gamma-pin backtest would need historical per-day
options chains (open interest + gamma by strike, across time) to replay
this exact condition — no such archive exists anywhere in this codebase,
Tradier only ever serves the CURRENT live chain (not history), and the
Robinhood MCP channel used to backtest DRUCK/CIE/Breakout only provides
OHLCV bars, not historical option chains. Rather than fabricate a backtest
or skip the caveat, this ships the same way CIE shipped its dark-pool axis:
disclosed as unmeasured, not claimed profitable or unprofitable. Do not set
IAM_PRIMARY_SYSTEM=SML_GAMMA_PIN or represent this as a proven signal.

Direction is a disclosed proxy (sign of max_oi_strike - spot), not a
validated edge — see gamma_flow_engine.detect_pin_risk()'s docstring.

This build does NOT flip anything live by itself. IAM_PAPER_MODE=true is
still the default, and iam_executor's IAM_PRIMARY_SYSTEM gate is untouched —
nobody has added SML_GAMMA_PIN to it.

Env vars:
  GAMMA_PIN_SCAN_ENABLED     = true   — master switch
  GAMMA_PIN_SCAN_INTERVAL    = 300    — seconds between passes
  GAMMA_PIN_SCAN_SYMBOLS     = ""     — comma override; empty -> dynamic
                                        universe (IAM_SYMBOL_ALLOWLIST ->
                                        market-scanner candidates -> quoted
                                        universe; never hardcoded)
  GAMMA_PIN_SCAN_TOP_N       = 10     — dynamic-universe size cap
  GAMMA_PIN_MAX_EXPIRATIONS  = 8      — expirations pulled per chain fetch
                                        (matches tradier_api's own default)
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("GAMMA-PIN-SCANNER")

_ENABLED         = os.environ.get("GAMMA_PIN_SCAN_ENABLED", "true").strip().lower() == "true"
_INTERVAL        = int(float(os.environ.get("GAMMA_PIN_SCAN_INTERVAL", "300")))
_MAX_EXPIRATIONS = int(os.environ.get("GAMMA_PIN_MAX_EXPIRATIONS", "8"))
_SCAN_TOP_N      = int(os.environ.get("GAMMA_PIN_SCAN_TOP_N", "10"))

_started = False
_lock = threading.Lock()
_last_fired: dict = {}
_status = {
    "running": False,
    "last_pass_ts": None,
    "signals_fired_total": 0,
    "last_signal": None,
    "chain_data_available": None,
    "last_error": None,
}


def _symbols() -> list:
    """
    Universe resolution — DYNAMIC by default, never a hardcoded list
    (operator directive 2026-07-19 + Prime Directive #1), same resolution
    order as druck_scanner.py/orb_scanner.py/imo_scanner.py:
      1. GAMMA_PIN_SCAN_SYMBOLS env (explicit operator override)
      2. IAM_SYMBOL_ALLOWLIST env (if the operator restricted execution)
      3. Live market-scanner candidates (state.scan_results, top N)
      4. Live quoted universe (state.quotes)
    Empty when no live universe exists yet — the pass skips honestly.
    """
    raw = os.environ.get("GAMMA_PIN_SCAN_SYMBOLS", "").strip() or os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip()
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
    import tradier_api
    from gamma_flow_engine import calculate_gex_profile, detect_pin_risk

    fired = 0
    got_data = False
    syms = _symbols()
    if not syms:
        logger.info("[GAMMA-PIN-SCANNER] no live universe yet (market scanner warming up) — pass skipped")
    for sym in syms:
        try:
            raw_chain = tradier_api.get_option_chain_schwab_format(sym, max_expirations=_MAX_EXPIRATIONS)
            if not raw_chain:
                logger.info(f"[GAMMA-PIN-SCANNER] {sym}: no Tradier option chain "
                            f"(TRADIER_API_KEY required) — skipping")
                continue
            got_data = True

            spot = float(raw_chain.get("underlyingPrice") or 0.0)
            if spot <= 0:
                continue

            profile = calculate_gex_profile(raw_chain, spot, sym)
            if not profile:
                continue

            try:
                import core.signal_history as signal_history
                signal_history.record(sym, "GAMMA_PIN_SCAN", {
                    "profile_shape": profile.profile_shape,
                    "zero_gamma_line": profile.zero_gamma_line,
                    "max_oi_strike": profile.max_oi_strike,
                })
            except Exception:
                pass

            pin = detect_pin_risk(raw_chain, profile)
            if not pin or not pin.get("direction"):
                continue

            action = pin["direction"]
            key = f'{pin["expiry"]}|{pin["max_oi_strike"]}|{action}'
            with _lock:
                if _last_fired.get(sym) == key:
                    continue
                _last_fired[sym] = key

            conf = 90.0  # matches _check_pin_risk()'s existing urgency_score=90.0, not a new invented number
            resolution = {
                "action":                action,
                "system":                "SML_GAMMA_PIN",
                "rationale":             f"Gamma pin risk: {pin['dte']}DTE expiry {pin['expiry']}, "
                                         f"spot ${spot:.2f} within 0.5% of max-OI strike "
                                         f"${pin['max_oi_strike']:.2f} — dealer-hedging-flow direction "
                                         f"proxy, not backtested (no historical options-chain data "
                                         f"source exists to measure this constraint)",
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
                "symbol": sym, "action": action, "expiry": pin["expiry"], "dte": pin["dte"],
                "max_oi_strike": pin["max_oi_strike"], "confidence": conf, "ts": time.time(),
            }
            logger.info(f"[GAMMA-PIN-SCANNER] ⚡ {sym} {action} {pin['dte']}DTE "
                        f"pin@{pin['max_oi_strike']} → executor")
        except Exception as e:
            logger.warning(f"[GAMMA-PIN-SCANNER] {sym}: {e}")
        time.sleep(0.5)

    _status["last_pass_ts"] = time.time()
    _status["chain_data_available"] = got_data
    return fired


def _loop():
    logger.info(f"[GAMMA-PIN-SCANNER] Online — {_symbols()} every {_INTERVAL}s (live Tradier chains, no backtest evidence yet)")
    while True:
        try:
            scan_once()
        except Exception as e:
            _status["last_error"] = str(e)
            logger.error(f"[GAMMA-PIN-SCANNER] pass failed: {e}")
        time.sleep(_INTERVAL)


def status() -> dict:
    return {**_status, "enabled": _ENABLED, "running": _started,
            "interval_s": _INTERVAL, "symbols": _symbols(),
            "max_expirations": _MAX_EXPIRATIONS}


def start_gamma_pin_scanner():
    global _started
    if not _ENABLED:
        logger.info("[GAMMA-PIN-SCANNER] GAMMA_PIN_SCAN_ENABLED=false — not starting")
        return
    if _started:
        return
    _started = True
    _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="gamma-pin-scanner").start()
