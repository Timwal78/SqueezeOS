import asyncio
import logging
import sys
import os
from datetime import datetime

# Add internal modules to path
sys.path.append(os.path.join(os.getcwd(), 'core'))
sys.path.append(os.path.join(os.getcwd(), 'tradingagents'))

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
        self.watchlist = ["IWM", "SPY"] # Base anchors
        self.engine = GammaFlowEngine(self.polygon, self.watchlist)
        self.last_discovery = 0
        
    async def discover_tickers(self):
        """Dynamically discovers high-velocity tickers from the live tape."""
        if not self.alpaca.available:
            logger.warning("[CEO] Alpaca not available for discovery.")
            return
        
        try:
            actives = self.alpaca.get_most_actives(top=15)
            new_tickers = [a['symbol'] for a in actives if a.get('symbol')]
            
            # Merge with anchors and remove duplicates
            combined = list(dict.fromkeys(["IWM", "SPY"] + new_tickers))[:20]
            
            if set(combined) != set(self.watchlist):
                logger.info(f"🔄 [CEO] Dynamic Discovery: {', '.join(combined)}")
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
                spot = profile['spot_price']
                call_wall = profile['call_wall']
                put_wall = profile['put_wall']
                z_score = profile['inventory_z']
                
                # Zero-Fake check: if spot is 0, it's fake data or missing
                if spot <= 0:
                    continue

                logger.info(f"[{ticker}] Spot: {spot} | Walls: {put_wall}-{call_wall} | Stress: {z_score:.2f}")
                
                if spot > call_wall and z_score > 1.5:
                    logger.info(f"🔥 FIRE SIGNAL: {ticker} breaking Call Wall with high stress!")
                    
                    try:
                        import sys
                        import os
                        ta_path = os.path.join(os.path.dirname(__file__), 'tradingagents')
                        if ta_path not in sys.path:
                            sys.path.append(ta_path)
                            
                        from tradingagents.graph.trading_graph import TradingAgentsGraph
                        from tradingagents.default_config import DEFAULT_CONFIG
                        
                        ta_config = DEFAULT_CONFIG.copy()
                        ta = TradingAgentsGraph(debug=True, config=ta_config)
                        
                        today = datetime.now().strftime('%Y-%m-%d')
                        logger.info(f"🧠 [CEO] Convening Council of Agents for {ticker}...")
                        
                        _, decision = ta.propagate(ticker, today)
                        
                        logger.info(f"⚖️ [COUNCIL] Decision for {ticker}: {decision.get('action', 'HOLD')} | Confidence: {decision.get('confidence', 0)}")
                        
                        # Trigger Execution if Council agrees
                        if decision.get('action') == 'BUY' and decision.get('confidence', 0) > 0.7:
                            logger.info(f"🚀 [CEO] EXECUTION APPROVED: Buying {ticker}")
                            
                            # Calculate Position Sizing (Institutional: 5% of equity)
                            account = self.alpaca.get_account()
                            equity = float(account.get('equity', 0))
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
