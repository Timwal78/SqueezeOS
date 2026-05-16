from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import json

app = FastAPI(title="SqueezeOS V2 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Institutional state snapshot and engine integration point
# In production, this would read from a shared state or DB
@app.get("/api/terminal")
async def get_terminal_data():
    return {
        "status": "ONLINE",
        "master_decision": "STRONG LONG",
        "master_grade": "A+",
        "war_room_score": {"bull": 88, "bear": 12, "edge": 76},
        "apex_score": 6,
        "leviathan_matrix": "TRAPPING",
        "tickers": {
            "GME": {
                "price": 25.50, 
                "call_wall": 30.00, 
                "put_wall": 20.00, 
                "gex": 1500000,
                "apex": 6,
                "conviction": 85,
                "wrb_grade": "A+"
            }
        },
        "agents": [
            {"name": "War Room Beast", "status": "DOMINATING", "last_thought": "Elite bullish setup detected. GME aligned across all 5 engines."},
            {"name": "SML Analyst", "status": "SCANNING", "last_thought": "Confirming Apex breakout at $25.50."},
            {"name": "Leviathan", "status": "HUNTING", "last_thought": "Liquidity sweep confirmed on lower wick."}
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8182)
