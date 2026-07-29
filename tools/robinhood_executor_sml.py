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
# Prefer env; else local tools\logs next to this script (never hard-require C:\SqueezeOS —
# that path triggers "The system cannot find the path specified" on some Windows setups).
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_LOG_DIR = os.path.join(_SCRIPT_DIR, "logs")
LOG_DIR = os.environ.get("LOG_DIR") or _DEFAULT_LOG_DIR
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError:
    LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SqueezeOS", "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "robinhood_executor.log")

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
# ═══════════════════════════════════════════════════════════════════════════
# DESK LOCK — POLL is NOT env-configurable on the money path.
# Stale PC executor.env (POLL=300) + load_dotenv(override=True) kept beating
# START_EXECUTOR.bat and put the desk back on a 5-minute loop after every
# restart. Only ALLOW_SLOW_POLL=true may unlock a custom interval.
# ═══════════════════════════════════════════════════════════════════════════
if os.environ.get("ALLOW_SLOW_POLL", "false").lower() == "true":
    try:
        POLL_INTERVAL_S = int(str(os.environ.get("POLL_INTERVAL_S", "45")).strip())
    except Exception:
        POLL_INTERVAL_S = 45
    if POLL_INTERVAL_S < 15:
        POLL_INTERVAL_S = 15
else:
    POLL_INTERVAL_S = 45  # LOCKED

MIN_GOD_STACKED = 3  # LOCKED — gate is god_stacked >= 3; stale env had 4/5
# Allow explicit unlock only for research
if os.environ.get("ALLOW_CUSTOM_MIN_GOD", "false").lower() == "true":
    try:
        MIN_GOD_STACKED = max(1, min(6, int(os.environ.get("MIN_GOD_STACKED", "3"))))
    except Exception:
        MIN_GOD_STACKED = 3
PDT_BALANCE_LIMIT  = float(os.environ.get("PDT_BALANCE_LIMIT", "25000.0"))  # real FINRA PDT equity threshold for margin accounts (was 2100.0 -- ~12x too low, operator confirmed 2026-07-29 the account is margin, under $25k)
PDT_MAX_TRADES     = int(os.environ.get("PDT_MAX_TRADES", "3"))
PAPER_MODE           = os.environ.get("ROBINHOOD_PAPER_MODE", "false").lower() == "true"
KILL_SWITCH          = os.environ.get("KILL_SWITCH", "false").lower() == "true"
MAX_EQUITY_SHARES    = int(os.environ.get("MAX_EQUITY_SHARES", "500"))  # hard ceiling; real limit is MAX_ORDER_USD
MAX_ORDER_USD        = float(os.environ.get("MAX_ORDER_USD", "150.0"))
MAX_DAILY_LOSS_USD   = float(os.environ.get("MAX_DAILY_LOSS_USD", "100.0"))
MAX_ORDERS_PER_DAY   = int(os.environ.get("MAX_ORDERS_PER_DAY", "25"))
MAX_DAILY_NOTIONAL   = float(os.environ.get("MAX_DAILY_NOTIONAL_USD", "1500.0"))
MAX_PER_SCAN         = int(os.environ.get("MAX_PER_SCAN", "3"))
STOP_LOSS_PCT        = float(os.environ.get("STOP_LOSS_PCT", "5.0"))    # fallback if no cached ATR: close if down this % from avg cost
TAKE_PROFIT_PCT      = float(os.environ.get("TAKE_PROFIT_PCT", "15.0")) # fallback if no cached ATR: close if up this % from avg cost
# ATR-based stop/take-profit — same multiplier convention as execution_engine.py's
# atr_multiplier (1.5x ATR stop, 2.5x that for target = same ~1:2.5 risk:reward).
# ATR comes from the harmonic matrix engine's sml_matrix.atr on the signal that
# opened the position (see _symbol_atr below) — used in place of the fixed
# STOP_LOSS_PCT/TAKE_PROFIT_PCT whenever a real ATR reading is cached for that
# symbol, since a fixed percentage is either too tight or too loose depending on
# how volatile a given $1-$50 name actually is.
ATR_STOP_MULTIPLIER  = float(os.environ.get("ATR_STOP_MULTIPLIER", "1.5"))
ATR_TP_MULTIPLIER    = float(os.environ.get("ATR_TP_MULTIPLIER", "3.75"))
POSITION_MONITOR_ENABLED = os.environ.get("POSITION_MONITOR_ENABLED", "true").lower() == "true"
# Options sleeve continuous harvest (MM forced-move 50–500%)
OPT_HARD_STOP = float(os.environ.get("OPT_HARD_STOP", "-0.20"))
OPT_SCALE_1 = float(os.environ.get("OPT_SCALE_1", "0.50"))
OPT_SCALE_2 = float(os.environ.get("OPT_SCALE_2", "1.50"))
OPT_BANK_300 = float(os.environ.get("OPT_BANK_300", "3.00"))
OPT_BANK_500 = float(os.environ.get("OPT_BANK_500", "5.00"))
OPT_GIVEBACK_ARM = float(os.environ.get("OPT_GIVEBACK_ARM", "0.50"))
OPT_GIVEBACK_FRAC = float(os.environ.get("OPT_GIVEBACK_FRAC", "0.35"))
OPT_TRAIL = float(os.environ.get("OPT_TRAIL", "0.22"))
OPT_TRAIL_LATE = float(os.environ.get("OPT_TRAIL_LATE", "0.18"))
OPT_DELTA_EXIT = float(os.environ.get("OPT_DELTA_EXIT", "0.60"))
_OPT_BOOK_FILE = os.path.join(LOG_DIR, "option_book.json")
# Skip a BUY when the bid-ask spread is wider than this % of the midpoint —
# a market/marketable order into a thin $1-$50 name eats the whole spread as
# instant slippage. Applies to entries only, NEVER to exits. 0 disables.
MAX_SPREAD_PCT       = float(os.environ.get("MAX_SPREAD_PCT", "2.0"))
# Alert when an accepted order is still unfilled after this many minutes.
FILL_ALERT_MINUTES   = float(os.environ.get("FILL_ALERT_MINUTES", "10.0"))

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

_PDT_FILE = os.path.join(LOG_DIR, "pdt_trades.json")

def _load_pdt_trades() -> list:
    try:
        with open(_PDT_FILE, "r") as f:
            data = json.load(f)
        return [float(t) for t in data] if isinstance(data, list) else []
    except Exception:
        return []

def _save_pdt_trades(trades: list) -> None:
    try:
        with open(_PDT_FILE, "w") as f:
            json.dump(trades, f)
    except Exception as e:
        logger.warning(f"[PDT] save failed: {e}")

_ATR_FILE = os.path.join(LOG_DIR, "symbol_atr.json")

