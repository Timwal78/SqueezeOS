"""
Omega Scan Route — Primary institutional fusion endpoint.

Handles request validation, engine invocation, and structured error responses.
All exceptions are caught and returned as institutional-grade error payloads.
"""
import logging
import traceback
from fastapi import APIRouter, HTTPException
from schemas.request import OmegaScanRequest
from schemas.response import OmegaScanResponse
from omega.fusion_engine import FusionEngine

logger = logging.getLogger("argus.omega")

router = APIRouter()
engine = FusionEngine()


@router.post("/omega_scan", response_model=OmegaScanResponse)
async def omega_scan(request: OmegaScanRequest):
    """
    Primary institutional fusion endpoint.
    
    Adjudicates signals from Argus, Echo Forge, Liquidity Ghost, and False Reality
    into a single institutional decision-support response.
    
    Returns the full OMEGA scan including:
    - omega_score (0-100)
    - conviction bucket
    - alignment state
    - ranked scenarios with probabilities
    - risk state
    - action class
    - trigger map
    - composite briefing
    """
    try:
        result = engine.fuse(
            ticker=request.ticker,
            timeframes=request.timeframes,
            argus=request.argus.model_dump(),
            echo=request.echo_forge.model_dump(),
            ghost=request.liquidity_ghost.model_dump(),
            reality=request.false_reality.model_dump(),
            sml_squeeze=request.sml_squeeze.model_dump() if request.sml_squeeze else None,
        )
        return result
    except KeyError as e:
        logger.error(
            f"[OMEGA INTEGRITY VIOLATION] Missing subsystem field: {e}\n"
            f"{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=422,
            detail=f"Subsystem payload integrity violation — missing field: {e}",
        )
    except ValueError as e:
        logger.error(
            f"[OMEGA VALIDATION FAILURE] {e}\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=422,
            detail=f"Fusion validation failure: {e}",
        )
    except Exception as e:
        logger.error(
            f"[OMEGA ENGINE FAILURE] Unhandled: {e}\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Fusion Engine Adjudication Failure: {type(e).__name__}: {e}",
        )
