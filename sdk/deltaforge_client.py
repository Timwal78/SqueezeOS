"""
ScriptMaster DeltaForge™ — BYOK execution client.

    "Trade the Delta. Catch the Explosion."

This client runs on YOUR machine with YOUR broker keys. The DeltaForge API
only ever sees your DeltaForge key — it returns signals and order payloads;
every order is built, sized, and submitted locally. Nothing custodial exists
anywhere in this system.

Quickstart (paper mode is the default — nothing is submitted until you
explicitly arm live mode):

    from deltaforge_client import DeltaForgeClient, TradierBroker, RiskEngine

    client = DeltaForgeClient(df_key="df_... or your founder key")
    broker = TradierBroker(token="YOUR-tradier-token",
                           account_id="YOUR-account-id", sandbox=True)
    risk = RiskEngine(max_risk_pct=1.5, daily_loss_limit_pct=4.0,
                      max_open_positions=3, max_consecutive_losses=3)

    result = client.run_once("NVDA", broker=broker, risk=risk)
    print(result)

Live arming requires BOTH paper=False on run_once AND the environment var
DELTAFORGE_ARM_LIVE=true. The kill switch DELTAFORGE_KILL_SWITCH=true halts
everything instantly regardless of any other setting.

Robinhood support is optional and requires `pip install robin_stocks`; you
log in yourself (robin_stocks.robinhood.login(...)) before passing
RobinhoodBroker — this file never touches your credentials.

Dependencies: requests (Tradier + API). Optional: robin_stocks.
"""

from __future__ import annotations

import os
import json
import time
import math
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable

import requests

logger = logging.getLogger("deltaforge.client")

DEFAULT_API_BASE = "https://squeezeos-api.onrender.com"


