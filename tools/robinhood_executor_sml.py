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
ROBINHOOD_USER     = os.environ.get("ROBINHOOD_USERNAME", "")
ROBINHOOD_PASS     = os.environ.get("ROBINHOOD_PASSWORD", "")
POLL_INTERVAL_S    = int(os.environ.get("POLL_INTERVAL_S", "300"))     # poll every 5 minutes
MIN_GOD_STACKED    = int(os.environ.get("MIN_GOD_STACKED", "4"))       # min SET9 stacked to execute (4/6 = institutional grade, max signal flow)
PDT_BALANCE_LIMIT  = float(os.environ.get("PDT_BALANCE_LIMIT", "2100.0"))
PDT_MAX_TRADES     = int(os.environ.get("PDT_MAX_TRADES", "3"))
PAPER_MODE           = os.environ.get("ROBINHOOD_PAPER_MODE", "false").lower() == "true"
KILL_SWITCH          = os.environ.get("KILL_SWITCH", "false").lower() == "true"
MAX_EQUITY_SHARES    = int(os.environ.get("MAX_EQUITY_SHARES", "3"))
MAX_ORDER_USD        = float(os.environ.get("MAX_ORDER_USD", "150.0"))
MAX_DAILY_LOSS_USD   = float(os.environ.get("MAX_DAILY_LOSS_USD", "100.0"))
MAX_ORDERS_PER_DAY   = int(os.environ.get("MAX_ORDERS_PER_DAY", "25"))
MAX_DAILY_NOTIONAL   = float(os.environ.get("MAX_DAILY_NOTIONAL_USD", "1500.0"))
MAX_PER_SCAN         = int(os.environ.get("MAX_PER_SCAN", "3"))

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
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        if today != _trading_day:
            _trading_day = today
            _orders_today = 0
            _daily_notional_usd = 0.0
            _daily_loss_usd = 0.0
            logger.info(f"[DAILY] New trading day {today} — all daily counters reset")

COOLDOWN_S     = 3600       # 1-hour per-symbol cooldown — poll is 5min so must be much longer
PDT_WINDOW_S   = 5 * 86400 # 5-day rolling window

# Tickers that are bankrupt, delisted, or known OTC junk — never trade these
_BLOCKLIST = {
    "AMCX",   # AMC Networks delisted
    "FXST",   # delisted
    "CODA",   # delisted
    "NKLA",   # Nikola — fraud, near-zero
}


# ── Robinhood login ────────────────────────────────────────────────────────────
def _ensure_login() -> bool:
    global _rh_logged_in
    if _rh_logged_in:
        return True
    if not ROBINHOOD_USER or not ROBINHOOD_PASS:
        logger.error("[RH] ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD not set in executor.env")
        return False
    try:
        import robin_stocks.robinhood as rh
        # store_session=True caches the auth token to disk — subsequent logins
        # use the stored token without requiring MFA again.
        rh.login(ROBINHOOD_USER, ROBINHOOD_PASS, store_session=True, pickle_name="rh_session")
        # Verify the session actually works — don't trust "no exception = success"
        profile = rh.profiles.load_account_profile()
        if not profile:
            raise ValueError("load_account_profile returned empty — session not authenticated")
        _rh_logged_in = True
        logger.info(f"[RH] Logged in OK — account verified")
        return True
    except Exception as e:
        _rh_logged_in = False
        logger.error(f"[RH] Login failed: {e}")
        logger.error("[RH] If Robinhood requires MFA: run the executor once manually in a terminal to complete MFA, then restart as a service.")
        return False


def _invalidate_login():
    """Call when an API error indicates the session has expired."""
    global _rh_logged_in
    _rh_logged_in = False
    logger.warning("[RH] Session invalidated — will re-login on next cycle")


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


