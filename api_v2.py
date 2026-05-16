import asyncio
import logging
import sys
import os
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── load .env before anything else ───────────────────────────────────────────
def _load_dotenv(path: str):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── sys path ──────────────────────────────────────────────────────────────────
for _p in (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tradingagents"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SML-API-V2")

app = FastAPI(title="SqueezeOS V2 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── constants (all user-configurable via env) ─────────────────────────────────
PERMANENT_WATCHES = ["IWM", "AMC", "GME"]   # always in watchlist, no price filter
PRICE_MIN  = float(os.environ.get("DISCOVERY_PRICE_MIN", "1.0"))
PRICE_MAX  = float(os.environ.get("DISCOVERY_PRICE_MAX", "50.0"))
DELTA_MIN  = float(os.environ.get("OPTIONS_DELTA_MIN",   "0.35"))
DELTA_MAX  = float(os.environ.get("OPTIONS_DELTA_MAX",   "0.45"))
MAX_SPREAD = float(os.environ.get("OPTIONS_MAX_SPREAD",  "0.30"))  # max bid/ask spread %

# ── shared state ──────────────────────────────────────────────────────────────
_tradier       = None
_polygon       = None
_engine        = None
_engine_ready  = False

_council_cache:  Dict[str, Dict] = {}
_live_tickers:   List[str]       = list(PERMANENT_WATCHES)
_ticker_quotes:  Dict[str, Dict] = {}
_options_cache:  List[Dict]      = []

_last_discovery = 0.0
_last_options   = 0.0
_last_quotes    = 0.0

# ── provider init ─────────────────────────────────────────────────────────────
def _init_providers():
    global _tradier, _polygon, _engine, _engine_ready
    try:
        from data_providers import TradierProvider, PolygonProvider
        _tradier = TradierProvider()
        _polygon = PolygonProvider()
        from gamma_flow_engine import GammaFlowEngine
        _engine = GammaFlowEngine(_polygon, list(PERMANENT_WATCHES))
        _engine_ready = True
        logger.info("[API] Providers ready — Tradier=%s Polygon=%s",
                    getattr(_tradier, "available", False),
                    getattr(_polygon, "available", False))
    except Exception as e:
        logger.warning("[API] Provider init failed: %s", e)

@app.on_event("startup")
async def startup():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _init_providers)
    asyncio.create_task(_background_loop())

async def _background_loop():
    """Refresh quotes, discovery, and options every 30 s."""
    while True:
        await asyncio.sleep(30)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _refresh_all)

def _refresh_all():
    global _live_tickers, _ticker_quotes, _options_cache
    global _last_discovery, _last_options, _last_quotes
    now = time.time()

    if now - _last_discovery > 300:          # every 5 min
        _live_tickers   = _discover_tickers()
        _last_discovery = now

    if now - _last_quotes > 30:             # every 30 s
        _ticker_quotes = _fetch_quotes(_live_tickers)
        _last_quotes   = now

    if now - _last_options > 120:           # every 2 min
        _options_cache = _build_recommendations()
        _last_options  = now

# ── ticker discovery ──────────────────────────────────────────────────────────
def _discover_tickers() -> List[str]:
    """Dynamic $1-$50 movers via Polygon grouped daily. Permanent watches always included."""
    watchlist = list(PERMANENT_WATCHES)

    if _polygon and getattr(_polygon, "available", False):
        try:
            today_str = date.today().strftime("%Y-%m-%d")
            results   = _polygon.get_grouped_daily(today_str) or []

            # Filter by close price and sort by volume descending
            filtered = [
                r for r in results
                if isinstance(r, dict)
                and PRICE_MIN <= float(r.get("c", 0)) <= PRICE_MAX
                and r.get("T") not in watchlist
                and r.get("T")
            ]
            filtered.sort(key=lambda r: r.get("v", 0), reverse=True)

            for r in filtered[:20]:
                sym = r["T"]
                if sym not in watchlist:
                    watchlist.append(sym)
                if len(watchlist) >= 25:
                    break

            logger.info("[DISCOVERY] %d tickers (Polygon)", len(watchlist))
        except Exception as e:
            logger.warning("[DISCOVERY] Polygon error: %s", e)

    return watchlist

