"""
SqueezeOS Robinhood Executor — SML Polling Engine
══════════════════════════════════════════════════
Runs as a Windows Service (NSSM). No inbound ports, no tunnel needed.
Polls squeezeos-api.onrender.com/api/beastmode every POLL_INTERVAL_S seconds.
Executes equity orders on Robinhood when GOD_MODE confirmed.

Safety gates:
  - GOD_MODE tier + god_stacked >= MIN_GOD_STACKED (default 5)
  - PDT shield: checks Robinhood portfolio value; if < $2,100 → max 3 day trades / 5 days
  - 5-min per-symbol cooldown
  - KILL_SWITCH env var halts all execution immediately
  - PAPER_MODE logs orders without sending to Robinhood

Runs forever. NSSM restarts it if it crashes.
Logs to: C:\\SqueezeOS\\robinhood_executor.log
"""

import os
import sys
import json
import time
import logging

# Force UTF-8 output so emoji in log messages don't crash on Windows cp1252
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import hmac
import hashlib
import threading
from datetime import datetime
import zoneinfo
from logging.handlers import RotatingFileHandler
from urllib.request import urlopen, Request as URLRequest
from urllib.error import URLError

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.environ.get("DOTENV_PATH",
            os.path.join(os.path.dirname(__file__), "executor.env")),
            override=True)

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_DIR  = os.environ.get("LOG_DIR", r"C:\SqueezeOS")
LOG_FILE = os.path.join(LOG_DIR, "robinhood_executor.log")
os.makedirs(LOG_DIR, exist_ok=True)

_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding='utf-8')
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler, logging.StreamHandler()])
logger = logging.getLogger("RH.Executor")

# ── Configuration ──────────────────────────────────────────────────────────────
SQUEEZEOS_API_URL  = os.environ.get("SQUEEZEOS_API_URL", "https://squeezeos-api.onrender.com")

_macro_cache: dict = {}
_MACRO_CACHE_TTL   = 3600   # matches server-side 1-hour TTL
_MACRO_GATE_SECRET = os.environ.get("MACRO_GATE_SECRET", "")

# Always-watched anchors — injected into every oracle poll regardless of live universe
_MANDATORY_ANCHORS = {"AMC", "GME", "IWM"}

def _get_macro_regime(symbol: str) -> str:
    """
    Query internal 741 macro gate on SqueezeOS server.
    Requires MACRO_GATE_SECRET in executor.env — endpoint is not public.
    Fails open: no secret configured or fetch error → UNKNOWN (never blocks trades).
    Only PERFECT_BEARISH_REGIME blocks BUY orders.
    """
    if not _MACRO_GATE_SECRET:
        return "UNKNOWN"   # no secret → fail open, never block trades
    now = time.time()
    cached = _macro_cache.get(symbol)
    if cached and now - cached["ts"] < _MACRO_CACHE_TTL:
        return cached["regime"]
    try:
        req = URLRequest(f"{SQUEEZEOS_API_URL}/api/macro/{symbol}",
                         headers={"User-Agent": "SqueezeOS-RH-Executor/2.0",
                                  "X-Macro-Secret": _MACRO_GATE_SECRET})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        regime = data.get("regime", "UNKNOWN")
    except Exception as e:
        logger.warning(f"[MACRO] {symbol} regime fetch failed: {e} — failing open")
        regime = "UNKNOWN"
    _macro_cache[symbol] = {"regime": regime, "ts": now}
    return regime


_anchor365_cache: dict = {}
_ANCHOR365_CACHE_TTL = 3600   # daily EMA moves slowly — 1hr cache is plenty


def _get_365_anchor(symbol: str) -> str:
    """
    Query internal 365-day EMA anchor gate on SqueezeOS server (core/api/macro_bp.py).
    Requires MACRO_GATE_SECRET (same secret as the 741 gate) in executor.env —
    endpoint is not public. Fails open: no secret configured or fetch error →
    UNKNOWN (never blocks trades). Returns "ABOVE" | "BELOW" | "UNKNOWN".
    """
    if not _MACRO_GATE_SECRET:
        return "UNKNOWN"
    now = time.time()
    cached = _anchor365_cache.get(symbol)
    if cached and now - cached["ts"] < _ANCHOR365_CACHE_TTL:
        return cached["signal"]
    try:
        req = URLRequest(f"{SQUEEZEOS_API_URL}/api/anchor365/{symbol}",
                         headers={"User-Agent": "SqueezeOS-RH-Executor/2.0",
                                  "X-Macro-Secret": _MACRO_GATE_SECRET})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        signal = data.get("signal", "UNKNOWN")
    except Exception as e:
        logger.warning(f"[365-ANCHOR] {symbol} fetch failed: {e} — failing open")
        signal = "UNKNOWN"
    _anchor365_cache[symbol] = {"signal": signal, "ts": now}
    return signal


ROBINHOOD_USER     = os.environ.get("ROBINHOOD_USERNAME", "")
ROBINHOOD_PASS     = os.environ.get("ROBINHOOD_PASSWORD", "")
POLL_INTERVAL_S    = int(os.environ.get("POLL_INTERVAL_S", "180"))     # poll every 3 minutes
MIN_GOD_STACKED    = int(os.environ.get("MIN_GOD_STACKED", "3"))       # min SET9 stacked to execute (3/6 = 50% convergence, max signal flow)
PDT_BALANCE_LIMIT  = float(os.environ.get("PDT_BALANCE_LIMIT", "2100.0"))
PDT_MAX_TRADES     = int(os.environ.get("PDT_MAX_TRADES", "3"))
PAPER_MODE           = os.environ.get("ROBINHOOD_PAPER_MODE", "false").lower() == "true"
KILL_SWITCH          = os.environ.get("KILL_SWITCH", "false").lower() == "true"
MAX_EQUITY_SHARES    = int(os.environ.get("MAX_EQUITY_SHARES", "500"))  # hard ceiling; real limit is MAX_ORDER_USD
MAX_ORDER_USD        = float(os.environ.get("MAX_ORDER_USD", "150.0"))
MAX_DAILY_LOSS_USD   = float(os.environ.get("MAX_DAILY_LOSS_USD", "100.0"))
MAX_ORDERS_PER_DAY   = int(os.environ.get("MAX_ORDERS_PER_DAY", "25"))
MAX_DAILY_NOTIONAL   = float(os.environ.get("MAX_DAILY_NOTIONAL_USD", "1500.0"))
MAX_PER_SCAN         = int(os.environ.get("MAX_PER_SCAN", "3"))
STOP_LOSS_PCT        = float(os.environ.get("STOP_LOSS_PCT", "5.0"))    # close position if down this % from avg cost
TAKE_PROFIT_PCT      = float(os.environ.get("TAKE_PROFIT_PCT", "15.0")) # close position if up this % from avg cost
POSITION_MONITOR_ENABLED = os.environ.get("POSITION_MONITOR_ENABLED", "true").lower() == "true"

# Symbols that must NEVER be held overnight — 0DTE options only, no equity route.
# Mirrors IAM_ODTE_ONLY_SYMBOLS in iam_executor.py (same operator rule: IWM is
# same-day options only, never purchased for next-day-or-later).
ODTE_ONLY_SYMBOLS = {
    s.strip().upper() for s in os.environ.get("ROBINHOOD_ODTE_ONLY_SYMBOLS", "IWM").split(",") if s.strip()
}

