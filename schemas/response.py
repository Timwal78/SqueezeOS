from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from .subsystem import ArgusData, EchoForgeData, LiquidityGhostData, FalseRealityData

class TriggerMapResponse(BaseModel):
    confirm_above: Optional[float] = None
    invalidate_below: Optional[float] = None
    sweep_target: Optional[float] = None
    trap_trigger: Optional[str] = None
    confirmation_mode: str

class OmegaScores(BaseModel):
    argus_strength: float
    echo_strength: float
    liquidity_strength: float
    truth_adjusted_strength: float
    alignment_strength: float

class Subsystems(BaseModel):
    argus: ArgusData
    echo_forge: EchoForgeData
    liquidity_ghost: LiquidityGhostData
    false_reality: FalseRealityData

class OmegaScanResponse(BaseModel):
    ticker: str
    timeframes: List[str]
    omega_score: float = Field(..., ge=0, le=100)
    conviction: str
    alignment_state: str
    dominant_scenario: str
    alternate_scenario: str
    risk_state: str
    action_class: str
    time_horizon: str
    composite_briefing: str
    trigger_map: TriggerMapResponse
    scores: OmegaScores
    scenario_probabilities: Dict[str, float]
    subsystems: Subsystems