# ── live quotes ───────────────────────────────────────────────────────────────
def _fetch_quotes(symbols: List[str]) -> Dict[str, Dict]:
    quotes: Dict[str, Dict] = {}
    if not symbols:
        return quotes

    # Tradier batch
    if _tradier and getattr(_tradier, "available", False):
        try:
            raw = _tradier.get_quotes(symbols) or {}
            for sym, q in raw.items():
                last = q.get("last") or q.get("close") or 0
                if last:
                    quotes[sym] = {
                        "price":      float(last),
                        "change_pct": float(q.get("change_percentage", 0)),
                        "volume":     int(q.get("volume", 0)),
                    }
        except Exception as e:
            logger.warning("[QUOTES] Tradier: %s", e)

    # yfinance fallback for anything missing
    missing = [s for s in symbols if s not in quotes]
    if missing:
        try:
            import yfinance as yf
            tickers = yf.Tickers(" ".join(missing))
            for sym in missing:
                try:
                    info  = tickers.tickers[sym].fast_info
                    price = float(info.last_price or 0)
                    if price:
                        quotes[sym] = {"price": price, "change_pct": 0, "volume": 0}
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[QUOTES] yfinance: %s", e)

    return quotes

# ── 0DTE options ──────────────────────────────────────────────────────────────
def _today_expiration() -> Optional[str]:
    d = date.today()
    return d.strftime("%Y-%m-%d") if d.weekday() < 5 else None

def _fetch_chain(symbol: str, expiration: str) -> List[Dict]:
    if not (_tradier and getattr(_tradier, "available", False)):
        return []
    try:
        chain = _tradier.get_option_chain(symbol, expiration)
        return chain if isinstance(chain, list) else []
    except Exception as e:
        logger.warning("[OPTIONS] Tradier %s: %s", symbol, e)
        return []

def _score_option(opt: Dict, symbol: str, spot: float) -> Optional[Dict]:
    """Return a scored recommendation dict or None if filtered out."""
    raw_delta = opt.get("delta") or opt.get("greeks", {}).get("delta") if isinstance(opt.get("greeks"), dict) else opt.get("delta")
    if raw_delta is None:
        return None

    delta = abs(float(raw_delta))
    if not (DELTA_MIN <= delta <= DELTA_MAX):
        return None

    bid = float(opt.get("bid") or 0)
    ask = float(opt.get("ask") or 0)
    if bid <= 0 or ask <= 0:
        return None

    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None

    spread_pct = (ask - bid) / mid
    if spread_pct > MAX_SPREAD:
        return None

    strike   = float(opt.get("strike") or 0)
    opt_type = (opt.get("option_type") or opt.get("type") or "").lower()
    if opt_type not in ("call", "put"):
        return None
    expiration = opt.get("expiration_date", _today_expiration() or "")

    # Grade: A = ideal delta, tight spread; B = acceptable; C = borderline
    if 0.38 <= delta <= 0.42 and spread_pct < 0.15:
        grade = "A"
    elif spread_pct < 0.20:
        grade = "B"
    else:
        grade = "C"

    target = round(mid * 2.0, 2)
    stop   = round(mid * 0.50, 2)

    if opt_type == "call":
        trigger  = round(strike + 0.10, 2)
        otm      = spot < strike
        action   = "WATCH" if abs(spot - strike) < 0.75 else ("BUY" if spot >= strike else "WATCH")
        instr    = (
            f"BUY ${mid:.2f} if {symbol} breaks ${trigger:.2f} → "
            f"TARGET ${target:.2f} | STOP ${stop:.2f} | CLOSE by 3:30 PM"
        )
        if spot > strike + 1.50:
            action = "HOLD"   # too deep ITM
            instr  = f"HOLD or SELL — deep ITM. Lock gains above ${target:.2f}."
    else:
        trigger  = round(strike - 0.10, 2)
        action   = "WATCH" if abs(spot - strike) < 0.75 else ("BUY" if spot <= strike else "WATCH")
        instr    = (
            f"BUY ${mid:.2f} if {symbol} breaks below ${trigger:.2f} → "
            f"TARGET ${target:.2f} | STOP ${stop:.2f} | CLOSE by 3:30 PM"
        )
        if spot < strike - 1.50:
            action = "HOLD"
            instr  = f"HOLD or SELL — deep ITM. Lock gains below ${stop:.2f}."

    return {
        "symbol":      symbol,
        "strike":      strike,
        "type":        opt_type,
        "expiration":  expiration,
        "dte":         0,
        "mid":         round(mid, 2),
        "delta":       round(delta, 3),
        "grade":       grade,
        "action":      action,
        "target":      target,
        "stop":        stop,
        "instruction": instr,
    }