def _load_symbol_atr() -> dict:
    try:
        with open(_ATR_FILE, "r") as f:
            data = json.load(f)
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_symbol_atr(d: dict) -> None:
    try:
        with open(_ATR_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        logger.warning(f"[ATR] save failed: {e}")

_last_execution     = _load_last_execution()  # symbol → epoch, persisted across restarts
_pdt_trades         = _load_pdt_trades()      # epoch timestamps of day trades — persisted:
                                              # the 5-day PDT window must survive NSSM restarts,
                                              # otherwise every crash/reboot silently disarms the shield
_symbol_atr         = _load_symbol_atr()      # symbol → last known real ATR (from sml_matrix.atr
                                              # on the signal that triggered a BUY), persisted so
                                              # the position monitor still has it after a restart
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
# Anti-loop rules (the "Trying to log in..." spam):
#  1) NEVER call rh.login() if the existing session still verifies.
#  2) NEVER wipe the pickle on a soft failure (that forces full MFA loop).
#  3) On hard failure, cool down for AUTH_COOLDOWN_S — do not hammer RH.
#  4) Health check only VERIFIES; it does not invalidate a good session.
_AUTH_FAILURE_ALERTED = False
_LAST_LOGIN_ATTEMPT_TS = 0.0
_AUTH_COOLDOWN_S = int(os.environ.get("RH_AUTH_COOLDOWN_S", "900"))  # 15 min default
_AUTH_HARD_FAIL_UNTIL = 0.0  # epoch — skip all login attempts until this time
_LOGIN_ATTEMPTS_WINDOW = []  # timestamps of rh.login() calls
_MAX_LOGINS_PER_HOUR = int(os.environ.get("RH_MAX_LOGINS_PER_HOUR", "4"))


def _rh_verify_session() -> bool:
    """Return True only if the active session can actually read account data."""
    try:
        import robin_stocks.robinhood as rh
        profile = rh.profiles.load_account_profile()
        return bool(profile and profile.get("account_number"))
    except Exception:
        return False


def _pickle_paths():
    home = os.path.expanduser("~")
    # robin_stocks pickle_name="rh_session" → various path conventions
    return [
        os.path.join(home, ".tokens", "robinhoodrh_session.pickle"),
        os.path.join(home, ".tokens", "rh_session.pickle"),
        os.path.join(home, ".tokens", "robinhood.pickle"),
    ]


def _load_device_token():
    import pickle
    for pickle_path in _pickle_paths():
        if not os.path.exists(pickle_path):
            continue
        try:
            with open(pickle_path, "rb") as f:
                stored = pickle.load(f)
            if isinstance(stored, dict) and stored.get("device_token"):
                return stored.get("device_token"), pickle_path
        except Exception:
            continue
    return None, None


def _rh_force_reauth() -> bool:
    """
    Hard re-auth using stored device_token. Does NOT delete pickle first
    (deleting pickle is what restarts the MFA / 'Trying to log in' loop).
    """
    import robin_stocks.robinhood as rh

    device_token, pickle_path = _load_device_token()
    if not device_token:
        logger.error(
            "[RH-AUTH] No device_token in pickle — MFA required. "
            "On the PC: stop executor, delete only if corrupt, run once interactively to complete MFA, then restart."
        )
        return False

    try:
        logger.info("[RH-AUTH] Soft re-auth with existing device_token (pickle kept)")
        rh.login(
            ROBINHOOD_USER,
            ROBINHOOD_PASS,
            store_session=True,
            pickle_name="rh_session",
            device_token=device_token,
        )
        if _rh_verify_session():
            logger.info("[RH-AUTH] Re-auth OK via device_token")
            return True
        logger.error("[RH-AUTH] Re-auth returned but session still invalid")
        return False
    except Exception as e:
        logger.error(f"[RH-AUTH] Re-auth failed: {e}")
        return False


def _login_rate_limited() -> bool:
    """True if we already hit rh.login too many times this hour."""
    global _LOGIN_ATTEMPTS_WINDOW
    now = time.time()
    _LOGIN_ATTEMPTS_WINDOW = [t for t in _LOGIN_ATTEMPTS_WINDOW if now - t < 3600]
    return len(_LOGIN_ATTEMPTS_WINDOW) >= _MAX_LOGINS_PER_HOUR


def _note_login_attempt():
    global _LAST_LOGIN_ATTEMPT_TS, _LOGIN_ATTEMPTS_WINDOW
    now = time.time()
    _LAST_LOGIN_ATTEMPT_TS = now
    _LOGIN_ATTEMPTS_WINDOW.append(now)


def _ensure_login() -> bool:
    """
    Idempotent session ensure. Prefer verify-only; call rh.login sparingly.
    """
    global _rh_logged_in, _AUTH_FAILURE_ALERTED, _AUTH_HARD_FAIL_UNTIL

    # Already good this process
    if _rh_logged_in and _rh_verify_session():
        return True

    # Session may still be valid even if flag is false (e.g. after soft invalidate)
    if _rh_verify_session():
        _rh_logged_in = True
        _AUTH_FAILURE_ALERTED = False
        return True

    now = time.time()
    if now < _AUTH_HARD_FAIL_UNTIL:
        left = int(_AUTH_HARD_FAIL_UNTIL - now)
        logger.warning(f"[RH] Auth cooldown active — {left}s left (not calling rh.login)")
        return False

    if not ROBINHOOD_USER or not ROBINHOOD_PASS:
        logger.error("[RH] ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not set in executor.env")
        return False

    if _login_rate_limited():
        logger.error(
            f"[RH] Login rate limit ({_MAX_LOGINS_PER_HOUR}/hour) — stopping login spam. "
            "Fix MFA/device_token on PC, then restart executor."
        )
        _AUTH_HARD_FAIL_UNTIL = now + _AUTH_COOLDOWN_S
        return False

    # Cooldown between attempts
    if _LAST_LOGIN_ATTEMPT_TS and (now - _LAST_LOGIN_ATTEMPT_TS) < 60:
        logger.info("[RH] Skipping login — attempted <60s ago")
        return False

    import robin_stocks.robinhood as rh

    # Step 1: normal login (uses cached pickle / refresh_token) — ONE try
    _note_login_attempt()
    try:
        logger.info("[RH] Attempting session restore (rh.login once)…")
        rh.login(ROBINHOOD_USER, ROBINHOOD_PASS, store_session=True, pickle_name="rh_session")
        if _rh_verify_session():
            _rh_logged_in = True
            _AUTH_FAILURE_ALERTED = False
            _AUTH_HARD_FAIL_UNTIL = 0.0
            logger.info("[RH] Session verified — logged in OK")
            return True
        logger.warning("[RH] Login returned but session invalid — trying device_token path once")
    except Exception as e:
        logger.warning(f"[RH] Login error: {e} — trying device_token path once")

    # Step 2: device_token path (still keeps pickle)
    _note_login_attempt()
    if _rh_force_reauth():
        _rh_logged_in = True
        _AUTH_FAILURE_ALERTED = False
        _AUTH_HARD_FAIL_UNTIL = 0.0
        return True

    # Step 3: hard fail — long cooldown so we do NOT loop "Trying to log in…"
    _rh_logged_in = False
    _AUTH_HARD_FAIL_UNTIL = time.time() + _AUTH_COOLDOWN_S
    if not _AUTH_FAILURE_ALERTED:
        _AUTH_FAILURE_ALERTED = True
        _discord_critical(
            f"[RH] ❌ Auth failed — cooling down {_AUTH_COOLDOWN_S}s. "
            "Manual MFA on PC required if device_token expired. Executor will NOT spam login."
        )
    logger.error(f"[RH] Auth failed — cooldown {_AUTH_COOLDOWN_S}s (no more login spam)")
    return False


def _invalidate_login():
    """Soft flag only — does NOT delete pickle or call rh.login."""
    global _rh_logged_in
    _rh_logged_in = False
    logger.info("[RH] Soft session flag cleared — next cycle will VERIFY before any login")


def _healthcheck_session() -> bool:
    """
    Periodic health check: verify only. Login only if verify fails.
    This replaces the old pattern of invalidate+login every 30 min (login loop).
    """
    if _rh_verify_session():
        global _rh_logged_in, _AUTH_FAILURE_ALERTED
        _rh_logged_in = True
        _AUTH_FAILURE_ALERTED = False
        logger.info("[RH] Health check OK — session still valid (no re-login)")
        return True
    logger.warning("[RH] Health check failed — will attempt ensure_login once")
    return _ensure_login()


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
# Check and record are split on purpose: a PDT slot is only consumed by an order
# Robinhood actually accepted. Recording at check time burned slots on orders
# that were later rejected (e.g. the GTC market-order rejections) — under the
# balance limit, 3 failed attempts would lock ALL trading for 5 days.
def _pdt_allowed() -> bool:
    balance = _get_rh_portfolio_value()   # network call — keep outside the lock
    now = time.time()
    cutoff = now - PDT_WINDOW_S
    with _lock:
        _pdt_trades[:] = [t for t in _pdt_trades if t > cutoff]
        if balance < PDT_BALANCE_LIMIT:
            if len(_pdt_trades) >= PDT_MAX_TRADES:
                logger.warning(
                    f"[PDT] BLOCKED — balance ${balance:.2f} < ${PDT_BALANCE_LIMIT} "
                    f"and {len(_pdt_trades)}/{PDT_MAX_TRADES} day trades used"
                )
                return False
            logger.info(f"[PDT] Balance ${balance:.2f} — PDT active: {len(_pdt_trades)}/{PDT_MAX_TRADES} used")
        else:
            logger.info(f"[PDT] Balance ${balance:.2f} — above PDT limit, full trading allowed")
    return True


def _pdt_record():
    """Consume a PDT slot for an order Robinhood confirmed (or a paper fill)."""
    now = time.time()
    cutoff = now - PDT_WINDOW_S
    with _lock:
        _pdt_trades[:] = [t for t in _pdt_trades if t > cutoff]
        _pdt_trades.append(now)
        _save_pdt_trades(_pdt_trades)


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


# ── Holiday calendar guard ─────────────────────────────────────────────────────
# The weekday/hour check above doesn't know about market holidays — on July 4th
# etc. the executor would poll and fire orders that Robinhood just rejects.
# Ask Robinhood's own market calendar (cached per day, fails OPEN so a calendar
# outage can never block trading on a real session day).
_trading_day_cache = {"date": "", "is_open": True}

def _is_trading_day() -> bool:
    today = datetime.now(_ET).strftime("%Y-%m-%d")
    if _trading_day_cache["date"] == today:
        return _trading_day_cache["is_open"]
    if PAPER_MODE or not _rh_logged_in:
        return True   # no session to ask — fail open, don't cache
    try:
        import robin_stocks.robinhood as rh
        hours = rh.markets.get_market_today_hours("XNYS")
        if isinstance(hours, dict) and hours.get("is_open") is not None:
            is_open = bool(hours["is_open"])
            _trading_day_cache["date"]    = today
            _trading_day_cache["is_open"] = is_open
            if not is_open:
                logger.info(f"[CALENDAR] {today} is a market holiday per Robinhood calendar — standing down for the day")
            return is_open
    except Exception as e:
        logger.debug(f"[CALENDAR] market hours fetch failed: {e} — failing open")
    return True


# ── Open-order reconciliation (read-only) ──────────────────────────────────────
# The executor fires orders and moves on — nothing ever confirmed they FILLED.
# A GFD limit can sit unfilled all day (position still open, stop-loss thinks
# it's closing, daily counters already charged). Each cycle: list open stock
# orders, log them, and alert once per order once it's stale. Observation only —
# never cancels anything (the operator may have placed orders manually).
_fill_alerted_ids: set = set()

def _reconcile_open_orders():
    if PAPER_MODE or not _rh_logged_in:
        return
    try:
        import robin_stocks.robinhood as rh
        open_orders = rh.orders.get_all_open_stock_orders() or []
    except Exception as e:
        logger.warning(f"[ORDERS] open-order fetch failed: {e}")
        return
    if not open_orders:
        return
    from datetime import timezone as _tz
    now_utc = datetime.now(_tz.utc)
    for o in open_orders:
        try:
            oid   = str(o.get("id") or "")
            state = o.get("state", "")
            side  = o.get("side", "")
            qty   = float(o.get("quantity") or 0)
            px    = o.get("price") or o.get("average_price") or "?"
            symbol = ""
            try:
                import robin_stocks.robinhood as rh
                instr  = rh.stocks.get_instrument_by_url(o.get("instrument", ""))
                symbol = (instr or {}).get("symbol", "").upper()
            except Exception:
                pass
            age_min = 0.0
            created = o.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age_min = (now_utc - created_dt).total_seconds() / 60.0
                except Exception:
                    pass
            logger.info(f"[ORDERS] open: {symbol or '?'} {side} x{qty:g} @ {px} state={state} age={age_min:.0f}m")
            if age_min > FILL_ALERT_MINUTES and oid and oid not in _fill_alerted_ids:
                _fill_alerted_ids.add(oid)
                msg = f"⏳ {symbol or 'order'} {side} x{qty:g} unfilled for {age_min:.0f} min (state={state}) — check the Robinhood app"
                logger.warning(f"[ORDERS] {msg}")
                _discord_critical(msg)
        except Exception as e:
            logger.debug(f"[ORDERS] reconcile entry error: {e}")


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

    # Bearish signals from the real beastmode poll carry their stack count in
    # bear_god_stacked, not god_stacked (which stays 0 on a genuine bear
    # setup) — reading god_stacked unconditionally here meant a real, fully
    # confirmed bearish GOD_MODE signal (side="sell") was silently skipped as
    # "0 < MIN_GOD_STACKED" every time, since its bull count is naturally ~0.
    # The STOP_LOSS/TAKE_PROFIT and TV-webhook sml_proxy dicts don't carry a
    # bear_god_stacked key at all (they set god_stacked directly to bypass
    # this gate for risk exits / already-scored external signals), so the
    # "in sml" check keeps their existing behavior unchanged.
    if side == "sell" and "bear_god_stacked" in sml:
        god_count = sml.get("bear_god_stacked", 0)
    else:
        god_count = sml.get("god_stacked", 0)
    if god_count < MIN_GOD_STACKED:
        logger.info(f"[EXEC] {symbol} god_stacked={god_count} < {MIN_GOD_STACKED} — skip")
        return

    # Cache the real ATR this BUY signal was scored on — the position monitor
    # (_check_stop_losses) uses it for volatility-adaptive stops instead of a
    # fixed percentage. Only real signals carry an ATR; the STOP_LOSS/TAKE_PROFIT
    # proxy sml built by _check_stop_losses itself never overwrites this.
    if side == "buy":
        try:
            atr_val = float(sml.get("atr") or 0)
        except (TypeError, ValueError):
            atr_val = 0.0
        if atr_val > 0:
            _symbol_atr[symbol] = atr_val
            _save_symbol_atr(_symbol_atr)

    # Stop-loss/take-profit closes are risk exits, not signal trades — an
    # entry-quality gate (e.g. dark-pool "accumulation" vetoing a SELL) must
    # never hold a position past its stop. Only signal-driven trades get gated.
    is_risk_exit = side == "sell" and sml.get("signal") in ("STOP_LOSS", "TAKE_PROFIT")
    if not is_risk_exit and not _direction_gates_pass(symbol, side, log_prefix="EXEC"):
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

    # Spread guard — entries only. Crossing a wide bid-ask on a thin name is
    # guaranteed slippage; skipping the entry costs nothing. Exits are exempt:
    # a wide spread must never keep a stop-loss from getting out. Fails open.
    if side == "buy" and MAX_SPREAD_PCT > 0:
        try:
            import robin_stocks.robinhood as rh
            q = (rh.stocks.get_quotes(symbol) or [{}])[0] or {}
            bid = float(q.get("bid_price") or 0)
            ask = float(q.get("ask_price") or 0)
            if bid > 0 and ask > bid:
                spread_pct = (ask - bid) / ((ask + bid) / 2) * 100.0
                if spread_pct > MAX_SPREAD_PCT:
                    logger.warning(f"[EXEC] {symbol} BUY skipped — bid-ask spread {spread_pct:.2f}% > {MAX_SPREAD_PCT}% (bid ${bid:.2f} / ask ${ask:.2f})")
                    return
        except Exception as e:
            logger.debug(f"[EXEC] {symbol} spread check failed: {e} — proceeding")

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
                        raw_qty   = float(pos.get("quantity") or 0)
                        owned_qty = int(raw_qty)
                        avg_cost  = float(pos.get("average_buy_price") or 0)
                        if raw_qty - owned_qty > 0.000001:
                            # Whole-share orders can't touch the fractional tail —
                            # surface it so it doesn't sit stranded invisibly.
                            logger.warning(f"[EXEC] {symbol} holds {raw_qty} shares — selling {owned_qty} whole, {raw_qty - owned_qty:.6f} fractional remainder stays (close manually in the app)")
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
        _pdt_record()
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
                    _pdt_record()
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

            # ATR-based stop/target when this symbol has a cached real ATR from
            # the signal that opened it; otherwise fall back to the fixed
            # STOP_LOSS_PCT/TAKE_PROFIT_PCT (unchanged previous behavior).
            atr = _symbol_atr.get(symbol, 0.0)
            if atr > 0:
                stop_pct = (atr * ATR_STOP_MULTIPLIER / avg_cost) * 100.0
                tp_pct   = (atr * ATR_TP_MULTIPLIER   / avg_cost) * 100.0
            else:
                stop_pct = STOP_LOSS_PCT
                tp_pct   = TAKE_PROFIT_PCT

            if pct_move <= -stop_pct:
                logger.warning(f"[STOP-LOSS] {symbol} down {pct_move:.1f}% (avg ${avg_cost:.2f} -> ${price:.2f}, stop {stop_pct:.1f}%{' ATR-based' if atr > 0 else ''}) — closing position")
                sml_proxy = {"god_stacked": MIN_GOD_STACKED, "tier": "GOD_MODE", "signal": "STOP_LOSS"}
                _execute(symbol, "sell", sml_proxy, scan_counter)
            elif pct_move >= tp_pct:
                logger.info(f"[TAKE-PROFIT] {symbol} up {pct_move:.1f}% (avg ${avg_cost:.2f} -> ${price:.2f}, target {tp_pct:.1f}%{' ATR-based' if atr > 0 else ''}) — closing position")
                sml_proxy = {"god_stacked": MIN_GOD_STACKED, "tier": "GOD_MODE", "signal": "TAKE_PROFIT"}
                _execute(symbol, "sell", sml_proxy, scan_counter)
        except Exception as e:
            logger.warning(f"[STOP-LOSS] position check error: {e}")

    # scan_counter only increments on confirmed placement — returning it (instead
    # of counting attempts) stops the cycle summary claiming rejected orders as
    # "placed", which is exactly what the GTC-rejection logs showed.
    return scan_counter[0]


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
    selected server-side / gamma-ramp desk (scan_options + contract_selector —
    MM forced-move band abs(Δ) ∈ [0.30, 0.40], target 0.35). We never re-derive
    strike/expiration/delta locally: the upstream picked one specific listed
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

    # MM forced-move delta band (shared with gamma_ramp contract_selector / scan_options)
    try:
        _ad = abs(float(sniper.get("delta") or 0))
    except (TypeError, ValueError):
        _ad = 0.0
    _src = str(sniper.get("source") or sml.get("signal") or "")
    _is_gamma = bool(sml.get("gamma_ramp")) or "gamma" in _src.lower()
    # Hard reject out-of-band deltas for options sleeve (0.30–0.40). Soft allow
    # if delta missing (legacy pack) unless gamma_ramp which always stamps Δ.
    if _ad > 0 and not (0.30 <= _ad <= 0.40):
        logger.warning(
            f"[EXEC-OPT] {symbol} {option_type} Δ={_ad:.3f} outside MM band 0.30–0.40 — skip"
        )
        return
    if _is_gamma and _ad <= 0:
        logger.warning(f"[EXEC-OPT] {symbol} gamma_ramp intent missing delta — skip")
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
    # Prefer desk NBBO pin (bid+0.01 / explicit limit_price) for MM sleeve —
    # ask*1.05 was a legacy slippage buffer that overpays gamma entries.
    bid = 0.0
    try:
        bid = float(sniper.get("bid") or 0)
    except (TypeError, ValueError):
        bid = 0.0
    limit_price = None
    for cand in (sniper.get("limit_price"), sniper.get("nbbo_buy")):
        try:
            if cand is not None and float(cand) > 0:
                limit_price = round(float(cand), 2)
                break
        except (TypeError, ValueError):
            pass
    if limit_price is None:
        if bid > 0 and ask > 0:
            limit_price = round(min(ask, bid + 0.01), 2)
        elif ask > 0:
            # tiny buffer only when no bid — not 5% blowout
            limit_price = round(ask * 1.01, 2)
        else:
            limit_price = 0.0
    if ask > 0 and limit_price > ask * 1.05:
        limit_price = round(ask * 1.05, 2)  # hard cap
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
        _pdt_record()
        with _lock:
            _orders_today += 1
            _daily_notional_usd += cost
        try:
            _track_option_entry(symbol, option_type, sniper, qty, limit_price)
        except Exception:
            pass
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
                    # Day-only: entries are meant to fill immediately at ask+5%.
                    # A lingering GTC could fill days later at a stale price the
                    # signal no longer supports.
                    timeInForce="gfd",
                )
                logger.info(f"[RH] Raw option response for {symbol}: {r}")
                rh_state = (r or {}).get("state", "") if isinstance(r, dict) else ""
                order_id = str((r or {}).get("id", "") or (r or {}).get("order_id", "") or "no-id") if isinstance(r, dict) else "no-id"
                _GOOD_STATES = {"confirmed", "queued", "unconfirmed", "partially_filled", "filled"}
                if rh_state in _GOOD_STATES or (isinstance(r, dict) and "id" in r):
                    logger.info(f"[RH] Option order confirmed {symbol} {option_type} x{qty} | id={order_id} state={rh_state}")
                    result = {"placed": True, "raw": r}
                    scan_counter[0] += 1
                    _pdt_record()
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