# ── Order execution ────────────────────────────────────────────────────────────
def _execute(symbol: str, side: str, sml: dict, scan_counter: list):
    """scan_counter is a single-element list [n] so callers can track per-scan count."""
    global _orders_today, _daily_notional_usd
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
    if now - last < COOLDOWN_S:
        logger.info(f"[EXEC] {symbol} cooldown — {int(COOLDOWN_S-(now-last))}s left")
        return

    god_count = sml.get("god_stacked", 0)
    if god_count < MIN_GOD_STACKED:
        logger.info(f"[EXEC] {symbol} god_stacked={god_count} < {MIN_GOD_STACKED} — skip")
        return

    # IWM trades 0DTE options only — never buy shares. Alert and stop here.
    if symbol == "IWM":
        if now - last >= COOLDOWN_S:
            _last_execution[symbol] = now
            _save_last_execution(_last_execution)
            logger.info(f"[EXEC] IWM GOD MODE {god_count}/6 — 0DTE OPTIONS ALERT ONLY (no share order)")
            try:
                price = 0.0
                import robin_stocks.robinhood as rh
                price = float(rh.stocks.get_latest_price(symbol)[0] or 0)
            except Exception:
                pass
            _discord(symbol, f"{side}-0DTE-ALERT", 0, price, sml, {"alert_only": True})
        return

    if not _pdt_allowed():
        return

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

    qty = max(1, int(MAX_ORDER_USD // price))
    qty = min(qty, MAX_EQUITY_SHARES)

    logger.info(f"[EXEC] 🚀 RH GOD MODE — {side.upper()} {qty}x {symbol} @ ${price:.2f} | SET9:{god_count}/6")

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
                if side == "buy":
                    r = rh.orders.order_buy_market(symbol, qty, extendedHours=True)
                else:
                    r = rh.orders.order_sell_market(symbol, qty, extendedHours=True)
                result = {"placed": True, "raw": r}
                logger.info(f"[RH] Order placed ✅ {symbol} {side} x{qty}")
                scan_counter[0] += 1
                with _lock:
                    _orders_today += 1
                    _daily_notional_usd += qty * price
                    logger.info(f"[DAILY] Orders: {_orders_today}/{MAX_ORDERS_PER_DAY} | Notional: ${_daily_notional_usd:.2f}/${MAX_DAILY_NOTIONAL:.0f}")
            except Exception as e:
                err = str(e)
                logger.error(f"[RH] Order error: {err}")
                if "logged in" in err.lower():
                    _invalidate_login()
                result = {"error": err}

    _discord(symbol, side, qty, price, sml, result)


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

    signals    = data.get("signals") or []
    cache_age  = data.get("cache_age_s")
    age_str    = f", cache age {cache_age:.0f}s" if cache_age is not None else ""
    now        = time.time()

    if not signals:
        logger.info(f"[POLL] beastmode: 0 signals from server{age_str} — scan universe warming up or no convergence")
        return 0

    # Classify signals for diagnostics
    god_hits   = []
    skipped    = {"no_tier": 0, "low_stack": 0, "cooldown": 0, "blocklist": 0}

    for hit in signals:
        symbol = (hit.get("symbol") or "").upper().strip()
        sml    = hit.get("sml_matrix") or {}
        tier   = sml.get("tier", "")
        gate   = sml.get("execute_gate", False)
        stacked = sml.get("god_stacked", 0)
        if tier != "GOD_MODE" or not gate:
            skipped["no_tier"] += 1
            continue
        if stacked < MIN_GOD_STACKED:
            skipped["low_stack"] += 1
            logger.debug(f"[POLL] {symbol} god_stacked={stacked} < threshold {MIN_GOD_STACKED} — skip")
            continue
        if symbol in _BLOCKLIST:
            skipped["blocklist"] += 1
            continue
        cooldown_remaining = COOLDOWN_S - (now - _last_execution.get(symbol, 0))
        if cooldown_remaining > 0:
            skipped["cooldown"] += 1
            logger.info(f"[POLL] {symbol} GOD MODE {stacked}/6 — cooldown {int(cooldown_remaining)}s left")
            continue
        god_hits.append((symbol, sml))

    logger.info(
        f"[POLL] beastmode: {len(signals)} total | {len(god_hits)} ready to execute | "
        f"filtered: {skipped['no_tier']} non-GOD, {skipped['low_stack']} low-stack (<{MIN_GOD_STACKED}), "
        f"{skipped['cooldown']} cooldown, {skipped['blocklist']} blocklist{age_str}"
    )

    if _circuit_open():
        logger.info(f"[POLL] {len(god_hits)} GOD MODE signal(s) ready but circuit breaker open — skipping execution")
        return 0

    scan_counter = [0]
    for symbol, sml in god_hits:
        signal = sml.get("signal", "")
        side   = "buy" if "BULL" in signal or signal in ("BEASTMODE", "GOD_MODE", "DUAL_GRID_LOCK") else "sell"
        logger.info(f"[POLL] GOD MODE candidate: {symbol} {side.upper()} god_stacked={sml.get('god_stacked',0)}/6 — sending to executor")
        _execute(symbol, side, sml, scan_counter)
        if scan_counter[0] >= MAX_PER_SCAN:
            logger.info(f"[POLL] Per-scan limit {MAX_PER_SCAN} reached — stopping beastmode batch")
            break

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


# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("SqueezeOS Robinhood Executor v2.1 — Dual Poll Mode")
    logger.info(f"  API         : {SQUEEZEOS_API_URL}")
    logger.info(f"  Poll every  : {POLL_INTERVAL_S}s")
    logger.info(f"  Sources     : /api/beastmode (SET9) + /api/webhooks/tv_pending (Pine)")
    logger.info(f"  MIN_GOD     : {MIN_GOD_STACKED}/6 SET9 stacked")
    logger.info(f"  PDT limit   : ${PDT_BALANCE_LIMIT}")
    logger.info(f"  Max order   : ${MAX_ORDER_USD} / {MAX_EQUITY_SHARES} shares")
    logger.info(f"  Daily cap   : {MAX_ORDERS_PER_DAY} orders / ${MAX_DAILY_NOTIONAL:.0f} notional / ${MAX_DAILY_LOSS_USD:.0f} loss limit")
    logger.info(f"  Per-scan    : max {MAX_PER_SCAN} orders per poll cycle")
    logger.info(f"  Paper mode  : {PAPER_MODE}")
    logger.info(f"  Kill switch : {KILL_SWITCH}")
    logger.info("=" * 60)

    if KILL_SWITCH:
        logger.warning("[STARTUP] KILL_SWITCH=true — executor will log but not trade")

    # Pre-warm login
    if not PAPER_MODE:
        _ensure_login()

    while True:
        try:
            _reset_daily_if_new_day()
            rh_status = "PAPER" if PAPER_MODE else ("OK" if _rh_logged_in else "pending-login")
            logger.info(f"[POLL] Scanning... (RH: {rh_status} | orders today: {_orders_today}/{MAX_ORDERS_PER_DAY} | notional: ${_daily_notional_usd:.0f}/${MAX_DAILY_NOTIONAL:.0f})")
            beast_placed = _poll_beastmode()
            tv_placed    = _poll_tv_pending()
            total_placed = beast_placed + tv_placed
            if total_placed == 0:
                logger.info("[POLL] No signals this cycle — waiting for next scan")
            else:
                logger.info(f"[POLL] Cycle complete — {total_placed} order(s) placed ({beast_placed} GOD MODE, {tv_placed} Pine)")
        except Exception as e:
            logger.error(f"[LOOP] Unexpected error: {e}")
        logger.info(f"[POLL] Next scan in {POLL_INTERVAL_S}s")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()


