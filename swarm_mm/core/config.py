"""Shared constants, types, and config for all swarm variants."""

from __future__ import annotations

import os
from enum import Enum
from typing import Literal

# ── Identity / payments (SML multi-rail) ─────────────────────────────────────
SML_PAYMENT_RECEIVER = os.environ.get(
    "SML_PAYMENT_RECEIVER",
    "0x72330994f379a71542e7bd5a4cf99a9d9743f4aa",
)
SOLANA_PAYMENT_RECEIVER = os.environ.get(
    "SOLANA_PAYMENT_RECEIVER",
    "E4d3JwcTjeqTRkkQS4moszcfa4R7G1NMgPSew4KBNFrB",
)
XRPL_PAYMENT_RECEIVER = os.environ.get("XRPL_PAYMENT_RECEIVER", "").strip()
# Same ACP EOA on Robinhood Chain for USDG (not a separate brokerage wallet)
USDG_PAYMENT_RECEIVER = os.environ.get(
    "USDG_PAYMENT_RECEIVER",
    SML_PAYMENT_RECEIVER,
)

BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_CHAIN_ID = 8453
ROBINHOOD_CHAIN_ID = 4663
USDG_ROBINHOOD = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
SOLANA_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
# Solana mainnet-beta CAIP-2 (matches mcp-x402 / agent402)
SOLANA_CAIP2 = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

OPERATOR_KEY_ENV = "SML_API_KEY"
OPERATOR_HEADER = "X-Operator-Key"

# ── Pricing (x402) ───────────────────────────────────────────────────────────
PRICE_SIGNAL_SUB_USD = 19.0          # Variant A monthly
PRICE_SIM_PREMIUM_USD = 9.0          # Variant D premium analytics
PRICE_B2B_PLATFORM_USD = 5000.0      # Variant C monthly seat
PRICE_B2B_REBATE_SHARE = 0.02        # 2% of incremental rebate improvement
PRICE_CRYPTO_REBATE_SHARE = 0.005     # 0.5% of gross maker rebate
PRICE_LEVELS_CALL_USD = 0.001        # hot call floor (snacks)
PRICE_VENUE_MAP_USD = 0.001
PRICE_REBATE_TRACKER_USD = 0.001
PRICE_BROKER_ORDERS_USD = 0.001
PRICE_B2B_OPTIMIZE_USD = 0.05
PRICE_B2B_REPORT_USD = 0.10

PLAN_SIM_FREE = "sim_free"
PLAN_SIM_PREMIUM = "sim_premium"
PLAN_SIGNAL = "signal"
PLAN_B2B = "b2b"

# ── Engine defaults ──────────────────────────────────────────────────────────
DEFAULT_CONFIDENCE = 0.75
DEFAULT_SWARM_DEPTH = 5
MAX_SWARM_PARTICIPANTS = 50_000
SIM_BALANCES = (10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)
DEFAULT_SIM_BALANCE = 100_000
MAKER_REBATE_BPS_DEFAULT = 0.20
SPREAD_CAPTURE_BPS_DEFAULT = 1.5
VENUE_WEIGHTS_DEFAULT = {
    "IEX": 0.60,
    "MEMX": 0.25,
    "NYSE": 0.10,
    "NASDAQ": 0.05,
}
CRYPTO_DEX_WEIGHTS_DEFAULT = {
    "hyperliquid": 0.40,
    "dydx": 0.25,
    "gmx": 0.20,
    "drift": 0.15,
}

DISCLAIMER = (
    "Educational / research signals only. Not investment advice. "
    "Not a broker-dealer, ATS, or investment adviser. "
    "Users place orders through their own licensed brokerage accounts. "
    "Past simulated performance is not indicative of future results. "
    "Script Master Labs — SDVOSB."
)

MECHANISM_ONE_LINER = (
    "Thousands of traders broadcast intent. The swarm compresses that into "
    "shared maker price levels + venue weights. You keep your broker. "
    "You keep your capital. The swarm sells coordination — not custody."
)

MECHANISM_BULLETS = [
    "Intent in: each participant states size/side preference (or sim does).",
    "Swarm math: aggregate notional + urgency → resting limit ladder around mid.",
    "Venue map: weight maker-rebate venues (e.g. IEX/MEMX) for fill quality.",
    "Signal out: levels + broker-native order preview — you submit at YOUR broker.",
    "No pooled book: Variant A never holds funds, never routes as a broker.",
]


class Variant(str, Enum):
    A_SIGNAL = "A"
    B_CRYPTO = "B"
    C_B2B = "C"
    D_SIM = "D"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    BOTH = "both"


class OrderStatus(str, Enum):
    RESTING = "resting"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    SIMULATED = "simulated"


SideLit = Literal["buy", "sell", "both"]
VariantLit = Literal["A", "B", "C", "D"]
