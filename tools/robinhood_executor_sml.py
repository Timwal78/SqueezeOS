#!/usr/bin/env python3
"""
SML Sovereign Harmonic Matrix v7.0 — Robinhood Auto-Executor

Polls SqueezeOS for SML BASE-4 grid matrix signals + council bias,
then executes equity fractional orders AND/OR options via robin_stocks.

Run via PM2:
  pm2 start robinhood_executor_sml.py --name robinhood-executor --interpreter python

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ENV VARIABLES  (set in .env or PM2 environment)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core:
  SQUEEZEOS_URL            API base (default: https://squeezeos-api.onrender.com)
  SML_WEBHOOK_SECRET       Matches SqueezeOS SML_WEBHOOK_SECRET (for trade log posts)
  WATCHLIST                Comma-separated symbols (default: GME,AMC,MSTR,NVDA,SPY,QQQ,TSLA,PLTR)
  POLL_INTERVAL_SECONDS    Seconds between polls (default: 60)
  LIVE_TRADING             "true" to place REAL orders (default: paper mode)

Equity:
  MAX_POSITION_DOLLARS     Max dollars per equity position (default: 500)
  SML_MIN_CONVICTION       Min combined conviction to enter equity (default: 70)

Options (set OPTIONS_ENABLED=true to activate):
  OPTIONS_ENABLED          "true" to enable options orders (default: false)
  MAX_OPTIONS_DOLLARS      Max premium per options trade (default: 200)
  OPTIONS_DTE_MIN          Min days to expiration (default: 7)
  OPTIONS_DTE_MAX          Max days to expiration (default: 21)
  OPTIONS_MIN_CONVICTION   Min conviction to use options (default: 80)
  OPTIONS_CONTRACTS        Number of contracts per trade (default: 1)

Notifications:
  DISCORD_WEBHOOK_ROBINHOOD  Dedicated Robinhood trade channel
  DISCORD_WEBHOOK_ALL        Fallback if ROBINHOOD webhook not set

Auth:
  RH_USERNAME              Robinhood email (only if pickle expired)
  RH_PASSWORD              Robinhood password (only if pickle expired)
  RH_PICKLE_PATH           Path to robinhood.pickle (default: ~/.tokens/robinhood.pickle)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SIGNAL → POSITION SIZE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Combined conviction = SML conviction × SqueezeOS bias multiplier:
  BUY (IGNITION) ×1.25 / BUY ×1.10 / HOLD ×1.00 / SELL ×0.50 / SHIELD blocks entry

Equity sizing:
  100 → 100%    90 → 80%    80 → 60%    75 → 35%    55 → 15%

Options fire when:
  OPTIONS_ENABLED=true AND combined_conviction ≥ OPTIONS_MIN_CONVICTION
  Bullish signal (BUY/BUY_IGNITION) → ATM call | Bearish (SELL/SHIELD exit) → ATM put

PDT: tracks same-day round-trips, warns at 3/5-day limit.
Trade log: all orders posted to GET https://squeezeos-api.onrender.com/api/sml/trades
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, date, timedelta
from typing import Optional

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap env
# ─────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("RH-SML")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
SQUEEZEOS_URL          = os.getenv("SQUEEZEOS_URL", "https://squeezeos-api.onrender.com").rstrip("/")
SML_WEBHOOK_SECRET     = os.getenv("SML_WEBHOOK_SECRET", "")
WATCHLIST              = [s.strip().upper() for s in os.getenv("WATCHLIST", "GME,AMC,MSTR,NVDA,SPY,QQQ,TSLA,PLTR").split(",") if s.strip()]
POLL_INTERVAL          = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
LIVE_TRADING           = os.getenv("LIVE_TRADING", "false").lower() == "true"

# Equity
MAX_POSITION_DOLLARS   = float(os.getenv("MAX_POSITION_DOLLARS", "500"))
SML_MIN_CONVICTION     = int(os.getenv("SML_MIN_CONVICTION", "70"))

# Options
OPTIONS_ENABLED        = os.getenv("OPTIONS_ENABLED", "false").lower() == "true"
MAX_OPTIONS_DOLLARS    = float(os.getenv("MAX_OPTIONS_DOLLARS", "200"))
OPTIONS_DTE_MIN        = int(os.getenv("OPTIONS_DTE_MIN", "7"))
OPTIONS_DTE_MAX        = int(os.getenv("OPTIONS_DTE_MAX", "21"))
OPTIONS_MIN_CONVICTION = int(os.getenv("OPTIONS_MIN_CONVICTION", "80"))
OPTIONS_CONTRACTS      = int(os.getenv("OPTIONS_CONTRACTS", "1"))

# Discord — dedicated Robinhood channel
DISCORD_WEBHOOK        = (
    os.getenv("DISCORD_WEBHOOK_ROBINHOOD") or
    os.getenv("DISCORD_WEBHOOK_ALL") or ""
)

# Robinhood auth
RH_USERNAME            = os.getenv("RH_USERNAME", "")
RH_PASSWORD            = os.getenv("RH_PASSWORD", "")
RH_PICKLE_PATH         = os.getenv("RH_PICKLE_PATH", os.path.expanduser("~/.tokens/robinhood.pickle"))

# Equity size curve: conviction threshold → fraction of MAX_POSITION_DOLLARS
_SIZE_CURVE: list[tuple[int, float]] = [
    (100, 1.00),
    (90,  0.80),
    (80,  0.60),
    (75,  0.35),
    (55,  0.15),
    (0,   0.00),
]

_BIAS_MULT: dict[str, float] = {
    "BUY (IGNITION)": 1.25,
    "BUY":            1.10,
    "HOLD":           1.00,
    "SELL":           0.50,
    "SHIELD":         0.00,
}

_BULLISH_BIASES = {"BUY (IGNITION)", "BUY"}
_BEARISH_BIASES = {"SELL", "SHIELD"}


def _size_for_conviction(conviction: int) -> float:
    for threshold, size in _SIZE_CURVE:
        if conviction >= threshold:
            return size
    return 0.0


def _fetch(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Fetch failed %s — %s", url, exc)
        return None


def _next_expiry(dte_min: int = 7, dte_max: int = 21) -> str:
    """Return the nearest Friday expiration within DTE range (YYYY-MM-DD)."""
    today = date.today()
    for delta in range(dte_min, dte_max + 1):
        candidate = today + timedelta(days=delta)
        if candidate.weekday() == 4:  # Friday
            return candidate.isoformat()
    # Fallback: first Friday after dte_min
    for delta in range(dte_min, 90):
        candidate = today + timedelta(days=delta)
        if candidate.weekday() == 4:
            return candidate.isoformat()
    return (today + timedelta(days=dte_min)).isoformat()


def _atm_strike(price: float) -> float:
    """Round to ATM strike: nearest $1 under $50, $5 under $200, $10 above."""
    if price < 50:
        return round(price)
    elif price < 200:
        return round(price / 5) * 5
    return round(price / 10) * 10


# ─────────────────────────────────────────────────────────────────────────────
# Trade log — posts completed trades to SqueezeOS for visibility
# ─────────────────────────────────────────────────────────────────────────────
def _log_trade_remote(trade: dict):
    """POST trade record to SqueezeOS /api/sml/trade so it shows in /api/sml/trades."""
    url = f"{SQUEEZEOS_URL}/api/sml/trade"
    if SML_WEBHOOK_SECRET:
        url += f"?secret={SML_WEBHOOK_SECRET}"
    try:
        requests.post(url, json=trade, timeout=5)
    except Exception as exc:
        logger.warning("Trade log post failed — %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Robinhood client
# ─────────────────────────────────────────────────────────────────────────────
class RobinhoodClient:
    def __init__(self):
        self._rh = None

    def login(self) -> bool:
        try:
            import robin_stocks.robinhood as rh
            self._rh = rh
            pickle_name = os.path.splitext(os.path.basename(RH_PICKLE_PATH))[0]
            self._rh.login(
                username=RH_USERNAME or None,
                password=RH_PASSWORD or None,
                store_session=True,
                pickle_name=pickle_name,
            )
            logger.info("[RH] Logged in (pickle=%s)", pickle_name)
            return True
        except Exception as exc:
            logger.error("[RH] Login failed — %s", exc)
            return False

    def buying_power(self) -> float:
        if not self._rh:
            return 0.0
        try:
            profile = self._rh.profiles.load_portfolio_profile()
            return float(profile.get("withdrawable_amount") or 0.0)
        except Exception as exc:
            logger.warning("[RH] buying_power — %s", exc)
            return 0.0

    def price(self, symbol: str) -> Optional[float]:
        if not self._rh:
            return None
        try:
            prices = self._rh.stocks.get_latest_price(symbol)
            return float(prices[0]) if prices else None
        except Exception as exc:
            logger.warning("[RH] price(%s) — %s", symbol, exc)
            return None

    # ── Equity ────────────────────────────────────────────────────────────────

    def buy_equity(self, symbol: str, dollars: float) -> Optional[dict]:
        if not LIVE_TRADING:
            logger.info("[PAPER] BUY EQUITY %s $%.2f", symbol, dollars)
            return {"paper": True, "symbol": symbol, "dollars": dollars}
        try:
            result = self._rh.orders.order_buy_fractional_by_price(symbol, dollars)
            logger.info("[LIVE] BUY %s $%.2f → id=%s", symbol, dollars, result.get("id", "?"))
            return result
        except Exception as exc:
            logger.error("[RH] buy_equity(%s) — %s", symbol, exc)
            return None

    def sell_equity(self, symbol: str, shares: float) -> Optional[dict]:
        if not LIVE_TRADING:
            logger.info("[PAPER] SELL EQUITY %s %.6f shares", symbol, shares)
            return {"paper": True, "symbol": symbol, "shares": shares}
        try:
            result = self._rh.orders.order_sell_fractional_by_price(
                symbol, shares, priceType="ask_price", timeInForce="gfd"
            )
            logger.info("[LIVE] SELL %s %.6f → id=%s", symbol, shares, result.get("id", "?"))
            return result
        except Exception as exc:
            logger.error("[RH] sell_equity(%s) — %s", symbol, exc)
            return None

    def open_shares(self, symbol: str) -> float:
        if not self._rh or not LIVE_TRADING:
            return 0.0
        try:
            positions = self._rh.account.get_open_stock_positions()
            for p in (positions or []):
                if symbol.upper() in p.get("instrument", "").upper():
                    return float(p.get("quantity", 0))
        except Exception as exc:
            logger.warning("[RH] open_shares(%s) — %s", symbol, exc)
        return 0.0

    # ── Options ───────────────────────────────────────────────────────────────

    def _find_option(self, symbol: str, expiry: str, strike: float, opt_type: str) -> Optional[dict]:
        try:
            opts = self._rh.options.find_options_by_expiration_and_strike(
                symbol, expiry, str(strike), optionType=opt_type
            )
            return opts[0] if opts else None
        except Exception as exc:
            logger.warning("[RH] find_option(%s %s %s) — %s", symbol, strike, opt_type, exc)
            return None

    def _mid_price(self, option: dict) -> float:
        ask = float(option.get("ask_price") or 0)
        bid = float(option.get("bid_price") or 0)
        if ask <= 0:
            return bid
        return round((ask + bid) / 2 + 0.05, 2)  # slight offset to improve fill

    def buy_option(self, symbol: str, opt_type: str,
                   strike: Optional[float] = None,
                   expiry: Optional[str] = None,
                   contracts: int = 1) -> Optional[dict]:
        """
        Buy a call or put option.
        opt_type: 'call' or 'put'
        If strike/expiry are None they are chosen automatically (ATM, next weekly).
        """
        if not LIVE_TRADING:
            current = self.price(symbol) or 0.0
            strike = strike or _atm_strike(current)
            expiry = expiry or _next_expiry(OPTIONS_DTE_MIN, OPTIONS_DTE_MAX)
            logger.info("[PAPER] BUY %s %s $%.0f %s x%d", opt_type.upper(), symbol, strike, expiry, contracts)
            return {"paper": True, "symbol": symbol, "option_type": opt_type,
                    "strike": strike, "expiry": expiry, "contracts": contracts}

        current = self.price(symbol) or 0.0
        if current <= 0:
            logger.warning("[RH] Cannot price %s for options", symbol)
            return None

        strike = strike or _atm_strike(current)
        expiry = expiry or _next_expiry(OPTIONS_DTE_MIN, OPTIONS_DTE_MAX)

        option = self._find_option(symbol, expiry, strike, opt_type)
        if not option:
            logger.warning("[RH] No %s %s $%.0f %s option found", symbol, opt_type, strike, expiry)
            return None

        limit_price = self._mid_price(option)
        if limit_price <= 0:
            logger.warning("[RH] Zero premium for %s %s — skip", symbol, opt_type)
            return None

        # Check cost vs budget
        cost = limit_price * 100 * contracts  # each contract = 100 shares
        if cost > MAX_OPTIONS_DOLLARS:
            logger.warning("[RH] Options cost $%.2f > MAX_OPTIONS_DOLLARS $%.2f — skip", cost, MAX_OPTIONS_DOLLARS)
            return None

        try:
            result = self._rh.orders.order_buy_option_limit(
                positionEffect="open",
                creditOrDebit="debit",
                price=limit_price,
                symbol=symbol,
                quantity=contracts,
                expirationDate=expiry,
                strike=strike,
                optionType=opt_type,
                timeInForce="gfd",
            )
            logger.info("[LIVE] BUY %s %s $%.0f %s @$%.2f → id=%s",
                        opt_type.upper(), symbol, strike, expiry, limit_price, result.get("id", "?"))
            return {**result, "strike": strike, "expiry": expiry, "limit_price": limit_price, "cost": cost}
        except Exception as exc:
            logger.error("[RH] buy_option(%s %s) — %s", symbol, opt_type, exc)
            return None

    def sell_option_to_close(self, symbol: str, opt_type: str,
                             strike: float, expiry: str, contracts: int = 1) -> Optional[dict]:
        """Sell-to-close an existing option position."""
        if not LIVE_TRADING:
            logger.info("[PAPER] SELL-TO-CLOSE %s %s $%.0f %s x%d", opt_type.upper(), symbol, strike, expiry, contracts)
            return {"paper": True, "symbol": symbol, "closed": True}

        option = self._find_option(symbol, expiry, strike, opt_type)
        if not option:
            logger.warning("[RH] Cannot find option to close: %s %s $%.0f %s", symbol, opt_type, strike, expiry)
            return None

        limit_price = self._mid_price(option)
        try:
            result = self._rh.orders.order_sell_option_limit(
                positionEffect="close",
                creditOrDebit="credit",
                price=limit_price,
                symbol=symbol,
                quantity=contracts,
                expirationDate=expiry,
                strike=strike,
                optionType=opt_type,
                timeInForce="gfd",
            )
            logger.info("[LIVE] SELL-TO-CLOSE %s %s $%.0f %s @$%.2f", opt_type.upper(), symbol, strike, expiry, limit_price)
            return result
        except Exception as exc:
            logger.error("[RH] sell_option_to_close(%s) — %s", symbol, exc)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Signal evaluator
# ─────────────────────────────────────────────────────────────────────────────
class SignalEvaluator:
    def evaluate(self, symbol: str) -> dict:
        sml = _fetch(f"{SQUEEZEOS_URL}/api/sml/signal/{symbol}") or {}
        sml_active      = sml.get("active", False)
        sml_conviction  = int(sml.get("conviction", 0))
        sml_signal_type = sml.get("signal_type", "NONE")
        sml_action      = sml.get("action", "WATCH")

        sqz      = _fetch(f"{SQUEEZEOS_URL}/api/preview/{symbol}") or {}
        sqz_bias = sqz.get("bias", "HOLD")

        bias_mult         = _BIAS_MULT.get(sqz_bias, 1.0)
        combined          = min(100, int(sml_conviction * bias_mult))
        position_frac     = _size_for_conviction(combined)
        dollars_to_deploy = round(MAX_POSITION_DOLLARS * position_frac, 2)

        use_options = (
            OPTIONS_ENABLED and
            sml_active and
            combined >= OPTIONS_MIN_CONVICTION
        )

        if sml_action == "EXIT":
            final_action = "EXIT"
        elif sqz_bias == "SHIELD" or not sml_active:
            final_action = "HOLD"
        elif combined < SML_MIN_CONVICTION or position_frac == 0.0:
            final_action = "HOLD"
        else:
            final_action = "BUY"

        return {
            "symbol":              symbol,
            "final_action":        final_action,
            "sml_signal_type":     sml_signal_type,
            "sml_conviction":      sml_conviction,
            "sml_active":          sml_active,
            "sqz_bias":            sqz_bias,
            "bias_mult":           bias_mult,
            "combined_conviction": combined,
            "position_frac":       position_frac,
            "dollars_to_deploy":   dollars_to_deploy,
            "use_options":         use_options,
            "ts":                  time.time(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Discord
# ─────────────────────────────────────────────────────────────────────────────
def _discord(msg: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=5)
    except Exception:
        pass


def _fmt_equity_msg(ev: dict, pnl: Optional[float] = None) -> str:
    mode = "📄 PAPER" if not LIVE_TRADING else "💰 LIVE"
    ts   = datetime.utcnow().strftime("%H:%M:%S UTC")
    sym  = ev["symbol"]
    if ev["final_action"] == "BUY":
        return (
            f"**{mode} BUY EQUITY** | `{sym}` | **${ev['dollars_to_deploy']:.2f}**\n"
            f"SML: `{ev['sml_signal_type']}` · Conviction: `{ev['combined_conviction']}/100`\n"
            f"SqueezeOS: `{ev['sqz_bias']}` · Size: `{ev['position_frac']*100:.0f}%`\n"
            f"_{ts}_"
        )
    pnl_str = f" | PnL: `${pnl:+.2f}`" if pnl is not None else ""
    return f"**{mode} EXIT EQUITY** | `{sym}`{pnl_str} | _{ts}_"


def _fmt_options_msg(ev: dict, strike: float, expiry: str, opt_type: str,
                     cost: float, pnl: Optional[float] = None) -> str:
    mode   = "📄 PAPER" if not LIVE_TRADING else "💰 LIVE"
    ts     = datetime.utcnow().strftime("%H:%M:%S UTC")
    sym    = ev["symbol"]
    action = "BUY" if pnl is None else "CLOSE"
    emoji  = "📈" if opt_type == "call" else "📉"
    pnl_str = f" | PnL: `${pnl:+.2f}`" if pnl is not None else f" | Premium: `${cost:.2f}`"
    return (
        f"**{mode} {action} {opt_type.upper()} OPTION** {emoji} | `{sym}` `${strike:.0f}` `{expiry}`\n"
        f"SML: `{ev['sml_signal_type']}` · Conviction: `{ev['combined_conviction']}/100` · `{ev['sqz_bias']}`{pnl_str}\n"
        f"_{ts}_"
    )


# ─────────────────────────────────────────────────────────────────────────────
# PDT guard
# ─────────────────────────────────────────────────────────────────────────────
class PDTGuard:
    def __init__(self):
        self._trades: list[dict] = []

    def record(self, symbol: str):
        today = date.today().isoformat()
        self._trades.append({"symbol": symbol, "date": today})
        count = sum(1 for t in self._trades if t["date"] == today)
        if count >= 3:
            msg = (
                f"⚠️ **PDT WARNING** — {count} same-day round-trips today.\n"
                f"Accounts under $25k are limited to 3 per rolling 5-day window.\n"
                f"Symbol: `{symbol}`"
            )
            logger.warning("[PDT] %d day-trades today", count)
            _discord(msg)

    def today_count(self) -> int:
        today = date.today().isoformat()
        return sum(1 for t in self._trades if t["date"] == today)


# ─────────────────────────────────────────────────────────────────────────────
# Main executor
# ─────────────────────────────────────────────────────────────────────────────
class SMLExecutor:
    def __init__(self, rh: RobinhoodClient, evaluator: SignalEvaluator):
        self.rh           = rh
        self.evaluator    = evaluator
        self.pdt          = PDTGuard()
        self._eq_positions: dict[str, dict]   = {}  # symbol → equity position
        self._opt_positions: dict[str, dict]  = {}  # symbol → options position

    def _eq_shares(self, symbol: str) -> float:
        if LIVE_TRADING:
            return self.rh.open_shares(symbol)
        return self._eq_positions.get(symbol, {}).get("shares", 0.0)

    # ── Equity trade handlers ─────────────────────────────────────────────────

    def _enter_equity(self, symbol: str, ev: dict):
        dollars = ev["dollars_to_deploy"]
        if dollars <= 0:
            return
        if LIVE_TRADING and self.rh.buying_power() < dollars:
            _discord(f"⚠️ `{symbol}` — buying power too low for ${dollars:.2f} entry")
            return
        order = self.rh.buy_equity(symbol, dollars)
        if order is None:
            return
        price  = self.rh.price(symbol) or 0.0
        shares = dollars / price if price > 0 else 0.0
        self._eq_positions[symbol] = {
            "shares":        shares,
            "entry_price":   price,
            "entry_dollars": dollars,
            "entry_ts":      time.time(),
            "entry_signal":  ev["sml_signal_type"],
            "entry_date":    date.today().isoformat(),
        }
        logger.info("[EQ] ENTER %s $%.2f @ $%.4f (%.6f sh)", symbol, dollars, price, shares)
        _discord(_fmt_equity_msg(ev))
        _log_trade_remote({
            "symbol": symbol, "action": "BUY", "asset_type": "equity",
            "signal_type": ev["sml_signal_type"],
            "combined_conviction": ev["combined_conviction"],
            "sqz_bias": ev["sqz_bias"],
            "dollars": dollars, "shares": shares, "price": price,
            "mode": "live" if LIVE_TRADING else "paper", "ts": time.time(),
        })

    def _exit_equity(self, symbol: str, ev: dict):
        pos    = self._eq_positions.get(symbol, {})
        shares = pos.get("shares") or self._eq_shares(symbol)
        if shares <= 0:
            return
        order = self.rh.sell_equity(symbol, shares)
        if order is None:
            return
        current = self.rh.price(symbol) or 0.0
        pnl     = (current - pos.get("entry_price", current)) * shares
        if pos.get("entry_date") == date.today().isoformat():
            self.pdt.record(symbol)
        logger.info("[EQ] EXIT %s %.6f sh | PnL $%.2f", symbol, shares, pnl)
        _discord(_fmt_equity_msg(ev, pnl=pnl))
        _log_trade_remote({
            "symbol": symbol, "action": "EXIT", "asset_type": "equity",
            "signal_type": ev["sml_signal_type"],
            "combined_conviction": ev["combined_conviction"],
            "sqz_bias": ev["sqz_bias"],
            "shares": shares, "price": current, "pnl": round(pnl, 2),
            "mode": "live" if LIVE_TRADING else "paper", "ts": time.time(),
        })
        self._eq_positions.pop(symbol, None)

    # ── Options trade handlers ────────────────────────────────────────────────

    def _enter_option(self, symbol: str, ev: dict):
        price = self.rh.price(symbol) or 0.0
        if price <= 0:
            return
        is_bullish  = ev["sqz_bias"] in _BULLISH_BIASES
        opt_type    = "call" if is_bullish else "put"
        strike      = _atm_strike(price)
        expiry      = _next_expiry(OPTIONS_DTE_MIN, OPTIONS_DTE_MAX)

        order = self.rh.buy_option(symbol, opt_type, strike, expiry, OPTIONS_CONTRACTS)
        if order is None:
            return

        cost = order.get("cost", MAX_OPTIONS_DOLLARS)
        self._opt_positions[symbol] = {
            "opt_type":      opt_type,
            "strike":        strike,
            "expiry":        expiry,
            "contracts":     OPTIONS_CONTRACTS,
            "entry_premium": cost / (OPTIONS_CONTRACTS * 100) if OPTIONS_CONTRACTS else 0,
            "entry_cost":    cost,
            "entry_ts":      time.time(),
            "entry_date":    date.today().isoformat(),
            "entry_signal":  ev["sml_signal_type"],
        }
        logger.info("[OPT] ENTER %s %s $%.0f %s x%d | ~$%.2f",
                    opt_type.upper(), symbol, strike, expiry, OPTIONS_CONTRACTS, cost)
        _discord(_fmt_options_msg(ev, strike, expiry, opt_type, cost))
        _log_trade_remote({
            "symbol": symbol, "action": f"BUY_{opt_type.upper()}", "asset_type": opt_type,
            "signal_type": ev["sml_signal_type"],
            "combined_conviction": ev["combined_conviction"],
            "sqz_bias": ev["sqz_bias"],
            "strike": strike, "expiry": expiry, "contracts": OPTIONS_CONTRACTS,
            "option_type": opt_type, "dollars": cost,
            "mode": "live" if LIVE_TRADING else "paper", "ts": time.time(),
        })

    def _exit_option(self, symbol: str, ev: dict):
        pos = self._opt_positions.get(symbol)
        if not pos:
            return
        order = self.rh.sell_option_to_close(
            symbol, pos["opt_type"], pos["strike"], pos["expiry"], pos["contracts"]
        )
        if order is None:
            return
        logger.info("[OPT] CLOSE %s %s $%.0f %s", pos["opt_type"].upper(), symbol, pos["strike"], pos["expiry"])
        _discord(_fmt_options_msg(ev, pos["strike"], pos["expiry"], pos["opt_type"], 0, pnl=None))
        _log_trade_remote({
            "symbol": symbol, "action": f"CLOSE_{pos['opt_type'].upper()}", "asset_type": pos["opt_type"],
            "signal_type": ev["sml_signal_type"],
            "combined_conviction": ev["combined_conviction"],
            "sqz_bias": ev["sqz_bias"],
            "strike": pos["strike"], "expiry": pos["expiry"], "contracts": pos["contracts"],
            "option_type": pos["opt_type"],
            "mode": "live" if LIVE_TRADING else "paper", "ts": time.time(),
        })
        self._opt_positions.pop(symbol, None)

    # ── Main per-symbol loop ──────────────────────────────────────────────────

    def _run_symbol(self, symbol: str):
        ev     = self.evaluator.evaluate(symbol)
        action = ev["final_action"]

        # ── Equity ────────────────────────────────────────────
        if action == "BUY" and self._eq_shares(symbol) == 0.0:
            self._enter_equity(symbol, ev)
        elif action == "EXIT" and self._eq_shares(symbol) > 0.0:
            self._exit_equity(symbol, ev)

        # ── Options (only when OPTIONS_ENABLED and conviction high enough) ────
        if OPTIONS_ENABLED:
            has_open_option = symbol in self._opt_positions
            if action == "BUY" and ev["use_options"] and not has_open_option:
                self._enter_option(symbol, ev)
            elif action == "EXIT" and has_open_option:
                self._exit_option(symbol, ev)

        if action == "HOLD":
            logger.debug("[%s] HOLD | conv=%d | bias=%s | active=%s",
                         symbol, ev["combined_conviction"], ev["sqz_bias"], ev["sml_active"])

    def run_forever(self):
        mode    = "PAPER" if not LIVE_TRADING else "LIVE 💰"
        opt_str = f"+ OPTIONS (≥{OPTIONS_MIN_CONVICTION} conv, max ${MAX_OPTIONS_DOLLARS})" if OPTIONS_ENABLED else "equity only"
        banner  = (
            f"**SML Robinhood Executor started**\n"
            f"Mode: `{mode}` | Assets: `{opt_str}`\n"
            f"Watching: `{', '.join(WATCHLIST)}`\n"
            f"Max equity: `${MAX_POSITION_DOLLARS:.0f}` | Min conviction: `{SML_MIN_CONVICTION}/100` | Poll: `{POLL_INTERVAL}s`\n"
            f"Trade log: `{SQUEEZEOS_URL}/api/sml/trades`"
        )
        logger.info("═" * 60)
        logger.info("  SML Sovereign Harmonic Matrix — Robinhood Executor")
        logger.info("  Mode: %s | %s", mode, opt_str)
        logger.info("  Watching: %s", ", ".join(WATCHLIST))
        logger.info("  Max equity $%.0f | Min conviction %d | Poll %ds",
                    MAX_POSITION_DOLLARS, SML_MIN_CONVICTION, POLL_INTERVAL)
        logger.info("  Trade log: %s/api/sml/trades", SQUEEZEOS_URL)
        logger.info("═" * 60)
        _discord(banner)

        while True:
            for sym in WATCHLIST:
                try:
                    self._run_symbol(sym)
                except Exception as exc:
                    logger.error("[%s] Error: %s", sym, exc)

            eq_open  = list(self._eq_positions.keys())
            opt_open = list(self._opt_positions.keys())
            logger.info("[Cycle] Sleep %ds | EQ: %s | OPT: %s | PDT: %d",
                        POLL_INTERVAL,
                        eq_open or "none",
                        opt_open or "none",
                        self.pdt.today_count())
            time.sleep(POLL_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not LIVE_TRADING:
        logger.info("PAPER MODE — set LIVE_TRADING=true in .env for real orders")
    if OPTIONS_ENABLED:
        logger.info("OPTIONS ENABLED — calls/puts at conviction ≥ %d, max $%.0f/trade",
                    OPTIONS_MIN_CONVICTION, MAX_OPTIONS_DOLLARS)

    rh = RobinhoodClient()
    if not rh.login():
        logger.error("Robinhood login failed — exiting")
        raise SystemExit(1)

    SMLExecutor(rh=rh, evaluator=SignalEvaluator()).run_forever()
