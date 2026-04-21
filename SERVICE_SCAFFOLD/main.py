from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from reference_impl import FusionEngine

app = FastAPI(title="ARGUS OMEGA")

class EventRisk(BaseModel):
    expansion: float = Field(ge=0, le=1)
    reversal: float = Field(ge=0, le=1)
    squeeze: float = Field(ge=0, le=1)
    trap: float = Field(ge=0, le=1)

class TriggerMap(BaseModel):
    confirm_above: Optional[float] = None
    invalidate_below: Optional[float] = None

class ArgusInput(BaseModel):
    state_score: float = Field(ge=0, le=100)
    bias: str
    stability: str
    event_risk: EventRisk
    confidence: float = Field(ge=0, le=1)
    trigger_map: Optional[TriggerMap] = None

class EchoInput(BaseModel):
    similarity_score: float = Field(ge=0, le=1)
    echo_type: str
    continuation_probability: float = Field(ge=0, le=1)
    reversal_probability: float = Field(ge=0, le=1)
    failure_probability: float = Field(ge=0, le=1)
    resolution_window_bars: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    top_matches: List[Dict[str, Any]] = []

class GhostInput(BaseModel):
    destination_score: float = Field(ge=0, le=1)
    primary_magnet: Optional[float] = None
    secondary_magnet: Optional[float] = None
    sweep_probability_up: float = Field(ge=0, le=1)
    sweep_probability_down: float = Field(ge=0, le=1)
    post_sweep_reversal_probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)

class RealityInput(BaseModel):
    truth_score: float = Field(ge=0, le=1)
    deception_score: float = Field(ge=0, le=1)
    breakout_validity: float = Field(ge=0, le=1)
    trap_probability: float = Field(ge=0, le=1)
    failure_warning: bool
    confidence: float = Field(ge=0, le=1)

class OmegaRequest(BaseModel):
    ticker: str
    timeframes: List[str]
    argus: ArgusInput
    echo_forge: EchoInput
    liquidity_ghost: GhostInput
    false_reality: RealityInput

engine = FusionEngine()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/omega_scan")
def omega_scan(req: OmegaRequest):
    return engine.fuse(
        req.ticker,
        req.timeframes,
        req.argus.model_dump(),
        req.echo_forge.model_dump(),
        req.liquidity_ghost.model_dump(),
        req.false_reality.model_dump(),
    )