def _build_recommendations() -> List[Dict]:
    """Real 0DTE options recommendations — IWM primary, AMC/GME always watched."""
    exp = _today_expiration()
    if not exp:
        return []   # weekend / holiday — no 0DTE

    recs = []
    for symbol in ["IWM", "AMC", "GME"]:
        spot = _ticker_quotes.get(symbol, {}).get("price", 0)
        if spot <= 0:
            continue
        for opt in _fetch_chain(symbol, exp):
            scored = _score_option(opt, symbol, spot)
            if scored:
                recs.append(scored)

    # A grades first, then by closeness to ideal delta 0.40
    recs.sort(key=lambda x: (x["grade"], abs(x["delta"] - 0.40)))
    return recs[:20]

# ── terminal ticker map ───────────────────────────────────────────────────────
def _build_tickers() -> Dict[str, Any]:
    result = {}
    for sym in _live_tickers:
        quote = _ticker_quotes.get(sym, {})
        price = quote.get("price", 0)
        if price <= 0:
            continue
        # Enforce price filter except for permanent watches
        if sym not in PERMANENT_WATCHES and not (PRICE_MIN <= price <= PRICE_MAX):
            continue

        gex = call_wall = put_wall = apex = 0
        if _engine_ready and _engine:
            try:
                p = _engine.get_ticker_profile(sym)
                if p:
                    gex       = int(p.get("total_gex", 0))
                    call_wall = float(p.get("call_wall", 0))
                    put_wall  = float(p.get("put_wall", 0))
                    apex      = int(p.get("urgency_score", 0))
            except Exception:
                pass

        result[sym] = {
            "price":      round(price, 2),
            "call_wall":  call_wall,
            "put_wall":   put_wall,
            "gex":        gex,
            "apex":       apex,
            "conviction": int(abs(gex) / 1_000_000) if gex else 0,
            "wrb_grade":  "—",
            "change_pct": round(quote.get("change_pct", 0), 2),
        }
    return result

def _council_agents() -> List[Dict]:
    agents = [
        {"name": "War Room Beast",  "status": "SCANNING",   "last_thought": "Monitoring IWM 0DTE gamma flow."},
        {"name": "SML Analyst",     "status": "MONITORING", "last_thought": "Tracking call wall vs put wall."},
        {"name": "Leviathan",       "status": "LISTENING",  "last_thought": "Dark pool feeds active."},
        {"name": "Risk Governor",   "status": "STANDBY",    "last_thought": "Position limits nominal."},
    ]
    if _council_cache:
        last = _council_cache[next(reversed(_council_cache))]
        if last.get("action") not in ("ANALYZING", "ERROR", None):
            agents[0]["status"]      = last.get("action", "SCANNING")
            agents[0]["last_thought"] = (last.get("reasoning") or "")[:120] or agents[0]["last_thought"]
    return agents

