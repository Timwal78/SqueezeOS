"""
Active Position / Exit Manager
==============================
Closes the single largest hole in this codebase's execution layer:

    iam_executor.py could BUY options but had no code path anywhere that
    could ever SELL one.

`sell_to_close` appears exactly twice in this repo outside its own tests —
both inside tools/gamma_ramp/, a separate desk with its own Robinhood-side
executor. The IAM path (CASCADE / S/R Matrix / Breakout / MM-V4 / S/R
Zone+Pattern / Squeeze Fuel — every system the operator has live-armed) has
`_execute_tradier_options()` for buy_to_open and nothing on the other side.
`_close_equity_position()` only ever closes EQUITY. So with the currently
recommended `IAM_INSTRUMENT=options`, every call and put those systems opened
was held to expiry or closed by hand.

That is also the mechanical reason "sells are consistently late": on the
options leg there were no automated sells at all, and on the equity leg the
only protection was a single static GTC stop placed at entry−N% that never
moved again — so a position that ran up 20% and gave it all back still exited
at the original stop, converting a winner into a full stop-loss.

What this module does
---------------------
Manages ONLY positions this executor itself opened and registered (see
`register_*`). It never adopts, touches, or sells a position the operator
opened by hand, and never opens a position of its own — every order it can
possibly place is a closing sell.

Per position, on a fast loop (default 15s, vs. the 300s scanner cadence):
  1. HARD STOP      — fixed % below entry. Backstop for the equity GTC stop,
                      and the ONLY stop an option position has ever had.
  2. ATR TRAIL      — ratchets up with the position's high-water mark and
                      never loosens. This is what stops giving back a winner.
  3. PROFIT TARGET  — optional fixed R-multiple / % target.
  4. GIVEBACK LOCK  — once a position has been up `arm_pct`, exit if it
                      retraces `giveback_pct` of the peak gain.
  5. TIME STOP      — options only: force-close before expiry rather than
                      letting a contract expire worthless or auto-exercise.
  6. REVERSAL       — `on_reversal(symbol)` lets a scanner flatten instantly
                      on an opposing signal instead of waiting a scan cycle.

Storage: Redis when REDIS_URL is set (the same shared instance CASCADE /
AEO / paper_trade_ledger already use), local JSON otherwise. This matters and
is not a technicality — the JSON fallback does NOT survive a Render redeploy,
so on a redeploy the registry is lost and any open option becomes orphaned
again, exactly the state this module exists to fix. `status()` discloses which
backend actually answered so this is never silently ambiguous.

PAPER MODE is fully respected: it evaluates the same exit logic and records
the close to paper_trade_ledger, but places no broker order.

Environment variables (all optional):
  POSITION_MANAGER_ENABLED     = true   # master switch for the loop
  POSITION_MANAGER_INTERVAL    = 15     # seconds between management passes
  IAM_TRAIL_ATR_MULT           = 2.0    # ATR trailing-stop distance (0 disables)
  IAM_TRAIL_ARM_PCT            = 1.0    # only start trailing once up this %
  IAM_TARGET_PCT               = 0      # fixed profit target %, 0 disables
  IAM_GIVEBACK_ARM_PCT         = 8.0    # arm the giveback lock once up this %
  IAM_GIVEBACK_PCT             = 40.0   # exit after retracing this % of peak gain
  IAM_OPTION_TIME_STOP_MIN     = 30     # close options this many minutes before
                                        #   the 16:00 ET close on expiry day (0 disables)
  IAM_OPTION_HARD_STOP_PCT     = 35.0   # hard stop for OPTION positions, on premium
"""

import os
import json
import time
import logging
import threading
import zoneinfo
from datetime import datetime, time as _dtime
from typing import Optional

logger = logging.getLogger("POSITION-MGR")

_TZ_ET = zoneinfo.ZoneInfo("America/New_York")

_REDIS_URL = os.environ.get("REDIS_URL", "")
_JSON_PATH = os.environ.get("POSITION_MANAGER_JSON_PATH", "position_manager_state.json")
_REDIS_KEY = "position_manager:open"


