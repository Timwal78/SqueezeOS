"""
IAM Auto-Execution Layer
========================
Bridges IAM resolution → live broker execution.

Supported brokers:
  • Tradier   — server-side equity + options orders via tradier_api.py
  • Robinhood — client-side polling service picks up Discord alerts
                (robin_stocks can't run on Render — Windows/local only)

Execution is gated by the FULL safety stack before any order is placed.
All gates are independent — any single failure blocks the trade.

Environment variables (all default to safe/disabled):
  IAM_AUTO_TRADING          = false      # master arm switch
  IAM_EXECUTION_MODE        = alert      # alert | tradier | both
  IAM_INSTRUMENT            = equity     # equity | options | auto
  IAM_MIN_CONFIDENCE        = 70         # min resolution_confidence % to execute
  IAM_REQUIRED_WINDOW       = NEAR_TERM  # NEAR_TERM | IMMEDIATE (comma-separated for both)
  IAM_MAX_SHARES            = 5          # max shares per equity order
  IAM_MAX_ORDER_USD         = 500        # max notional per order
  IAM_MAX_ORDERS_PER_DAY    = 5          # hard daily cap
  IAM_MAX_NOTIONAL_PER_DAY  = 2000       # max total $ deployed per day
  IAM_DAILY_LOSS_LIMIT      = 300        # auto-disarm when realized loss hits this
  IAM_COOLDOWN_SECONDS      = 3600       # min seconds between same-symbol orders
  IAM_PAPER_MODE            = true       # log but never send orders (default safe)
  IAM_OPTION_EXPIRY_DAYS    = 1          # target DTE for options orders
  IAM_OPTION_CONTRACT_QTY   = 1         # number of option contracts
  IAM_DELTA_MIN             = 0.32       # delta bracket lower bound
  IAM_DELTA_MAX             = 0.40       # delta bracket upper bound
  IAM_ODTE_ONLY_SYMBOLS     = IWM        # comma-separated; these symbols ALWAYS route
                                          # to same-day (0DTE) options, never equity,
                                          # regardless of IAM_INSTRUMENT/IAM_OPTION_EXPIRY_DAYS —
                                          # never held overnight or later. Still fully
                                          # eligible for the dynamic scan universe.
  IAM_OPTIONS_SYSTEMS       = ""         # comma-separated system tags that always buy
                                          # calls/puts (via Tradier) regardless of the
                                          # global IAM_INSTRUMENT setting, e.g.
                                          # SML_SR_MATRIX,SML_SR_ZONE_PATTERN
  IAM_MAX_OPEN_CALLS        = 1          # real-money cap on concurrently open Tradier
  IAM_MAX_OPEN_PUTS         = 1          # call/put positions, account-wide. 0=uncapped.
                                          # Paper mode ignores this (nothing real to count).
  TRADIER_ACCOUNT_ID        = ...        # required for live Tradier orders
"""

import os
import re
import time
import logging
import threading
import zoneinfo
from datetime import datetime, timezone, timedelta, time as _dtime
from typing import Optional

from core.execution_lock import claim_entry

logger = logging.getLogger("IAM-EXEC")

def _get_macro_regime(symbol: str) -> str:
    """
    Returns the Pure Macro regime for a symbol (core/api/macro_bp.py -- anchor
    period is whatever MACRO_STACK_CSV's last value is, not necessarily 741).
    Direct Python import — no HTTP call, no public exposure of the paid product.
    Fails open: UNKNOWN / INSUFFICIENT_DATA never block a trade.
    Only PERFECT_BEARISH_REGIME blocks BUY orders.
    """
    try:
        from core.api.macro_bp import _compute_regime
        return _compute_regime(symbol).get("regime", "UNKNOWN")
    except Exception as e:
        logger.warning(f"[IAM-EXEC] macro regime check failed for {symbol}: {e} — failing open")
        return "UNKNOWN"

# ── Config ─────────────────────────────────────────────────────────────────────
def _env_bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("true", "1", "yes")

def _env_float(key: str, default: float) -> float:
    try:    return float(os.environ.get(key, default))
    except: return default

def _env_int(key: str, default: int) -> int:
    try:    return int(os.environ.get(key, default))
    except: return default

PAPER_MODE         = lambda: _env_bool("IAM_PAPER_MODE", True)

# Operator decision (Timothy, 2026-07-19: "ok put it on paper mode"): the
# PAPER desk runs out of the box — while PAPER_MODE is true, the arm switch
# defaults ON so paper signals flow with zero Render configuration. The
# moment IAM_PAPER_MODE=false (live money), the default flips back to
# DISARMED and going live requires BOTH explicit flags:
#   IAM_PAPER_MODE=false + IAM_AUTO_TRADING=true
ARMED              = lambda: _env_bool("IAM_AUTO_TRADING", PAPER_MODE())
# "both" default = Discord alerts + (paper) broker path, so the position
# ledger and daily-loss breaker exercise during the burn-in.
EXECUTION_MODE     = lambda: os.environ.get("IAM_EXECUTION_MODE", "both").strip().lower()
INSTRUMENT         = lambda: os.environ.get("IAM_INSTRUMENT",  "equity").strip().lower()
MIN_CONFIDENCE     = lambda: _env_float("IAM_MIN_CONFIDENCE", 70.0)
MAX_SHARES         = lambda: _env_int("IAM_MAX_SHARES", 5)
# MAX_ORDERS_PER_DAY/MAX_NOTIONAL_PER_DAY raised 5->15 / $2000->$6000
# (2026-08-01, operator directive after a 7-engine profitability audit
# flagged these as unwidened since being set for ~1-2 systems). Both are
# ACCOUNT-WIDE, shared by all 7 live IAM_PRIMARY_SYSTEM engines -- the old
# 5-order/$2000 ceiling could be exhausted by literally 4-5 systems each
# firing once, silently starving the rest for the remainder of the day.
# 15 orders gives ~2/system/day average with real buffer for scale-ins;
# $6000 is sized against MAX_ORDER_USD (500) so the notional cap doesn't
# bottleneck before the order-count cap does (15*500=$7500 theoretical max,
# $6000 covers ~12 full-size orders). See CLAUDE.md's caps-audit section.
MAX_ORDER_USD      = lambda: _env_float("IAM_MAX_ORDER_USD", 500.0)
MAX_ORDERS_PER_DAY = lambda: _env_int("IAM_MAX_ORDERS_PER_DAY", 15)
MAX_NOTIONAL_PER_DAY = lambda: _env_float("IAM_MAX_NOTIONAL_PER_DAY", 6000.0)
DAILY_LOSS_LIMIT   = lambda: _env_float("IAM_DAILY_LOSS_LIMIT", 150.0)  # 7% of ~$2k account
STOP_LOSS_PCT      = lambda: _env_float("IAM_STOP_LOSS_PCT", 3.0)  # hard protective stop below entry; 0 disables

# Primary signal system(s) — when set, ONLY resolutions tagged with one of
# these systems (resolution["system"]) place broker orders; every other
# system is downgraded to alert-only. Untagged resolutions default to "IAM"
# (the IAM engine is the producer that predates tagging). Comma-separated —
# e.g. IAM_PRIMARY_SYSTEM=SML_CASCADE,SML_BREAKOUT lets both trade live at
# once; IAM_PRIMARY_SYSTEM=SML_ORB_MM (single value) behaves exactly as
# before. Empty set means the gate is open (no restriction).
PRIMARY_SYSTEM     = lambda: {s.strip().upper() for s in
                               os.environ.get("IAM_PRIMARY_SYSTEM", "").split(",") if s.strip()}

