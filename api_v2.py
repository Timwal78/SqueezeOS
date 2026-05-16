import asyncio
import logging
import sys
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── engine path ──────────────────────────────────────────────────────────────
_core_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core")
_ta_path   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tradingagents")
for p in (_core_path, _ta_path):
    if p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SML-API-V2")

app = FastAPI(title="SqueezeOS V2 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── shared state ──────────────────────────────────────────────────────────────
_engine       = None   # GammaFlowEngine, lazily started
_engine_ready = False
_council_cache: Dict[str, Dict] = {}   # ticker → latest decision

def _init_engine():
    global _engine, _engine_ready
    try:
        from data_providers import PolygonProvider
        from gamma_flow_engine import GammaFlowEngine
        polygon = PolygonProvider()
        _engine = GammaFlowEngine(polygon, ["IWM", "SPY"])
        _engine_ready = True
        logger.info("[API] GammaFlowEngine initialized")
    except Exception as e:
        logger.warning(f"[API] GammaFlowEngine unavailable: {e}")

@app.on_event("startup")
async def startup():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _init_engine)

# ── helpers ───────────────────────────────────────────────────────────────────
def _safe_profile(ticker: str) -> Optional[Dict]:
    if not _engine_ready or _engine is None:
        return None
    try:
        return _engine.get_ticker_profile(ticker)
    except Exception:
        return None

def _build_terminal_tickers() -> Dict[str, Any]:
    if not _engine_ready or _engine is None:
        return {
            "IWM": {"price": 0.0, "call_wall": 0.0, "put_wall": 0.0, "gex": 0, "apex": 0, "conviction": 0, "wrb_grade": "—"},
        }
    tickers = {}
    for sym in getattr(_engine, "watchlist", ["IWM", "SPY"]):
        p = _safe_profile(sym)
        if not p:
            continue
        tickers[sym] = {
            "price":      p.get("spot_price", 0.0),
            "call_wall":  p.get("call_wall", 0.0),
            "put_wall":   p.get("put_wall", 0.0),
            "gex":        int(p.get("total_gex", 0)),
            "apex":       int(p.get("urgency_score", 0)),
            "conviction": int(p.get("confidence_pct", 0)),
            "wrb_grade":  p.get("grade", "—"),
        }
    return tickers or {
        "IWM": {"price": 0.0, "call_wall": 0.0, "put_wall": 0.0, "gex": 0, "apex": 0, "conviction": 0, "wrb_grade": "—"},
    }

def _council_agents() -> list:
    base = [
        {"name": "War Room Beast",  "status": "SCANNING",   "last_thought": "Awaiting gamma trigger."},
        {"name": "SML Analyst",     "status": "MONITORING", "last_thought": "Tracking call wall positioning."},
        {"name": "Leviathan",       "status": "LISTENING",  "last_thought": "Dark pool feeds active."},
        {"name": "Risk Governor",   "status": "STANDBY",    "last_thought": "Position limits nominal."},
    ]
    # Overlay latest council decisions as thoughts
    for agent in base:
        if _council_cache:
            last_ticker = next(reversed(_council_cache))
            d = _council_cache[last_ticker]
            if agent["name"] == "War Room Beast":
                agent["status"] = d.get("action", "HOLD")
                agent["last_thought"] = d.get("reasoning", agent["last_thought"])[:120]
    return base

# ── /api/terminal ─────────────────────────────────────────────────────────────
@app.get("/api/terminal")
async def get_terminal_data():
    tickers = _build_terminal_tickers()

    # Derive master signal from council cache or engine state
    if _council_cache:
        last = _council_cache[next(reversed(_council_cache))]
        master_decision = last.get("action", "HOLD")
        master_grade    = last.get("grade", "B")
        bull            = last.get("bull", 50)
        bear            = 100 - bull
        edge            = bull - bear
    else:
        master_decision = "INITIALIZING"
        master_grade    = "—"
        bull, bear, edge = 50, 50, 0

    return {
        "status":          "ONLINE" if _engine_ready else "WARMING_UP",
        "master_decision": master_decision,
        "master_grade":    master_grade,
        "war_room_score":  {"bull": bull, "bear": bear, "edge": edge},
        "agents":          _council_agents(),
        "tickers":         tickers,
        # ── fields required by SML.tsx ──
        "options":         [],   # populated by /api/council analysis
        "whale_alerts":    [],   # populated by whale_stalker_engine when wired
        "news":            [],   # populated by news provider when wired
    }

# ── /api/council ──────────────────────────────────────────────────────────────
class CouncilRequest(BaseModel):
    ticker: str

def _run_council(ticker: str):
    """Blocking call — runs in thread pool so it doesn't block the event loop."""
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        cfg = DEFAULT_CONFIG.copy()
        ta  = TradingAgentsGraph(debug=False, config=cfg)
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"[COUNCIL] Convening for {ticker} ({today})")

        _, decision = ta.propagate(ticker, today)

        action     = decision.get("action", "HOLD")
        confidence = decision.get("confidence", 0.0)
        reasoning  = decision.get("reasoning", "")

        bull = int(min(100, max(0, 50 + confidence * 50 if action == "BUY" else 50 - confidence * 50)))
        _council_cache[ticker] = {
            "ticker":     ticker,
            "action":     action,
            "confidence": confidence,
            "reasoning":  reasoning,
            "grade":      "A" if confidence > 0.8 else "B" if confidence > 0.6 else "C",
            "bull":       bull,
            "timestamp":  datetime.now().isoformat(),
        }
        logger.info(f"[COUNCIL] {ticker} → {action} ({confidence:.2%})")
    except Exception as e:
        logger.error(f"[COUNCIL] Failed for {ticker}: {e}")
        _council_cache[ticker] = {
            "ticker":    ticker,
            "action":    "ERROR",
            "error":     str(e),
            "timestamp": datetime.now().isoformat(),
        }

@app.post("/api/council")
async def trigger_council(body: CouncilRequest, background_tasks: BackgroundTasks):
    """Enqueue a council analysis for a ticker. Returns immediately; result is cached."""
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")

    # Mark as in-progress
    _council_cache[ticker] = {
        "ticker":    ticker,
        "action":    "ANALYZING",
        "timestamp": datetime.now().isoformat(),
    }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_council, ticker)

    return {"status": "COUNCIL_CONVENED", "ticker": ticker, "msg": "Analysis in progress — poll GET /api/council/{ticker}"}

@app.get("/api/council/{ticker}")
async def get_council_decision(ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in _council_cache:
        raise HTTPException(status_code=404, detail=f"No council decision for {ticker}. POST /api/council first.")
    return _council_cache[ticker]

@app.get("/api/council")
async def list_council_decisions():
    return {"decisions": list(_council_cache.values())}

# ── /api/health ───────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status":        "ok",
        "engine_ready":  _engine_ready,
        "council_cache": len(_council_cache),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8182, log_level="info")
