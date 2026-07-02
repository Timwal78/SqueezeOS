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
  TRADIER_ACCOUNT_ID        = ...        # required for live Tradier orders
"""

import os
import time
import logging
import threading
import zoneinfo
from datetime import datetime, timezone, timedelta, time as _dtime
from typing import Optional

logger = logging.getLogger("IAM-EXEC")

def _get_macro_regime(symbol: str) -> str:
    """
    Returns the 741 Pure Macro regime for a symbol.
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

ARMED              = lambda: _env_bool("IAM_AUTO_TRADING", False)
EXECUTION_MODE     = lambda: os.environ.get("IAM_EXECUTION_MODE", "alert").strip().lower()
INSTRUMENT         = lambda: os.environ.get("IAM_INSTRUMENT",  "equity").strip().lower()
MIN_CONFIDENCE     = lambda: _env_float("IAM_MIN_CONFIDENCE", 70.0)
PAPER_MODE         = lambda: _env_bool("IAM_PAPER_MODE", True)
MAX_SHARES         = lambda: _env_int("IAM_MAX_SHARES", 5)
MAX_ORDER_USD      = lambda: _env_float("IAM_MAX_ORDER_USD", 500.0)
MAX_ORDERS_PER_DAY = lambda: _env_int("IAM_MAX_ORDERS_PER_DAY", 5)
MAX_NOTIONAL_PER_DAY = lambda: _env_float("IAM_MAX_NOTIONAL_PER_DAY", 2000.0)
DAILY_LOSS_LIMIT   = lambda: _env_float("IAM_DAILY_LOSS_LIMIT", 150.0)  # 7% of ~$2k account
COOLDOWN_SECONDS   = lambda: _env_int("IAM_COOLDOWN_SECONDS", 600)   # 10 min default — AMC moves in waves
OPTION_EXPIRY_DAYS = lambda: _env_int("IAM_OPTION_EXPIRY_DAYS", 1)
OPTION_QTY         = lambda: _env_int("IAM_OPTION_CONTRACT_QTY", 1)
DELTA_MIN          = lambda: _env_float("IAM_DELTA_MIN", 0.32)
DELTA_MAX          = lambda: _env_float("IAM_DELTA_MAX", 0.40)

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


# ── Safety gate stack ──────────────────────────────────────────────────────────
def _gate_check(sym: str, resolution: dict, time_window: str,
                confidence: float) -> Optional[str]:
    """
    Returns None if all gates pass, or a reason string if blocked.
    All checks are fast — no network calls.
    """
    _roll_day()

    if not ARMED():
        return "IAM_AUTO_TRADING not enabled"

    mode = EXECUTION_MODE()
    if mode not in ("alert", "tradier", "both"):
        return f"unknown IAM_EXECUTION_MODE={mode}"

    if _state["breaker_tripped"]:
        return f"daily-loss breaker tripped (realized={_state['realized_pnl']:.2f})"

    if not _is_market_hours() and mode != "alert":
        return "outside market hours"

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


# ── Tradier execution ──────────────────────────────────────────────────────────
def _execute_tradier(sym: str, action: str, resolution: dict, price: float) -> dict:
    instrument = INSTRUMENT()
    # Tradier does not support options orders in extended hours — fall back to equity
    if _is_extended_hours():
        logger.info(f"[IAM-EXEC] Extended hours: routing {sym} to equity (options unavailable)")
        return _execute_tradier_equity(sym, action, price)
    # auto mode: try options on any symbol — chain availability is the natural gate.
    # BUY signal → calls; SELL signal → puts. Falls back gracefully if no chain exists.
    if instrument in ("options", "auto"):
        return _execute_tradier_options(sym, action, resolution, price)
    else:
        return _execute_tradier_equity(sym, action, price)