# Execution symbol allowlist — OPT-IN gate, empty by default (all symbols
# allowed). Operator directive 2026-07-19: universes are DYNAMIC, never
# hardcoded (Prime Directive #1) — so no default ticker list here. Setting a
# comma list restricts ENTRIES only; exits/closes are never blocked. The
# 2026-07-17 scoreboard (docs/ENGINE_SCOREBOARD_2026-07-17.md) documents
# which engine×symbol pairs measured an edge if a restriction is ever wanted.
SYMBOL_ALLOWLIST   = lambda: set() if os.environ.get("IAM_SYMBOL_ALLOWLIST", "").strip() == "*" else {
    s.strip().upper() for s in os.environ.get("IAM_SYMBOL_ALLOWLIST", "").split(",") if s.strip()
}
COOLDOWN_SECONDS   = lambda: _env_int("IAM_COOLDOWN_SECONDS", 600)   # 10 min default — AMC moves in waves
OPTION_EXPIRY_DAYS = lambda: _env_int("IAM_OPTION_EXPIRY_DAYS", 1)
OPTION_QTY         = lambda: _env_int("IAM_OPTION_CONTRACT_QTY", 1)
DELTA_MIN          = lambda: _env_float("IAM_DELTA_MIN", 0.32)
DELTA_MAX          = lambda: _env_float("IAM_DELTA_MAX", 0.40)

# Per-system options override (2026-07-30 operator directive) — systems listed
# here always route their BUY entries to calls, regardless of the global
# IAM_INSTRUMENT setting. SELL entries already always try to buy a put
# (bear_protect_and_put in _execute_tradier) for every system, unconditional
# on IAM_INSTRUMENT — so this override only needs to affect the BUY/call side.
# Comma-separated, same convention as IAM_PRIMARY_SYSTEM. Empty = no override
# (falls back to the global IAM_INSTRUMENT setting for every system).
OPTIONS_SYSTEMS    = lambda: {s.strip().upper() for s in
                               os.environ.get("IAM_OPTIONS_SYSTEMS", "").split(",") if s.strip()}

# Concurrent open-option-position cap, real Tradier account state (not a
# per-symbol/per-system count — an account-wide comfort limit while the
# operator gets used to real options execution). 0 or negative = unlimited.
# Only enforced live (PAPER_MODE has no real Tradier positions to count).
# Raised 1->3 (2026-08-01, operator directive after the 7-engine
# profitability audit): the original 1/1 was set 2026-07-30 when far fewer
# systems traded options live. With 7 systems now sharing this ACCOUNT-WIDE
# cap and no equity fallback on cap-hit (a blocked signal is just dropped),
# whichever system opened a call first could silently starve every other
# system's BUY signal until it closed, regardless of that signal's own
# evidence quality. 3 is a deliberately measured step (not 7-for-7 parity,
# which would be reckless given several of these engines still carry
# disclosed evidence caveats) -- see CLAUDE.md's caps-audit section.
MAX_OPEN_CALLS     = lambda: _env_int("IAM_MAX_OPEN_CALLS", 3)
MAX_OPEN_PUTS      = lambda: _env_int("IAM_MAX_OPEN_PUTS", 3)

REQUIRED_WINDOWS   = {"NEAR_TERM", "IMMEDIATE"}

# ── State ──────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cooldowns: dict = {}     # symbol → last execution epoch
_state = {
    "date":            None,
    "orders_today":    0,
    "notional_today":  0.0,
    "realized_pnl":    0.0,
    "breaker_tripped": False,
    "last_order":      None,
}

# In-process position ledger: symbol → {"qty": int, "avg": float}.
# P&L basis is the SIGNAL price at order time, not the broker fill price —
# an approximation, but it is what makes the daily-loss breaker actually
# fire: before this ledger existed, nothing ever called record_fill(), so
# the breaker could never trip in either paper or live mode.
_positions: dict = {}


def _ledger_buy(sym: str, qty: int, price: float, system: str = "IAM"):
    if qty <= 0 or price <= 0:
        return
    with _lock:
        pos = _positions.get(sym, {"qty": 0, "avg": 0.0})
        total_cost = pos["avg"] * pos["qty"] + price * qty
        pos["qty"] += qty
        pos["avg"] = total_cost / pos["qty"]
        _positions[sym] = pos
    # Persistent, system-tagged record (operator directive 2026-07-25: "all
    # paper trades should be recorded") -- this in-process _positions dict
    # above resets daily and on restart with no per-system attribution; that
    # gap is exactly what paper_trade_ledger.py exists to close. Paper only,
    # matching what was actually asked for.
    if PAPER_MODE():
        try:
            import paper_trade_ledger
            paper_trade_ledger.record_open(system, sym, qty, price)
        except Exception as e:
            logger.warning(f"[IAM-EXEC] paper_trade_ledger record_open failed (non-fatal): {e}")


def _ledger_sell(sym: str, qty: int, price: float, system: str = "IAM"):
    """Reduce/close the tracked position and feed realized P&L to the breaker."""
    if qty <= 0 or price <= 0:
        return
    with _lock:
        pos = _positions.get(sym)
        if not pos or pos["qty"] <= 0:
            return
        closed = min(qty, pos["qty"])
        realized = (price - pos["avg"]) * closed
        pos["qty"] -= closed
        if pos["qty"] <= 0:
            _positions.pop(sym, None)
    record_fill(realized)
    if PAPER_MODE():
        try:
            import paper_trade_ledger
            paper_trade_ledger.record_close(system, sym, qty, price)
        except Exception as e:
            logger.warning(f"[IAM-EXEC] paper_trade_ledger record_close failed (non-fatal): {e}")
    logger.info(f"[IAM-EXEC] Ledger: closed {closed}x {sym} @ ${price:.2f} → realized {realized:+.2f} (basis=signal price)")


def _roll_day():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _state["date"] != today:
        with _lock:
            _state.update(
                date=today, orders_today=0, notional_today=0.0,
                realized_pnl=0.0, breaker_tripped=False
            )
            logger.info(f"[IAM-EXEC] New trading day {today} — counters reset.")


def record_fill(realized_pnl_delta: float = 0.0):
    """Call after a fill to feed the daily-loss breaker."""
    _roll_day()
    with _lock:
        _state["realized_pnl"] += realized_pnl_delta
        if _state["realized_pnl"] <= -abs(DAILY_LOSS_LIMIT()):
            _state["breaker_tripped"] = True
            logger.error(
                f"[IAM-EXEC] 🛑 DAILY-LOSS BREAKER — realized {_state['realized_pnl']:.2f} "
                f"≤ -{DAILY_LOSS_LIMIT():.2f}. IAM execution halted for the rest of {_state['date']}."
            )


def status() -> dict:
    _roll_day()
    return {
        "armed":               ARMED(),
        "execution_mode":      EXECUTION_MODE(),
        "instrument":          INSTRUMENT(),
        "paper_mode":          PAPER_MODE(),
        "min_confidence":      MIN_CONFIDENCE(),
        "required_windows":    list(REQUIRED_WINDOWS),
        "market_hours_now":    _is_market_hours(),
        "orders_today":        _state["orders_today"],
        "max_orders_per_day":  MAX_ORDERS_PER_DAY(),
        "notional_today":      round(_state["notional_today"], 2),
        "max_notional_per_day": MAX_NOTIONAL_PER_DAY(),
        "realized_pnl_today":  round(_state["realized_pnl"], 2),
        "daily_loss_limit":    DAILY_LOSS_LIMIT(),
        "breaker_tripped":     _state["breaker_tripped"],
        "cooldown_seconds":    COOLDOWN_SECONDS(),
        "last_order":          _state["last_order"],
        "stop_loss_pct":       STOP_LOSS_PCT(),
        "open_positions":      {s: dict(p) for s, p in _positions.items()},
        "pnl_basis":           "signal_price_approx",
    }


# ── Market hours guard ─────────────────────────────────────────────────────────
_TZ_ET = zoneinfo.ZoneInfo("America/New_York")

