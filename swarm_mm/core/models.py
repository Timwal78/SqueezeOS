"""Shared Pydantic models for swarm MM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from swarm_mm.core.config import Side, Variant


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PriceLevel(BaseModel):
    price: float
    size: float
    side: Side
    confidence: float = Field(ge=0.0, le=1.0)
    venue_hint: Optional[str] = None
    expected_rebate_bps: float = 0.0
    rationale: str = ""


class VenueAllocation(BaseModel):
    venue: str
    weight: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class SwarmIntent(BaseModel):
    """Aggregated participant intent for a ticker/side."""

    ticker: str
    side: Side
    notional_usd: float = 0.0
    participant_count: int = 0
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    ts: datetime = Field(default_factory=utcnow)


class LevelRequest(BaseModel):
    ticker: str
    side: Side = Side.BOTH
    confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    notional_usd: Optional[float] = None
    depth: int = Field(default=5, ge=1, le=20)

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        t = (v or "").strip().upper()
        if not t or len(t) > 12:
            raise ValueError("invalid ticker")
        return t


class LevelResponse(BaseModel):
    ticker: str
    side: Side
    mid: float
    spread_bps: float
    levels: list[PriceLevel]
    swarm_participants: int
    confidence_threshold: float
    generated_at: datetime = Field(default_factory=utcnow)
    variant: Variant = Variant.A_SIGNAL
    disclaimer: str
    paper: bool = False


class VenueMapResponse(BaseModel):
    ticker: str
    allocations: list[VenueAllocation]
    summary: str
    generated_at: datetime = Field(default_factory=utcnow)
    disclaimer: str


class RebateEstimate(BaseModel):
    user_id: str
    ticker: str
    estimated_maker_rebate_usd: float
    estimated_spread_capture_usd: float
    notional_usd: float
    bps_rebate: float
    bps_spread: float
    window: str = "30d"
    generated_at: datetime = Field(default_factory=utcnow)


class SimJoinRequest(BaseModel):
    user_id: str
    starting_balance: float = Field(default=100_000, ge=1_000, le=1_000_000)


class SimTradeRequest(BaseModel):
    user_id: str
    ticker: str
    side: Side
    price: float = Field(gt=0)
    size: float = Field(gt=0)

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return (v or "").strip().upper()

    @field_validator("side")
    @classmethod
    def side_buy_sell(cls, v: Side) -> Side:
        if v not in (Side.BUY, Side.SELL):
            raise ValueError("side must be buy or sell")
        return v


class SimAccount(BaseModel):
    user_id: str
    cash: float
    starting_balance: float
    equity: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    open_orders: int = 0
    fills: int = 0
    maker_rebate_earned: float = 0.0
    joined_at: datetime = Field(default_factory=utcnow)
    premium: bool = False
    variant: Variant = Variant.D_SIM


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    equity: float
    realized_pnl: float
    return_pct: float
    fills: int
    maker_rebate_earned: float


class LeaderboardResponse(BaseModel):
    timeframe: str
    entries: list[LeaderboardEntry]
    generated_at: datetime = Field(default_factory=utcnow)
    paper: bool = True
    disclaimer: str


class UpgradeRequest(BaseModel):
    user_id: str
    target_variant: Variant


class B2BConfigureRequest(BaseModel):
    customer_id: str
    asset_universe: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "IWM"])
    risk_params: dict[str, Any] = Field(default_factory=dict)


class B2BOptimizeRequest(BaseModel):
    customer_id: str
    target: str = Field(default="rebate_capture", pattern="^(rebate_capture|spread)$")


class CryptoDepositRequest(BaseModel):
    vault_id: str
    asset: str
    amount: float = Field(gt=0)
    chain: str = Field(default="base", pattern="^(solana|base)$")
    # US geofence — caller must attest non-US
    non_us_attestation: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"
    product: str = "swarm-mm"
    version: str
    variants: list[str]
    pay_to: str
    paper_default: bool = True


class ErrorBody(BaseModel):
    error: str
    detail: Optional[str] = None
    disclaimer: Optional[str] = None