def _classify_tier(tier_val: str, dual_val: bool, sig_val: str) -> str:
    """
    Returns the executor-facing tier label ('GOD_MODE'/'DUAL_GRID_LOCK'/
    'GRID_LOCK') for one side (bull or bear) of a symbol's harmonic result, or
    "" if that side doesn't qualify at all. Module-level (not a poll-local
    closure) so it's independently testable.
    """
    if dual_val:
        return "DUAL_GRID_LOCK"
    if tier_val == "GOD_MODE":
        return "GOD_MODE"
    if "GRID" in (sig_val or "").upper():
        return "GRID_LOCK"
    return ""


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
        grid369 = hit.get("grid369") or {}
        sniper  = hit.get("options_sniper") or {}

        # sml_matrix.signal/tier only ever reflect the BULL ladder, and
        # bear_signal/bear_tier the BEAR ladder — two separate fields, not one
        # field that flips to a "_BEAR"-suffixed value on a bearish setup.
        # Checking "BEAR" in sml.get("signal") (the bull-only field) could
        # never match anything real, which meant every plain bearish signal
        # (bear_tier=GOD_MODE but tier=NONE since god_stacked=0) was silently
        # dropped as "no_tier" before ever reaching _execute() — this poll
        # loop could effectively never detect a real bearish opportunity.
        # Classify both sides independently instead and pick whichever
        # actually qualifies (or the stronger one if, rarely, both do).
        bull_stacked = sml.get("god_stacked", 0)
        bear_stacked = sml.get("bear_god_stacked", 0)
        bull_class = _classify_tier(sml.get("tier", ""),
                                     grid369.get("dual_grid_lock", False), sml.get("signal", ""))
        bear_class = _classify_tier(sml.get("bear_tier", ""),
                                     grid369.get("dual_grid_lock_bear", False), sml.get("bear_signal", ""))

        if bull_class and bear_class:
            is_bear = bear_stacked > bull_stacked
        else:
            is_bear = bool(bear_class) and not bull_class

        effective_tier = bear_class if is_bear else bull_class
        stacked        = bear_stacked if is_bear else bull_stacked

        if effective_tier not in _VALID_TIERS:
            skipped["no_tier"] += 1
            continue
        min_stack = _TIER_MIN_STACK.get(effective_tier, MIN_GOD_STACKED)
        if stacked < min_stack:
            skipped["low_stack"] += 1
            logger.debug(f"[POLL] {symbol} {effective_tier} stacked={stacked} < {min_stack} — skip")
            continue
        if symbol in _BLOCKLIST:
            skipped["blocklist"] += 1
            continue
        cooldown_remaining = COOLDOWN_S - (now - _last_execution.get(symbol, 0))
        if cooldown_remaining > 0:
            skipped["cooldown"] += 1
            logger.info(f"[POLL] {symbol} {effective_tier} {stacked}/6 — cooldown {int(cooldown_remaining)}s left")
            continue
        god_hits.append((symbol, sml, effective_tier, sniper, is_bear))

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
    for symbol, sml, tier_label, sniper, is_bear in god_hits:
        side = "sell" if is_bear else "buy"
        if scan_counter[0] >= MAX_PER_SCAN:
            deferred += 1
            continue
        side_stacked = sml.get('bear_god_stacked', 0) if is_bear else sml.get('god_stacked', 0)
        logger.info(f"[POLL] {tier_label}: {symbol} {side.upper()} stacked={side_stacked}/6")

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


