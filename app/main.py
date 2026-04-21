"""
Argus Omega — Institutional-grade fusion engine for market intelligence.

Main application entry point. Configures FastAPI with:
- CORS middleware for cross-origin access
- Structured logging
- Dual route registration (versioned + spec-compliant)
- Health check endpoint
- Startup/shutdown lifecycle hooks
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import omega_scan
from app.config import APP_NAME, DEBUG, HOST, PORT
from app.utils.discord import send_system_alert

# Configure structured logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("argus.omega")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for Argus Omega."""
    logger.info("=" * 60)
    logger.info("  ARGUS OMEGA — Institutional Fusion Engine ONLINE")
    logger.info(f"  Debug: {DEBUG} | Host: {HOST} | Port: {PORT}")
    logger.info("=" * 60)
    
    # Institutional Health Reporting
    await send_system_alert(
        "Master Engine ONLINE", 
        "Argus Omega is now monitoring institutional fusion layers.",
        color=0x2ecc71 # Green
    )
    yield
    logger.info("ARGUS OMEGA — Shutting down.")


app = FastAPI(
    title=APP_NAME,
    description=(
        "Institutional-grade fusion layer for Argus Intelligence Systems. "
        "Adjudicates signals from ARGUS, ECHO FORGE, LIQUIDITY GHOST, and FALSE REALITY "
        "into a single decision-support output with conviction, scenario ranking, "
        "and action classification."
    ),
    version="1.0.0",
    debug=DEBUG,
    lifespan=lifespan,
)

# CORS — allow dashboard and external integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes at both paths:
# /omega_scan — as specified in SPEC_MASTER.md
# /api/v1/omega_scan — versioned API path for production integrations
app.include_router(omega_scan.router, tags=["Fusion"])
app.include_router(omega_scan.router, prefix="/api/v1", tags=["Fusion (Versioned)"])


@app.get("/health", tags=["System"])
async def health_check():
    """System health check — returns operational status."""
    return {
        "status": "operational",
        "engine": "Omega Fusion v1.0.0",
        "subsystems": ["argus", "echo_forge", "liquidity_ghost", "false_reality"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
