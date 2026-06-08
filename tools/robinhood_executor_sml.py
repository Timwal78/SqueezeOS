#!/usr/bin/env python3
"""
SML Sovereign Harmonic Matrix v7.0 — Robinhood Auto-Executor

Polls SqueezeOS for SML BASE-4 grid matrix signals + council bias,
then executes paper or live fractional trades via robin_stocks.

Run via PM2:
  pm2 start robinhood_executor_sml.py --name robinhood-executor --interpreter python

Required env vars (or .env file in the same directory):
  SQUEEZEOS_URL            SqueezeOS API base (default: https://squeezeos-api.onrender.com)
  WATCHLIST                Comma-separated symbols (default: GME,AMC,MSTR,NVDA,SPY,QQQ,TSLA,PLTR)
  MAX_POSITION_DOLLARS     Max dollars per position (default: 500)
  SML_MIN_CONVICTION       Min combined conviction score to enter (default: 70, range 0-100)
  POLL_INTERVAL_SECONDS    Seconds between signal polls (default: 60)
  LIVE_TRADING             "true" to place real orders (default: paper mode)
  DISCORD_WEBHOOK_ROBINHOOD  Your dedicated Robinhood trade notification webhook
  DISCORD_WEBHOOK_ALL      Fallback webhook if ROBINHOOD-specific one isn't set
  RH_USERNAME              Robinhood email (only needed if pickle is expired)
  RH_PASSWORD              Robinhood password (only needed if pickle is expired)
  RH_PICKLE_PATH           Path to robinhood.pickle (default: ~/.tokens/robinhood.pickle)

Signal → position size table:
  FULL_SPECTRUM       (conviction 100) → 100% of MAX_POSITION_DOLLARS
  PRIME_INSTITUTIONAL (conviction 90)  → 80%
  APEX_SINGULARITY    (conviction 80)  → 60%
  PRIME_SIGNAL        (conviction 75)  → 35%
  CRITICAL_MASS       (conviction 55)  → 15%
  below SML_MIN_CONVICTION              → no entry

SqueezeOS bias modifiers applied on top:
  BUY (IGNITION) → conviction × 1.25 (capped at 100)
  BUY            → conviction × 1.10
  HOLD           → conviction × 1.00 (no change)
  SELL           → conviction × 0.50
  SHIELD         → blocks all long entries regardless of SML conviction

PDT guard: tracks same-day round-trips. Warns when approaching 3/5-day limit.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, date
from typing import Optional

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap env from .env if present
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
# Config (all from env)
# ─────────────────────────────────────────────────────────────────────────────
SQUEEZEOS_URL          = os.getenv("SQUEEZEOS_URL", "https://squeezeos-api.onrender.com").rstrip("/")
WATCHLIST              = [s.strip().upper() for s in os.getenv("WATCHLIST", "GME,AMC,MSTR,NVDA,SPY,QQQ,TSLA,PLTR").split(",") if s.strip()]
MAX_POSITION_DOLLARS   = float(os.getenv("MAX_POSITION_DOLLARS", "500"))
SML_MIN_CONVICTION     = int(os.getenv("SML_MIN_CONVICTION", "70"))
POLL_INTERVAL          = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
LIVE_TRADING           = os.getenv("LIVE_TRADING", "false").lower() == "true"
DISCORD_WEBHOOK        = (
    os.getenv("DISCORD_WEBHOOK_ROBINHOOD") or
    os.getenv("DISCORD_WEBHOOK_ALL") or
    ""
)
RH_USERNAME            = os.getenv("RH_USERNAME", "")
RH_PASSWORD            = os.getenv("RH_PASSWORD", "")
RH_PICKLE_PATH         = os.getenv("RH_PICKLE_PATH", os.path.expanduser("~/.tokens/robinhood.pickle"))

# Conviction → fraction of MAX_POSITION_DOLLARS (evaluated at first match ≥ threshold)
_SIZE_CURVE: list[tuple[int, float]] = [
    (100, 1.00),   # FULL_SPECTRUM
    (90,  0.80),   # PRIME_INSTITUTIONAL
    (80,  0.60),   # APEX_SINGULARITY
    (75,  0.35),   # PRIME_SIGNAL
    (55,  0.15),   # CRITICAL_MASS
    (0,   0.00),   # below threshold
]

# SqueezeOS council bias → conviction multiplier
_BIAS_MULT: dict[str, float] = {
    "BUY (IGNITION)": 1.25,
    "BUY":            1.10,
    "HOLD":           1.00,
    "SELL":           0.50,
    "SHIELD":         0.00,   # blocks all long entries
}


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


# ─────────────────────────────────────────────────────────────────────────────
# Robinhood client wrapper
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
            logger.warning("[RH] buying_power error — %s", exc)
            return 0.0

    def price(self, symbol: str) -> Optional[float]:
        if not self._rh:
            return None
        try:
            prices = self._rh.stocks.get_latest_price(symbol)
            return float(prices[0]) if prices else None
        except Exception as exc:
            logger.warning("[RH] price(%s) error — %s", symbol, exc)
            return None

    def buy(self, symbol: str, dollars: float) -> Optional[dict]:
        if not LIVE_TRADING:
            logger.info("[PAPER] BUY %s $%.2f", symbol, dollars)
            return {"paper": True, "symbol": symbol, "dollars": dollars}
        try:
            result = self._rh.orders.order_buy_fractional_by_price(symbol, dollars)
            logger.info("[LIVE] BUY %s $%.2f → order_id=%s", symbol, dollars, result.get("id", "?"))
            return result
        except Exception as exc:
            logger.error("[RH] buy(%s) failed — %s", symbol, exc)
            return None

    def sell(self, symbol: str, shares: float) -> Optional[dict]:
        if not LIVE_TRADING:
            logger.info("[PAPER] SELL %s %.6f shares", symbol, shares)
            return {"paper": True, "symbol": symbol, "shares": shares}
        try:
            result = self._rh.orders.order_sell_fractional_by_price(
                symbol, shares, priceType="ask_price", timeInForce="gfd"
            )
            logger.info("[LIVE] SELL %s %.6f → order_id=%s", symbol, shares, result.get("id", "?"))
            return result
        except Exception as exc:
            logger.error("[RH] sell(%s) failed — %s", symbol, exc)
            return None

    def open_shares(self, symbol: str) -> float:
        """Return current share count for symbol from live RH account."""
        if not self._rh or not LIVE_TRADING:
            return 0.0
        try:
            positions = self._rh.account.get_open_stock_positions()
            for p in (positions or []):
                instrument = p.get("instrument", "")
                if symbol.upper() in instrument.upper():
                    return float(p.get("quantity", 0))
        except Exception as exc:
            logger.warning("[RH] open_shares(%s) error — %s", symbol, exc)
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Signal evaluator — combines SML matrix signal + SqueezeOS council bias
# ─────────────────────────────────────────────────────────────────────────────
class SignalEvaluator:
    def evaluate(self, symbol: str) -> dict:
        # 1. SML BASE-4 Harmonic Matrix signal from SqueezeOS signal store
        sml = _fetch(f"{SQUEEZEOS_URL}/api/sml/signal/{symbol}") or {}
        sml_active      = sml.get("active", False)
        sml_conviction  = int(sml.get("conviction", 0))
        sml_signal_type = sml.get("signal_type", "NONE")
        sml_action      = sml.get("action", "WATCH")

        # 2. SqueezeOS council bias (free 15-min cache)
        sqz = _fetch(f"{SQUEEZEOS_URL}/api/preview/{symbol}") or {}
        sqz_bias = sqz.get("bias", "HOLD")

        # 3. Combine
        bias_mult         = _BIAS_MULT.get(sqz_bias, 1.0)
        combined          = min(100, int(sml_conviction * bias_mult))
        position_frac     = _size_for_conviction(combined)
        dollars_to_deploy = round(MAX_POSITION_DOLLARS * position_frac, 2)

        # 4. Final action
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
            "ts":                  time.time(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Discord notifications
# ─────────────────────────────────────────────────────────────────────────────
def _discord(msg: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=5)
    except Exception:
        pass


def _fmt_trade_msg(ev: dict, pnl: Optional[float] = None) -> str:
    mode   = "📄 PAPER" if not LIVE_TRADING else "💰 LIVE"
    sym    = ev["symbol"]
    action = ev["final_action"]
    sig    = ev["sml_signal_type"]
    conv   = ev["combined_conviction"]
    bias   = ev["sqz_bias"]
    ts     = datetime.utcnow().strftime("%H:%M:%S UTC")

    if action == "BUY":
        return (
            f"**{mode} BUY** | `{sym}` | **${ev['dollars_to_deploy']:.2f}**\n"
            f"SML: `{sig}` · Combined conviction: `{conv}/100`\n"
            f"SqueezeOS bias: `{bias}` · Size: `{ev['position_frac']*100:.0f}%` of max\n"
            f"_{ts}_"
        )
    elif action == "EXIT":
        pnl_str = f" | PnL: `${pnl:+.2f}`" if pnl is not None else ""
        return (
            f"**{mode} EXIT** | `{sym}` | `CONVERGENCE_RELEASED`{pnl_str}\n"
            f"_{ts}_"
        )
    return f"**HOLD** `{sym}` — conviction {conv}/100 below threshold | _{ts}_"


# ─────────────────────────────────────────────────────────────────────────────
# PDT (Pattern Day Trade) guard
# ─────────────────────────────────────────────────────────────────────────────
class PDTGuard:
    """
    Tracks same-day round-trip trades. Warns when close to the 3-trade limit
    for accounts under $25k. Does NOT block trades — only warns via Discord.
    """
    def __init__(self):
        self._day_trades: list[dict] = []  # {symbol, opened_date, closed_date}

    def record_roundtrip(self, symbol: str):
        today = date.today().isoformat()
        self._day_trades.append({"symbol": symbol, "date": today})
        rolling = sum(1 for t in self._day_trades if t["date"] == today)
        if rolling >= 3:
            msg = (
                f"⚠️ **PDT WARNING** — {rolling} same-day round-trips today (`{today}`).\n"
                f"Accounts under $25k are limited to 3 day trades per rolling 5-day window.\n"
                f"Most recent: `{symbol}`"
            )
            logger.warning(msg)
            _discord(msg)

    def today_count(self) -> int:
        today = date.today().isoformat()
        return sum(1 for t in self._day_trades if t["date"] == today)


# ─────────────────────────────────────────────────────────────────────────────
# Main executor
# ─────────────────────────────────────────────────────────────────────────────
class SMLExecutor:
    def __init__(self, rh: RobinhoodClient, evaluator: SignalEvaluator):
        self.rh        = rh
        self.evaluator = evaluator
        self.pdt       = PDTGuard()
        # In-memory position tracker (paper mode only; live mode reads from RH)
        self._positions: dict[str, dict] = {}

    def _current_shares(self, symbol: str) -> float:
        if LIVE_TRADING:
            return self.rh.open_shares(symbol)
        return self._positions.get(symbol, {}).get("shares", 0.0)

    def _run_symbol(self, symbol: str):
        ev = self.evaluator.evaluate(symbol)
        action = ev["final_action"]

        if action == "BUY" and self._current_shares(symbol) == 0.0:
            dollars = ev["dollars_to_deploy"]
            if dollars <= 0:
                return

            # Buying power check (live only)
            if LIVE_TRADING:
                bp = self.rh.buying_power()
                if bp < dollars:
                    logger.warning("[%s] Buying power $%.2f < needed $%.2f — skip", symbol, bp, dollars)
                    _discord(f"⚠️ `{symbol}` — low buying power (${bp:.2f}), skipped ${dollars:.2f} entry")
                    return

            order = self.rh.buy(symbol, dollars)
            if order is None:
                return

            price  = self.rh.price(symbol) or 0.0
            shares = (dollars / price) if price > 0 else 0.0
            self._positions[symbol] = {
                "shares":         shares,
                "entry_price":    price,
                "entry_dollars":  dollars,
                "entry_ts":       time.time(),
                "entry_signal":   ev["sml_signal_type"],
                "entry_date":     date.today().isoformat(),
            }
            logger.info("[%s] ENTERED $%.2f @ $%.4f (%.6f shares) | signal=%s",
                        symbol, dollars, price, shares, ev["sml_signal_type"])
            _discord(_fmt_trade_msg(ev))

        elif action == "EXIT" and self._current_shares(symbol) > 0.0:
            pos    = self._positions.get(symbol, {})
            shares = pos.get("shares", self._current_shares(symbol))
            order  = self.rh.sell(symbol, shares)
            if order is None:
                return

            current_price = self.rh.price(symbol) or 0.0
            pnl = (current_price - pos.get("entry_price", current_price)) * shares

            # PDT tracking — only record if same-day as entry
            entry_date = pos.get("entry_date", "")
            if entry_date == date.today().isoformat():
                self.pdt.record_roundtrip(symbol)

            logger.info("[%s] EXITED %.6f shares | PnL $%.2f", symbol, shares, pnl)
            _discord(_fmt_trade_msg(ev, pnl=pnl))

            if symbol in self._positions:
                del self._positions[symbol]

        else:
            logger.debug("[%s] HOLD | conv=%d | bias=%s | active=%s",
                         symbol, ev["combined_conviction"], ev["sqz_bias"], ev["sml_active"])

    def run_forever(self):
        mode = "PAPER" if not LIVE_TRADING else "LIVE 💰"
        banner = (
            f"**SML Robinhood Executor started** | Mode: `{mode}`\n"
            f"Watching: `{', '.join(WATCHLIST)}`\n"
            f"Max position: `${MAX_POSITION_DOLLARS:.0f}` | Min conviction: `{SML_MIN_CONVICTION}/100`\n"
            f"Poll interval: `{POLL_INTERVAL}s`"
        )
        logger.info("═" * 55)
        logger.info("  SML Sovereign Harmonic Matrix — Robinhood Executor")
        logger.info("  Mode: %s | Symbols: %s", mode, ", ".join(WATCHLIST))
        logger.info("  Max $%.0f | Min conviction: %d | Poll: %ds",
                    MAX_POSITION_DOLLARS, SML_MIN_CONVICTION, POLL_INTERVAL)
        logger.info("═" * 55)
        _discord(banner)

        while True:
            for sym in WATCHLIST:
                try:
                    self._run_symbol(sym)
                except Exception as exc:
                    logger.error("[%s] Unhandled error: %s", sym, exc)

            open_syms = list(self._positions.keys()) if self._positions else []
            logger.info("[Cycle] Done — sleeping %ds | Positions: %s | PDT today: %d",
                        POLL_INTERVAL,
                        open_syms if open_syms else "none",
                        self.pdt.today_count())
            time.sleep(POLL_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not LIVE_TRADING:
        logger.info("PAPER MODE — set LIVE_TRADING=true to execute real orders")

    rh = RobinhoodClient()
    if not rh.login():
        logger.error("Robinhood login failed — exiting")
        raise SystemExit(1)

    SMLExecutor(rh=rh, evaluator=SignalEvaluator()).run_forever()