# ── Config ─────────────────────────────────────────────────────────────────────
def _env_bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("true", "1", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.environ.get(key, default)))
    except (TypeError, ValueError):
        return default


ENABLED              = lambda: _env_bool("POSITION_MANAGER_ENABLED", True)
INTERVAL             = lambda: max(5, _env_int("POSITION_MANAGER_INTERVAL", 15))
TRAIL_ATR_MULT       = lambda: _env_float("IAM_TRAIL_ATR_MULT", 2.0)
TRAIL_ARM_PCT        = lambda: _env_float("IAM_TRAIL_ARM_PCT", 1.0)
TARGET_PCT           = lambda: _env_float("IAM_TARGET_PCT", 0.0)
GIVEBACK_ARM_PCT     = lambda: _env_float("IAM_GIVEBACK_ARM_PCT", 8.0)
GIVEBACK_PCT         = lambda: _env_float("IAM_GIVEBACK_PCT", 40.0)
OPTION_TIME_STOP_MIN = lambda: _env_int("IAM_OPTION_TIME_STOP_MIN", 30)
OPTION_HARD_STOP_PCT = lambda: _env_float("IAM_OPTION_HARD_STOP_PCT", 35.0)


# ── State ──────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_positions: dict = {}      # broker symbol (equity ticker or OCC) -> position dict
_started = False
_status = {
    "running": False,
    "passes": 0,
    "exits_fired_total": 0,
    "last_pass_ts": None,
    "last_exit": None,
    "last_error": None,
}


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning(f"[POSITION-MGR] Redis unavailable ({e}) — falling back to local JSON")
        return None


def _persist():
    """Write the registry through to whichever backend is configured. Best
    effort: a persistence failure must never stop the exit logic from running,
    since an unmanaged position is worse than an unsaved one."""
    try:
        snapshot = {k: dict(v) for k, v in _positions.items()}
        r = _get_redis()
        if r is not None:
            r.set(_REDIS_KEY, json.dumps(snapshot))
            return
        with open(_JSON_PATH, "w") as f:
            json.dump(snapshot, f, indent=2)
    except Exception as e:
        logger.warning(f"[POSITION-MGR] persist failed (non-fatal): {e}")


def _restore():
    """Reload the registry at startup so a redeploy does not orphan open
    positions. Only ever restores entries THIS module wrote."""
    global _positions
    try:
        r = _get_redis()
        raw = None
        if r is not None:
            raw = r.get(_REDIS_KEY)
        elif os.path.exists(_JSON_PATH):
            with open(_JSON_PATH) as f:
                raw = f.read()
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                with _lock:
                    _positions = loaded
                logger.info(f"[POSITION-MGR] restored {len(loaded)} tracked position(s)")
    except Exception as e:
        logger.warning(f"[POSITION-MGR] restore failed (starting empty): {e}")


def backend_name() -> str:
    return "redis" if _get_redis() is not None else "local_json_no_redis_configured"


# ── Registration ───────────────────────────────────────────────────────────────
def register_equity(symbol: str, qty: int, entry_price: float, system: str,
                    atr_value: Optional[float] = None, stop_price: Optional[float] = None):
    """Called by iam_executor right after a real (or paper) equity BUY fill."""
    _register(symbol.upper().strip(), {
        "kind": "equity",
        "symbol": symbol.upper().strip(),
        "underlying": symbol.upper().strip(),
        "qty": int(qty),
        "entry_price": float(entry_price),
        "peak": float(entry_price),
        "atr": float(atr_value) if atr_value else None,
        "hard_stop": float(stop_price) if stop_price else None,
        "system": (system or "IAM").upper(),
        "opened_at": time.time(),
        "expiry": None,
    })


def register_option(option_symbol: str, underlying: str, qty: int, entry_price: float,
                    system: str, expiry: Optional[str] = None):
    """
    Called by iam_executor right after a real (or paper) option buy_to_open.

    `entry_price` is the option PREMIUM per contract, not the underlying's
    price — every stop/trail/target for this position is computed on premium,
    which is the only thing that actually determines this position's P&L.
    """
    _register(option_symbol.upper().strip(), {
        "kind": "option",
        "symbol": option_symbol.upper().strip(),
        "underlying": underlying.upper().strip(),
        "qty": int(qty),
        "entry_price": float(entry_price),
        "peak": float(entry_price),
        "atr": None,  # premium ATR is not available; option stops are % based
        "hard_stop": round(float(entry_price) * (1.0 - OPTION_HARD_STOP_PCT() / 100.0), 2),
        "system": (system or "IAM").upper(),
        "opened_at": time.time(),
        "expiry": expiry,
    })


