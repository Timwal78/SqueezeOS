from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal

class ArgusEventRisk(BaseModel):
    expansion: float = Field(..., ge=0, le=1)
    reversal: float = Field(..., ge=0, le=1)
    squeeze: float = Field(..., ge=0, le=1)
    trap: float = Field(..., ge=0, le=1)

class ArgusTriggerMap(BaseModel):
    confirm_above: Optional[float] = None
    invalidate_below: Optional[float] = None

class ArgusData(BaseModel):
    state_score: float = Field(..., ge=0, le=100)
    bias: Literal["bullish", "unstable_bullish", "bearish", "unstable_bearish", "neutral", "fractured"]
    stability: Literal["stable", "fragile", "distorted", "breaking"]
    event_risk: ArgusEventRisk
    confidence: float = Field(..., ge=0, le=1)
    trigger_map: Optional[ArgusTriggerMap] = None

class EchoMatch(BaseModel):
    ticker: str
    date: str
    similarity: float = Field(..., ge=0, le=1)

class EchoForgeData(BaseModel):
    similarity_score: float = Field(..., ge=0, le=1)
    echo_type: str
    continuation_probability: float = Field(..., ge=0, le=1)
    reversal_probability: float = Field(..., ge=0, le=1)
    failure_probability: float = Field(..., ge=0, le=1)
    resolution_window_bars: int
    confidence: float = Field(..., ge=0, le=1)
    top_matches: List[EchoMatch]

class LiquidityGhostData(BaseModel):
    destination_score: float = Field(..., ge=0, le=1)
    primary_magnet: Optional[float] = None
    secondary_magnet: Optional[float] = None
    sweep_probability_up: float = Field(..., ge=0, le=1)
    sweep_probability_down: float = Field(..., ge=0, le=1)
    post_sweep_reversal_probability: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)

class FalseRealityData(BaseModel):
    truth_score: float = Field(..., ge=0, le=1)
    deception_score: float = Field(..., ge=0, le=1)
    breakout_validity: float = Field(..., ge=0, le=1)
    trap_probability: float = Field(..., ge=0, le=1)
    failure_warning: bool
    confidence: float = Field(..., ge=0, le=1)

class SmlSqueezeData(BaseModel):
    cycle_147_score: float = Field(..., ge=0, le=1)
    ftd_t35_score: Optional[float] = None
    xrt_flow_score: Optional[float] = None
    structure_score: Optional[float] = None
    composite: Optional[float] = None
