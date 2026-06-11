"""
FTD Data Oracle — FastAPI web service wrapper
Exposes ftd_data.py as x402-ready HTTP endpoints.
"""
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# Import core engine
import sys
sys.path.insert(0, os.path.dirname(__file__))
from ftd_data import FTDDataLayer

app = FastAPI(
    title="FTD Data Oracle",
    description="SEC Reg SHO Fails-To-Deliver data — x402 gated",
    version="1.0.0"
)

_ftd = FTDDataLayer()

@app.get("/health")
def health():
    return {"status": "ok", "service": "ftd-data-oracle"}

@app.get("/v1/ftd/{ticker}")
def ftd_by_ticker(ticker: str):
    """FTD data for a ticker. Returns latest SEC Reg SHO fails-to-deliver."""
    try:
        result = _ftd.get_ftd(ticker.upper())
        if not result:
            raise HTTPException(status_code=404, detail=f"No FTD data for {ticker}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/threshold")
def threshold_list():
    """Current Reg SHO threshold securities list."""
    try:
        return _ftd.get_threshold_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/registry")
def registry():
    """Cached FTD registry snapshot."""
    import json, pathlib
    reg = pathlib.Path(__file__).parent / "ftd_registry.json"
    if reg.exists():
        return json.loads(reg.read_text())
    return {"error": "registry not found"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("ftd_server:app", host="0.0.0.0", port=port, reload=False)