def _register(key: str, pos: dict):
    with _lock:
        _positions[key] = pos
    _persist()
    logger.info(f"[POSITION-MGR] tracking {pos['kind']} {key} "
                f"{pos['qty']}x @ ${pos['entry_price']:.2f} (system={pos['system']})")


def untrack(symbol: str):
    """Stop managing a position (it was closed elsewhere, or never filled)."""
    with _lock:
        removed = _positions.pop(symbol.upper().strip(), None)
    if removed:
        _persist()
    return removed


def tracked() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _positions.items()}


# ── Pricing ────────────────────────────────────────────────────────────────────
def _current_quote(pos: dict) -> Optional[dict]:
    """
    Real bid/ask/last for the tracked instrument. Tradier's /markets/quotes
    accepts OCC option symbols as well as equity tickers, so one path serves
    both. Returns None on any failure — the caller must then leave the
    position alone rather than acting on a guessed price.
    """
    try:
        import execution_quality
        return execution_quality.live_nbbo(pos["symbol"])
    except Exception as e:
        logger.warning(f"[POSITION-MGR] quote failed for {pos['symbol']}: {e}")
        return None


# ── Exit decision (pure — unit-testable without a broker) ──────────────────────
def evaluate_exit(pos: dict, price: float, now_et: Optional[datetime] = None) -> Optional[str]:
    """
    Returns an exit reason string, or None to hold. Pure function of the
    position dict and the current price — no I/O, so the whole exit policy is
    testable without touching Tradier.

    `pos["peak"]` is expected to already be updated by the caller.
    """
    entry = pos.get("entry_price") or 0.0
    if entry <= 0 or price <= 0:
        return None

    peak = max(pos.get("peak") or entry, entry)
    gain_pct = (price - entry) / entry * 100.0
    peak_gain_pct = (peak - entry) / entry * 100.0

    # 1. HARD STOP — the floor. Never removed, never widened.
    hard = pos.get("hard_stop")
    if hard and price <= hard:
        return f"HARD_STOP @ ${price:.2f} ≤ ${hard:.2f}"

    # 2. PROFIT TARGET
    target = TARGET_PCT()
    if target > 0 and gain_pct >= target:
        return f"TARGET hit +{gain_pct:.1f}% ≥ {target:.1f}%"

    # 3. ATR TRAILING STOP (equity only — needs a real ATR in price units).
    #    Only arms once the position is genuinely in profit, so noise around
    #    the entry cannot stop us out instantly.
    atr_v = pos.get("atr")
    mult = TRAIL_ATR_MULT()
    if atr_v and mult > 0 and peak_gain_pct >= TRAIL_ARM_PCT():
        trail_level = peak - (atr_v * mult)
        if price <= trail_level:
            return (f"ATR_TRAIL @ ${price:.2f} ≤ ${trail_level:.2f} "
                    f"(peak ${peak:.2f} − {mult:.1f}×ATR {atr_v:.2f})")

    # 4. GIVEBACK LOCK — protects a runner that has no meaningful ATR basis
    #    (every option position) once it has actually made money.
    arm = GIVEBACK_ARM_PCT()
    give = GIVEBACK_PCT()
    if arm > 0 and give > 0 and peak_gain_pct >= arm and peak_gain_pct > 0:
        retraced = (peak_gain_pct - gain_pct) / peak_gain_pct * 100.0
        if retraced >= give:
            return (f"GIVEBACK_LOCK — gave back {retraced:.0f}% of a "
                    f"+{peak_gain_pct:.1f}% peak (now +{gain_pct:.1f}%)")

    # 5. TIME STOP (options only) — do not carry a contract into the close on
    #    expiry day. An expiring long option is a guaranteed total loss if it
    #    finishes out of the money, and an unwanted assignment if it doesn't.
    if pos.get("kind") == "option" and pos.get("expiry"):
        mins = OPTION_TIME_STOP_MIN()
        if mins > 0:
            now = now_et or datetime.now(_TZ_ET)
            if now.strftime("%Y-%m-%d") == pos["expiry"]:
                close_dt = now.replace(hour=16, minute=0, second=0, microsecond=0)
                mins_left = (close_dt - now).total_seconds() / 60.0
                if 0 < mins_left <= mins:
                    return f"TIME_STOP — {mins_left:.0f} min to expiry close"

    return None