def _poll_iam_primary() -> int:
    """
    Poll signals queued by iam_executor.execute_from_resolution() for the IAM
    primary systems (CASCADE / SR-Matrix / Breakout / MM-V4 -- whatever
    IAM_PRIMARY_SYSTEM lists on the server). These are the SAME signals that
    already placed a real Tradier order server-side; this queue exists so
    Robinhood places the trade too, independently, on its own account.
    Explicit operator decision (2026-07-29): both brokers execute the same
    signal -- Robinhood holds the funds and has no PDT rule, doubled exposure
    across the two accounts is intended, not a bug.

    Same queue/poll shape as _poll_tv_pending() (core/api/iam_pending_bp.py
    mirrors tradingview_webhook_bp.py's queue exactly), kept as a distinct
    endpoint so IAM-primary and raw TradingView-Pine fills stay separately
    attributable in this log, even though they're executed identically once
    popped here.
    Returns number of orders placed.
    """
    url = f"{SQUEEZEOS_API_URL}/api/webhooks/iam_pending"
    try:
        req = URLRequest(url, headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[IAM-POLL] iam_pending fetch failed: {e}")
        return 0

    signals = data.get("signals") or []
    if not signals:
        return 0

    logger.info(f"[IAM-POLL] {len(signals)} IAM primary-system signal(s) from webhook queue (CASCADE/SR-Matrix/Breakout/MM-V4)")
    scan_counter = [0]
    for sig in signals:
        symbol    = (sig.get("symbol") or "").upper().strip()
        direction = (sig.get("action") or "").upper().strip()
        system    = sig.get("system", "IAM")
        price     = float(sig.get("price") or 0.0)

        if not symbol or direction not in ("BUY", "SELL"):
            continue

        side = "buy" if direction == "BUY" else "sell"
        logger.info(f"[IAM-POLL] {system} → {direction} {symbol} @ ${price:.2f} (Robinhood leg, Tradier already placed server-side)")

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

# Server discovery healthy = hundreds of tickers (Polygon full-market scan).
# ~25 or fewer means the server is running on its Tradier seed list only —
# Alpaca/Polygon keys missing or their APIs failing. Warn at most once an hour
# so the operator sees WHY the "100% FETCH" universe looks tiny.
_UNIVERSE_WARN_FLOOR   = 25
_universe_last_warn_ts = 0.0

def _warn_if_universe_degraded(universe_size: int):
    """Warn only when BOTH oracle batch AND live market scan look tiny.

    /api/oracle universe_size can stick at 3 (ORACLE_SYMBOLS seed) while
    /api/market/scan already has 100+ quotes powering beastmode — that is NOT
    degraded money-path. Prefer market scan size when available.
    """
    global _universe_last_warn_ts
    live_mkt = 0
    try:
        req = URLRequest(f"{SQUEEZEOS_API_URL}/api/market/scan",
                         headers={"User-Agent": "SqueezeOS-RH-Executor/2.0"})
        with urlopen(req, timeout=12) as resp:
            m = json.loads(resp.read())
        live_mkt = int(m.get("universe_size") or len(m.get("quotes") or {}) or 0)
    except Exception:
        live_mkt = 0
    effective = max(int(universe_size or 0), live_mkt)
    if effective <= 0:
        return
    now = time.time()
    if effective <= _UNIVERSE_WARN_FLOOR and now - _universe_last_warn_ts > 3600:
        _universe_last_warn_ts = now
        logger.warning(
            f"[ORACLE] Effective scan universe is only {effective} tickers "
            f"(oracle_batch={universe_size}, market_scan={live_mkt}) — discovery DEGRADED. "
            f"Check ALPACA/POLYGON/TRADIER on squeezeos-api and "
            f"{SQUEEZEOS_API_URL}/api/truth/providers + /api/market/scan."
        )
    elif live_mkt > _UNIVERSE_WARN_FLOOR and int(universe_size or 0) <= _UNIVERSE_WARN_FLOOR:
        # Quiet info once/hour — money path is fine via market/beastmode
        if now - _universe_last_warn_ts > 3600:
            _universe_last_warn_ts = now
            logger.info(
                f"[ORACLE] batch seed={universe_size} but market scan={live_mkt} — "
                f"beastmode universe healthy (not degraded)"
            )


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
        _warn_if_universe_degraded(int(data.get("universe_size") or 0))
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




# ── Options continuous harvest book (50–500%, sell before giveback) ───────────
def _load_option_book() -> dict:
    try:
        with open(_OPT_BOOK_FILE, "r") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"positions": {}}
    except Exception:
        return {"positions": {}}