# ── /api/terminal ─────────────────────────────────────────────────────────────
@app.get("/api/terminal")
async def get_terminal_data():
    tickers = _build_tickers()
    options = list(_options_cache)

    master_decision = "SCANNING"
    master_grade    = "—"
    bull            = 50

    if _council_cache:
        last = _council_cache[next(reversed(_council_cache))]
        if last.get("action") not in ("ANALYZING", "ERROR", None):
            master_decision = last.get("action", "SCANNING")
            master_grade    = last.get("grade", "—")
            bull            = last.get("bull", 50)

    bear = 100 - bull
    edge = bull - bear

    return {
        "status":          "ONLINE" if _engine_ready else "WARMING_UP",
        "master_decision": master_decision,
        "master_grade":    master_grade,
        "war_room_score":  {"bull": bull, "bear": bear, "edge": edge},
        "agents":          _council_agents(),
        "tickers":         tickers,
        "options":         options,
        "whale_alerts":    [],
        "news":            [],
    }

# ── /api/council ──────────────────────────────────────────────────────────────
class CouncilRequest(BaseModel):
    ticker: str

def _run_council(ticker: str):
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        cfg = DEFAULT_CONFIG.copy()
        cfg["llm_provider"]    = os.environ.get("TRADINGAGENTS_LLM_PROVIDER",    "openai")
        cfg["backend_url"]     = os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL",  "https://openrouter.ai/api/v1")
        cfg["deep_think_llm"]  = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM",   "google/gemini-2.5-flash-preview-05-20")
        cfg["quick_think_llm"] = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM",  "meta-llama/llama-4-scout")

        ta     = TradingAgentsGraph(debug=False, config=cfg)
        today  = datetime.now().strftime("%Y-%m-%d")
        logger.info("[COUNCIL] Convening for %s (%s)", ticker, today)

        _, decision = ta.propagate(ticker, today)

        action     = decision.get("action", "HOLD")
        confidence = float(decision.get("confidence", 0))
        reasoning  = decision.get("reasoning", "")
        bull       = int(min(100, max(0, 50 + confidence * 50 if action == "BUY" else 50 - confidence * 50)))

        _council_cache[ticker] = {
            "ticker":     ticker,
            "action":     action,
            "confidence": confidence,
            "reasoning":  reasoning,
            "grade":      "A" if confidence > 0.8 else "B" if confidence > 0.6 else "C",
            "bull":       bull,
            "timestamp":  datetime.now().isoformat(),
        }
        logger.info("[COUNCIL] %s → %s (%.0f%%)", ticker, action, confidence * 100)

    except Exception as e:
        logger.error("[COUNCIL] %s failed: %s", ticker, e)
        _council_cache[ticker] = {
            "ticker":    ticker,
            "action":    "ERROR",
            "error":     str(e),
            "timestamp": datetime.now().isoformat(),
        }

@app.post("/api/council")
async def trigger_council(body: CouncilRequest):
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    _council_cache[ticker] = {"ticker": ticker, "action": "ANALYZING", "timestamp": datetime.now().isoformat()}
    asyncio.get_event_loop().run_in_executor(None, _run_council, ticker)
    return {"status": "COUNCIL_CONVENED", "ticker": ticker}

@app.get("/api/council/{ticker}")
async def get_council_decision(ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in _council_cache:
        raise HTTPException(status_code=404, detail=f"No decision for {ticker} — POST /api/council first")
    return _council_cache[ticker]

@app.get("/api/council")
async def list_council_decisions():
    return {"decisions": list(_council_cache.values())}

@app.get("/api/health")
async def health():
    return {
        "status":        "ok",
        "engine_ready":  _engine_ready,
        "live_tickers":  _live_tickers,
        "options_count": len(_options_cache),
        "council_count": len(_council_cache),
        "price_filter":  f"${PRICE_MIN}-${PRICE_MAX}",
        "delta_filter":  f"{DELTA_MIN}-{DELTA_MAX}",
        "permanent":     PERMANENT_WATCHES,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8182, log_level="info")
