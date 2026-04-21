from pydantic import BaseModel, Field
from typing import List, Optional
from .subsystem import ArgusData, EchoForgeData, LiquidityGhostData, FalseRealityData, SmlSqueezeData

class OmegaScanRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    timeframes: List[str] = Field(default=["15m", "1h", "1d"])
    argus: ArgusData
    echo_forge: EchoForgeData
    liquidity_ghost: LiquidityGhostData
    false_reality: FalseRealityData
    sml_squeeze: Optional[SmlSqueezeData] = None