def _save_option_book(book: dict) -> None:
    try:
        with open(_OPT_BOOK_FILE, "w") as f:
            json.dump(book, f, indent=2)
    except Exception as e:
        logger.warning(f"[OPT-BOOK] save failed: {e}")


def _option_book_key(symbol: str, strike, expiration: str, option_type: str) -> str:
    return f"{symbol.upper()}|{float(strike):.4f}|{str(expiration)[:10]}|{(option_type or 'call').lower()}"


def _track_option_entry(symbol: str, option_type: str, sniper: dict, qty: int, limit_price: float):
    """Record BTO so continuous manage can scale/trail/giveback-lock."""
    book = _load_option_book()
    pos = book.setdefault("positions", {})
    k = _option_book_key(symbol, sniper.get("strike"), sniper.get("expiration"), option_type)
    prev = pos.get(k) or {}
    prev_qty = int(prev.get("qty") or 0)
    prev_entry = float(prev.get("entry") or 0)
    new_qty = prev_qty + max(1, int(qty))
    # VWAP entry if adding
    if prev_qty > 0 and prev_entry > 0:
        entry = (prev_entry * prev_qty + float(limit_price) * qty) / new_qty
    else:
        entry = float(limit_price)
    pos[k] = {
        "symbol": symbol.upper(),
        "option_type": (option_type or "call").lower(),
        "strike": float(sniper.get("strike") or 0),
        "expiration": str(sniper.get("expiration") or "")[:10],
        "occ": sniper.get("symbol") or sniper.get("occ") or "",
        "qty": new_qty,
        "entry": entry,
        "peak": max(float(prev.get("peak") or 0), entry),
        "scaled": bool(prev.get("scaled") or False),
        "scale_frac": float(prev.get("scale_frac") or 0),
        "entry_delta": abs(float(sniper.get("delta") or prev.get("entry_delta") or 0.35)),
        "entry_ts": prev.get("entry_ts") or time.time(),
        "source": sniper.get("source") or prev.get("source") or "options_sleeve",
    }
    book["positions"] = pos
    _save_option_book(book)
    logger.info(f"[OPT-BOOK] track {k} qty={new_qty} entry={entry:.2f} Δ={pos[k]['entry_delta']}")


