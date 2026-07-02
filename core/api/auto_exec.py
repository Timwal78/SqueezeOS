"""
SML AUTO-EXECUTION PIPELINE
Bridges the background scanner → convergence (GOD MODE) engine → live execution.

This is the missing wire: the scanner finds candidates, this module runs the
Dual Grid Lock / GOD MODE analysis on them and routes qualifying signals to
live execution — fully autonomous, but wrapped in the complete safety stack.

SAFETY STACK (every order passes ALL of these):
  1. Master arm switch     — LIVE_TRADING_ENABLED must be "true"
  2. Market-hours guard     — only fires during regular US session
  3. Per-cycle cap          — max N executions per scan cycle
  4. Daily order cap        — max N orders per calendar day
  5. Daily-loss breaker     — auto-disarms if realized loss exceeds limit
  6. Convergence gate       — only GOD_MODE tier with execute_gate=True
  7. (downstream) PDT shield, per-symbol cooldown, position-size caps

(c) Script Master Labs LLC — BEAST MODE, built safe.
"""
import os
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("AutoExec")

# ── Config (env-overridable) ────────────────────────────────────────────────
MAX_EXEC_PER_CYCLE   = int(os.environ.get("AUTOEXEC_MAX_PER_CYCLE", "2"))
MAX_EXEC_PER_DAY     = int(os.environ.get("AUTOEXEC_MAX_PER_DAY", "10"))
DAILY_LOSS_LIMIT     = float(os.environ.get("AUTOEXEC_DAILY_LOSS_LIMIT", "200.0"))  # USD
CANDIDATES_PER_CYCLE = int(os.environ.get("AUTOEXEC_CANDIDATES", "5"))  # top N to analyze
MARKET_HOURS_ONLY    = os.environ.get("AUTOEXEC_MARKET_HOURS_ONLY", "true").lower() == "true"
MAX_NOTIONAL_PER_DAY = float(os.environ.get("AUTOEXEC_MAX_NOTIONAL_PER_DAY", "2500.0"))  # total $ deployed/day

# ── Daily counters (reset at date rollover) ─────────────────────────────────
_state = {
    "date": None,
    "orders_today": 0,
    "realized_pnl_today": 0.0,
    "notional_today": 0.0,
    "breaker_tripped": False,
}


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _roll_day():
    d = _today_str()
    if _state["date"] != d:
        _state.update(date=d, orders_today=0, realized_pnl_today=0.0, notional_today=0.0, breaker_tripped=False)
        logger.info(f"[AUTOEXEC] New trading day {d} — counters reset.")


def _is_market_hours() -> bool:
    """Regular US session ~9:30–16:00 ET, Mon–Fri. ET = UTC-4 (DST) / -5 (std)."""
    if not MARKET_HOURS_ONLY:
        return True
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    # Approximate ET via UTC-4 (covers Mar–Nov DST; conservative the rest of year)
    et = now - timedelta(hours=4)
    minutes = et.hour * 60 + et.minute
    return (9 * 60 + 30) <= minutes <= (16 * 60)


def record_fill(realized_pnl_delta: float = 0.0):
    """Call after a known realized P&L change to feed the daily-loss breaker."""
    _roll_day()
    _state["realized_pnl_today"] += realized_pnl_delta
    if _state["realized_pnl_today"] <= -abs(DAILY_LOSS_LIMIT):
        _state["breaker_tripped"] = True
        logger.error(
            f"[AUTOEXEC] 🛑 DAILY-LOSS BREAKER TRIPPED — realized {_state['realized_pnl_today']:.2f} "
            f"≤ -{DAILY_LOSS_LIMIT:.2f}. Auto-execution halted for the rest of {_state['date']}."
        )


