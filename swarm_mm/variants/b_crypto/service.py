"""Variant B — Crypto-Only Swarm (DEX-native, US geofenced).

Non-custodial vault pattern. This module is the coordination + accounting
scaffold. On-chain vault contracts are separate deliverables (Rust/Solidity).
US persons blocked: non_us_attestation required on every capital path.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from swarm_mm.core.config import (
    CRYPTO_DEX_WEIGHTS_DEFAULT,
    DISCLAIMER,
    PRICE_CRYPTO_REBATE_SHARE,
    Side,
    Variant,
)
from swarm_mm.core.engine import compute_levels, crypto_dex_weights
from swarm_mm.core.models import CryptoDepositRequest, LevelRequest
from swarm_mm.core.state import store

BLOCKED_MSG = (
    "US persons are blocked at the product/contract layer. "
    "Provide non_us_attestation=true only if you are not a US person. "
    "This is software coordination for non-US crypto spot/perps maker flow."
)


def _vault_key(vault_id: str) -> str:
    return f"crypto:vault:{vault_id}"


def _user_pos_key(user_id: str) -> str:
    return f"crypto:pos:{user_id}"


def deposit(req: CryptoDepositRequest, user_id: str = "anonymous") -> dict[str, Any]:
    if not req.non_us_attestation:
        raise PermissionError(BLOCKED_MSG)

    vault = store.get(_vault_key(req.vault_id)) or {
        "vault_id": req.vault_id,
        "balances": {},
        "chain_balances": {},
        "depositors": {},
        "created_at": time.time(),
        "geofence": "block_us",
        "custodial": False,
        "status": "scaffold",  # on-chain vault not deployed in this MVP
    }
    asset = req.asset.upper()
    chain = req.chain
    vault["balances"][asset] = float(vault["balances"].get(asset, 0.0)) + float(req.amount)
    cb_key = f"{chain}:{asset}"
    vault["chain_balances"][cb_key] = float(vault["chain_balances"].get(cb_key, 0.0)) + float(req.amount)
    dep = vault["depositors"].get(user_id, {})
    dep[asset] = float(dep.get(asset, 0.0)) + float(req.amount)
    vault["depositors"][user_id] = dep
    vault["updated_at"] = time.time()
    store.set(_vault_key(req.vault_id), vault)

    # user position mirror
    up = store.get(_user_pos_key(user_id)) or {"user_id": user_id, "vaults": {}, "rebates_usd": 0.0}
    uv = up["vaults"].get(req.vault_id, {"balances": {}, "open_orders": []})
    uv["balances"][asset] = float(uv["balances"].get(asset, 0.0)) + float(req.amount)
    up["vaults"][req.vault_id] = uv
    store.set(_user_pos_key(user_id), up)

    return {
        "status": "accepted_offchain_scaffold",
        "vault_id": req.vault_id,
        "asset": asset,
        "amount": req.amount,
        "chain": chain,
        "custodial": False,
        "on_chain_deployed": False,
        "note": (
            "MVP records deposit intent + internal balances. "
            "Production requires audited non-custodial vault contracts on Base/Solana."
        ),
        "fee_share": PRICE_CRYPTO_REBATE_SHARE,
        "disclaimer": DISCLAIMER + " " + BLOCKED_MSG,
    }


def withdraw(vault_id: str, asset: str, amount: float, user_id: str, non_us_attestation: bool) -> dict[str, Any]:
    if not non_us_attestation:
        raise PermissionError(BLOCKED_MSG)
    asset = asset.upper()
    vault = store.get(_vault_key(vault_id))
    if not vault:
        raise ValueError("unknown vault_id")
    up = store.get(_user_pos_key(user_id)) or {"vaults": {}}
    uv = up.get("vaults", {}).get(vault_id, {"balances": {}})
    have = float(uv.get("balances", {}).get(asset, 0.0))
    if amount > have:
        raise ValueError("insufficient vault balance for user")
    uv["balances"][asset] = have - amount
    up["vaults"][vault_id] = uv
    store.set(_user_pos_key(user_id), up)
    vault["balances"][asset] = float(vault["balances"].get(asset, 0.0)) - amount
    if user_id in vault.get("depositors", {}):
        vault["depositors"][user_id][asset] = float(vault["depositors"][user_id].get(asset, 0.0)) - amount
    store.set(_vault_key(vault_id), vault)
    return {
        "status": "withdraw_queued_scaffold",
        "vault_id": vault_id,
        "asset": asset,
        "amount": amount,
        "custodial": False,
        "disclaimer": DISCLAIMER,
    }


def positions(user_id: str) -> dict[str, Any]:
    up = store.get(_user_pos_key(user_id)) or {"user_id": user_id, "vaults": {}, "rebates_usd": 0.0}
    # Attach illustrative open maker orders from engine on major pairs
    open_orders = []
    for pair in ("BTC", "ETH", "SOL"):
        lr = compute_levels(
            LevelRequest(ticker=pair, side=Side.BOTH, confidence_threshold=0.7, depth=2),
            variant=Variant.B_CRYPTO,
            paper=True,
        )
        for lv in lr.levels[:2]:
            open_orders.append(
                {
                    "pair": pair,
                    "side": lv.side.value,
                    "price": lv.price,
                    "size": lv.size,
                    "venue": "hyperliquid",
                    "status": "simulated_maker",
                    "expected_rebate_bps": lv.expected_rebate_bps,
                }
            )
    up = dict(up)
    up["open_maker_orders"] = open_orders
    up["dex_weights"] = crypto_dex_weights()
    up["pnl"] = {"realized": 0.0, "unrealized": 0.0, "rebates": up.get("rebates_usd", 0.0)}
    up["disclaimer"] = DISCLAIMER + " Crypto positions scaffold — not live DEX orders until vault deploy."
    return up


def rebalance(vault_id: str, target_dex_weights: dict[str, float], non_us_attestation: bool) -> dict[str, Any]:
    if not non_us_attestation:
        raise PermissionError(BLOCKED_MSG)
    vault = store.get(_vault_key(vault_id))
    if not vault:
        raise ValueError("unknown vault_id")
    # normalize
    s = sum(max(0.0, float(v)) for v in target_dex_weights.values()) or 1.0
    norm = {k: round(max(0.0, float(v)) / s, 4) for k, v in target_dex_weights.items()}
    # fill missing defaults
    for k, v in CRYPTO_DEX_WEIGHTS_DEFAULT.items():
        norm.setdefault(k, 0.0)
    vault["dex_weights"] = norm
    vault["rebalanced_at"] = time.time()
    store.set(_vault_key(vault_id), vault)
    return {
        "vault_id": vault_id,
        "target_dex_weights": norm,
        "status": "rebalance_queued_scaffold",
        "plan_id": str(uuid.uuid4()),
        "disclaimer": DISCLAIMER,
    }


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "crypto_swarm.deposit",
            "description": "Deposit into non-custodial crypto MM vault (US geofenced).",
            "price_usd": 0.0,
            "input": {
                "vault_id": "string",
                "asset": "string",
                "amount": "number",
                "chain": "solana|base",
                "non_us_attestation": "bool required",
            },
        },
        {
            "name": "crypto_swarm.positions",
            "description": "Open maker orders, P&L, rebates for user.",
            "price_usd": 0.001,
            "input": {"user_id": "string"},
        },
        {
            "name": "crypto_swarm.withdraw",
            "description": "Withdraw from vault (non-custodial).",
            "price_usd": 0.0,
            "input": {"vault_id": "string", "asset": "string", "amount": "number", "non_us_attestation": "bool"},
        },
        {
            "name": "crypto_swarm.rebalance",
            "description": "Set target DEX weights for vault maker inventory.",
            "price_usd": 0.01,
            "input": {"vault_id": "string", "target_dex_weights": "object", "non_us_attestation": "bool"},
        },
    ]