def _execute_option_sell(symbol: str, option_type: str, strike, expiration: str, qty: int, limit_price: float, reason: str) -> dict:
    """Sell-to-close option contracts on RH — bank gains / stop / trail."""
    if qty <= 0:
        return {"error": "qty<=0"}
    if PAPER_MODE:
        logger.info(f"[PAPER] Would SELL_TO_CLOSE {qty}x {symbol} {strike}{option_type[0].upper()} {expiration} @ ${limit_price:.2f} ({reason})")
        return {"paper": True, "placed": True}
    if not _ensure_login():
        return {"error": "login_failed"}
    try:
        import robin_stocks.robinhood as rh
        # Prefer bid-side pin for exits (sell); limit_price already computed
        r = rh.orders.order_sell_option_limit(
            positionEffect="close",
            creditOrDebit="credit",
            price=float(limit_price),
            symbol=symbol,
            quantity=int(qty),
            expirationDate=str(expiration)[:10],
            strike=float(strike),
            optionType=(option_type or "call").lower(),
            timeInForce="gfd",
        )
        logger.info(f"[RH] Raw option SELL response {symbol}: {r}")
        rh_state = (r or {}).get("state", "") if isinstance(r, dict) else ""
        order_id = str((r or {}).get("id", "") or "") if isinstance(r, dict) else ""
        good = {"confirmed", "queued", "unconfirmed", "partially_filled", "filled"}
        if rh_state in good or (isinstance(r, dict) and "id" in r):
            logger.info(f"[RH] Option SELL ok {symbol} x{qty} {reason} id={order_id} state={rh_state}")
            return {"placed": True, "raw": r, "reason": reason}
        err = (r or {}).get("detail", "") if isinstance(r, dict) else str(r)
        logger.error(f"[RH] Option SELL failed {symbol}: {err}")
        return {"error": err or "unknown", "raw": r}
    except Exception as e:
        err = str(e)
        logger.error(f"[RH] Option SELL error: {err}")
        if "logged in" in err.lower():
            _invalidate_login()
        return {"error": err}


def _option_mark_from_rh(symbol: str, option_type: str, strike, expiration: str) -> dict:
    """Best-effort mark for open option: last/bid/ask from robin_stocks."""
    out = {"bid": 0.0, "ask": 0.0, "last": 0.0, "mark": 0.0, "delta": 0.0}
    try:
        import robin_stocks.robinhood as rh
        if not _ensure_login():
            return out
        # get_option_market_data_by_id needs id; use find_options / market data helper
        data = None
        try:
            data = rh.options.get_option_market_data(
                symbol,
                str(expiration)[:10],
                str(strike),
                (option_type or "call").lower(),
            )
        except Exception:
            data = None
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            bid = float(data.get("bid_price") or data.get("bid") or 0) or 0.0
            ask = float(data.get("ask_price") or data.get("ask") or 0) or 0.0
            last = float(data.get("last_trade_price") or data.get("mark_price") or 0) or 0.0
            mark = last if last > 0 else ((bid + ask) / 2.0 if bid and ask else bid or ask)
            g = data.get("delta") or (data.get("greeks") or {}).get("delta")
            out = {"bid": bid, "ask": ask, "last": last, "mark": float(mark or 0), "delta": abs(float(g or 0))}
    except Exception as e:
        logger.debug(f"[OPT-BOOK] mark fail {symbol}: {e}")
    return out


