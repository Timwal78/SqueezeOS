"""
FTD Data Oracle — FastAPI web service
Exposes SEC Reg SHO Fails-To-Deliver data via HTTP endpoints.
Uses only stdlib — no pandas dependency.
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
import uvicorn

# Start background pollers before app starts
from ftd_data import get_store, start_ftd_pollers, cycle_summary_for

logging.basicConfig(level=logging.INFO)
start_ftd_pollers()  # kicks off background SEC polling threads

app = FastAPI(
    title="FTD Data Oracle",
    description="SEC Reg SHO Fails-To-Deliver data — public regulatory feed",
    version="1.0.0"
)

@app.get("/health")
def health():
    store = get_store()
    return {"status": "ok", "service": "ftd-data-oracle", **store.status()}

@app.get("/v1/ftd/{ticker}")
def ftd_series(ticker: str, limit: int = 90):
    """FTD time series for a ticker (up to 180 days)."""
    store = get_store()
    records = store.series_for(ticker.upper(), limit=limit)
    if not records:
        raise HTTPException(status_code=404, detail=f"No FTD data for {ticker.upper()} — data may still be loading or symbol has no recent FTDs")
    return {"ticker": ticker.upper(), "records": records, "count": len(records)}

@app.get("/v1/ftd/{ticker}/latest")
def ftd_latest(ticker: str):
    """Latest FTD ratio + pressure context for a ticker."""
    store = get_store()
    result = store.latest_ratio(ticker.upper())
    if not result:
        raise HTTPException(status_code=404, detail=f"No FTD data for {ticker.upper()}")
    return result

@app.get("/v1/threshold")
def threshold_list():
    """Current Reg SHO threshold securities list."""
    store = get_store()
    return {"securities": store.threshold_list(), "count": len(store.threshold_list())}

@app.get("/v1/threshold/{ticker}")
def is_threshold(ticker: str):
    """Is ticker on the Reg SHO threshold list?"""
    store = get_store()
    on_list = store.is_on_threshold_list(ticker.upper())
    entry_date = store.threshold_entry_date(ticker.upper())
    return {"ticker": ticker.upper(), "on_threshold_list": on_list, "entry_date": str(entry_date) if entry_date else None}

@app.get("/v1/basket/{etf}")
def basket(etf: str):
    """ETF basket FTD breakdown (XRT, IWM, IJR, KRE)."""
    store = get_store()
    result = store.basket_breakdown(etf.upper())
    if not result:
        raise HTTPException(status_code=404, detail=f"No basket data for {etf.upper()} — supported: XRT, IWM, IJR, KRE")
    return result

@app.get("/v1/cycle/{ticker}")
def cycle_summary(ticker: str):
    """Settlement cycle summary for a ticker."""
    return cycle_summary_for(ticker.upper())

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("ftd_server:app", host="0.0.0.0", port=port, reload=False)