def _execute_tradier_equity(sym: str, action: str, price: float) -> dict:
    try:
        from tradier_api import place_equity_order
        side = "buy" if action == "BUY" else "sell"
        qty  = max(1, min(MAX_SHARES(), int(MAX_ORDER_USD() / price))) if price > 0 else 1

        if PAPER_MODE():
            mode_label = f"EXT-HOURS limit" if _is_extended_hours() else "market"
            logger.info(f"[IAM-EXEC][PAPER] Would {side.upper()} {qty}x {sym} @ ${price:.2f} ({mode_label})")
            return {"mode": "paper", "side": side, "qty": qty, "price": price, "placed": False}

        if _is_extended_hours():
            limit_px = round(price * 1.002, 2) if side == "buy" else round(price * 0.998, 2)
            duration = _ext_hours_duration()
            result = place_equity_order(sym, qty, side, order_type="limit",
                                        duration=duration, limit_price=limit_px)
        else:
            result = place_equity_order(sym, qty, side, order_type="market", duration="day")
        result["qty"]   = qty
        result["price"] = price
        result["side"]  = side
        return result
    except Exception as e:
        logger.error(f"[IAM-EXEC] Tradier equity error for {sym}: {e}")
        return {"status": "error", "message": str(e)}


def _execute_tradier_options(sym: str, action: str, resolution: dict, price: float) -> dict:
    """
    Route IAM action to 0DTE or near-term options via Tradier.
    BUY  → buy calls (action = buy_to_open)
    SELL → buy puts  (action = buy_to_open)
    Contract selection targets the 0.32–0.40 delta bracket (gamma inflection zone).
    """
    try:
        from tradier_api import place_option_order
        import tradier_api as tradier

        # Determine expiry: today for 0DTE, or nearest available
        now   = datetime.now(timezone.utc) - timedelta(hours=4)
        expiry_dt = now + timedelta(days=OPTION_EXPIRY_DAYS())
        # Skip weekends
        while expiry_dt.weekday() >= 5:
            expiry_dt += timedelta(days=1)
        expiry_str = expiry_dt.strftime("%Y-%m-%d")

        option_type = "call" if action == "BUY" else "put"
        qty         = OPTION_QTY()

        # Fetch option chain from Tradier
        chain = tradier.get_option_chain(sym, expiry_str)
        if not chain:
            return {"status": "error", "message": f"No option chain for {sym} {expiry_str}"}

        options = chain.get("options", {}).get("option", [])
        if isinstance(options, dict):
            options = [options]

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
        ask_price     = float(best.get("ask") or best.get("last") or 0)

        if ask_price <= 0:
            return {"status": "error", "message": f"No valid ask for {option_symbol}"}

        # Limit order at ask + 5% slippage
        limit = round(ask_price * 1.05, 2)

        if PAPER_MODE():
            logger.info(f"[IAM-EXEC][PAPER] Would BTO {qty}x {option_symbol} @ ${limit:.2f} limit")
            return {"mode": "paper", "option_symbol": option_symbol,
                    "qty": qty, "limit": limit, "placed": False}

        result = place_option_order(option_symbol, qty, "buy_to_open", limit_price=limit)
        result["option_symbol"] = option_symbol
        result["qty"]           = qty
        result["limit"]         = limit
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

        # Gate check
        block_reason = _gate_check(sym, resolution, time_window, confidence)
        if block_reason:
            logger.info(f"[IAM-EXEC] {sym} blocked: {block_reason}")
            return

        # 741 Pure Macro Matrix gate — only blocks BUY; SELL/exits always proceed
        if action == "BUY":
            macro = _get_macro_regime(sym)
            if macro == "PERFECT_BEARISH_REGIME":
                logger.warning(
                    f"[IAM-EXEC] {sym} BUY blocked — 741 macro regime is PERFECT_BEARISH_REGIME"
                )
                return
            logger.info(f"[IAM-EXEC] {sym} macro regime={macro} — BUY allowed")

        mode = EXECUTION_MODE()
        logger.info(
            f"[IAM-EXEC] 🎯 {sym} {action} | window={time_window} | "
            f"conf={confidence:.0f}% | mode={mode} | paper={PAPER_MODE()}"
        )

        broker_result = None

        # ── Tradier execution ──
        if mode in ("tradier", "both"):
            if not _is_market_hours():
                logger.warning(f"[IAM-EXEC] {sym} Tradier skipped — outside market hours")
            else:
                # Use price from resolution if caller didn't provide live price
                exec_price = price or 0.0
                broker_result = _execute_tradier(sym, action, resolution, exec_price)

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