def _manage_option_book() -> int:
    """
    Continuous options harvest loop:
      hard stop -20% · scale +50% · scale +150% · bank +300/+500 ·
      giveback lock (sell before loss of gains) · peak trail · Δ≥0.60 exit
    Returns number of sell orders placed.
    """
    if not POSITION_MONITOR_ENABLED:
        return 0
    book = _load_option_book()
    positions = book.get("positions") or {}
    if not positions:
        return 0
    placed = 0
    keep = {}
    for k, pos in list(positions.items()):
        try:
            symbol = pos["symbol"]
            otype = pos.get("option_type") or "call"
            strike = pos.get("strike")
            exp = pos.get("expiration")
            qty = int(pos.get("qty") or 0)
            entry = float(pos.get("entry") or 0)
            if qty <= 0 or entry <= 0:
                continue
            md = _option_mark_from_rh(symbol, otype, strike, exp)
            mark = float(md.get("mark") or 0)
            bid = float(md.get("bid") or 0)
            if mark <= 0:
                keep[k] = pos
                continue
            peak = max(float(pos.get("peak") or entry), mark)
            pos["peak"] = peak
            ret = (mark - entry) / entry
            peak_ret = (peak - entry) / entry if entry > 0 else 0.0
            scaled = bool(pos.get("scaled"))
            scale_frac = float(pos.get("scale_frac") or 0)
            exit_qty = 0
            reason = ""

            if ret <= OPT_HARD_STOP:
                exit_qty, reason = qty, "hard_stop"
            elif ret >= OPT_BANK_500:
                exit_qty, reason = qty, "bank_500"
            elif (not scaled) and ret >= OPT_SCALE_1:
                exit_qty, reason = max(1, qty // 2), "scale_50"
            elif scaled and scale_frac < 0.75 and ret >= OPT_SCALE_2:
                exit_qty, reason = max(1, qty // 2), "scale_150"
            elif scaled and ret >= OPT_BANK_300 and qty > 1:
                exit_qty, reason = max(1, qty - 1), "bank_300"
            elif peak_ret >= OPT_GIVEBACK_ARM and peak_ret > 0:
                giveback = (peak - mark) / entry
                frac_lost = giveback / peak_ret if peak_ret > 0 else 0.0
                if frac_lost >= OPT_GIVEBACK_FRAC and ret > 0:
                    exit_qty, reason = qty, "giveback_lock"
                elif ret <= 0:
                    exit_qty, reason = qty, "giveback_to_red"
            if not reason and scaled:
                trail = OPT_TRAIL_LATE if scale_frac >= 0.75 else OPT_TRAIL
                if peak > 0 and (mark - peak) / peak <= -trail:
                    exit_qty, reason = qty, "trail"
            dlt = float(md.get("delta") or pos.get("entry_delta") or 0)
            if not reason and dlt >= OPT_DELTA_EXIT and ret >= 0.50:
                exit_qty, reason = qty, "delta_expansion"

            if exit_qty > 0:
                # sell pin: ask-0.01 or bid
                ask = float(md.get("ask") or 0)
                if bid > 0 and ask > 0:
                    px = round(max(bid, ask - 0.01), 2)
                elif bid > 0:
                    px = round(bid, 2)
                else:
                    px = round(mark * 0.98, 2)
                logger.info(
                    f"[OPT-BOOK] EXIT {reason} {symbol} {otype} K={strike} exp={exp} "
                    f"qty={exit_qty} ret={ret*100:.1f}% peak_ret={peak_ret*100:.1f}% mark={mark:.2f}"
                )
                res = _execute_option_sell(symbol, otype, strike, exp, exit_qty, px, reason)
                if res.get("placed") or res.get("paper"):
                    placed += 1
                    qty_left = qty - exit_qty
                    if reason.startswith("scale") and qty_left > 0:
                        pos["qty"] = qty_left
                        pos["scaled"] = True
                        pos["scale_frac"] = 0.5 if reason == "scale_50" else 0.75
                        pos["peak"] = mark
                        keep[k] = pos
                    elif reason == "bank_300" and qty_left > 0:
                        pos["qty"] = qty_left
                        pos["scaled"] = True
                        pos["scale_frac"] = max(scale_frac, 0.9)
                        keep[k] = pos
                    # else fully closed — drop
                else:
                    keep[k] = pos  # retry next tick
            else:
                keep[k] = pos
        except Exception as e:
            logger.warning(f"[OPT-BOOK] manage error {k}: {e}")
            keep[k] = pos
    book["positions"] = keep
    book["last_manage_ts"] = time.time()
    _save_option_book(book)
    if placed:
        logger.info(f"[OPT-BOOK] harvest sells placed={placed} open_left={len(keep)}")
    return placed


# ── Gamma Ramp outbox poll (Tradier data → RH funded exec) ─────────────────────
# Reads RH-ready option intents written by tools/gamma_ramp/live_engine.py via
# rh_route.py. Same sniper contract shape as beastmode options path.
GAMMA_RAMP_OUTBOX_DIR = os.environ.get(
    "GAMMA_RAMP_OUTBOX_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamma_ramp", "rh_outbox"),
)
GAMMA_RAMP_POLL_ENABLED = os.environ.get("GAMMA_RAMP_POLL_ENABLED", "true").lower() == "true"


def _poll_gamma_ramp() -> int:
    """Consume pending gamma-ramp option intents from the shared outbox."""
    if not GAMMA_RAMP_POLL_ENABLED:
        return 0
    try:
        from pathlib import Path as _P
        outbox = _P(GAMMA_RAMP_OUTBOX_DIR)
    except Exception:
        return 0
    if not outbox.is_dir():
        return 0

    files = sorted(outbox.glob("gr_*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        return 0

    scan_counter = [0]
    done_dir = outbox / "done"
    done_dir.mkdir(exist_ok=True)

    for fpath in files:
        if scan_counter[0] >= MAX_PER_SCAN:
            break
        try:
            intent = json.loads(fpath.read_text())
        except Exception as e:
            logger.warning(f"[GAMMA-RAMP] bad intent file {fpath.name}: {e}")
            continue

        status = (intent.get("status") or "pending").lower()
        if status in ("acked", "done", "error"):
            continue
        action = (intent.get("action") or "BUY_TO_OPEN").upper()
        if action != "BUY_TO_OPEN":
            if action == "SELL_TO_CLOSE":
                # Continuous harvest path — actually sell on RH, don't park exits
                otype = (intent.get("option_type") or ("call" if intent.get("side") == "CALL" else "put")).lower()
                qty_e = max(1, int(intent.get("qty") or 1))
                strike_e = intent.get("strike")
                exp_e = intent.get("expiration")
                bid_e = float(intent.get("bid") or intent.get("limit_price") or intent.get("mid") or 0)
                ask_e = float(intent.get("ask") or 0)
                if bid_e > 0 and ask_e > 0:
                    px_e = round(max(bid_e, ask_e - 0.01), 2)
                elif bid_e > 0:
                    px_e = round(bid_e, 2)
                else:
                    px_e = round(float(intent.get("limit_price") or intent.get("mid") or 0.01), 2)
                reason_e = str(intent.get("reason") or "gamma_exit")
                logger.info(
                    f"[GAMMA-RAMP] EXIT {reason_e} {symbol} {otype} K={strike_e} exp={exp_e} qty={qty_e} @ {px_e}"
                )
                res_e = _execute_option_sell(symbol, otype, strike_e, exp_e, qty_e, px_e, reason_e)
                intent["status"] = "acked" if res_e.get("placed") or res_e.get("paper") else "error"
                intent["sell_result"] = {k2: res_e.get(k2) for k2 in ("placed", "paper", "error", "reason") if k2 in res_e or res_e.get(k2) is not None}
                intent["acked_ts"] = time.time()
                if res_e.get("placed") or res_e.get("paper"):
                    scan_counter[0] += 1
                    # shrink book if tracked
                    try:
                        book = _load_option_book()
                        kk = _option_book_key(symbol, strike_e, exp_e, otype)
                        if kk in (book.get("positions") or {}):
                            left = int(book["positions"][kk].get("qty") or 0) - qty_e
                            if left > 0:
                                book["positions"][kk]["qty"] = left
                            else:
                                book["positions"].pop(kk, None)
                            _save_option_book(book)
                    except Exception:
                        pass
                try:
                    fpath.write_text(json.dumps(intent, indent=2))
                    fpath.rename(done_dir / fpath.name)
                except Exception:
                    pass
            continue

        symbol = (intent.get("underlying") or "").upper().strip()
        option_type = (intent.get("option_type") or ("call" if intent.get("side") == "CALL" else "put")).lower()
        if option_type not in ("call", "put"):
            option_type = "call"

        sniper = {
            "strike": intent.get("strike"),
            "expiration": intent.get("expiration"),
            "ask": intent.get("ask") or intent.get("limit_price") or intent.get("mid"),
            "premium": intent.get("mid") or intent.get("ask") or intent.get("limit_price"),
            "bid": intent.get("bid"),
            "delta": intent.get("delta"),
            "gamma": intent.get("gamma"),
            "symbol": intent.get("occ"),
            "dte": intent.get("dte"),
            "source": "gamma_ramp",
            "limit_price": intent.get("limit_price"),
        }
        sml = intent.get("sml") or {
            "god_stacked": 6,
            "tier": "GOD_MODE",
            "execute_gate": True,
            "signal": f"GAMMA_RAMP_{intent.get('side')}",
            "confidence": 90.0,
            "gamma_ramp": True,
            "reason": intent.get("reason"),
        }

        # Optional qty override for this intent
        prev_qty = None
        if intent.get("qty"):
            try:
                global ROBINHOOD_OPTION_QTY
                prev_qty = ROBINHOOD_OPTION_QTY
                ROBINHOOD_OPTION_QTY = max(1, int(intent["qty"]))
            except Exception:
                prev_qty = None

        logger.info(
            f"[GAMMA-RAMP] RH route → {option_type.upper()} {symbol} "
            f"Δ={sniper.get('delta')} K={sniper.get('strike')} exp={sniper.get('expiration')} "
            f"id={intent.get('id')}"
        )
        before = scan_counter[0]
        try:
            _execute_option(symbol, option_type, sml, sniper, scan_counter)
        finally:
            if prev_qty is not None:
                ROBINHOOD_OPTION_QTY = prev_qty

        # Mark consumed so we don't re-fire (whether placed or gated)
        intent["status"] = "acked" if scan_counter[0] > before else "acked_no_fill"
        intent["acked_ts"] = time.time()
        intent["placed"] = scan_counter[0] > before
        try:
            fpath.write_text(json.dumps(intent, indent=2))
            fpath.rename(done_dir / fpath.name)
        except Exception as e:
            logger.warning(f"[GAMMA-RAMP] could not archive {fpath.name}: {e}")

    if scan_counter[0]:
        logger.info(f"[GAMMA-RAMP] placed {scan_counter[0]} option order(s) from outbox")
    return scan_counter[0]


# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    global _rh_logged_in  # explicitly declare global so Python never creates a local shadow
    logger.info("=" * 60)
    logger.info("SqueezeOS Robinhood Executor v3.7 — spread guard on entries + open-order fill reconciliation + holiday calendar")
    logger.info(f"  API         : {SQUEEZEOS_API_URL}")
    logger.info(f"  Poll every  : {POLL_INTERVAL_S}s  [DESK-LOCKED — env cannot set 300]")
    logger.info(f"  Hours       : 4:00 AM–8:00 PM ET (pre-market + regular + after-hours)")
    logger.info(f"  Ext hours   : LIMIT orders (buy +0.2% / sell -0.2% from last price)")
    logger.info(f"  Sources     : beastmode | TV webhook | oracle | gamma_ramp outbox→RH ({GAMMA_RAMP_OUTBOX_DIR})")
    logger.info(f"  Options Δ   : 0.30–0.40 target 0.35 | MM short-GEX forced-move | C+P")
    logger.info(f"  Options exit: stop -20% | scale +50%/+150% | bank +300/+500 | giveback lock | trail | Δ-exit 0.60")
    logger.info(f"  Options loop: CONTINUOUS harvest every poll — sell before loss of gains")
    logger.info(f"  Oracle      : 100% FETCH — uses live scan universe, no hardcoded watchlist")
    logger.info(f"  MIN_GOD     : {MIN_GOD_STACKED}/6 stacked (GRID_LOCK: {max(2,MIN_GOD_STACKED-1)}) [LOCKED]  |  ORACLE_MIN_CONF: {ORACLE_MIN_CONFIDENCE}%")
    logger.info(f"  PDT limit   : ${PDT_BALANCE_LIMIT}")
    logger.info(f"  Max order   : ${MAX_ORDER_USD} / {MAX_EQUITY_SHARES} shares")
    logger.info(f"  Daily cap   : {MAX_ORDERS_PER_DAY} orders / ${MAX_DAILY_NOTIONAL:.0f} notional / ${MAX_DAILY_LOSS_USD:.0f} loss limit")
    logger.info(f"  Per-scan    : max {MAX_PER_SCAN} orders per poll cycle")
    logger.info(f"  Position mon: stop-loss {STOP_LOSS_PCT}% / take-profit {TAKE_PROFIT_PCT}% (enabled={POSITION_MONITOR_ENABLED})")
    logger.info(f"  Spread guard: skip BUY if bid-ask > {MAX_SPREAD_PCT}% of mid (exits exempt)")
    logger.info(f"  Fill monitor: alert if an order sits unfilled > {FILL_ALERT_MINUTES:.0f} min")
    logger.info(f"  Paper mode  : {PAPER_MODE}")
    logger.info(f"  Kill switch : {KILL_SWITCH}")
    logger.info("=" * 60)

    # Fail loud if somehow still slow (should be impossible without ALLOW_SLOW_POLL)
    if POLL_INTERVAL_S > 90:
        logger.error(f"[STARTUP] FATAL: POLL_INTERVAL_S={POLL_INTERVAL_S} — refusing to run slow desk")
        raise SystemExit(2)
    if POLL_INTERVAL_S != 45 and os.environ.get("ALLOW_SLOW_POLL", "false").lower() != "true":
        logger.error(f"[STARTUP] FATAL: poll not locked at 45 (got {POLL_INTERVAL_S})")
        raise SystemExit(2)

    if KILL_SWITCH:
        logger.warning("[STARTUP] KILL_SWITCH=true — executor will log but not trade")

    # Pre-warm login ONCE
    if not PAPER_MODE:
        _ensure_login()

    _last_login_check  = time.time()
    _LOGIN_RECHECK_S   = int(os.environ.get("RH_LOGIN_RECHECK_S", "1800"))  # verify only every 30 min
    _auth_retry_count  = 0
    # Longer backoff — never sub-minute hammering that triggers RH "Trying to log in" loop
    _AUTH_BACKOFF      = [300, 600, 900, 1800, 3600]

    while True:
        try:
            _reset_daily_if_new_day()

            # Proactive session HEALTH CHECK every 30 min — verify only, no forced re-login
            if not PAPER_MODE and time.time() - _last_login_check > _LOGIN_RECHECK_S:
                ok = _healthcheck_session()
                _last_login_check = time.time()
                if ok:
                    _auth_retry_count = 0
                else:
                    delay = _AUTH_BACKOFF[min(_auth_retry_count, len(_AUTH_BACKOFF) - 1)]
                    _auth_retry_count += 1
                    logger.error(f"[AUTH] Health/re-auth failed (attempt {_auth_retry_count}) — backing off {delay}s (no login spam)")
                    time.sleep(delay)
                    continue

            # If flag says logged out, VERIFY first; login only if verify fails
            if not PAPER_MODE and not _rh_logged_in:
                if _rh_verify_session():
                    _rh_logged_in = True
                    _auth_retry_count = 0
                else:
                    ok = _ensure_login()
                    if not ok:
                        delay = _AUTH_BACKOFF[min(_auth_retry_count, len(_AUTH_BACKOFF) - 1)]
                        _auth_retry_count += 1
                        logger.error(f"[AUTH] Cannot authenticate (attempt {_auth_retry_count}) — skip cycle, retry in {delay}s")
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
            if not _is_trading_day():
                logger.info(f"[POLL] Market holiday — standing by, next check in {POLL_INTERVAL_S}s")
                time.sleep(POLL_INTERVAL_S)
                continue
            logger.info(f"[POLL] Scanning... (RH: {rh_status} | orders today: {_orders_today}/{MAX_ORDERS_PER_DAY} | notional: ${_daily_notional_usd:.0f}/${MAX_DAILY_NOTIONAL:.0f})")
            _reconcile_open_orders()
            stop_placed   = _check_stop_losses()
            beast_placed  = _poll_beastmode()
            tv_placed     = _poll_tv_pending()
            iam_placed    = _poll_iam_primary()
            oracle_placed = _poll_oracle()
            gamma_placed  = _poll_gamma_ramp()
            opt_book_placed = _manage_option_book()
            total_placed  = stop_placed + beast_placed + tv_placed + iam_placed + oracle_placed + gamma_placed + opt_book_placed
            if total_placed == 0:
                logger.info("[POLL] No signals this cycle — waiting for next scan")
            else:
                logger.info(
                    f"[POLL] Cycle complete — {total_placed} order(s) placed "
                    f"({stop_placed} stop/tp, {beast_placed} GOD, {tv_placed} Pine, "
                    f"{iam_placed} IAM-Primary, {oracle_placed} Oracle, {gamma_placed} GammaRamp→RH)"
                )
        except Exception as e:
            logger.error(f"[LOOP] Unexpected error: {e}")
        logger.info(f"[POLL] Next scan in {POLL_INTERVAL_S}s")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()