# ── State ──────────────────────────────────────────────────────────────────────
_rh_logged_in   = False
_COOLDOWN_FILE = os.path.join(LOG_DIR, "last_execution.json")

def _load_last_execution() -> dict:
    try:
        with open(_COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_last_execution(d: dict) -> None:
    try:
        with open(_COOLDOWN_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        logger.warning(f"[COOLDOWN] save failed: {e}")

_last_execution     = _load_last_execution()  # symbol → epoch, persisted across restarts
_pdt_trades         = []        # epoch timestamps of day trades
_daily_loss_usd     = 0.0
_orders_today       = 0
_daily_notional_usd = 0.0
_trading_day        = ""        # "YYYY-MM-DD" — reset counters at midnight
_lock               = threading.Lock()


def _reset_daily_if_new_day():
    global _orders_today, _daily_notional_usd, _daily_loss_usd, _trading_day
    today = datetime.now(_ET).strftime("%Y-%m-%d")   # always ET, not system clock
    with _lock:
        if today != _trading_day:
            _trading_day = today
            _orders_today = 0
            _daily_notional_usd = 0.0
            _daily_loss_usd = 0.0
            logger.info(f"[DAILY] New trading day {today} ET — all daily counters reset")

COOLDOWN_S     = int(os.environ.get("COOLDOWN_S", "900"))   # 15-min buy cooldown per symbol (one 15-min bar)
PDT_WINDOW_S   = 5 * 86400 # 5-day rolling window

# Tickers that are bankrupt, delisted, or known OTC junk — never trade these
_BLOCKLIST = {
    "AMCX",   # AMC Networks delisted
    "FXST",   # delisted
    "CODA",   # delisted
    "NKLA",   # Nikola — fraud, near-zero
    "ZXZZT",  # Nasdaq test ticker — not a real security
    "ZVZZT",  # Nasdaq test ticker
    "ZAZZT",  # Nasdaq test ticker
    "ZBZZT",  # Nasdaq test ticker
}


# ── Robinhood login ────────────────────────────────────────────────────────────
_AUTH_FAILURE_ALERTED = False   # only alert Discord once per process until recovered

def _rh_verify_session() -> bool:
    """Return True only if the active session can actually read account data."""
    try:
        import robin_stocks.robinhood as rh
        profile = rh.profiles.load_account_profile()
        return bool(profile and profile.get("account_number"))
    except Exception:
        return False


def _rh_force_reauth() -> bool:
    """
    Hard re-authentication using the stored device_token to bypass MFA.
    Works headlessly as long as the device_token pickle exists.
    Deletes the stale pickle and re-logs in from scratch using device_token.
    """
    import pickle, os, requests
    import robin_stocks.robinhood as rh

    pickle_path = os.path.join(os.path.expanduser("~"), ".tokens", "robinhoodrh_session.pickle")

    device_token = None
    if os.path.exists(pickle_path):
        try:
            with open(pickle_path, "rb") as f:
                stored = pickle.load(f)
            device_token = stored.get("device_token")
        except Exception:
            pass

    if not device_token:
        logger.error("[RH-AUTH] No device_token in pickle — MFA required. Run executor manually once to complete MFA.")
        return False

    # Delete stale pickle so robin_stocks does a clean login
    try:
        os.remove(pickle_path)
    except Exception:
        pass

    try:
        # Pass device_token explicitly so Robinhood skips MFA challenge
        rh.login(
            ROBINHOOD_USER,
            ROBINHOOD_PASS,
            store_session=True,
            pickle_name="rh_session",
            device_token=device_token,
        )
        if _rh_verify_session():
            logger.info("[RH-AUTH] Force re-auth succeeded via device_token")
            return True
        else:
            logger.error("[RH-AUTH] Force re-auth: login returned no exception but session invalid")
            return False
    except Exception as e:
        logger.error(f"[RH-AUTH] Force re-auth failed: {e}")
        return False


def _ensure_login() -> bool:
    global _rh_logged_in, _AUTH_FAILURE_ALERTED
    if _rh_logged_in:
        return True
    if not ROBINHOOD_USER or not ROBINHOOD_PASS:
        logger.error("[RH] ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not set in executor.env")
        return False

    import robin_stocks.robinhood as rh

    # Step 1: try normal login (uses cached pickle / refresh_token)
    try:
        rh.login(ROBINHOOD_USER, ROBINHOOD_PASS, store_session=True, pickle_name="rh_session")
        if _rh_verify_session():
            _rh_logged_in = True
            _AUTH_FAILURE_ALERTED = False
            logger.info("[RH] Session verified — logged in OK")
            return True
        logger.warning("[RH] Normal login returned no error but session invalid — forcing re-auth")
    except Exception as e:
        logger.warning(f"[RH] Normal login error: {e} — forcing re-auth")

    # Step 2: hard re-auth via stored device_token (no MFA required)
    if _rh_force_reauth():
        _rh_logged_in = True
        _AUTH_FAILURE_ALERTED = False
        return True

    # Step 3: complete failure — alert and back off
    _rh_logged_in = False
    if not _AUTH_FAILURE_ALERTED:
        _AUTH_FAILURE_ALERTED = True
        _discord_critical("[RH] ❌ Authentication failed — executor is OFFLINE. Manual MFA re-auth required.")
    return False


def _invalidate_login():
    global _rh_logged_in
    _rh_logged_in = False
    logger.warning("[RH] Session invalidated — will re-auth on next cycle")


def _discord_critical(message: str):
    """Fire a plain-text Discord alert for system-level failures (auth down, circuit tripped, etc.)."""
    try:
        from urllib.request import urlopen, Request as URLRequest
        import json as _json
        url = os.environ.get("DISCORD_WEBHOOK_BEAST", "") or os.environ.get("DISCORD_WEBHOOK_ALL", "")
        if not url:
            return
        payload = _json.dumps({"content": f"🚨 **SQUEEZEOS EXECUTOR** {message}"}).encode()
        req = URLRequest(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=8):
            pass
    except Exception:
        pass


# ── Portfolio value (for PDT check) ───────────────────────────────────────────
def _get_rh_portfolio_value() -> float:
    try:
        import robin_stocks.robinhood as rh
        profile = rh.profiles.load_portfolio_profile()
        equity  = profile.get("equity") or profile.get("extended_hours_equity") or "0"
        return float(equity)
    except Exception as e:
        logger.warning(f"[RH] Could not fetch portfolio value: {e}")
        return 0.0  # fail-safe: assume below PDT limit, enforce restrictions


# ── PDT shield ─────────────────────────────────────────────────────────────────
def _pdt_allowed() -> bool:
    now = time.time()
    cutoff = now - PDT_WINDOW_S
    with _lock:
        _pdt_trades[:] = [t for t in _pdt_trades if t > cutoff]
        balance = _get_rh_portfolio_value()
        if balance < PDT_BALANCE_LIMIT:
            if len(_pdt_trades) >= PDT_MAX_TRADES:
                logger.warning(
                    f"[PDT] BLOCKED — balance ${balance:.2f} < ${PDT_BALANCE_LIMIT} "
                    f"and {len(_pdt_trades)}/{PDT_MAX_TRADES} day trades used"
                )
                return False
            logger.info(f"[PDT] Balance ${balance:.2f} — PDT active: {len(_pdt_trades)+1}/{PDT_MAX_TRADES}")
        else:
            logger.info(f"[PDT] Balance ${balance:.2f} — above PDT limit, full trading allowed")
        _pdt_trades.append(now)
    return True


# ── Circuit breaker ────────────────────────────────────────────────────────────
def _circuit_open() -> bool:
    if KILL_SWITCH:
        logger.warning("[CIRCUIT] KILL_SWITCH=true — all execution halted")
        return True
    with _lock:
        if _daily_loss_usd >= MAX_DAILY_LOSS_USD:
            logger.warning(f"[CIRCUIT] Daily loss ${_daily_loss_usd:.2f} >= limit ${MAX_DAILY_LOSS_USD}")
            return True
        if _orders_today >= MAX_ORDERS_PER_DAY:
            logger.warning(f"[CIRCUIT] Daily order cap reached: {_orders_today}/{MAX_ORDERS_PER_DAY} — no more orders today")
            return True
        if _daily_notional_usd >= MAX_DAILY_NOTIONAL:
            logger.warning(f"[CIRCUIT] Daily notional ${_daily_notional_usd:.2f} >= cap ${MAX_DAILY_NOTIONAL} — halted")
            return True
    return False


# ── Market hours guard ─────────────────────────────────────────────────────────
_ET = zoneinfo.ZoneInfo("America/New_York")

def _market_open() -> bool:
    """Returns True during regular hours AND extended hours (4:00–20:00 ET) Mon–Fri."""
    now_et = datetime.now(_ET)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    t = now_et.time()
    from datetime import time as dtime
    return dtime(4, 0) <= t < dtime(20, 0)

def _is_extended_hours() -> bool:
    """True if currently in pre-market (4:00–9:30) or after-hours (16:00–20:00) ET."""
    now_et = datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    from datetime import time as dtime
    return dtime(4, 0) <= t < dtime(9, 30) or dtime(16, 0) <= t < dtime(20, 0)


# ── Discord alert ──────────────────────────────────────────────────────────────
_DISCORD_URL = os.environ.get("DISCORD_WEBHOOK_BEAST", "") or os.environ.get("DISCORD_WEBHOOK_ALL", "")

def _discord(symbol: str, side: str, qty: int, price: float, sml: dict, result: dict):
    if not _DISCORD_URL:
        return
    mode   = "📋 PAPER" if PAPER_MODE else "🔴 LIVE"
    placed = result.get("placed") or result.get("paper")
    error  = result.get("error")
    status = "✅ EXECUTED" if placed else (f"❌ {error}" if error else "⏭️ SKIPPED")
    payload = {"embeds": [{"title": f"⚡ GOD MODE {side.upper()} — {symbol} [{mode}]",
        "color": 0x00FF66 if placed else 0xFF0055,
        "fields": [
            {"name": "Status",       "value": status,                          "inline": True},
            {"name": "Mode",         "value": mode,                            "inline": True},
            {"name": "Order",        "value": f"{qty}x {symbol} @ ${price:.2f}", "inline": True},
            {"name": "SET9 Stacked", "value": f"{sml.get('god_stacked',0)}/6", "inline": True},
            {"name": "Score",        "value": str(sml.get("harmonic_score",0)),"inline": True},
        ],
        "footer": {"text": "ScriptMaster Labs | SqueezeOS | Robinhood Executor"},
        "timestamp": datetime.now().isoformat(),
    }]}
    try:
        import urllib.request as _ul
        data = json.dumps(payload).encode()
        req  = _ul.Request(_DISCORD_URL, data=data, headers={"Content-Type": "application/json"})
        with _ul.urlopen(req, timeout=8):
            pass
    except Exception as e:
        logger.warning(f"[Discord] Failed: {e}")


def _direction_gates_pass(symbol: str, side: str, log_prefix: str = "EXEC") -> bool:
    """
    Shared pre-trade direction gates — 741 macro regime, 365-day EMA anchor,
    Proprietary 5-EMA stack, and dark-pool volume (321 anchor). Used by both
    the equity path (_execute) and the options path (_execute_option) so a
    contract buy is never allowed to skip checks a share buy would have to
    pass. All gates fail OPEN (never block) on missing secrets or fetch
    errors — an unreachable check must never widen what already blocked.
    Returns True if the trade may proceed.
    """
    # ── 741 Pure Macro Matrix gate (BUY only) ────────────────────────────────
    if side == "buy":
        macro = _get_macro_regime(symbol)
        if macro == "PERFECT_BEARISH_REGIME":
            logger.warning(f"[{log_prefix}] {symbol} BUY blocked — 741 macro regime is PERFECT_BEARISH_REGIME")
            return False
        logger.info(f"[{log_prefix}] {symbol} macro regime={macro} — BUY allowed")

        # ── 365-day EMA anchor gate (BUY only) ───────────────────────────────
        anchor365 = _get_365_anchor(symbol)
        if anchor365 == "BELOW":
            logger.warning(f"[{log_prefix}] {symbol} BUY blocked — price is BELOW the 365-day EMA anchor")
            return False
        logger.info(f"[{log_prefix}] {symbol} 365-day anchor={anchor365} — BUY allowed")

    # ── Proprietary 5-EMA Stack + Dark-Pool Volume (321) Guardrails ─────────
    try:
        url = f"{SQUEEZEOS_API_URL}/api/ema/{symbol}"
        req = URLRequest(url, headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=10) as resp:
            ema_data = json.loads(resp.read())

        if ema_data.get("status") == "success":
            suite = ema_data.get("ema_suite", {})
            e5 = suite.get("engine_5", {})
            e5_signal = e5.get("signal", "")
            if side == "buy" and e5_signal == "BEAR_STACK_5EMA":
                logger.warning(f"[{log_prefix}] {symbol} blocked — Proprietary 5-EMA stack is BEARISH")
                return False
            if side == "sell" and e5_signal == "BULL_STACK_5EMA":
                logger.warning(f"[{log_prefix}] {symbol} blocked — Proprietary 5-EMA stack is BULLISH")
                return False

            # Engine 3 — dark-pool volume kinetics (the "321" anchor). Volume
            # distribution (mirror_lock_bear) on a BUY, or fresh accumulation
            # (mirror_lock_bull) on a SELL/close, is the same "don't fight the
            # tape" logic already applied to Engine 5 above.
            e3 = suite.get("engine_3", {})
            if side == "buy" and (e3.get("mirror_lock_bear") or e3.get("signal") == "DISTRIBUTION"):
                logger.warning(f"[{log_prefix}] {symbol} blocked — dark-pool volume (321) shows DISTRIBUTION")
                return False
            if side == "sell" and e3.get("signal") in ("DARK_POOL_CEILING_BREACH", "DARK_POOL_ACCUMULATION"):
                logger.warning(f"[{log_prefix}] {symbol} blocked — dark-pool volume (321) shows active ACCUMULATION")
                return False
    except Exception as e:
        logger.warning(f"[{log_prefix}] Proprietary 5-EMA/321 check failed for {symbol}: {e}")

    return True


# ── Order execution ────────────────────────────────────────────────────────────
def _execute(symbol: str, side: str, sml: dict, scan_counter: list):
    """scan_counter is a single-element list [n] so callers can track per-scan count."""
    global _orders_today, _daily_notional_usd, _daily_loss_usd
    if _circuit_open():
        return

    if symbol in _BLOCKLIST:
        logger.warning(f"[EXEC] {symbol} is on the blocklist (bankrupt/delisted) — skip")
        return

    if scan_counter[0] >= MAX_PER_SCAN:
        logger.info(f"[EXEC] {symbol} — per-scan batch limit {MAX_PER_SCAN} reached, deferring to next cycle")
        return

    now  = time.time()
    last = _last_execution.get(symbol, 0)
    # Cooldown only applies to BUY — never block an exit (position check is the SELL gate).
    if side == "buy" and now - last < COOLDOWN_S:
        logger.info(f"[EXEC] {symbol} BUY cooldown — {int(COOLDOWN_S-(now-last))}s left")
        return

    god_count = sml.get("god_stacked", 0)
    if god_count < MIN_GOD_STACKED:
        logger.info(f"[EXEC] {symbol} god_stacked={god_count} < {MIN_GOD_STACKED} — skip")
        return

    if not _direction_gates_pass(symbol, side, log_prefix="EXEC"):
        return

    # 0DTE-only symbols (IWM) trade options only — never buy shares. The beastmode
    # poll routes these through _execute_option() with a real sniper contract
    # before ever reaching this function; this branch only exists as a fallback
    # for the TV webhook / oracle poll paths, which don't have a server-selected
    # contract available, so they can only alert rather than auto-execute.
    if symbol in ODTE_ONLY_SYMBOLS:
        if now - last >= COOLDOWN_S:
            _last_execution[symbol] = now
            _save_last_execution(_last_execution)
            logger.info(f"[EXEC] {symbol} GOD MODE {god_count}/6 — 0DTE OPTIONS ALERT ONLY (no sniper contract available on this path)")
            try:
                price = 0.0
                import robin_stocks.robinhood as rh
                price = float(rh.stocks.get_latest_price(symbol)[0] or 0)
            except Exception:
                pass
            _discord(symbol, "ALERT", 0, price, sml, {"alert_only": True, "note": "IWM 0DTE — manual options entry only"})
        return

    if not _pdt_allowed():
        return

    # Cooldown write happens AFTER PDT check so a blocked trade doesn't lock the symbol
    _last_execution[symbol] = now
    _save_last_execution(_last_execution)

    # Get live price from Robinhood
    try:
        import robin_stocks.robinhood as rh
        price = float(rh.stocks.get_latest_price(symbol)[0] or 0)
    except Exception:
        price = 0.0

    if price <= 0:
        logger.warning(f"[EXEC] {symbol} no live price — abort")
        return

    avg_cost = 0.0
    if side == "sell":
        # Sell only what we actually own — never short, never guess quantity.
        try:
            import robin_stocks.robinhood as rh
            positions = rh.account.get_open_stock_positions()
            owned_qty = 0
            for pos in (positions or []):
                try:
                    instr = rh.stocks.get_instrument_by_url(pos["instrument"])
                    if (instr or {}).get("symbol", "").upper() == symbol:
                        owned_qty = int(float(pos.get("quantity") or 0))
                        avg_cost = float(pos.get("average_buy_price") or 0)
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[EXEC] {symbol} SELL — could not fetch position: {e}")
            owned_qty = 0

        if owned_qty <= 0:
            logger.info(f"[EXEC] {symbol} SELL signal — no position to close, skipping (no shorts)")
            return
        qty = owned_qty
        logger.info(f"[EXEC] {symbol} SELL — closing full position: {qty} shares @ ${price:.2f}")
    else:
        qty = max(1, int(MAX_ORDER_USD // price))
        qty = min(qty, MAX_EQUITY_SHARES)
        # Never exceed what's left of today's notional budget
        with _lock:
            remaining_notional = MAX_DAILY_NOTIONAL - _daily_notional_usd
        budget_qty = max(1, int(remaining_notional // price))
        qty = min(qty, budget_qty)
        if qty <= 0:
            logger.warning(f"[EXEC] {symbol} BUY — daily notional budget exhausted, skipping")
            return

    logger.info(f"[EXEC] RH GOD MODE — {side.upper()} {qty}x {symbol} @ ${price:.2f} | SET9:{god_count}/6")

    result = {}
    if PAPER_MODE:
        logger.info(f"[PAPER] Would {side.upper()} {qty}x {symbol} @ ${price:.2f}")
        result = {"paper": True}
        scan_counter[0] += 1
        with _lock:
            _orders_today += 1
            _daily_notional_usd += qty * price
            logger.info(f"[DAILY] Orders: {_orders_today}/{MAX_ORDERS_PER_DAY} | Notional: ${_daily_notional_usd:.2f}/${MAX_DAILY_NOTIONAL:.0f}")
    else:
        if not _ensure_login():
            result = {"error": "login_failed"}
        else:
            try:
                import robin_stocks.robinhood as rh
                # robin_stocks defaults timeInForce to "gtc" on every order_* helper, but
                # Robinhood rejects GTC on market orders ("Invalid Good Til Canceled order.")
                # since a market order fills-or-dies immediately — there's nothing to leave
                # open. Extended-hours orders are day-only for the same reason (they can't
                # carry into the next session). Every order below must be explicit "gfd".
                if _is_extended_hours():
                    if side == "buy":
                        limit_px = round(price * 1.002, 2)  # 0.2% above last price to ensure fill
                        r = rh.orders.order_buy_limit(symbol, qty, limit_px, timeInForce="gfd", extendedHours=True)
                        logger.info(f"[RH] Extended hours BUY LIMIT {qty}x {symbol} @ ${limit_px:.2f}")
                    else:
                        limit_px = round(price * 0.998, 2)  # 0.2% below last price to ensure fill
                        r = rh.orders.order_sell_limit(symbol, qty, limit_px, timeInForce="gfd", extendedHours=True)
                        logger.info(f"[RH] Extended hours SELL LIMIT {qty}x {symbol} @ ${limit_px:.2f}")
                elif side == "buy":
                    r = rh.orders.order_buy_market(symbol, qty, timeInForce="gfd")
                else:
                    r = rh.orders.order_sell_market(symbol, qty, timeInForce="gfd")
                # Log full raw response so we can see exactly what Robinhood returns
                logger.info(f"[RH] Raw response for {symbol}: {r}")
                rh_detail = (r or {}).get("detail", "") if isinstance(r, dict) else ""
                rh_state  = (r or {}).get("state", "") if isinstance(r, dict) else ""
                order_id  = (r or {}).get("id", "") or (r or {}).get("order_id", "") or "no-id"
                order_id  = str(order_id) if order_id else "no-id"
                _GOOD_STATES = {"confirmed", "queued", "unconfirmed", "partially_filled", "filled"}
                if rh_state in _GOOD_STATES:
                    logger.info(f"[RH] Order confirmed {symbol} {side} x{qty} | id={order_id} state={rh_state}")
                    result = {"placed": True, "raw": r}
                    scan_counter[0] += 1
                    with _lock:
                        _orders_today += 1
                        _daily_notional_usd += qty * price
                        # Realized P&L on this exit — the only place _daily_loss_usd is
                        # ever updated. Without this the MAX_DAILY_LOSS_USD circuit
                        # breaker is checked every cycle but never actually trips.
                        if side == "sell" and avg_cost > 0:
                            realized_pnl = (price - avg_cost) * qty
                            if realized_pnl < 0:
                                _daily_loss_usd += abs(realized_pnl)
                                logger.warning(f"[DAILY] Realized loss ${abs(realized_pnl):.2f} on {symbol} — daily loss now ${_daily_loss_usd:.2f}/${MAX_DAILY_LOSS_USD:.0f}")
                            else:
                                logger.info(f"[DAILY] Realized gain ${realized_pnl:.2f} on {symbol}")
                        logger.info(f"[DAILY] Orders: {_orders_today}/{MAX_ORDERS_PER_DAY} | Notional: ${_daily_notional_usd:.2f}/${MAX_DAILY_NOTIONAL:.0f}")
                else:
                    logger.error(f"[RH] Order NOT confirmed {symbol} {side}: state='{rh_state}' detail='{rh_detail}'")
                    result = {"error": rh_detail or rh_state or "unknown", "raw": r}
            except Exception as e:
                err = str(e)
                logger.error(f"[RH] Order error: {err}")
                if "logged in" in err.lower():
                    _invalidate_login()
                result = {"error": err}

    _discord(symbol, side, qty, price, sml, result)


# ── Position monitor — the only price-based exit in this executor ──────────────
# Every other SELL path (GOD_MODE bear reversal, Oracle SELL/SHIELD) is
# signal-based only: a position can sit through an arbitrary drawdown waiting
# for an equally rare opposing signal to fire. This runs every poll cycle,
# before any new BUY signals are processed, and closes anything that's moved
# past STOP_LOSS_PCT or TAKE_PROFIT_PCT from its average cost basis.
def _check_stop_losses() -> int:
    if not POSITION_MONITOR_ENABLED or PAPER_MODE:
        return 0
    if not _ensure_login():
        return 0

    try:
        import robin_stocks.robinhood as rh
        positions = rh.account.get_open_stock_positions()
    except Exception as e:
        logger.warning(f"[STOP-LOSS] could not fetch positions: {e}")
        return 0

    scan_counter = [0]
    placed = 0
    for pos in (positions or []):
        try:
            qty = float(pos.get("quantity") or 0)
            avg_cost = float(pos.get("average_buy_price") or 0)
            if qty <= 0 or avg_cost <= 0:
                continue
            import robin_stocks.robinhood as rh
            instr = rh.stocks.get_instrument_by_url(pos["instrument"])
            symbol = (instr or {}).get("symbol", "").upper()
            if not symbol:
                continue
            price = float(rh.stocks.get_latest_price(symbol)[0] or 0)
            if price <= 0:
                continue
            pct_move = (price - avg_cost) / avg_cost * 100.0

            if pct_move <= -STOP_LOSS_PCT:
                logger.warning(f"[STOP-LOSS] {symbol} down {pct_move:.1f}% (avg ${avg_cost:.2f} -> ${price:.2f}) — closing position")
                sml_proxy = {"god_stacked": MIN_GOD_STACKED, "tier": "GOD_MODE", "signal": "STOP_LOSS"}
                _execute(symbol, "sell", sml_proxy, scan_counter)
                placed += 1
            elif pct_move >= TAKE_PROFIT_PCT:
                logger.info(f"[TAKE-PROFIT] {symbol} up {pct_move:.1f}% (avg ${avg_cost:.2f} -> ${price:.2f}) — closing position")
                sml_proxy = {"god_stacked": MIN_GOD_STACKED, "tier": "GOD_MODE", "signal": "TAKE_PROFIT"}
                _execute(symbol, "sell", sml_proxy, scan_counter)
                placed += 1
        except Exception as e:
            logger.warning(f"[STOP-LOSS] position check error: {e}")

    return placed


ROBINHOOD_OPTION_QTY = int(os.environ.get("ROBINHOOD_OPTION_QTY", "1"))


def _discord_option(symbol: str, option_type: str, sniper: dict, qty: int, limit_price: float, sml: dict, result: dict):
    if not _DISCORD_URL:
        return
    mode   = "📋 PAPER" if PAPER_MODE else "🔴 LIVE"
    placed = result.get("placed") or result.get("paper")
    error  = result.get("error")
    status = "✅ EXECUTED" if placed else (f"❌ {error}" if error else "⏭️ SKIPPED")
    payload = {"embeds": [{"title": f"⚡ GOD MODE {option_type.upper()} — {symbol} [{mode}]",
        "color": 0x00FF66 if placed else 0xFF0055,
        "fields": [
            {"name": "Status",     "value": status,                                                     "inline": True},
            {"name": "Mode",       "value": mode,                                                        "inline": True},
            {"name": "Contract",   "value": f"{qty}x {symbol} {sniper.get('strike')}{option_type[0].upper()} {sniper.get('expiration')} @ ${limit_price:.2f}", "inline": False},
            {"name": "Delta",      "value": str(sniper.get("delta", "—")),                                "inline": True},
            {"name": "SET9 Stacked","value": f"{sml.get('god_stacked',0)}/6",                            "inline": True},
        ],
        "footer": {"text": "ScriptMaster Labs | SqueezeOS | Robinhood Executor"},
        "timestamp": datetime.now().isoformat(),
    }]}
    try:
        import urllib.request as _ul
        data = json.dumps(payload).encode()
        req  = _ul.Request(_DISCORD_URL, data=data, headers={"Content-Type": "application/json"})
        with _ul.urlopen(req, timeout=8):
            pass
    except Exception as e:
        logger.warning(f"[Discord] Option alert failed: {e}")


def _execute_option(symbol: str, option_type: str, sml: dict, sniper: dict, scan_counter: list):
    """
    Buy-to-open a single option contract on Robinhood using the contract already
    selected server-side (core/convergence_engine.py's scan_options() — same
    0.35-0.45 delta bracket logic Tradier execution uses). We never re-derive
    strike/expiration/delta locally: the server picked one specific listed
    contract, and that's the one we place on Robinhood — same underlying,
    same exchange-standardized strike/expiration, different broker.

    Only ever buy_to_open. No naked options, no selling to open, no shorting.
    """
    global _orders_today, _daily_notional_usd
    if _circuit_open():
        return
    if symbol in _BLOCKLIST:
        logger.warning(f"[EXEC-OPT] {symbol} is on the blocklist — skip")
        return
    if scan_counter[0] >= MAX_PER_SCAN:
        logger.info(f"[EXEC-OPT] {symbol} — per-scan batch limit {MAX_PER_SCAN} reached, deferring")
        return
    if sniper.get("error"):
        logger.info(f"[EXEC-OPT] {symbol} {option_type} — no contract available: {sniper['error']}")
        return

    strike     = sniper.get("strike")
    expiration = sniper.get("expiration")
    ask        = sniper.get("ask") or sniper.get("premium")
    try:
        strike = float(strike)
        ask    = float(ask)
    except (TypeError, ValueError):
        strike = None
        ask    = 0.0

    if not strike or not expiration or ask <= 0:
        logger.warning(f"[EXEC-OPT] {symbol} {option_type} — incomplete contract from server (strike={strike} exp={expiration} ask={ask}) — skip")
        return

    # Same direction gates as the equity path (741 macro / 365 anchor / 5-EMA /
    # 321 dark-pool volume). A call is a bullish bet same as a share buy, so it
    # goes through the "buy" gates. A put is the bearish/protective side — those
    # same bearish-blocking gates would be backwards here, so puts skip them
    # entirely (mirrors how _execute()'s "sell" side only gets the inverse checks).
    if option_type == "call" and not _direction_gates_pass(symbol, "buy", log_prefix="EXEC-OPT"):
        return

    if not _pdt_allowed():
        return

    now = time.time()
    _last_execution[symbol] = now
    _save_last_execution(_last_execution)

    qty         = ROBINHOOD_OPTION_QTY
    limit_price = round(ask * 1.05, 2)   # 5% above ask, matches Tradier route's slippage buffer
    cost        = limit_price * 100 * qty

    with _lock:
        remaining_notional = MAX_DAILY_NOTIONAL - _daily_notional_usd
    if cost > remaining_notional:
        logger.warning(f"[EXEC-OPT] {symbol} {option_type} — ${cost:.2f} would exceed remaining daily notional budget (${remaining_notional:.2f} left), skipping")
        return

    logger.info(
        f"[EXEC-OPT] RH GOD MODE — BUY {qty}x {symbol} {strike}{option_type[0].upper()} "
        f"{expiration} @ ${limit_price:.2f} limit | delta={sniper.get('delta')}"
    )

    result = {}
    if PAPER_MODE:
        logger.info(f"[PAPER] Would BUY {qty}x {symbol} {strike}{option_type[0].upper()} {expiration} @ ${limit_price:.2f}")
        result = {"paper": True}
        scan_counter[0] += 1
        with _lock:
            _orders_today += 1
            _daily_notional_usd += cost
    else:
        if not _ensure_login():
            result = {"error": "login_failed"}
        else:
            try:
                import robin_stocks.robinhood as rh
                r = rh.orders.order_buy_option_limit(
                    positionEffect="open",
                    creditOrDebit="debit",
                    price=limit_price,
                    symbol=symbol,
                    quantity=qty,
                    expirationDate=expiration,
                    strike=strike,
                    optionType=option_type,
                    timeInForce="gtc",
                )
                logger.info(f"[RH] Raw option response for {symbol}: {r}")
                rh_state = (r or {}).get("state", "") if isinstance(r, dict) else ""
                order_id = str((r or {}).get("id", "") or (r or {}).get("order_id", "") or "no-id") if isinstance(r, dict) else "no-id"
                _GOOD_STATES = {"confirmed", "queued", "unconfirmed", "partially_filled", "filled"}
                if rh_state in _GOOD_STATES or (isinstance(r, dict) and "id" in r):
                    logger.info(f"[RH] Option order confirmed {symbol} {option_type} x{qty} | id={order_id} state={rh_state}")
                    result = {"placed": True, "raw": r}
                    scan_counter[0] += 1
                    with _lock:
                        _orders_today += 1
                        _daily_notional_usd += cost
                else:
                    err_detail = (r or {}).get("detail", "") if isinstance(r, dict) else str(r)
                    logger.error(f"[RH] Option order NOT confirmed {symbol} {option_type}: {err_detail}")
                    result = {"error": err_detail or "unknown", "raw": r}
            except Exception as e:
                err = str(e)
                logger.error(f"[RH] Option order error: {err}")
                if "logged in" in err.lower():
                    _invalidate_login()
                result = {"error": err}

    _discord_option(symbol, option_type, sniper, qty, limit_price, sml, result)


# ── Beastmode poll (server-side SET9 convergence scanner) ─────────────────────
def _poll_beastmode() -> int:
    """Returns number of orders placed this poll. 0 = no signals or all filtered."""
    url = f"{SQUEEZEOS_API_URL}/api/beastmode"
    try:
        req = URLRequest(url, headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[POLL] beastmode fetch failed: {e}")
        return 0

    if data.get("status") != "success":
        logger.warning(f"[POLL] beastmode status={data.get('status')} — server may be down or scan failed")
        return 0

    signals   = data.get("signals") or []
    cache_age = data.get("cache_age_s")
    stale     = data.get("stale", False)
    age_str   = f", cache {cache_age:.0f}s old{'  (STALE)' if stale else ''}" if cache_age is not None else ""
    now       = time.time()

    if not signals:
        logger.info(f"[POLL] beastmode: 0 signals from server{age_str} — scan universe warming up or no convergence yet")
        return 0

    # Accept GOD_MODE, DUAL_GRID_LOCK, and GRID_LOCK tiers
    # GRID_LOCK is one tier below GOD_MODE — valid signal, requires stacked >= 2
    _VALID_TIERS     = {"GOD_MODE", "DUAL_GRID_LOCK", "GRID_LOCK"}
    _TIER_MIN_STACK  = {"GOD_MODE": MIN_GOD_STACKED, "DUAL_GRID_LOCK": MIN_GOD_STACKED, "GRID_LOCK": max(2, MIN_GOD_STACKED - 1)}

    god_hits = []
    skipped  = {"no_tier": 0, "low_stack": 0, "cooldown": 0, "blocklist": 0}

    for hit in signals:
        symbol  = (hit.get("symbol") or "").upper().strip()
        sml     = hit.get("sml_matrix") or {}
        sniper  = hit.get("options_sniper") or {}
        tier    = sml.get("tier", "")
        stacked = sml.get("god_stacked", 0)
        signal  = sml.get("signal", "")
        # Infer tier from signal name when tier field is absent/unknown
        if tier not in _VALID_TIERS:
            if "DUAL" in signal.upper():
                tier = "DUAL_GRID_LOCK"
            elif "GRID" in signal.upper():
                tier = "GRID_LOCK"
        effective_tier = tier if tier in _VALID_TIERS else tier
        if effective_tier not in _VALID_TIERS:
            skipped["no_tier"] += 1
            continue
        min_stack = _TIER_MIN_STACK.get(effective_tier, MIN_GOD_STACKED)
        if stacked < min_stack:
            skipped["low_stack"] += 1
            logger.debug(f"[POLL] {symbol} {tier} stacked={stacked} < {min_stack} — skip")
            continue
        if symbol in _BLOCKLIST:
            skipped["blocklist"] += 1
            continue
        cooldown_remaining = COOLDOWN_S - (now - _last_execution.get(symbol, 0))
        if cooldown_remaining > 0:
            skipped["cooldown"] += 1
            logger.info(f"[POLL] {symbol} {effective_tier} {stacked}/6 — cooldown {int(cooldown_remaining)}s left")
            continue
        god_hits.append((symbol, sml, effective_tier, sniper))

    logger.info(
        f"[POLL] beastmode: {len(signals)} raw | {len(god_hits)} ready | "
        f"skipped: {skipped['no_tier']} wrong-tier, {skipped['low_stack']} low-stack, "
        f"{skipped['cooldown']} cooldown, {skipped['blocklist']} blocklist{age_str}"
    )

    if _circuit_open():
        logger.info(f"[POLL] {len(god_hits)} signal(s) ready but circuit breaker open — skip")
        return 0

    scan_counter = [0]
    deferred     = 0
    for symbol, sml, tier_label, sniper in god_hits:
        signal = sml.get("signal", "")
        # Explicit bear check rather than an incomplete bull allowlist: the
        # harmonic engine's 3-stack bull label ("INSTITUTIONAL_CONVERGENCE")
        # has no "_BULL" suffix unlike the 4/6-stack labels, so checking for
        # "BULL in signal or signal in (...)" silently misread it as bearish.
        # Every bear label is consistently suffixed "_BEAR" — check that instead.
        is_bear = "BEAR" in signal
        side    = "sell" if is_bear else "buy"
        if scan_counter[0] >= MAX_PER_SCAN:
            deferred += 1
            continue
        logger.info(f"[POLL] {tier_label}: {symbol} {side.upper()} stacked={sml.get('god_stacked',0)}/6")

        if symbol in ODTE_ONLY_SYMBOLS:
            # 0DTE-only symbols (IWM) never get an equity order — the sniper
            # contract the server already selected (forced same-day expiry for
            # these symbols) is the only route in or out.
            option_type = "put" if is_bear else "call"
            _execute_option(symbol, option_type, sml, sniper, scan_counter)
            continue

        _execute(symbol, side, sml, scan_counter)
        if is_bear:
            # Protect gains + treat the reversal as a PUT opportunity — mirrors
            # core/api/convergence_bp.py's bear leg (close existing long, then
            # buy the put), now on the Robinhood path too.
            _execute_option(symbol, "put", sml, sniper, scan_counter)

    if deferred:
        logger.info(f"[POLL] {deferred} signal(s) deferred — per-scan limit {MAX_PER_SCAN} reached (next cycle)")

    return scan_counter[0]


# ── Pine script TV webhook poll (Leviathan / MMLE Beast / Sniper) ──────────────
def _poll_tv_pending() -> int:
    """
    Poll signals queued by TradingView Pine script alerts via the webhook.
    These come from SML_Sniper v1.1 (15m EMA) and MMLE Beast (65m).
    Returns number of orders placed.
    """
    url = f"{SQUEEZEOS_API_URL}/api/webhooks/tv_pending"
    try:
        req = URLRequest(url, headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[TV-POLL] tv_pending fetch failed: {e}")
        return 0

    signals = data.get("signals") or []
    if not signals:
        return 0

    logger.info(f"[TV-POLL] {len(signals)} Pine script signal(s) from webhook queue (Sniper/MMLE)")
    scan_counter = [0]
    for sig in signals:
        symbol    = (sig.get("symbol") or "").upper().strip()
        direction = (sig.get("action") or "").upper().strip()
        system    = sig.get("system", "TradingView")
        price     = float(sig.get("price") or 0.0)

        if not symbol or direction not in ("BUY", "SELL"):
            continue

        side = "buy" if direction == "BUY" else "sell"
        logger.info(f"[TV-POLL] {system} → {direction} {symbol} @ ${price:.2f}")

        sml_proxy = {
            "god_stacked":   MIN_GOD_STACKED,
            "tier":          "GOD_MODE",
            "execute_gate":  True,
            "signal":        f"{system}_{direction}",
            "confidence":    sig.get("confidence", 80.0),
        }
        _execute(symbol, side, sml_proxy, scan_counter)

    return scan_counter[0]


# ── Oracle watchlist poll (direct BUY/SELL from multi-engine oracle) ───────────
# Polls the free /api/oracle endpoint for any symbol it's actively tracking.
# Fires on BUY or BUY (IGNITION) with confidence >= ORACLE_MIN_CONFIDENCE.
# This is the fallback when beastmode has no GOD_MODE hits (e.g., server warmup,
# quiet market, or no convergence in the full universe scan).
ORACLE_MIN_CONFIDENCE = float(os.environ.get("ORACLE_MIN_CONFIDENCE", "60.0"))  # match oracle's own BUY floor

def _poll_oracle() -> int:
    """
    Poll /api/oracle for BUY/SELL directives.

    /api/oracle (batch) returns:
      {"status": "success", "symbols": {"GME": {"directive": "BUY", "confidence": 75, ...}, ...}}

    The oracle batch only covers the server's ORACLE_SYMBOLS list (GME/AMC/IWM + extras).
    We also poll /api/history to catch BUY council verdicts for ANY symbol the engines touched.
    Returns number of orders placed.
    """
    now = time.time()
    scan_counter = [0]
    symbols_seen: dict = {}   # sym → {directive, confidence, price}

    # ── 1. Oracle batch (server's watchlist) ─────────────────────────────────
    try:
        req = URLRequest(f"{SQUEEZEOS_API_URL}/api/oracle",
                         headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        # API returns {"symbols": {"SYM": {"directive": "BUY", "confidence": N, "price": N}}}
        for sym, info in (data.get("symbols") or {}).items():
            if isinstance(info, dict):
                symbols_seen[sym.upper()] = info
    except Exception as e:
        logger.warning(f"[ORACLE] batch fetch failed: {e}")

    # ── 2. Signal history — catch BUY council verdicts from ALL scanned symbols ──
    try:
        req = URLRequest(f"{SQUEEZEOS_API_URL}/api/history",
                         headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=20) as resp:
            hist = json.loads(resp.read())
        # History returns list of {symbol, event_type, data:{directive/action, confidence, price}, ts}
        cutoff = now - 1800   # look back 30 min — catches signals between 3-min poll cycles
        for event in (hist.get("events") or hist.get("history") or []):
            ts  = float(event.get("ts") or event.get("timestamp") or 0)
            if ts < cutoff:
                continue
            sym = (event.get("symbol") or "").upper().strip()
            if not sym or sym in _BLOCKLIST:
                continue
            d = event.get("data") or {}
            directive  = (d.get("directive") or d.get("action") or "").upper()
            confidence = float(d.get("confidence") or 0)
            price      = float(d.get("price") or 0)
            if directive in ("BUY", "BUY (IGNITION)", "SELL") and confidence > 0:
                # History entries are more recent — overwrite batch entry for same symbol
                symbols_seen[sym] = {"directive": directive, "confidence": confidence, "price": price}
    except Exception as e:
        logger.debug(f"[ORACLE] history fetch failed: {e}")

    # ── 3. Mandatory anchors — always fetch AMC, GME, IWM even if absent from batch ──
    for anchor in _MANDATORY_ANCHORS:
        if anchor not in symbols_seen:
            try:
                req = URLRequest(f"{SQUEEZEOS_API_URL}/api/oracle/{anchor}",
                                 headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
                with urlopen(req, timeout=10) as resp:
                    oracle_resp = json.loads(resp.read())
                info = oracle_resp.get("oracle") or {}
                if info.get("directive"):
                    symbols_seen[anchor] = info
            except Exception as e:
                logger.debug(f"[ORACLE] mandatory anchor {anchor} fetch failed: {e}")

    if not symbols_seen:
        return 0

    buy_count  = 0
    sell_count = 0

    for sym, info in symbols_seen.items():
        if sym in _BLOCKLIST:
            continue
        directive  = (info.get("directive") or info.get("action") or "").upper()
        confidence = float(info.get("confidence") or 0)
        price      = float(info.get("price") or 0)

        sml_proxy = {
            "god_stacked": MIN_GOD_STACKED,
            "tier":        "GOD_MODE",
            "signal":      f"ORACLE_{directive}",
            "confidence":  confidence,
        }

        if directive in ("BUY", "BUY (IGNITION)"):
            buy_count += 1
            if confidence < ORACLE_MIN_CONFIDENCE:
                continue
            # BUY respects cooldown — don't spam the same symbol every 3 min
            if now - _last_execution.get(sym, 0) < COOLDOWN_S:
                continue
            logger.info(f"[ORACLE] BUY → {sym}  conf={confidence:.0f}%  price=${price:.2f}")
            _execute(sym, "buy", sml_proxy, scan_counter)
            if scan_counter[0] >= MAX_PER_SCAN:
                break

        elif directive in ("SELL", "SHIELD"):
            sell_count += 1
            if price <= 0:
                logger.debug(f"[ORACLE] SELL {sym} skipped — no live price data")
                continue
            if confidence < 20:
                logger.debug(f"[ORACLE] SELL {sym} skipped — confidence {confidence:.0f}% below floor")
                continue
            # SELL never blocked by cooldown — exits are always urgent
            logger.info(f"[ORACLE] SELL → {sym}  conf={confidence:.0f}%  price=${price:.2f}")
            _execute(sym, "sell", sml_proxy, scan_counter)

    if buy_count or sell_count or scan_counter[0]:
        logger.info(
            f"[ORACLE] {len(symbols_seen)} symbols | {buy_count} BUY | {sell_count} SELL | "
            f"{scan_counter[0]} orders placed"
        )

    return scan_counter[0]


# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    global _rh_logged_in  # explicitly declare global so Python never creates a local shadow
    logger.info("=" * 60)
    logger.info("SqueezeOS Robinhood Executor v3.5 — SELL confidence + price floor (no 0% ghost exits)")
    logger.info(f"  API         : {SQUEEZEOS_API_URL}")
    logger.info(f"  Poll every  : {POLL_INTERVAL_S}s")
    logger.info(f"  Hours       : 4:00 AM–8:00 PM ET (pre-market + regular + after-hours)")
    logger.info(f"  Ext hours   : LIMIT orders (buy +0.2% / sell -0.2% from last price)")
    logger.info(f"  Sources     : beastmode (GOD_MODE+DUAL_LOCK) | TV webhook (Pine) | oracle+history (live universe)")
    logger.info(f"  Oracle      : 100% FETCH — uses live scan universe, no hardcoded watchlist")
    logger.info(f"  MIN_GOD     : {MIN_GOD_STACKED}/6 stacked (GRID_LOCK: {max(2,MIN_GOD_STACKED-1)})  |  ORACLE_MIN_CONF: {ORACLE_MIN_CONFIDENCE}%")
    logger.info(f"  PDT limit   : ${PDT_BALANCE_LIMIT}")
    logger.info(f"  Max order   : ${MAX_ORDER_USD} / {MAX_EQUITY_SHARES} shares")
    logger.info(f"  Daily cap   : {MAX_ORDERS_PER_DAY} orders / ${MAX_DAILY_NOTIONAL:.0f} notional / ${MAX_DAILY_LOSS_USD:.0f} loss limit")
    logger.info(f"  Per-scan    : max {MAX_PER_SCAN} orders per poll cycle")
    logger.info(f"  Position mon: stop-loss {STOP_LOSS_PCT}% / take-profit {TAKE_PROFIT_PCT}% (enabled={POSITION_MONITOR_ENABLED})")
    logger.info(f"  Paper mode  : {PAPER_MODE}")
    logger.info(f"  Kill switch : {KILL_SWITCH}")
    logger.info("=" * 60)

    if KILL_SWITCH:
        logger.warning("[STARTUP] KILL_SWITCH=true — executor will log but not trade")

    # Pre-warm login
    if not PAPER_MODE:
        _ensure_login()

    _last_login_check  = time.time()
    _LOGIN_RECHECK_S   = 1800   # verify session every 30 min
    _auth_retry_count  = 0
    _AUTH_BACKOFF      = [60, 120, 300, 600, 1800]  # escalating retry delays on repeated failure

    while True:
        try:
            _reset_daily_if_new_day()

            # Proactive session health-check every 30 min
            if not PAPER_MODE and time.time() - _last_login_check > _LOGIN_RECHECK_S:
                _invalidate_login()
                ok = _ensure_login()
                _last_login_check = time.time()
                if ok:
                    _auth_retry_count = 0
                else:
                    delay = _AUTH_BACKOFF[min(_auth_retry_count, len(_AUTH_BACKOFF) - 1)]
                    _auth_retry_count += 1
                    logger.error(f"[AUTH] Re-auth failed (attempt {_auth_retry_count}) — backing off {delay}s")
                    time.sleep(delay)
                    continue

            # If we lost auth mid-cycle, recover before scanning
            if not PAPER_MODE and not _rh_logged_in:
                ok = _ensure_login()
                if not ok:
                    delay = _AUTH_BACKOFF[min(_auth_retry_count, len(_AUTH_BACKOFF) - 1)]
                    _auth_retry_count += 1
                    logger.error(f"[AUTH] Cannot authenticate (attempt {_auth_retry_count}) — skipping cycle, retry in {delay}s")
                    time.sleep(delay)
                    continue
                _auth_retry_count = 0

            rh_status = "PAPER" if PAPER_MODE else "OK"
            if not _market_open():
                from datetime import datetime as _dt
                now_et = _dt.now(_ET)
                logger.info(f"[POLL] Market closed ({now_et.strftime('%a %H:%M ET')}) — standing by, next check in {POLL_INTERVAL_S}s")
                time.sleep(POLL_INTERVAL_S)
                continue
            logger.info(f"[POLL] Scanning... (RH: {rh_status} | orders today: {_orders_today}/{MAX_ORDERS_PER_DAY} | notional: ${_daily_notional_usd:.0f}/${MAX_DAILY_NOTIONAL:.0f})")
            stop_placed   = _check_stop_losses()
            beast_placed  = _poll_beastmode()
            tv_placed     = _poll_tv_pending()
            oracle_placed = _poll_oracle()
            total_placed  = stop_placed + beast_placed + tv_placed + oracle_placed
            if total_placed == 0:
                logger.info("[POLL] No signals this cycle — waiting for next scan")
            else:
                logger.info(f"[POLL] Cycle complete — {total_placed} order(s) placed ({stop_placed} stop/take-profit, {beast_placed} GOD MODE, {tv_placed} Pine, {oracle_placed} Oracle)")
        except Exception as e:
            logger.error(f"[LOOP] Unexpected error: {e}")
        logger.info(f"[POLL] Next scan in {POLL_INTERVAL_S}s")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()


