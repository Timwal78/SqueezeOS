"""MCP tool catalog for swarm-mm (JSON-RPC friendly descriptors)."""

from __future__ import annotations

from typing import Any

from swarm_mm.variants.a_signal import service as signal
from swarm_mm.variants.b_crypto import service as crypto
from swarm_mm.variants.c_b2b import service as b2b
from swarm_mm.variants.d_sim import service as sim
from swarm_mm.core.config import DISCLAIMER


def all_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    tools.extend(signal.mcp_tools())
    tools.extend(crypto.mcp_tools())
    tools.extend(b2b.mcp_tools())
    tools.extend(
        [
            {
                "name": "sim_swarm.join",
                "description": "Join paper-trading swarm with virtual capital.",
                "price_usd": 0.0,
                "input": {"user_id": "string", "starting_balance": "number"},
            },
            {
                "name": "sim_swarm.trade",
                "description": "Place simulated limit order against real/synthetic market data.",
                "price_usd": 0.0,
                "input": {
                    "user_id": "string",
                    "ticker": "string",
                    "side": "buy|sell",
                    "price": "number",
                    "size": "number",
                },
            },
            {
                "name": "sim_swarm.leaderboard",
                "description": "Paper swarm leaderboard.",
                "price_usd": 0.0,
                "input": {"timeframe": "daily|weekly|all_time"},
            },
            {
                "name": "sim_swarm.upgrade",
                "description": "Request upgrade path from sim to A/B/C.",
                "price_usd": 0.0,
                "input": {"user_id": "string", "target_variant": "A|B|C"},
            },
            {
                "name": "signal_swarm.broker_orders",
                "description": (
                    "Preview broker-native limit order payloads from swarm levels. "
                    "User submits at their own broker — swarm never places orders."
                ),
                "price_usd": 0.001,
                "input": {
                    "broker": "alpaca|tradier|ibkr",
                    "ticker": "string",
                    "side": "buy|sell|both",
                    "confidence_threshold": "float",
                    "max_levels": "int",
                },
            },
        ]
    )
    return tools


def dispatch(tool: str, params: dict[str, Any]) -> Any:
    """Execute an MCP tool by dotted name."""
    if tool == "signal_swarm.levels":
        return signal.levels(**{k: params[k] for k in params if k in ("ticker", "side", "confidence_threshold", "notional_usd", "depth")}).model_dump(mode="json")
    if tool == "signal_swarm.venue_map":
        return signal.venue_map_for(params["ticker"]).model_dump(mode="json")
    if tool == "signal_swarm.rebate_tracker":
        return signal.rebate(params["user_id"], params["ticker"], float(params.get("notional_usd", 100_000))).model_dump(mode="json")
    if tool == "signal_swarm.broker_orders":
        from swarm_mm.variants.a_signal import brokers as broker_adapters

        return broker_adapters.preview_orders(
            broker=params.get("broker", "alpaca"),
            ticker=params["ticker"],
            side=params.get("side", "both"),
            confidence_threshold=float(params.get("confidence_threshold", 0.75)),
            max_levels=int(params.get("max_levels", 3)),
        )
    if tool == "sim_swarm.join":
        from swarm_mm.core.models import SimJoinRequest

        return sim.join(SimJoinRequest(**params)).model_dump(mode="json")
    if tool == "sim_swarm.trade":
        from swarm_mm.core.models import SimTradeRequest

        return sim.trade(SimTradeRequest(**params))
    if tool == "sim_swarm.leaderboard":
        return sim.leaderboard(params.get("timeframe", "all_time")).model_dump(mode="json")
    if tool == "sim_swarm.upgrade":
        from swarm_mm.core.models import UpgradeRequest
        from swarm_mm.core.config import Variant

        return sim.upgrade(UpgradeRequest(user_id=params["user_id"], target_variant=Variant(params["target_variant"])))
    if tool == "b2b_swarm.configure":
        from swarm_mm.core.models import B2BConfigureRequest

        return b2b.configure(B2BConfigureRequest(**params))
    if tool == "b2b_swarm.optimize":
        from swarm_mm.core.models import B2BOptimizeRequest

        return b2b.optimize(B2BOptimizeRequest(**params))
    if tool == "b2b_swarm.report":
        return b2b.report(params["customer_id"], params.get("period", "30d"))
    if tool == "crypto_swarm.deposit":
        from swarm_mm.core.models import CryptoDepositRequest

        return crypto.deposit(CryptoDepositRequest(**params), user_id=params.get("user_id", "anonymous"))
    if tool == "crypto_swarm.positions":
        return crypto.positions(params["user_id"])
    if tool == "crypto_swarm.withdraw":
        return crypto.withdraw(
            params["vault_id"],
            params["asset"],
            float(params["amount"]),
            params.get("user_id", "anonymous"),
            bool(params.get("non_us_attestation", False)),
        )
    if tool == "crypto_swarm.rebalance":
        return crypto.rebalance(
            params["vault_id"],
            params.get("target_dex_weights") or {},
            bool(params.get("non_us_attestation", False)),
        )
    raise KeyError(f"unknown tool: {tool}")


def manifest() -> dict[str, Any]:
    return {
        "name": "swarm-mm",
        "version": "0.1.0",
        "company": "Script Master Labs",
        "disclaimer": DISCLAIMER,
        "tools": all_tools(),
    }
