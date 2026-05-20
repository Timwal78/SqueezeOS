import asyncio
import logging
import sys
import os
import time
from datetime import datetime

# ── load .env ────────────────────────────────────────────────────────────────
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

# Add internal modules to path — use __file__ so it works from any cwd
_here = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_here, 'core'), os.path.join(_here, 'tradingagents')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gamma_flow_engine import GammaFlowEngine
from data_providers import PolygonProvider, AlpacaProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SML-CEO-V2")

class SqueezeOS_CEO:
    """
    The new Institutional CEO. 
    Replaces the legacy 'ceo_trader.py' with a multi-agent orchestration layer.
    """
    def __init__(self):
        self.polygon = PolygonProvider()
        self.alpaca = AlpacaProvider()
        self.watchlist = ["IWM", "AMC", "GME"] # Base anchors
        self.engine = GammaFlowEngine(self.polygon, self.watchlist)
        self.last_discovery = 0
        
    async def discover_tickers(self):
        """Dynamically discovers high-velocity tickers from the live tape in the $1-$60 sweet spot."""
        try:
            # 1. Widest free tier fetch: Polygon Grouped Daily (entire US market)
            poly_data = self.polygon.get_grouped_daily()
            new_tickers = []
            
            if poly_data:
                # Filter for sweet spot: $1 - $60
                candidates = [
                    v for k, v in poly_data.items()
                    if 1.0 <= v.get('price', 0) <= 60.0
                ]
                # Sort by volume to get the most active in this price range
                candidates.sort(key=lambda x: x.get('volume', 0), reverse=True)
                new_tickers = [x['symbol'] for x in candidates[:19]]
            else:
                # Fallback to Alpaca if Polygon fails
                if self.alpaca.available:
                    actives = self.alpaca.get_most_actives(top=50)
                    new_tickers = [a['symbol'] for a in actives if a.get('symbol')]
            
            # Merge with anchors and remove duplicates
            combined = list(dict.fromkeys(["IWM", "AMC", "GME"] + new_tickers))[:20]
            
            if set(combined) != set(self.watchlist):
                logger.info(f"🔄 [CEO] Dynamic Discovery ($1-$60 Wide Net): {', '.join(combined)}")
                self.watchlist = combined
                self.engine.watchlist = combined
                
        except Exception as e:
            logger.error(f"[CEO] Discovery failure: {e}")

    async def run(self):
        logger.info("🚀 SqueezeOS V2 Institutional CEO Initialized")
        logger.info("Mode: Multi-Agent Council (ChainML / Tauric)")
        
        # Initial discovery
        await self.discover_tickers()
        
        # Start the Gamma Engine in the background
        asyncio.create_task(self.engine.run_forever())
        
        while True:
            # Refresh watchlist every 5 minutes
            if time.time() - self.last_discovery > 300:
                await self.discover_tickers()
                self.last_discovery = time.time()

            for ticker in self.watchlist:
                profile = self.engine.get_ticker_profile(ticker)
                if not profile:
                    continue
                
                # EXECUTION PROTOCOL
                spot      = float(profile.get('spot_price',  0) or 0)
                call_wall = float(profile.get('call_wall',   0) or 0)
                put_wall  = float(profile.get('put_wall',    0) or 0)
                z_score   = float(profile.get('inventory_z', 0) or 0)
                
                # Zero-Fake check: if spot is 0, it's fake data or missing
                if spot <= 0:
                    continue

                logger.info(f"[{ticker}] Spot: {spot} | Walls: {put_wall}-{call_wall} | Stress: {z_score:.2f}")
                
                if spot > call_wall and z_score > 1.5:
                    logger.info(f"🔥 FIRE SIGNAL: {ticker} breaking Call Wall with high stress!")
                    
                    try:
                        from tradingagents.graph.trading_graph import TradingAgentsGraph
                        from tradingagents.default_config import DEFAULT_CONFIG
                        
                        ta_config = DEFAULT_CONFIG.copy()
                        ta_config["llm_provider"]    = os.environ.get("TRADINGAGENTS_LLM_PROVIDER",    "openai")
                        ta_config["backend_url"]     = os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL",  "https://openrouter.ai/api/v1")
                        ta_config["deep_think_llm"]  = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM",   "google/gemini-2.5-flash-preview-05-20")
                        ta_config["quick_think_llm"] = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM",  "meta-llama/llama-4-scout")
                        ta = TradingAgentsGraph(debug=True, config=ta_config)
                        
                        today = datetime.now().strftime('%Y-%m-%d')
                        logger.info(f"🧠 [CEO] Convening Council of Agents for {ticker}...")
                        
                        _, decision = ta.propagate(ticker, today)
                        
                        logger.info(f"⚖️ [COUNCIL] Decision for {ticker}: {decision.get('action', 'HOLD')} | Confidence: {decision.get('confidence', 0)}")
                        
                        # Trigger Execution if Council agrees
                        if decision.get('action') == 'BUY' and decision.get('confidence', 0) > 0.7:
                            logger.info(f"🚀 [CEO] EXECUTION APPROVED: Buying {ticker}")
                            
                            # Calculate Position Sizing (Institutional: 5% of equity)
                            try:
                                account = self.alpaca.get_account()
                            except Exception as _ae:
                                logger.error(f"[CEO] Alpaca account fetch failed: {_ae}")
                                continue
                            equity = float(account.get('equity', 0) or 0)
                            price = spot if spot > 0 else 100 # Fallback price
                            
                            if equity > 0:
                                qty = int((equity * 0.05) / price)
                                if qty > 0:
                                    logger.info(f"💼 [CEO] Sizing: {qty} shares of {ticker} (${equity * 0.05:.2f} risk)")
                                    res = self.alpaca.place_order(symbol=ticker, qty=qty, side='buy', order_type='market')
                                    if res.get('status') == 'success':
                                        logger.info(f"✅ [CEO] Order Placed: {res.get('order_id')}")
                                    else:
                                        logger.error(f"🛑 [CEO] Order Failed: {res.get('message')}")
                                else:
                                    logger.warning(f"⚠️ [CEO] Qty too small for {ticker}")
                            else:
                                logger.error("[CEO] Cannot size position: Equity is zero or account inaccessible.")
                            
                    except Exception as e:
                        logger.error(f"[CEO] Council Execution failed: {e}")
                
            await asyncio.sleep(10)

if __name__ == "__main__":
    ceo = SqueezeOS_CEO()
    asyncio.run(ceo.run())
