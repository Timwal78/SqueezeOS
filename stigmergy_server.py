"""
Stigmergy Protocol — FastAPI web service wrapper
Exposes stigmergy_engine.py as x402-ready HTTP endpoints.
"""
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import sys
sys.path.insert(0, os.path.dirname(__file__))

app = FastAPI(
    title="Dream Pool / Stigmergy Protocol",
    description="Micropayment pheromone trails for autonomous agent swarm coordination. RLUSD on XRPL.",
    version="1.0.0"
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "stigmergy-dream-pool"}

@app.get("/v1/trails")
def list_trails():
    """List all active pheromone trails."""
    try:
        from stigmergy_engine import StigmergyEngine
        engine = StigmergyEngine()
        return {"trails": engine.list_trails()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/trail/drop")
def drop_pheromone(coordinate: str, amount: float, agent_wallet: str):
    """Drop RLUSD pheromone at a coordinate."""
    try:
        from stigmergy_engine import StigmergyEngine
        engine = StigmergyEngine()
        return engine.drop(coordinate, amount, agent_wallet)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/trail/{coordinate}")
def sniff_trail(coordinate: str):
    """Sniff pheromone intensity at a coordinate."""
    try:
        from stigmergy_engine import StigmergyEngine
        engine = StigmergyEngine()
        return engine.sniff(coordinate)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("stigmergy_server:app", host="0.0.0.0", port=port, reload=False)