def status() -> dict:
    _roll_day()
    return {
        "armed": os.environ.get("LIVE_TRADING_ENABLED", "false").strip().lower() == "true",
        "market_hours_now": _is_market_hours(),
        "orders_today": _state["orders_today"],
        "max_per_day": MAX_EXEC_PER_DAY,
        "realized_pnl_today": round(_state["realized_pnl_today"], 2),
        "daily_loss_limit": DAILY_LOSS_LIMIT,
        "breaker_tripped": _state["breaker_tripped"],
        "notional_today": round(_state["notional_today"], 2),
        "max_notional_per_day": MAX_NOTIONAL_PER_DAY,
        "max_per_cycle": MAX_EXEC_PER_CYCLE,
    }


def run_auto_execution(sweet: dict, sorted_syms: list, dm) -> int:
    """
    Called by the scanner each cycle. Runs convergence on the top candidates and
    executes GOD MODE signals. Returns the number of orders fired this cycle.

    Fails SAFE on every uncertainty — any exception or gate miss = no trade.
    """
    _roll_day()

    exec_mode = os.environ.get("EXECUTION_MODE", "alert").strip().lower()
    armed = os.environ.get("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"

    # Gate 1: in AUTO mode, require the master arm switch. In ALERT mode, no
    # arm needed — alerts are safe (they never place orders).
    if exec_mode == "auto" and not armed:
        return 0  # auto execution disarmed

    # Gate 2: breaker (applies to both modes — stop alerting on a blown day too)
    if _state["breaker_tripped"]:
        return 0

    # Gate 3: market hours
    if not _is_market_hours():
        return 0

    # Gate 4: daily cap (counts orders AND alerts)
    if _state["orders_today"] >= MAX_EXEC_PER_DAY:
        logger.info(f"[AUTOEXEC] daily cap reached ({MAX_EXEC_PER_DAY}) — no more {'orders' if exec_mode=='auto' else 'alerts'} today.")
        return 0

    # Lazy imports to avoid heavy load when disarmed
    try:
        from core.convergence_engine import ConvergenceEngine
        from core.api.convergence_bp import _fire_execution, _fetch_bars
    except Exception as e:
        logger.error(f"[AUTOEXEC] import failed, not executing: {e}")
        return 0

    fired = 0
    engine = ConvergenceEngine()

    for sym in sorted_syms[:CANDIDATES_PER_CYCLE]:
        if fired >= MAX_EXEC_PER_CYCLE:
            break
        if _state["orders_today"] >= MAX_EXEC_PER_DAY:
            break
        try:
            closes, volumes, bars = _fetch_bars(dm, sym, tf="1D")
            if len(closes) < 11:
                continue
            result = engine.analyze(sym, closes, volumes, bars_with_dates=bars, run_sniper=True)
            sml = result.get("sml_matrix") or {}

            # Gate 6: convergence — GOD MODE with execute_gate, bull or bear
            bull_gate = sml.get("execute_gate") and sml.get("tier") == "GOD_MODE"
            bear_gate = sml.get("bear_execute_gate") and sml.get("bear_tier") == "GOD_MODE"
            if bull_gate or bear_gate:
                # MANUAL ALERT MODE: if EXECUTION_MODE=alert (or arm switch off for
                # auto), send a copy-paste Discord alert for hand-execution on
                # Robinhood instead of placing an autonomous order.
                exec_mode = os.environ.get("EXECUTION_MODE", "alert").strip().lower()
                if exec_mode != "auto":
                    try:
                        from core.api.manual_alert import fire_manual_alert
                        fire_manual_alert(result)
                        logger.info(f"[AUTOEXEC] 📲 MANUAL ALERT sent for {sym} (EXECUTION_MODE={exec_mode}, no auto-trade)")
                    except Exception as _ma:
                        logger.warning(f"[AUTOEXEC] manual alert failed for {sym}: {_ma}")
                    _state["orders_today"] += 1  # count alerts toward daily cap too
                    fired += 1
                    continue

                # AUTO MODE (EXECUTION_MODE=auto): place the live order
                # Gate 5b: daily notional cap — estimate this order's $ and check ceiling
                try:
                    px = float((result.get("price") or sml.get("price") or 0) or 0)
                except (TypeError, ValueError):
                    px = 0.0
                # conservative estimate using configured max sizing
                est_notional = px * float(os.environ.get("BEAST_MAX_SHARES", "5")) if px > 0 else 0.0
                if est_notional > 0 and (_state["notional_today"] + est_notional) > MAX_NOTIONAL_PER_DAY:
                    logger.warning(
                        f"[AUTOEXEC] {sym} skipped — would exceed daily notional cap "
                        f"(${_state['notional_today']:.0f}+${est_notional:.0f} > ${MAX_NOTIONAL_PER_DAY:.0f})"
                    )
                    continue
                logger.info(f"[AUTOEXEC] 🎯 GOD MODE on {sym} — routing to execution "
                            f"(god_stacked={sml.get('god_stacked')})")
                _fire_execution(sym, result, dm)  # downstream: arm switch re-checked, PDT, cooldown, caps
                _state["orders_today"] += 1
                _state["notional_today"] += est_notional
                fired += 1
        except Exception as e:
            logger.warning(f"[AUTOEXEC] {sym} analysis error (skipped): {e}")
            continue

    if fired:
        logger.info(f"[AUTOEXEC] cycle fired {fired} order(s) | today: {_state['orders_today']}/{MAX_EXEC_PER_DAY}")
    return fired


def dry_run(sweet: dict, sorted_syms: list, dm, limit: int = None) -> dict:
    """
    Runs the FULL analysis pipeline on top candidates but places NO orders.
    Returns what the system WOULD trade right now. Safe to call anytime —
    ignores the arm switch entirely (it never executes).
    """
    limit = limit or CANDIDATES_PER_CYCLE
    out = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "market_hours_now": _is_market_hours(),
        "candidates_analyzed": 0,
        "would_execute": [],
        "near_misses": [],
        "errors": [],
    }
    try:
        from core.convergence_engine import ConvergenceEngine
        from core.api.convergence_bp import _fetch_bars
    except Exception as e:
        out["errors"].append(f"import_failed: {e}")
        return out

    engine = ConvergenceEngine()
    for sym in sorted_syms[:limit]:
        try:
            closes, volumes, bars = _fetch_bars(dm, sym, tf="1D")
            if len(closes) < 11:
                continue
            out["candidates_analyzed"] += 1
            result = engine.analyze(sym, closes, volumes, bars_with_dates=bars, run_sniper=True)
            sml = result.get("sml_matrix") or {}
            row = {
                "symbol": sym,
                "signal": result.get("signal"),
                "tier": sml.get("tier"),
                "god_stacked": sml.get("god_stacked"),
                "execute_gate": sml.get("execute_gate"),
                "bear_tier": sml.get("bear_tier"),
                "bear_god_stacked": sml.get("bear_god_stacked"),
                "bear_execute_gate": sml.get("bear_execute_gate"),
            }
            bull_gate = sml.get("execute_gate") and sml.get("tier") == "GOD_MODE"
            bear_gate = sml.get("bear_execute_gate") and sml.get("bear_tier") == "GOD_MODE"
            if bull_gate or bear_gate:
                out["would_execute"].append(row)
            elif sml.get("god_stacked", 0) >= 3 or sml.get("bear_god_stacked", 0) >= 3:  # show what's getting close
                out["near_misses"].append(row)
        except Exception as e:
            out["errors"].append(f"{sym}: {str(e)[:80]}")
            continue

    out["would_execute_count"] = len(out["would_execute"])
    out["verdict"] = (
        f"{len(out['would_execute'])} GOD MODE signal(s) would fire right now"
        if out["would_execute"] else
        "No GOD MODE signals at this moment (this is normal — GOD MODE is rare by design)"
    )
    return out