# ═══════════════════════════════════════════════════════════════════════════
# Risk engine — Thaler mental accounting, enforced in code
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RiskEngine:
    """Hard limits. Every check must pass before a single contract is bought.

    max_risk_pct           — % of account equity risked per trade (the full
                             premium of a long option is the risk).
    daily_loss_limit_pct   — realized daily loss that halts trading for the day.
    max_open_positions     — cap on simultaneous DeltaForge positions.
    max_consecutive_losses — circuit breaker: N losses in a row = done today.
    cooldown_seconds       — minimum spacing between entries on one symbol.
    """
    max_risk_pct: float = 1.5
    daily_loss_limit_pct: float = 4.0
    max_open_positions: int = 3
    max_consecutive_losses: int = 3
    cooldown_seconds: int = 900

    _daily_pnl: float = field(default=0.0, init=False)
    _daily_date: str = field(default="", init=False)
    _consecutive_losses: int = field(default=0, init=False)
    _open_positions: dict = field(default_factory=dict, init=False)
    _last_entry: dict = field(default_factory=dict, init=False)

    def _roll_day(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._daily_date:
            self._daily_date = today
            self._daily_pnl = 0.0
            self._consecutive_losses = 0

    def pre_trade_check(self, symbol: str, equity: float) -> tuple[bool, str]:
        self._roll_day()
        if os.environ.get("DELTAFORGE_KILL_SWITCH", "").lower() == "true":
            return False, "KILL SWITCH is on (DELTAFORGE_KILL_SWITCH=true)"
        if equity <= 0:
            return False, "account equity unknown or zero"
        if self._daily_pnl <= -(equity * self.daily_loss_limit_pct / 100.0):
            return False, (f"daily loss limit hit ({self.daily_loss_limit_pct}% "
                           f"of equity) — done for the day")
        if self._consecutive_losses >= self.max_consecutive_losses:
            return False, (f"circuit breaker: {self._consecutive_losses} "
                           f"consecutive losses — done for the day")
        if len(self._open_positions) >= self.max_open_positions:
            return False, f"max open positions ({self.max_open_positions}) reached"
        last = self._last_entry.get(symbol, 0)
        if time.time() - last < self.cooldown_seconds:
            return False, f"cooldown: {symbol} entered {int(time.time() - last)}s ago"
        return True, "ok"

    def size_contracts(self, equity: float, limit_price: float) -> int:
        """Prospect-theory sizing: the premium IS the max loss. Never risk
        more than max_risk_pct of equity on one explosion attempt."""
        if limit_price <= 0:
            return 0
        risk_dollars = equity * self.max_risk_pct / 100.0
        return max(0, math.floor(risk_dollars / (limit_price * 100.0)))

    def record_entry(self, symbol: str, contract: str, qty: int, price: float):
        self._open_positions[contract] = {"symbol": symbol, "qty": qty,
                                          "entry": price, "ts": time.time()}
        self._last_entry[symbol] = time.time()

    def record_exit(self, contract: str, pnl_dollars: float):
        self._roll_day()
        self._open_positions.pop(contract, None)
        self._daily_pnl += pnl_dollars
        self._consecutive_losses = self._consecutive_losses + 1 if pnl_dollars < 0 else 0

    def status(self) -> dict:
        self._roll_day()
        return {"daily_pnl": round(self._daily_pnl, 2),
                "consecutive_losses": self._consecutive_losses,
                "open_positions": len(self._open_positions),
                "kill_switch": os.environ.get("DELTAFORGE_KILL_SWITCH", "").lower() == "true"}


# ═══════════════════════════════════════════════════════════════════════════
# Brokers — YOUR keys, YOUR machine
# ═══════════════════════════════════════════════════════════════════════════

class TradierBroker:
    """Direct Tradier REST with the customer's own token. Sandbox by default."""

    def __init__(self, token: str, account_id: str, sandbox: bool = True):
        self.token = token
        self.account_id = account_id
        self.base = ("https://sandbox.tradier.com/v1" if sandbox
                     else "https://api.tradier.com/v1")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/json"}

    def equity(self) -> float:
        r = requests.get(f"{self.base}/accounts/{self.account_id}/balances",
                         headers=self._headers(), timeout=15)
        r.raise_for_status()
        bal = (r.json().get("balances") or {})
        return float(bal.get("total_equity") or bal.get("account_value") or 0.0)

    def place_option_order(self, params: dict) -> dict:
        """params = the `tradier.params` payload from the API, with quantity
        filled in by the risk engine."""
        if not params.get("quantity"):
            raise ValueError("quantity not set — size via RiskEngine first")
        r = requests.post(f"{self.base}/accounts/{self.account_id}/orders",
                          headers=self._headers(), data=params, timeout=20)
        r.raise_for_status()
        return r.json()


class RobinhoodBroker:
    """Thin wrapper over robin_stocks. You call robin_stocks.robinhood.login()
    yourself before using this — credentials never pass through DeltaForge."""

    def __init__(self):
        try:
            import robin_stocks.robinhood as rh  # noqa: F401
            self._rh = rh
        except ImportError as e:
            raise ImportError("pip install robin_stocks to use RobinhoodBroker") from e

    def equity(self) -> float:
        profile = self._rh.profiles.load_portfolio_profile() or {}
        return float(profile.get("equity") or 0.0)

    def place_option_order(self, kwargs: dict) -> dict:
        """kwargs = the `robinhood.kwargs` payload from the API, with quantity
        filled in by the risk engine."""
        if not kwargs.get("quantity"):
            raise ValueError("quantity not set — size via RiskEngine first")
        return self._rh.orders.order_buy_option_limit(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════════════

class DeltaForgeClient:
    def __init__(self, df_key: str = "", api_base: str = DEFAULT_API_BASE):
        self.api_base = api_base.rstrip("/")
        self.df_key = df_key

    def get_signal(self, symbol: str, aggression: float = 0.85) -> dict:
        headers = {"X-DeltaForge-Key": self.df_key} if self.df_key else {}
        r = requests.get(f"{self.api_base}/api/deltaforge/signal/{symbol}",
                         params={"aggression": aggression}, headers=headers,
                         timeout=45)
        r.raise_for_status()
        return r.json()

    def run_once(self, symbol: str, broker=None, risk: Optional[RiskEngine] = None,
                 paper: bool = True, aggression: float = 0.85,
                 confirm: Optional[Callable[[dict], bool]] = None) -> dict:
        """Fetch signal → risk gates → size → (paper log | live submit).

        Live submission requires paper=False AND DELTAFORGE_ARM_LIVE=true in
        the environment. `confirm`, if given, is called with the final order
        and must return True — wire it to a prompt for human-in-the-loop.
        """
        sig = self.get_signal(symbol, aggression)
        result = {"symbol": symbol, "direction": sig.get("direction"),
                  "tier": sig.get("tier"), "action": "none"}

        if sig.get("direction") not in ("LONG", "SHORT"):
            result["reason"] = "no explosive setup"
            return result
        payloads = sig.get("order_payloads")
        if not payloads:
            result["reason"] = ("no order payloads — elite tier required "
                                f"(current tier: {sig.get('tier')})")
            return result
        if broker is None or risk is None:
            result["reason"] = "signal only — no broker/risk engine supplied"
            result["contract"] = sig.get("contract")
            return result

        equity = broker.equity()
        ok, why = risk.pre_trade_check(symbol, equity)
        if not ok:
            result["reason"] = f"risk engine blocked: {why}"
            return result

        contract = sig["contract"]
        qty = risk.size_contracts(equity, contract["ask"])
        if qty < 1:
            result["reason"] = (f"sized to 0 contracts — premium {contract['ask']} "
                                f"too large for {risk.max_risk_pct}% of ${equity:,.0f}")
            return result

        if isinstance(broker, TradierBroker):
            order = dict(payloads["tradier"]["params"], quantity=qty)
        else:
            order = dict(payloads["robinhood"]["kwargs"], quantity=qty)
        result.update({"contract": contract["contract"], "quantity": qty,
                       "limit_price": contract["ask"]})

        if confirm and not confirm(order):
            result.update(action="declined", reason="confirm callback returned False")
            return result

        armed = os.environ.get("DELTAFORGE_ARM_LIVE", "").lower() == "true"
        if paper or not armed:
            result.update(action="paper",
                          reason=("paper mode" if paper else
                                  "live not armed (set DELTAFORGE_ARM_LIVE=true)"),
                          order=order)
            logger.info("[PAPER] %s x%d %s", contract["contract"], qty,
                        json.dumps(order, default=str))
            return result

        resp = broker.place_option_order(order)
        risk.record_entry(symbol, contract["contract"], qty, contract["ask"])
        result.update(action="submitted", broker_response=resp)
        logger.info("[LIVE] submitted %s x%d", contract["contract"], qty)
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    c = DeltaForgeClient(df_key=os.environ.get("DELTAFORGE_KEY", ""))
    print(json.dumps(c.get_signal(sym), indent=2))
