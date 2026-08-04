"""Broker adapter interface for Variant A (signal → user broker execution).

IMPORTANT: Swarm MM does NOT place pooled orders. Each adapter builds an
order payload the USER (or their local agent) submits to their own brokerage
API under their own account. No capital custody. No PFOF.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from swarm_mm.core.config import DISCLAIMER, Side
from swarm_mm.core.engine import compute_levels
from swarm_mm.core.models import LevelRequest, PriceLevel


class BrokerAdapter(ABC):
    name: str

    @abstractmethod
    def format_limit_order(
        self,
        ticker: str,
        side: Side,
        price: float,
        qty: float,
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        """Return broker-native order body (NOT submitted by swarm)."""

    def signal_to_orders(
        self,
        ticker: str,
        side: Side = Side.BOTH,
        confidence_threshold: float = 0.75,
        max_levels: int = 3,
    ) -> dict[str, Any]:
        res = compute_levels(
            LevelRequest(ticker=ticker, side=side, confidence_threshold=confidence_threshold),
            paper=False,
        )
        orders: list[dict[str, Any]] = []
        for lv in res.levels[: max_levels * (2 if side == Side.BOTH else 1)]:
            if lv.confidence < confidence_threshold:
                continue
            orders.append(self.format_limit_order(ticker, lv.side, lv.price, lv.size))
        return {
            "broker": self.name,
            "ticker": ticker.upper(),
            "execution": "user_broker_only",
            "submit": False,
            "orders": orders,
            "levels_source": {
                "mid": res.mid,
                "spread_bps": res.spread_bps,
                "swarm_participants": res.swarm_participants,
            },
            "instructions": (
                f"Review and submit these limit orders via your {self.name} account API/UI. "
                "Swarm MM never transmits orders to a broker on your behalf in Variant A."
            ),
            "disclaimer": DISCLAIMER,
        }


class AlpacaAdapter(BrokerAdapter):
    name = "alpaca"

    def format_limit_order(
        self,
        ticker: str,
        side: Side,
        price: float,
        qty: float,
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        return {
            "symbol": ticker.upper(),
            "qty": str(int(max(1, qty))),
            "side": "buy" if side == Side.BUY else "sell",
            "type": "limit",
            "time_in_force": time_in_force,
            "limit_price": f"{price:.2f}",
            "extended_hours": False,
            "endpoint": "POST https://api.alpaca.markets/v2/orders",
            "auth": "APCA-API-KEY-ID + APCA-API-SECRET-KEY (user credentials)",
        }


class TradierAdapter(BrokerAdapter):
    name = "tradier"

    def format_limit_order(
        self,
        ticker: str,
        side: Side,
        price: float,
        qty: float,
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        return {
            "class": "equity",
            "symbol": ticker.upper(),
            "side": "buy" if side == Side.BUY else "sell",
            "quantity": int(max(1, qty)),
            "type": "limit",
            "duration": "day" if time_in_force == "day" else time_in_force,
            "price": round(price, 2),
            "endpoint": "POST https://api.tradier.com/v1/accounts/{account_id}/orders",
            "auth": "Authorization: Bearer <USER_TRADIER_TOKEN>",
        }


class IBKRAdapter(BrokerAdapter):
    name = "ibkr"

    def format_limit_order(
        self,
        ticker: str,
        side: Side,
        price: float,
        qty: float,
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        return {
            "conid": None,  # user resolves via IBKR contract search
            "symbol": ticker.upper(),
            "secType": "STK",
            "orderType": "LMT",
            "side": "BUY" if side == Side.BUY else "SELL",
            "quantity": int(max(1, qty)),
            "price": round(price, 2),
            "tif": "DAY" if time_in_force == "day" else time_in_force.upper(),
            "endpoint": "IBKR Client Portal / TWS API placeOrder (user session)",
            "auth": "User IBKR session — never SML credentials",
        }


ADAPTERS: dict[str, BrokerAdapter] = {
    "alpaca": AlpacaAdapter(),
    "tradier": TradierAdapter(),
    "ibkr": IBKRAdapter(),
    "interactive_brokers": IBKRAdapter(),
}


def get_adapter(broker: str) -> BrokerAdapter:
    key = (broker or "alpaca").strip().lower()
    if key not in ADAPTERS:
        raise ValueError(f"unsupported broker '{broker}'. choose: {sorted(set(ADAPTERS))}")
    return ADAPTERS[key]


def list_brokers() -> list[dict[str, str]]:
    return [
        {"id": "alpaca", "name": "Alpaca", "execution": "user_api"},
        {"id": "tradier", "name": "Tradier", "execution": "user_api"},
        {"id": "ibkr", "name": "Interactive Brokers", "execution": "user_session"},
    ]


def preview_orders(
    broker: str,
    ticker: str,
    side: str = "both",
    confidence_threshold: float = 0.75,
    max_levels: int = 3,
) -> dict[str, Any]:
    adapter = get_adapter(broker)
    side_e = Side(side) if not isinstance(side, Side) else side
    return adapter.signal_to_orders(ticker, side=side_e, confidence_threshold=confidence_threshold, max_levels=max_levels)