# ── Order placement ────────────────────────────────────────────────────────────
def _place_exit(pos: dict, quote: dict, reason: str) -> dict:
    """
    Close the position. Exits FAIL OPEN on pricing: if there is no real
    two-sided quote to build a marketable limit from, fall back to a market
    order rather than leaving the position open — being flat matters more
    than the fill.
    """
    import iam_executor

    if iam_executor.PAPER_MODE():
        px = quote.get("reference") or pos["entry_price"]
        logger.info(f"[POSITION-MGR][PAPER] Would CLOSE {pos['symbol']} "
                    f"{pos['qty']}x @ ${px:.2f} — {reason}")
        if pos["kind"] == "equity":
            try:
                import paper_trade_ledger
                paper_trade_ledger.record_close(pos["system"], pos["underlying"], pos["qty"], px)
            except Exception as e:
                logger.warning(f"[POSITION-MGR] paper ledger close failed: {e}")
        return {"mode": "paper", "placed": False, "price": px, "reason": reason}

    try:
        import tradier_api
        import execution_quality

        if pos["kind"] == "option":
            limit = execution_quality.marketable_limit(quote.get("bid"), quote.get("ask"), "sell")
            result = tradier_api.place_option_order(
                pos["symbol"], pos["qty"], "sell_to_close", limit_price=limit
            )
        else:
            # Verify against the REAL account before selling — self-healing if
            # the GTC stop (or anything else) already closed this. Selling a
            # quantity we no longer hold would be a naked short.
            live = tradier_api.get_position(pos["underlying"])
            held = int(live.get("quantity", 0)) if live else 0
            if held <= 0:
                logger.info(f"[POSITION-MGR] {pos['symbol']} already flat on the real "
                            f"account — untracking instead of selling")
                return {"status": "skipped", "message": "already flat", "untrack": True}
            qty = min(pos["qty"], held)
            limit = execution_quality.marketable_limit(quote.get("bid"), quote.get("ask"), "sell")
            if limit:
                result = tradier_api.place_equity_order(
                    pos["underlying"], qty, "sell", order_type="limit",
                    duration="day", limit_price=limit
                )
            else:
                result = tradier_api.place_equity_order(
                    pos["underlying"], qty, "sell", order_type="market", duration="day"
                )
        result["reason"] = reason
        return result
    except Exception as e:
        logger.error(f"[POSITION-MGR] exit order failed for {pos['symbol']}: {e}")
        return {"status": "error", "message": str(e), "reason": reason}


def close_position(symbol: str, reason: str) -> dict:
    """Force-close one tracked position now. Used by the loop and by
    `on_reversal()`."""
    key = symbol.upper().strip()
    with _lock:
        pos = _positions.get(key)
        if not pos:
            return {"status": "skipped", "message": "not tracked"}
        pos = dict(pos)

    quote = _current_quote(pos) or {}
    result = _place_exit(pos, quote, reason)

    ok = (result.get("status") == "success" or result.get("mode") == "paper"
          or result.get("untrack"))
    if ok:
        untrack(key)
        with _lock:
            _status["exits_fired_total"] += 1
            _status["last_exit"] = {
                "symbol": key, "reason": reason,
                "ts": time.time(), "result": result.get("status") or result.get("mode"),
            }
        logger.info(f"[POSITION-MGR] 🔻 CLOSED {key} — {reason}")
    else:
        logger.error(f"[POSITION-MGR] ❌ exit FAILED for {key} — {result} "
                     f"(still tracked, will retry next pass)")
    return result