def _is_market_hours() -> bool:
    """True during regular + extended hours (4:00 AM – 8:00 PM ET) Mon–Fri."""
    now_et = datetime.now(_TZ_ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    return _dtime(4, 0) <= t < _dtime(20, 0)

def _is_extended_hours() -> bool:
    """True during pre-market (4:00–9:30 ET) or after-hours (16:00–20:00 ET)."""
    now_et = datetime.now(_TZ_ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    return _dtime(4, 0) <= t < _dtime(9, 30) or _dtime(16, 0) <= t < _dtime(20, 0)

def _ext_hours_duration() -> str:
    """Tradier duration string: 'pre' for pre-market, 'post' for after-hours."""
    t = datetime.now(_TZ_ET).time()
    return "pre" if t < _dtime(9, 30) else "post"


# Real, observed 2026-07-30: Tradier started rejecting duration="post" equity
# orders ("Invalid parameter, duration: post market no longer available.") --
# apparently a Tradier-side change, not confirmable from this sandbox since
# docs.tradier.com/api.tradier.com are both network-blocked here. Rather than
# guess a replacement duration value on a live-money order parameter (the
# exact kind of unverified fabrication this codebase's golden rule forbids),
# this tracks per-value failures in-process and skips straight to the
# Robinhood-queue fallback (already a real, working safety net -- confirmed
# in production logs) instead of repeatedly re-attempting a call already
# known broken this run. Resets on every restart/redeploy so it always
# retries fresh in case Tradier restores support or this was transient.
_EXT_HOURS_DURATION_BROKEN: set = set()  # {"pre", "post"} as confirmed broken this run


def _is_ext_hours_duration_broken(duration: str) -> bool:
    return duration in _EXT_HOURS_DURATION_BROKEN


def _mark_ext_hours_duration_broken(duration: str, tradier_message: str) -> None:
    if duration not in _EXT_HOURS_DURATION_BROKEN:
        _EXT_HOURS_DURATION_BROKEN.add(duration)
        logger.error(
            f"[IAM-EXEC] Tradier rejected duration='{duration}' extended-hours equity "
            f"orders this run ({tradier_message!r}) -- Tradier's actual current "
            f"requirement couldn't be verified from this sandbox. Skipping further "
            f"Tradier attempts with this duration for the rest of this process's "
            f"uptime; falling straight to the Robinhood queue instead. Will retry "
            f"fresh on next restart/redeploy."
        )


# ── Safety gate stack ──────────────────────────────────────────────────────────
def _gate_check(sym: str, resolution: dict, time_window: str,
                confidence: float, is_exit: bool = False) -> Optional[str]:
    """
    Returns None if all gates pass, or a reason string if blocked.
    All checks are fast — no network calls.

    `is_exit=True` runs the EXIT-SAFE subset. This distinction is a real bug
    fix, not a refactor: this function previously applied every gate to every
    action, so a SELL — the signal that protects capital — could be silently
    refused by the daily order cap, the per-symbol cooldown, the confidence
    floor, the time-window filter, or the daily-loss breaker. The breaker case
    was the worst: once a bad day tripped it, the executor stopped closing
    losing positions at exactly the moment it most needed to. CLAUDE.md's
    "exits never blocked" was only ever true of the symbol allowlist.

    Gates that still apply to an exit are the ones that make an exit
    impossible rather than merely unwanted: the master arm switch, a valid
    execution mode, and market hours.
    """
    _roll_day()

    if not ARMED():
        return "IAM_AUTO_TRADING not enabled"

    mode = EXECUTION_MODE()
    if mode not in ("alert", "tradier", "both"):
        return f"unknown IAM_EXECUTION_MODE={mode}"

    if not _is_market_hours() and mode != "alert":
        return "outside market hours"

    if is_exit:
        # Everything below this line is an ENTRY-quality filter — "should we
        # open this?" — and none of it should ever stop us getting flat.
        return None

    if _state["breaker_tripped"]:
        return f"daily-loss breaker tripped (realized={_state['realized_pnl']:.2f})"

    # Allowlist blocks ENTRIES only — a SELL on an open position must always
    # be free to protect capital, even if the symbol was later delisted here.
    allow = SYMBOL_ALLOWLIST()
    if allow and sym.upper() not in allow and resolution.get("action") == "BUY":
        return f"{sym} not in IAM_SYMBOL_ALLOWLIST — no backtested edge, entry blocked"

    if _state["orders_today"] >= MAX_ORDERS_PER_DAY():
        return f"daily order cap reached ({_state['orders_today']}/{MAX_ORDERS_PER_DAY()})"

    if confidence < MIN_CONFIDENCE():
        return f"confidence {confidence:.1f}% < min {MIN_CONFIDENCE():.1f}%"

    if time_window not in REQUIRED_WINDOWS:
        return f"time_window={time_window} not in required {REQUIRED_WINDOWS}"

    now  = time.time()
    last = _cooldowns.get(sym, 0)
    remaining = COOLDOWN_SECONDS() - (now - last)
    if remaining > 0:
        return f"cooldown active — {int(remaining)}s remaining for {sym}"

    return None  # all gates passed


def _entry_gate_check(sym: str, resolution: dict, time_window: str,
                      confidence: float) -> Optional[str]:
    """
    The entry-only subset, callable independently. Used by the SELL branch's
    PUT leg: a bearish resolution's "close the long" half is an exit and must
    always run, but its "buy a put" half is a brand-new position opening real
    risk and still has to clear every entry gate.
    """
    return _gate_check(sym, resolution, time_window, confidence, is_exit=False)


# Symbols that must NEVER be held overnight — 0DTE options only, no equity route
# regardless of IAM_INSTRUMENT/IAM_OPTION_EXPIRY_DAYS. Still fully eligible for the
# dynamic scan universe (iam_scanner.py) — this only constrains execution, not discovery.
ODTE_ONLY_SYMBOLS = lambda: {
    s.strip().upper() for s in os.environ.get("IAM_ODTE_ONLY_SYMBOLS", "IWM").split(",") if s.strip()
}


# ── Preflight: live quote + ATR, fetched once per decision ─────────────────────
def _preflight(sym: str) -> tuple:
    """
    (quote, atr_value) — both real or both honestly None. Never fabricates a
    price. Failures here degrade to the previous behaviour (signal price, no
    chase guard) rather than blocking the trade, and are logged.
    """
    quote = None
    atr_value = None
    try:
        import execution_quality
        quote = execution_quality.live_nbbo(sym)
    except Exception as e:
        logger.warning(f"[IAM-EXEC] {sym} live quote unavailable ({e}) — falling back to signal price")
    try:
        import execution_quality
        from core.legacy import get_service
        dm = get_service("dm")
        if dm:
            bars = dm.get_bars(sym, "1D", 40) or []
            atr_value = execution_quality.atr(bars, 14)
            _bars_cache[sym] = bars
    except Exception as e:
        logger.warning(f"[IAM-EXEC] {sym} ATR unavailable ({e}) — chase guard degraded")
    return quote, atr_value


_bars_cache: dict = {}   # sym -> most recent bars pulled by _preflight this pass


def _chase_check(sym: str, action: str, signal_price: float, current_price: float) -> tuple:
    """(allowed, reason) — anti-chase entry guard. Fails OPEN when the real
    bar history needed to measure extension is unavailable, since refusing
    every entry on missing data would silently disable the live systems."""
    try:
        import execution_quality
        bars = _bars_cache.get(sym) or []
        if not bars or not signal_price or signal_price <= 0:
            return True, "no bars/signal price — chase guard not applied"
        return execution_quality.chase_guard(action, signal_price, current_price, bars)
    except Exception as e:
        logger.warning(f"[IAM-EXEC] {sym} chase guard error ({e}) — allowing")
        return True, f"chase guard error: {e}"


# ── Tradier execution ──────────────────────────────────────────────────────────
def _execute_tradier(sym: str, action: str, resolution: dict, price: float,
                     quote: Optional[dict] = None,
                     atr_value: Optional[float] = None) -> dict:
    instrument = INSTRUMENT()
    is_odte = sym.upper() in ODTE_ONLY_SYMBOLS()
    # Same system-tag resolution execute_from_resolution() already uses for
    # the primary-system gate -- threaded down into the equity ledger calls
    # so paper_trade_ledger.py can attribute fills per engine.
    system = (resolution.get("system") or "IAM").strip().upper()

    if action == "SELL":
        # Bearish resolution: never open a naked equity short. First close any
        # existing long to protect gains (position-tracking via tradier_api.get_position),
        # then treat the reversal as a PUT-buying opportunity — same policy as
        # core/api/convergence_bp.py's bear leg. This runs regardless of
        # IAM_INSTRUMENT, since "protect the long, buy the put" applies whether the
        # position was opened as equity or options.
        results: dict = {"mode": "bear_protect_and_put"}
        close_result = _close_equity_position(sym, price, system)
        if close_result is not None:
            results["close"] = close_result

        if is_odte and _is_extended_hours():
            results["put"] = {"status": "skipped", "message": f"{sym} is 0DTE-only; no same-day options in extended hours"}
        elif _is_extended_hours():
            results["put"] = {"status": "skipped", "message": "options unavailable in extended hours"}
        elif not claim_entry(sym, "PUT_ENTRY", "iam_executor"):
            # A put buy-to-open has no natural cap the way the equity close above
            # does (that's self-correcting — both engines check the real, shared
            # Tradier account before selling). core/api/convergence_bp.py already
            # claimed this leg this window.
            logger.info(f"[IAM-EXEC] {sym} PUT entry already claimed by another engine this window — skipping")
            results["put"] = {"status": "skipped", "message": "claimed by another engine"}
        elif (entry_block := _entry_gate_check(sym, resolution,
                                               resolution.get("_time_window", "NEAR_TERM"),
                                               float(resolution.get("resolution_confidence") or 0.0))):
            # The close above ran under the relaxed EXIT gate (capital
            # protection must never be blocked). This put buy is a NEW
            # position, so it independently re-clears the full entry stack —
            # daily order cap, cooldown, loss breaker, allowlist and all.
            logger.info(f"[IAM-EXEC] {sym} long closed, but PUT entry blocked: {entry_block}")
            results["put"] = {"status": "skipped", "message": f"entry gate: {entry_block}"}
        else:
            expiry_override = 0 if is_odte else None
            results["put"] = _execute_tradier_options(sym, action, resolution, price, expiry_days_override=expiry_override)

        close_ok = bool(close_result) and (
            close_result.get("status") == "success" or close_result.get("placed") or close_result.get("mode") == "paper"
        )
        put_result = results["put"]
        put_ok = put_result.get("status") == "success" or put_result.get("placed") or put_result.get("mode") == "paper"
        results["status"] = "success" if (close_ok or put_ok) else put_result.get("status", "error")
        results["placed"] = close_ok or put_ok
        return results

    # ── BUY entry — equity buy or call buy-to-open, whichever route is taken
    # below. Claimed once here (not per-branch) since every path past this
    # point for a BUY action opens a fresh long. core/api/convergence_bp.py's
    # own GOD_MODE gate trades the same Tradier account independently.
    if not claim_entry(sym, "LONG_ENTRY", "iam_executor"):
        logger.info(f"[IAM-EXEC] {sym} LONG entry already claimed by another engine this window — skipping")
        return {"status": "skipped", "message": "claimed by another engine"}

    if is_odte:
        # No equity fallback for these symbols under any circumstance — if same-day
        # options aren't tradeable right now (extended hours), skip rather than fall
        # back to equity, since equity carries no expiry and the whole point is that
        # this symbol is never held past today.
        if _is_extended_hours():
            logger.info(f"[IAM-EXEC] {sym} is 0DTE-only — skipping (no equity fallback, options unavailable in extended hours)")
            return {"status": "skipped", "message": f"{sym} is 0DTE-only; no same-day options in extended hours"}
        return _execute_tradier_options(sym, action, resolution, price, expiry_days_override=0)

    # Tradier does not support options orders in extended hours — fall back to equity
    if _is_extended_hours():
        logger.info(f"[IAM-EXEC] Extended hours: routing {sym} to equity (options unavailable)")
        return _execute_tradier_equity(sym, action, price, system, quote=quote, atr_value=atr_value)
    # auto mode: try options on any symbol — chain availability is the natural gate.
    # BUY signal → calls; SELL signal → puts. Falls back gracefully if no chain exists.
    # IAM_OPTIONS_SYSTEMS forces options for specific systems regardless of the
    # global IAM_INSTRUMENT setting (2026-07-30 operator directive — S/R Matrix
    # and S/R Zone+Pattern go to options while other systems stay whatever the
    # global setting already has them on).
    if instrument in ("options", "auto") or system in OPTIONS_SYSTEMS():
        return _execute_tradier_options(sym, action, resolution, price)
    else:
        return _execute_tradier_equity(sym, action, price, system, quote=quote, atr_value=atr_value)


def _close_equity_position(sym: str, price: float, system: str = "IAM") -> Optional[dict]:
    """
    Position-aware close: looks up any existing equity long via tradier_api.get_position()
    and sells the FULL held quantity to close it — never a fixed/computed size, since the
    goal is securing whatever gains have accrued, not opening a new directional bet.
    Returns None if flat (nothing to close).
    """
    try:
        from tradier_api import get_position, place_equity_order
        position = get_position(sym)
        if not position or position.get("quantity", 0) <= 0:
            logger.info(f"[IAM-EXEC] {sym} SELL signal — no existing long to close")
            return None

        qty = int(position["quantity"])

        if PAPER_MODE():
            logger.info(f"[IAM-EXEC][PAPER] Would close long: SELL {qty}x {sym} @ ${price:.2f} (protect gains)")
            _ledger_sell(sym, qty, price, system)
            _untrack(sym)
            return {"mode": "paper", "side": "sell", "qty": qty, "price": price, "placed": False}

        import execution_quality
        q = execution_quality.live_nbbo(sym) or {}

        if _is_extended_hours():
            if price <= 0:
                logger.warning(f"[IAM-EXEC] {sym} close skipped — extended hours requires a live price for the limit order")
                return {"status": "skipped", "message": "no live price for extended-hours limit close"}
            limit_px = (execution_quality.marketable_limit(q.get("bid"), q.get("ask"), "sell")
                        or round(price * 0.998, 2))
            duration = _ext_hours_duration()
            result = place_equity_order(sym, qty, "sell", order_type="limit",
                                        duration=duration, limit_price=limit_px)
        else:
            # Bounded exit price when the book supports one; a raw market
            # order otherwise. Exits FAIL OPEN — getting flat outranks the
            # fill, so a missing quote must never leave the position on.
            limit_px = execution_quality.marketable_limit(q.get("bid"), q.get("ask"), "sell")
            if limit_px:
                result = place_equity_order(sym, qty, "sell", order_type="limit",
                                            duration="day", limit_price=limit_px)
            else:
                logger.warning(f"[IAM-EXEC] {sym} no two-sided quote — closing with a MARKET order (fail open)")
                result = place_equity_order(sym, qty, "sell", order_type="market", duration="day")

        result["qty"]   = qty
        result["price"] = price
        result["side"]  = "sell"
        if result.get("status") == "success":
            _ledger_sell(sym, qty, price, system)
            _untrack(sym)
        logger.info(f"[IAM-EXEC] 🔻 Closed long to protect gains — SELL {qty}x {sym} @ ${price:.2f}")
        return result
    except Exception as e:
        logger.error(f"[IAM-EXEC] close-position error for {sym}: {e}")
        return {"status": "error", "message": str(e)}


def _execute_tradier_equity(sym: str, action: str, price: float, system: str = "IAM",
                            quote: Optional[dict] = None,
                            atr_value: Optional[float] = None) -> dict:
    try:
        from tradier_api import place_equity_order
        import execution_quality
        side = "buy" if action == "BUY" else "sell"

        # Price basis: the LIVE quote when we have one, not the signal price.
        # Every scanner in this repo hands the executor its signal bar's close
        # (breakout_scanner passes bars[-1]["c"], etc.). On a daily-bar engine
        # that can be a full session stale, and it was being used for BOTH
        # position sizing AND the protective stop level — so the "3% stop" was
        # 3% below a price that no longer existed.
        q = quote if quote is not None else execution_quality.live_nbbo(sym)
        exec_price = (q or {}).get("reference") or price
        if exec_price <= 0:
            return {"status": "error", "message": f"no usable price for {sym}"}

        qty  = max(1, min(MAX_SHARES(), int(MAX_ORDER_USD() / exec_price)))

        # Hard protective stop level for entries (0 disables)
        stop_px = round(exec_price * (1.0 - STOP_LOSS_PCT() / 100.0), 2) if (side == "buy" and STOP_LOSS_PCT() > 0) else None

        bid, ask = (q or {}).get("bid"), (q or {}).get("ask")
        book = execution_quality.have_book(bid, ask)

        # Spread guard — entries only, and only when we actually HAVE a book to
        # judge. A book too wide to trade is an immediate, guaranteed loss on a
        # position we chose to open. A MISSING quote is a different situation
        # and must not halt the desk: it degrades to a bounded fallback limit
        # below rather than blocking (a Tradier quote outage silently stopping
        # every entry would be its own outage).
        if book and side == "buy":
            ok, why = execution_quality.spread_ok(bid, ask, is_option=False, is_entry=True)
            if not ok:
                logger.info(f"[IAM-EXEC] {sym} equity entry skipped — {why}")
                return {"status": "skipped", "message": why}

        if PAPER_MODE():
            stop_note  = f" | hard stop ${stop_px:.2f}" if stop_px else ""
            logger.info(f"[IAM-EXEC][PAPER] Would {side.upper()} {qty}x {sym} @ ${exec_price:.2f}{stop_note}")
            if side == "buy":
                _ledger_buy(sym, qty, exec_price, system)
                _track_equity(sym, qty, exec_price, system, atr_value, stop_px)
            else:
                _ledger_sell(sym, qty, exec_price, system)
            return {"mode": "paper", "side": side, "qty": qty, "price": exec_price,
                    "stop_loss": stop_px, "placed": False}

        if _is_extended_hours():
            duration = _ext_hours_duration()
            if _is_ext_hours_duration_broken(duration):
                result = {"status": "skipped",
                          "message": f"Tradier duration='{duration}' known broken this run — see log; falling to Robinhood"}
            else:
                limit_px = (execution_quality.marketable_limit(bid, ask, side)
                            or execution_quality.fallback_limit(exec_price, side))
                result = place_equity_order(sym, qty, side, order_type="limit",
                                            duration=duration, limit_price=limit_px)
                if result.get("status") != "success" and "duration" in str(result.get("message", "")).lower():
                    _mark_ext_hours_duration_broken(duration, result.get("message", ""))
        else:
            # Marketable LIMIT, not a raw market order. A market order accepts
            # any print the book offers — on a thin symbol (and the scan
            # universe is deliberately wide, "no cap, many tickers") that is
            # unbounded slippage on entry AND on exit. This crosses the spread
            # by a bounded IAM_LIMIT_OFFSET_BPS so it still fills promptly.
            #
            # With no live book, fall back to a bounded limit off the reference
            # price rather than a market order — degraded, but never unbounded.
            limit_px = (execution_quality.marketable_limit(bid, ask, side)
                        or execution_quality.fallback_limit(exec_price, side))
            if limit_px:
                if not book:
                    logger.warning(f"[IAM-EXEC] {sym} no live book — bounded fallback limit "
                                   f"${limit_px:.2f} off reference ${exec_price:.2f}")
                result = place_equity_order(sym, qty, side, order_type="limit",
                                            duration="day", limit_price=limit_px)
            elif side == "sell":
                # Nothing priceable at all and we need to be flat. Exits fail
                # OPEN — an unmanaged position outranks a bad fill.
                logger.warning(f"[IAM-EXEC] {sym} nothing priceable — exiting with a MARKET order (fail open)")
                result = place_equity_order(sym, qty, side, order_type="market", duration="day")
            else:
                return {"status": "skipped",
                        "message": "no price at all to bound an entry — refused (fail closed)"}
        result["qty"]   = qty
        result["price"] = exec_price
        result["side"]  = side

        if result.get("status") == "success":
            if side == "buy":
                _ledger_buy(sym, qty, exec_price, system)
                # Hand the fill to the active exit manager. The GTC stop below
                # is a static floor that never moves once placed — it is what
                # let a position run up and give the whole gain back before
                # stopping out at the original level. position_manager adds the
                # ratcheting ATR trail / giveback lock on top of it.
                _track_equity(sym, qty, exec_price, system, atr_value, stop_px)
                # Attach the hard stop as a real GTC stop order — this is the
                # "sell before it loses big" wire. Regular-hours only: Tradier
                # rejects stop orders with pre/post durations.
                if stop_px and not _is_extended_hours():
                    stop_result = place_equity_order(sym, qty, "sell", order_type="stop",
                                                     duration="gtc", stop_price=stop_px)
                    result["stop_loss"] = stop_px
                    result["stop_order"] = stop_result
                    if stop_result.get("status") != "success":
                        logger.error(f"[IAM-EXEC] ⚠️ {sym} entry filled but protective stop FAILED: {stop_result}")
                elif stop_px:
                    result["stop_loss"] = stop_px
                    result["stop_order"] = {"status": "skipped", "message": "extended hours — place stop at next open"}
                    logger.warning(f"[IAM-EXEC] {sym} extended-hours entry — protective stop ${stop_px:.2f} NOT placed (Tradier restriction)")
            else:
                _ledger_sell(sym, qty, exec_price, system)
                _untrack(sym)
        return result
    except Exception as e:
        logger.error(f"[IAM-EXEC] Tradier equity error for {sym}: {e}")
        return {"status": "error", "message": str(e)}


# ── position_manager bridge ────────────────────────────────────────────────────
# Every call is best-effort: a failure to register a position with the exit
# manager must never abort or roll back an order that already reached the
# broker. It is logged loudly instead, because an untracked position is
# precisely the unmanaged state this whole layer exists to prevent.
def _track_equity(sym: str, qty: int, price: float, system: str,
                  atr_value: Optional[float], stop_px: Optional[float]):
    try:
        import position_manager
        position_manager.register_equity(sym, qty, price, system, atr_value, stop_px)
    except Exception as e:
        logger.error(f"[IAM-EXEC] ⚠️ {sym} filled but could NOT be registered with "
                     f"position_manager ({e}) — this position has no active exit management")


def _track_option(option_symbol: str, underlying: str, qty: int, premium: float,
                  system: str, expiry: Optional[str]):
    try:
        import position_manager
        position_manager.register_option(option_symbol, underlying, qty, premium, system, expiry)
    except Exception as e:
        logger.error(f"[IAM-EXEC] ⚠️ {option_symbol} filled but could NOT be registered with "
                     f"position_manager ({e}) — this option has no active exit management")


def _untrack(sym: str):
    try:
        import position_manager
        position_manager.untrack(sym)
    except Exception as e:
        logger.debug(f"[IAM-EXEC] untrack {sym} failed (non-fatal): {e}")


def _contract_from_result(broker_result: Optional[dict]) -> Optional[dict]:
    """
    Pull the option contract the Tradier leg actually selected out of its
    result, so the Robinhood leg can place the SAME contract instead of
    falling back to shares.

    Handles both result shapes:
      • BUY  → _execute_tradier_options returns the contract at the top level.
      • SELL → _execute_tradier returns {"mode": "bear_protect_and_put",
               "close": ..., "put": {...}}, so the contract is nested under
               "put" (the close leg is an equity sell and has no contract).

    Returns None when this signal did not route to options at all — the
    caller then queues an equity signal exactly as before.
    """
    if not isinstance(broker_result, dict):
        return None
    contract = broker_result.get("contract")
    if not contract:
        put_leg = broker_result.get("put")
        if isinstance(put_leg, dict):
            contract = put_leg.get("contract")
    if not isinstance(contract, dict):
        return None
    # Only forward a contract we can actually place: the Robinhood executor
    # refuses an incomplete sniper dict anyway, and forwarding a half-populated
    # one would silently downgrade that refusal into a skipped trade with a
    # confusing reason.
    if not contract.get("strike") or not contract.get("expiration"):
        logger.warning(f"[IAM-EXEC] option contract incomplete {contract} — "
                       f"queuing Robinhood leg as equity instead")
        return None
    return contract


_OCC_OPTION_RE = re.compile(r'^[A-Z]{1,6}\d{6}([CP])\d{8}$')


def _count_open_option_positions(option_type: str) -> int:
    """Real Tradier account state — counts currently-open (qty > 0) option
    positions of the given type via OCC symbol format (root + YYMMDD + C/P +
    strike*1000). Used by the IAM_MAX_OPEN_CALLS/IAM_MAX_OPEN_PUTS comfort cap
    (2026-07-30 operator directive) — account-wide, not per-symbol/system."""
    try:
        from tradier_api import get_positions
        want = "C" if option_type == "call" else "P"
        count = 0
        for p in get_positions():
            if p.get("quantity", 0) <= 0:
                continue
            m = _OCC_OPTION_RE.match((p.get("symbol") or "").upper())
            if m and m.group(1) == want:
                count += 1
        return count
    except Exception as e:
        logger.warning(f"[IAM-EXEC] open-option-position count failed ({option_type}): {e} — failing safe (treat as at-cap)")
        return 10**9  # fail safe: block new entries rather than risk exceeding the cap


def _execute_tradier_options(sym: str, action: str, resolution: dict, price: float,
                              expiry_days_override: int | None = None) -> dict:
    """
    Route IAM action to 0DTE or near-term options via Tradier.
    BUY  → buy calls (action = buy_to_open)
    SELL → buy puts  (action = buy_to_open)
    Contract selection targets the 0.32–0.40 delta bracket (gamma inflection zone).

    `expiry_days_override`, when set, takes precedence over IAM_OPTION_EXPIRY_DAYS —
    used by ODTE_ONLY_SYMBOLS (see _execute_tradier) to force same-day expiry
    regardless of the global setting.
    """
    try:
        from tradier_api import place_option_order
        import tradier_api as tradier
        import execution_quality

        option_type = "call" if action == "BUY" else "put"
        qty         = OPTION_QTY()
        # Same tag resolution _execute_tradier already does, so position_manager
        # can attribute an option exit to the engine that opened it.
        system_tag  = (resolution.get("system") or "IAM").strip().upper()

        # Account-wide open-position comfort cap (2026-07-30 operator directive:
        # "1 call 1 put at a time till i get comfortable"). Real-money only —
        # paper fills never appear in tradier.get_positions(), so this is a
        # no-op (and would always read 0) under PAPER_MODE.
        if not PAPER_MODE():
            cap = MAX_OPEN_CALLS() if option_type == "call" else MAX_OPEN_PUTS()
            if cap > 0:
                open_count = _count_open_option_positions(option_type)
                if open_count >= cap:
                    logger.info(f"[IAM-EXEC] {sym} {option_type} BTO skipped — "
                                f"open {option_type} cap reached ({open_count}/{cap})")
                    return {"status": "skipped", "message": f"{option_type} cap reached ({open_count}/{cap})"}

        # Determine expiry: today for 0DTE, or nearest available.
        # BUG FIX (2026-07-30): this used to call tradier.get_option_chain(),
        # which does not exist anywhere in tradier_api.py (only
        # get_option_chain_schwab_format and get_chain do) -- every options
        # order through this path has been raising AttributeError and
        # returning {"status": "error"} silently since this code was written.
        # This is the real root cause behind "0 puts ever purchased" despite
        # the SELL branch's automatic put-buy already being unconditional on
        # IAM_INSTRUMENT. Also fixed: the target date was a raw calendar-day
        # offset with no check that Tradier actually lists an expiration on
        # that date -- snapped to the nearest REAL listed expiration
        # on/after the target via get_expirations() instead of guessing.
        expiry_days = expiry_days_override if expiry_days_override is not None else OPTION_EXPIRY_DAYS()
        now   = datetime.now(timezone.utc) - timedelta(hours=4)
        target_dt = now + timedelta(days=expiry_days)
        target_str = target_dt.strftime("%Y-%m-%d")

        real_expirations = tradier.get_expirations(sym)
        if not real_expirations:
            return {"status": "error", "message": f"No listed expirations for {sym}"}
        on_or_after = [e for e in sorted(real_expirations) if e >= target_str]
        expiry_str = on_or_after[0] if on_or_after else sorted(real_expirations)[-1]

        # Fetch option chain from Tradier — get_chain() already returns the
        # flat contract list (no ["options"]["option"] unwrapping needed).
        options = tradier.get_chain(sym, expiry_str, greeks=True)
        if not options:
            return {"status": "error", "message": f"No option chain for {sym} {expiry_str}"}

        # Filter by type (call/put)
        filtered = [o for o in options if o.get("option_type") == option_type and price > 0]
        if not filtered:
            return {"status": "error", "message": f"No {option_type}s found in chain"}

        # Delta bracket filter — 0.32–0.40 only (gamma inflection zone)
        d_min = DELTA_MIN()
        d_max = DELTA_MAX()
        d_mid = (d_min + d_max) / 2.0
        bracket = []
        for o in filtered:
            greeks = o.get("greeks") or {}
            raw_delta = greeks.get("delta")
            if raw_delta is None:
                continue
            d = abs(float(raw_delta))  # puts have negative delta — use abs
            if d_min <= d <= d_max:
                bracket.append((d, o))

        if bracket:
            _, best = min(bracket, key=lambda x: abs(x[0] - d_mid))
            chosen_delta = abs(float((best.get("greeks") or {}).get("delta", 0)))
            logger.info(
                f"[IAM-EXEC] {sym} {option_type}: delta bracket [{d_min},{d_max}] "
                f"— {len(bracket)} candidates, picked delta={chosen_delta:.3f}"
            )
        else:
            # No greeks data or nothing in bracket — fall back to nearest ATM by strike
            logger.warning(
                f"[IAM-EXEC] {sym} {option_type}: no contracts in delta [{d_min},{d_max}] "
                f"— falling back to ATM by strike"
            )
            best = min(filtered, key=lambda o: abs(float(o.get("strike", 0)) - price))

        option_symbol = best["symbol"]

        def _f(key):
            try:
                v = best.get(key)
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        bid, ask = _f("bid"), _f("ask")

        # Spread guard on the CONTRACT, which never existed here. The old code
        # priced every entry at ask × 1.05 with no reference to the bid at all,
        # so on a 0.32-0.40Δ contract quoted 1.00 x 1.40 (a 33% spread, routine
        # on the wide scan universe this desk runs) it bought at 1.47 — a
        # position that must gain ~47% just to reach the mid it was worth at
        # the moment of purchase. That single line is a plausible contributor
        # to the "flat entries" symptom on its own.
        # Dead-contract check FIRST. Unlike the equity path (where a missing
        # quote degrades to a bounded fallback), an option with no bid is not a
        # data outage — it is a contract nobody will buy back, so there is no
        # exit at any price. core/api/delta_explosion_bp.py already excludes
        # these from its rankings for exactly this reason; the executor never
        # did. This one refuses to open, and that is deliberate.
        if not execution_quality.have_book(bid, ask):
            msg = (f"{option_symbol} has no real two-sided quote "
                   f"(bid={bid}, ask={ask}) — dead contract, entry refused")
            logger.info(f"[IAM-EXEC] {sym} {option_type} skipped — {msg}")
            return {"status": "skipped", "message": msg}

        ok, why = execution_quality.spread_ok(bid, ask, is_option=True, is_entry=True)
        if not ok:
            logger.info(f"[IAM-EXEC] {sym} {option_type} {option_symbol} skipped — {why}")
            return {"status": "skipped", "message": why}

        limit = execution_quality.marketable_limit(bid, ask, "buy")
        if not limit or limit <= 0:
            return {"status": "skipped",
                    "message": f"could not price {option_symbol} — entry refused (fail closed)"}

        # Premium basis for every downstream stop/trail/target on this
        # position. The mid is the honest mark; the limit is what we might pay.
        premium = (bid + ask) / 2.0 if (bid and ask) else limit

        # The exact contract this leg selected, in the shape the Robinhood PC
        # executor's _execute_option() sniper dict expects. Options are
        # exchange-standardized, so underlying + expiration + strike + type is
        # literally the same contract on both brokers -- passing this through
        # the pending queue is what stops a signal buying a CALL on Tradier and
        # SHARES on Robinhood. Robinhood deliberately never re-derives it.
        chosen_delta = None
        try:
            raw_d = (best.get("greeks") or {}).get("delta")
            chosen_delta = abs(float(raw_d)) if raw_d is not None else None
        except (TypeError, ValueError):
            chosen_delta = None

        contract = {
            "option_type": option_type,
            "strike":      float(best.get("strike") or 0),
            "expiration":  expiry_str,
            "bid":         bid,
            "ask":         ask,
            "premium":     premium,
            "limit_price": limit,
            "delta":       chosen_delta,
            "occ":         option_symbol,
            "source":      f"iam_executor:{system_tag}",
        }

        if PAPER_MODE():
            logger.info(f"[IAM-EXEC][PAPER] Would BTO {qty}x {option_symbol} @ ${limit:.2f} limit")
            _track_option(option_symbol, sym, qty, premium, system_tag, expiry_str)
            return {"mode": "paper", "option_symbol": option_symbol,
                    "qty": qty, "limit": limit, "premium": premium,
                    "contract": contract, "placed": False}

        result = place_option_order(option_symbol, qty, "buy_to_open", limit_price=limit)
        result["option_symbol"] = option_symbol
        result["qty"]           = qty
        result["limit"]         = limit
        result["premium"]       = premium
        result["contract"]      = contract
        if result.get("status") == "success":
            # THE fix for "no options position was ever sold by this executor."
            # Nothing in the IAM path had a sell_to_close anywhere — this hands
            # the contract to position_manager, which owns every exit from here.
            _track_option(option_symbol, sym, qty, premium, system_tag, expiry_str)
        return result

    except Exception as e:
        logger.error(f"[IAM-EXEC] Tradier options error for {sym}: {e}")
        return {"status": "error", "message": str(e)}


# ── Discord alert (for Robinhood client-side polling) ─────────────────────────
def _fire_discord_trade_alert(sym: str, action: str, resolution: dict,
                              time_window: str, confidence: float,
                              broker_result: Optional[dict] = None):
    """
    Posts a rich, copy-paste ready Discord embed for the Robinhood executor
    to pick up (or for manual execution).
    """
    try:
        from discord_alerts import DiscordAlerts
        discord = DiscordAlerts()
        url = discord.webhook_beast or discord.webhook_all
        if not url:
            return

        color = 0x00FF88 if action == "BUY" else 0xFF4444
        stress     = resolution.get("stress_before", resolution.get("total_system_stress", 0))
        rationale  = resolution.get("rationale", "")
        vehicle    = resolution.get("vehicle", "")
        invalidation = resolution.get("invalidation", "")
        confidence_str = f"{confidence:.0f}%"

        # Status line from broker result
        if broker_result:
            if broker_result.get("mode") == "paper":
                broker_line = f"📋 PAPER — {broker_result.get('side','?').upper()} {broker_result.get('qty','?')}x @ ${broker_result.get('price',0):.2f}"
            elif broker_result.get("status") == "success":
                broker_line = f"✅ TRADIER ORDER PLACED — ID: {broker_result.get('order_id','?')}"
            elif broker_result.get("status") == "error":
                broker_line = f"❌ ORDER FAILED — {broker_result.get('message','?')[:60]}"
            else:
                broker_line = "📲 ALERT ONLY — execute manually on Robinhood"
        else:
            broker_line = "📲 ALERT ONLY — execute manually on Robinhood"

        payload = {
            "embeds": [{
                "title": f"⚡ IAM TRADE SIGNAL — {sym} → {action}",
                "description": (
                    f"**IAM Obligation Resolved. The market is forced to act.**\n"
                    f"> {rationale}"
                ),
                "color": color,
                "fields": [
                    {"name": "Action",       "value": f"**{action}**",       "inline": True},
                    {"name": "Window",       "value": time_window,            "inline": True},
                    {"name": "Confidence",   "value": confidence_str,         "inline": True},
                    {"name": "System Stress","value": f"{stress:.1f}%",       "inline": True},
                    {"name": "Vehicle",      "value": vehicle or "—",         "inline": True},
                    {"name": "Broker",       "value": broker_line,            "inline": False},
                    {"name": "Invalidation", "value": invalidation or "—",    "inline": False},
                ],
                "footer": {
                    "text": "IAM v1 | Set IAM_AUTO_TRADING=true + IAM_EXECUTION_MODE=tradier for auto-execution"
                },
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        discord._post(url, payload)
    except Exception as e:
        logger.warning(f"[IAM-EXEC] Discord trade alert failed: {e}")


# ── Main entry point ───────────────────────────────────────────────────────────
def execute_from_resolution(sym: str, resolution: dict,
                            time_window: str, confidence: float,
                            price: float = 0.0):
    """
    Called from iam_bp.py after a successful paid resolution.
    Runs in a daemon thread — never blocks the HTTP response.

    Checks all safety gates, then routes to:
      • Tradier equity or options (if IAM_EXECUTION_MODE=tradier or both)
      • Discord alert for Robinhood (if mode=alert or both)
    """
    try:
        action = resolution.get("action", "HOLD")
        if action == "HOLD":
            logger.debug(f"[IAM-EXEC] {sym} resolved HOLD — no execution")
            return

        # A SELL is treated as an EXIT for gating purposes: its primary job is
        # closing an existing long. Its secondary put-buy leg re-checks the
        # full entry gate separately inside _execute_tradier, so relaxing the
        # gate here never lets an un-vetted new position through.
        is_exit = (action == "SELL")

        # Gate check
        block_reason = _gate_check(sym, resolution, time_window, confidence, is_exit=is_exit)
        if block_reason:
            logger.info(f"[IAM-EXEC] {sym} blocked: {block_reason}")
            return

        # Instant reversal exit — flatten any tracked position that opposes
        # this signal BEFORE doing anything else, rather than waiting for the
        # exit manager's next pass or (worse) the next 300s scanner cycle.
        try:
            import position_manager
            reversed_n = position_manager.on_reversal(sym, action)
            if reversed_n:
                logger.info(f"[IAM-EXEC] {sym} {action} — flattened {reversed_n} opposing position(s) first")
        except Exception as e:
            logger.warning(f"[IAM-EXEC] reversal check failed for {sym} (non-fatal): {e}")

        # Pure Macro Matrix gate — only blocks BUY; SELL/exits always proceed
        if action == "BUY":
            macro = _get_macro_regime(sym)
            if macro == "PERFECT_BEARISH_REGIME":
                logger.warning(
                    f"[IAM-EXEC] {sym} BUY blocked — macro regime is PERFECT_BEARISH_REGIME"
                )
                return
            logger.info(f"[IAM-EXEC] {sym} macro regime={macro} — BUY allowed")

        mode = EXECUTION_MODE()
        logger.info(
            f"[IAM-EXEC] 🎯 {sym} {action} | window={time_window} | "
            f"conf={confidence:.0f}% | mode={mode} | paper={PAPER_MODE()}"
        )

        broker_result = None

        # Primary-system gate: when IAM_PRIMARY_SYSTEM is set, only signals
        # from a system in that set reach the broker — everything else is
        # alert-only. Comma-separated, so multiple systems can be live at once.
        signal_system = (resolution.get("system") or "IAM").strip().upper()
        # Aliases: MM intel scanner historically tagged SML_MM_INTEL; primary list
        # uses SML_MM_V4. Treat them as the same sleeve.
        _MM_ALIASES = {"SML_MM_V4", "SML_MM_INTEL", "SML_MM_V4.0", "MM_V4"}
        if signal_system in _MM_ALIASES:
            signal_system = "SML_MM_V4"
        # Untagged IAM resolutions whose dominant label is MM v4 forced hedge
        # count as SML_MM_V4 so the primary list actually monetizes MM pressure.
        if signal_system in ("", "IAM"):
            dom = str(resolution.get("dominant_label") or resolution.get("engine_version") or "")
            eng = str((resolution.get("detail") or {}).get("engine_version") if isinstance(resolution.get("detail"), dict) else "")
            blob = f"{dom} {eng} {resolution.get('rationale') or ''}".upper()
            if "MM_V4" in blob or "SML_MM_V4" in blob or "MARKET MAKER REPOSITION" in blob:
                signal_system = "SML_MM_V4"
                resolution = dict(resolution)
                resolution["system"] = "SML_MM_V4"
        primary = PRIMARY_SYSTEM()
        # Normalize primary set aliases too
        if primary:
            norm = set()
            for s in primary:
                norm.add("SML_MM_V4" if s in _MM_ALIASES else s)
            primary = norm
        broker_allowed = not primary or signal_system in primary
        if not broker_allowed:
            logger.info(f"[IAM-EXEC] {sym} {action} from {signal_system} — "
                        f"broker execution reserved for primary system(s) {sorted(primary)}; alert-only")

        # ── Tradier execution ──
        if mode in ("tradier", "both") and broker_allowed:
            if not _is_market_hours():
                logger.warning(f"[IAM-EXEC] {sym} Tradier skipped — outside market hours")
            else:
                # One preflight fetch: live NBBO + ATR, reused by the anti-chase
                # guard and by the equity sizing/stop calc below so we don't hit
                # the API twice for the same decision.
                quote, atr_value = _preflight(sym)

                # ANTI-CHASE. The reported symptom is "the bot buys AFTER the
                # move, resulting in flat entries." Structurally that is what
                # these engines do: a daily Donchian break is only knowable at
                # the close of the breakout day, and an S/R pivot is confirmed
                # `bars` bars AFTER the pivot by design (no lookahead). By the
                # time an order is placed, part of the move has already
                # happened. This guard refuses the tail of it.
                #
                # It is a RISK FILTER, not a backtested edge — the published
                # backtests for these systems assumed entry at the signal bar's
                # close, so skipping extended entries makes live behaviour
                # closer to what was measured, not further from it. Entries
                # only; exits are never chase-guarded.
                if action == "BUY" and quote and quote.get("reference"):
                    allowed, why = _chase_check(sym, action, price, quote["reference"])
                    if not allowed:
                        logger.info(f"[IAM-EXEC] {sym} BUY refused — {why}")
                        return

                # Prefer the LIVE price over the scanner's (possibly stale)
                # signal-bar close for everything downstream.
                exec_price = (quote or {}).get("reference") or price or 0.0
                # Carry the gate inputs on a COPY (never mutate the caller's
                # dict) so the SELL branch's put leg can re-run the full entry
                # gate with the same window/confidence this signal arrived on.
                exec_resolution = {**resolution,
                                   "_time_window": time_window,
                                   "resolution_confidence": resolution.get(
                                       "resolution_confidence", confidence)}
                broker_result = _execute_tradier(sym, action, exec_resolution, exec_price,
                                                 quote=quote, atr_value=atr_value)

                if broker_result.get("status") == "success" or broker_result.get("placed") or broker_result.get("mode") == "paper":
                    with _lock:
                        _cooldowns[sym] = time.time()
                        _state["orders_today"] += 1
                        if exec_price > 0:
                            qty = broker_result.get("qty", 1)
                            _state["notional_today"] += exec_price * qty
                        _state["last_order"] = {
                            "symbol": sym, "action": action,
                            "time": datetime.now(timezone.utc).isoformat(),
                            "window": time_window, "confidence": confidence,
                            "paper": PAPER_MODE(),
                        }
                    logger.info(f"[IAM-EXEC] ✅ {sym} {action} — broker_result: {broker_result}")
                else:
                    logger.error(f"[IAM-EXEC] ❌ {sym} order failed: {broker_result}")

        # ── Robinhood pending queue (real order, independent of Tradier) ──
        # Explicit operator decision (2026-07-29): primary-system signals reach
        # BOTH brokers, each placing the trade independently on its own account
        # -- Robinhood holds the funds and has no PDT rule. This does NOT
        # replace the Tradier leg above; both execute. Same mode/broker_allowed
        # gate as Tradier (mode="alert" stays alert-only on both brokers), plus
        # a PAPER_MODE() check since this pushes a REAL order for the PC
        # executor to place -- there is no paper simulation on that end.
        if mode in ("tradier", "both") and broker_allowed and not PAPER_MODE():
            try:
                from core.api.iam_pending_bp import push_iam_primary_signal
                # Forward the exact contract the Tradier leg selected, when it
                # routed to options. Without this the Robinhood leg falls back
                # to shares -- the long-standing inconsistency where one signal
                # bought a CALL on one broker and SHARES on the other.
                contract = _contract_from_result(broker_result)
                push_iam_primary_signal(sym, action, signal_system, price or 0.0,
                                        confidence, contract=contract)
                leg = (f"{contract['option_type'].upper()} {contract['strike']} "
                       f"{contract['expiration']}") if contract else "equity"
                logger.info(f"[IAM-EXEC] {sym} {action} queued for Robinhood pickup "
                            f"(system={signal_system}, leg={leg})")
            except Exception as e:
                logger.debug(f"[IAM-EXEC] Robinhood queue push failed for {sym}: {e}")

        # ── Alert-only path (or mode=alert) ──
        if mode in ("alert", "both"):
            _fire_discord_trade_alert(sym, action, resolution, time_window,
                                      confidence, broker_result)
            # Mark cooldown even for alert-only (no repeat alerts for same signal)
            if mode == "alert":
                with _lock:
                    _cooldowns[sym] = time.time()
                    _state["orders_today"] += 1
                    _state["last_order"] = {
                        "symbol": sym, "action": action,
                        "time": datetime.now(timezone.utc).isoformat(),
                        "window": time_window, "confidence": confidence,
                        "alert_only": True,
                    }

    except Exception as e:
        logger.error(f"[IAM-EXEC] Unexpected error for {sym}: {e}", exc_info=True)


def execute_async(sym: str, resolution: dict, time_window: str,
                  confidence: float, price: float = 0.0):
    """Fire-and-forget wrapper. Call from iam_bp after resolution."""
    t = threading.Thread(
        target=execute_from_resolution,
        args=(sym, resolution, time_window, confidence, price),
        daemon=True,
        name=f"iam-exec-{sym}",
    )
    t.start()
