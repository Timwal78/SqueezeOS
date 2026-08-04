"""Variant D — Simulated Swarm (zero regulatory risk, launch first).

Paper-trading swarm proving the concept with zero real capital.
Tracks simulated fill rates, rebate earnings, spread capture, leaderboards.
Upgrade path to A/B/C when ready.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from swarm_mm.core.config import (
    DEFAULT_SIM_BALANCE,
    DISCLAIMER,
    MAKER_REBATE_BPS_DEFAULT,
    SIM_BALANCES,
    SPREAD_CAPTURE_BPS_DEFAULT,
    Side,
    Variant,
)
from swarm_mm.core.engine import compute_levels, fetch_quote
from swarm_mm.core.models import (
    LeaderboardEntry,
    LeaderboardResponse,
    LevelRequest,
    SimAccount,
    SimJoinRequest,
    SimTradeRequest,
    UpgradeRequest,
)
from swarm_mm.core.state import store


def _acct_key(user_id: str) -> str:
    return f"sim:acct:{user_id}"


def _orders_key(user_id: str) -> str:
    return f"sim:orders:{user_id}"


def _fills_key(user_id: str) -> str:
    return f"sim:fills:{user_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def join(req: SimJoinRequest) -> SimAccount:
    existing = store.get(_acct_key(req.user_id))
    if existing:
        return SimAccount(**existing)

    bal = float(req.starting_balance or DEFAULT_SIM_BALANCE)
    # Snap to nearest allowed band if far off
    if bal not in SIM_BALANCES:
        bal = min(SIM_BALANCES, key=lambda b: abs(b - bal))

    acct = SimAccount(
        user_id=req.user_id,
        cash=bal,
        starting_balance=bal,
        equity=bal,
        joined_at=_now(),
        variant=Variant.D_SIM,
    )
    store.set(_acct_key(req.user_id), acct.model_dump(mode="json"))
    store.set(_orders_key(req.user_id), [])
    store.set(_fills_key(req.user_id), [])
    # Index for leaderboard
    users = store.get("sim:users", []) or []
    if req.user_id not in users:
        users.append(req.user_id)
        store.set("sim:users", users)
    return acct


def get_account(user_id: str) -> Optional[SimAccount]:
    raw = store.get(_acct_key(user_id))
    return SimAccount(**raw) if raw else None


def _mark_equity(acct: dict, positions: dict[str, dict]) -> dict:
    unreal = 0.0
    for sym, pos in positions.items():
        qty = float(pos.get("qty", 0))
        avg = float(pos.get("avg", 0))
        if qty == 0:
            continue
        q = fetch_quote(sym)
        unreal += (q.mid - avg) * qty
    acct["unrealized_pnl"] = round(unreal, 4)
    acct["equity"] = round(float(acct["cash"]) + unreal + _inventory_cost(positions), 4)
    # inventory already in cash accounting via open cost; equity = cash + mtm of shares
    # Recompute cleanly:
    inv_value = 0.0
    for sym, pos in positions.items():
        qty = float(pos.get("qty", 0))
        if qty:
            inv_value += qty * fetch_quote(sym).mid
    acct["equity"] = round(float(acct["cash"]) + inv_value, 4)
    acct["unrealized_pnl"] = round(inv_value - _inventory_cost(positions), 4)
    return acct


def _inventory_cost(positions: dict[str, dict]) -> float:
    return sum(float(p.get("qty", 0)) * float(p.get("avg", 0)) for p in positions.values())


def _positions(user_id: str) -> dict[str, dict]:
    return store.get(f"sim:pos:{user_id}", {}) or {}


def _save_positions(user_id: str, pos: dict[str, dict]) -> None:
    store.set(f"sim:pos:{user_id}", pos)


def trade(req: SimTradeRequest) -> dict[str, Any]:
    """Place a simulated limit order and attempt immediate maker/taker fill vs synthetic/live mid."""
    acct_raw = store.get(_acct_key(req.user_id))
    if not acct_raw:
        raise ValueError("user not joined — call sim_swarm.join first")

    q = fetch_quote(req.ticker)
    order_id = str(uuid.uuid4())
    notional = req.price * req.size
    status = "resting"
    fill_price = None
    rebate = 0.0
    spread_cap = 0.0

    # Simple paper fill model:
    #  - buy limit >= ask → taker fill at ask (no maker rebate)
    #  - buy limit between bid and ask → partial maker probability by distance
    #  - buy limit <= bid → resting maker; immediate partial fill if within 1 tick of bid
    #  - symmetric for sells
    tick = max(0.01, q.mid * 0.0005)

    if req.side == Side.BUY:
        if req.price >= q.ask:
            status = "filled"
            fill_price = q.ask
            # taker — no rebate; pay half-spread vs mid as cost
            spread_cap = -abs(fill_price - q.mid) * req.size
        elif req.price >= q.bid - tick:
            status = "filled"
            fill_price = req.price
            rebate = notional * (MAKER_REBATE_BPS_DEFAULT / 10_000.0)
            spread_cap = (q.mid - fill_price) * req.size * 0.25  # latent edge
        else:
            status = "resting"
    else:  # SELL
        if req.price <= q.bid:
            status = "filled"
            fill_price = q.bid
            spread_cap = -abs(fill_price - q.mid) * req.size
        elif req.price <= q.ask + tick:
            status = "filled"
            fill_price = req.price
            rebate = notional * (MAKER_REBATE_BPS_DEFAULT / 10_000.0)
            spread_cap = (fill_price - q.mid) * req.size * 0.25
        else:
            status = "resting"

    orders = store.get(_orders_key(req.user_id), []) or []
    order = {
        "order_id": order_id,
        "ticker": req.ticker,
        "side": req.side.value,
        "price": req.price,
        "size": req.size,
        "status": status,
        "ts": _now().isoformat(),
        "quote_mid": q.mid,
        "quote_source": q.source,
    }
    orders.append(order)
    # cap order history
    store.set(_orders_key(req.user_id), orders[-500:])

    pos = _positions(req.user_id)
    cash = float(acct_raw["cash"])
    realized = float(acct_raw.get("realized_pnl", 0.0))
    fills_n = int(acct_raw.get("fills", 0))
    rebate_earned = float(acct_raw.get("maker_rebate_earned", 0.0))

    if status == "filled" and fill_price is not None:
        fills = store.get(_fills_key(req.user_id), []) or []
        fill = {
            "fill_id": str(uuid.uuid4()),
            "order_id": order_id,
            "ticker": req.ticker,
            "side": req.side.value,
            "price": fill_price,
            "size": req.size,
            "rebate": round(rebate, 6),
            "spread_capture": round(spread_cap, 6),
            "ts": _now().isoformat(),
            "paper": True,
        }
        fills.append(fill)
        store.set(_fills_key(req.user_id), fills[-2000:])
        fills_n += 1
        rebate_earned += rebate
        realized += spread_cap

        p = pos.get(req.ticker, {"qty": 0.0, "avg": 0.0})
        qty = float(p["qty"])
        avg = float(p["avg"])
        if req.side == Side.BUY:
            cost = fill_price * req.size
            if cash + rebate < cost:
                raise ValueError("insufficient simulated cash")
            new_qty = qty + req.size
            new_avg = ((avg * qty) + cost) / new_qty if new_qty else 0.0
            p = {"qty": new_qty, "avg": new_avg}
            cash = cash - cost + rebate
        else:
            if qty < req.size:
                # allow short paper inventory
                new_qty = qty - req.size
                # realize vs avg if long; if flat/short, avg resets
                if qty > 0:
                    close_qty = min(qty, req.size)
                    realized += (fill_price - avg) * close_qty
                p = {"qty": new_qty, "avg": avg if new_qty > 0 else (fill_price if new_qty < 0 else 0.0)}
                cash = cash + fill_price * req.size + rebate
            else:
                realized += (fill_price - avg) * req.size
                new_qty = qty - req.size
                p = {"qty": new_qty, "avg": avg if new_qty else 0.0}
                cash = cash + fill_price * req.size + rebate
        pos[req.ticker] = p
        _save_positions(req.user_id, pos)

    open_orders = sum(1 for o in orders if o.get("status") == "resting")
    acct_raw.update(
        {
            "cash": round(cash, 4),
            "realized_pnl": round(realized, 4),
            "fills": fills_n,
            "maker_rebate_earned": round(rebate_earned, 6),
            "open_orders": open_orders,
        }
    )
    acct_raw = _mark_equity(acct_raw, pos)
    store.set(_acct_key(req.user_id), acct_raw)

    return {
        "order": order,
        "fill_price": fill_price,
        "status": status,
        "rebate_usd": round(rebate, 6),
        "account": SimAccount(**acct_raw).model_dump(mode="json"),
        "paper": True,
        "disclaimer": DISCLAIMER,
    }


def leaderboard(timeframe: str = "all_time", limit: int = 25) -> LeaderboardResponse:
    users = store.get("sim:users", []) or []
    rows: list[LeaderboardEntry] = []
    for uid in users:
        raw = store.get(_acct_key(uid))
        if not raw:
            continue
        # refresh marks
        pos = _positions(uid)
        raw = _mark_equity(raw, pos)
        store.set(_acct_key(uid), raw)
        start = float(raw.get("starting_balance") or 1.0)
        eq = float(raw.get("equity") or 0.0)
        ret = ((eq - start) / start) * 100.0 if start else 0.0
        rows.append(
            LeaderboardEntry(
                rank=0,
                user_id=uid,
                equity=round(eq, 2),
                realized_pnl=round(float(raw.get("realized_pnl") or 0.0), 2),
                return_pct=round(ret, 4),
                fills=int(raw.get("fills") or 0),
                maker_rebate_earned=round(float(raw.get("maker_rebate_earned") or 0.0), 6),
            )
        )
    rows.sort(key=lambda r: (r.return_pct, r.equity), reverse=True)
    for i, r in enumerate(rows[:limit], start=1):
        r.rank = i
    return LeaderboardResponse(
        timeframe=timeframe,
        entries=rows[:limit],
        disclaimer=DISCLAIMER,
        paper=True,
    )


def upgrade(req: UpgradeRequest) -> dict[str, Any]:
    raw = store.get(_acct_key(req.user_id))
    if not raw:
        raise ValueError("user not joined")
    if req.target_variant == Variant.D_SIM:
        return {"user_id": req.user_id, "variant": "D", "status": "already_sim"}
    # Record intent; live onboarding is external (broker connect / vault / B2B contract)
    store.set(
        f"sim:upgrade:{req.user_id}",
        {
            "target": req.target_variant.value,
            "requested_at": _now().isoformat(),
            "status": "pending_onboarding",
            "sim_equity": raw.get("equity"),
            "sim_return_pct": (
                (float(raw["equity"]) - float(raw["starting_balance"]))
                / float(raw["starting_balance"])
                * 100.0
                if raw.get("starting_balance")
                else 0.0
            ),
        },
    )
    paths = {
        Variant.A_SIGNAL: {
            "next": "Connect brokerage API (Alpaca/Tradier/IBKR) and subscribe signal_swarm $19/mo",
            "endpoint": "/v1/signal/levels",
        },
        Variant.B_CRYPTO: {
            "next": "Non-US attestation + vault deposit on Base/Solana (legal review required)",
            "endpoint": "/v1/crypto/deposit",
        },
        Variant.C_B2B: {
            "next": "Enterprise contract + customer_id provisioning",
            "endpoint": "/v1/b2b/configure",
        },
    }
    info = paths[req.target_variant]
    return {
        "user_id": req.user_id,
        "from_variant": "D",
        "target_variant": req.target_variant.value,
        "status": "pending_onboarding",
        **info,
        "disclaimer": DISCLAIMER,
    }


def set_premium(user_id: str, premium: bool = True) -> SimAccount:
    raw = store.get(_acct_key(user_id))
    if not raw:
        raise ValueError("user not joined")
    raw["premium"] = premium
    store.set(_acct_key(user_id), raw)
    return SimAccount(**raw)


def swarm_levels_for_user(user_id: str, ticker: str, side: Side = Side.BOTH) -> dict:
    """Premium analytics: levels + account context."""
    acct = get_account(user_id)
    levels = compute_levels(
        LevelRequest(ticker=ticker, side=side, confidence_threshold=0.70),
        variant=Variant.D_SIM,
        paper=True,
    )
    return {
        "account": acct.model_dump(mode="json") if acct else None,
        "levels": levels.model_dump(mode="json"),
        "paper": True,
    }


def stats() -> dict[str, Any]:
    users = store.get("sim:users", []) or []
    return {
        "variant": "D",
        "users": len(users),
        "paper": True,
        "ts": time.time(),
    }