def on_reversal(underlying: str, new_action: str) -> int:
    """
    Instant flatten on an opposing signal, called by iam_executor before it
    acts on a new signal. Closes every tracked position on `underlying` whose
    direction opposes `new_action`, without waiting for the next management
    pass — this is the "instant signal reversal exit" path.

    Returns the number of positions closed.
    """
    und = underlying.upper().strip()
    closed = 0
    for key, pos in tracked().items():
        if pos.get("underlying") != und:
            continue
        # A long equity or a call is a bullish position; a put is bearish.
        is_bullish = not (pos["kind"] == "option" and _occ_type(pos["symbol"]) == "P")
        opposed = (new_action == "SELL" and is_bullish) or (new_action == "BUY" and not is_bullish)
        if opposed:
            close_position(key, f"REVERSAL — opposing {new_action} signal on {und}")
            closed += 1
    return closed


def _occ_type(occ: str) -> Optional[str]:
    """'C' or 'P' from an OCC symbol (root + YYMMDD + C/P + strike*1000)."""
    import re
    m = re.match(r'^[A-Z]{1,6}\d{6}([CP])\d{8}$', (occ or "").upper())
    return m.group(1) if m else None


# ── Management loop ────────────────────────────────────────────────────────────
def _is_market_hours() -> bool:
    now_et = datetime.now(_TZ_ET)
    if now_et.weekday() >= 5:
        return False
    return _dtime(9, 30) <= now_et.time() < _dtime(16, 0)


def _pass() -> int:
    """One management pass. Returns the number of exits fired."""
    fired = 0
    for key, pos in tracked().items():
        try:
            quote = _current_quote(pos)
            if not quote:
                continue
            price = quote.get("reference")
            if not price or price <= 0:
                continue

            # High-water mark ratchets UP only — a pullback must never lower
            # the peak, or the trailing stop and giveback lock both weaken
            # exactly when they are needed. (This is the same class of bug
            # already found and fixed in tools/gamma_ramp's manage_open().)
            if price > (pos.get("peak") or 0):
                with _lock:
                    if key in _positions:
                        _positions[key]["peak"] = price
                        pos["peak"] = price
                _persist()

            reason = evaluate_exit(pos, price)
            if reason:
                close_position(key, reason)
                fired += 1
        except Exception as e:
            logger.warning(f"[POSITION-MGR] {key}: {e}")
            _status["last_error"] = str(e)
    return fired


def _loop():
    logger.info(f"[POSITION-MGR] Online — managing exits every {INTERVAL()}s "
                f"(backend={backend_name()})")
    _status["running"] = True
    while True:
        try:
            if ENABLED() and _is_market_hours():
                fired = _pass()
                _status["passes"] += 1
                _status["last_pass_ts"] = time.time()
                if fired:
                    logger.info(f"[POSITION-MGR] pass fired {fired} exit(s)")
        except Exception as e:
            logger.error(f"[POSITION-MGR] loop error: {e}", exc_info=True)
            _status["last_error"] = str(e)
        time.sleep(INTERVAL())


def start_position_manager():
    """Idempotent daemon-thread start, matching every other scanner here."""
    global _started
    if _started:
        return
    if not ENABLED():
        logger.info("[POSITION-MGR] disabled via POSITION_MANAGER_ENABLED=false")
        return
    _started = True
    _restore()
    threading.Thread(target=_loop, daemon=True, name="position-manager").start()


def status() -> dict:
    return {
        **{k: v for k, v in _status.items()},
        "enabled": ENABLED(),
        "interval_s": INTERVAL(),
        "backend": backend_name(),
        "tracked_count": len(tracked()),
        "tracked": tracked(),
        "policy": {
            "trail_atr_mult": TRAIL_ATR_MULT(),
            "trail_arm_pct": TRAIL_ARM_PCT(),
            "target_pct": TARGET_PCT(),
            "giveback_arm_pct": GIVEBACK_ARM_PCT(),
            "giveback_pct": GIVEBACK_PCT(),
            "option_time_stop_min": OPTION_TIME_STOP_MIN(),
            "option_hard_stop_pct": OPTION_HARD_STOP_PCT(),
        },
    }
