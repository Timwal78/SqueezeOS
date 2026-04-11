import logging
import os
import yfinance as yf
import pandas as pd
from data_providers import DataManager
from mean_reversion_engine import MeanReversionEngine

# SqueezeOS Universal Discovery Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UNIVERSAL_SCANNER")

# Disable verbose sub-loggers
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("MEAN_REVERSION_ENGINE").setLevel(logging.WARNING)

class UniversalScanner:
    """
    SQUEEZE OS Universal Mean Reversion Scanner v1.0
    Logic: Discover Movers -> Filter Budget (<$50) -> Score Reversion -> Report.
    """

    def __init__(self, max_price=50.0, min_price=1.0):
        self.data_manager = DataManager()
        self.engine = MeanReversionEngine(max_price=max_price)
        self.min_price = min_price
        self.max_price = max_price

    def is_market_panicking(self):
        """Check if the broader market (SPY) is in a sharp sell-off (>5% drop in 3 days)."""
        logger.info("[REGIME] Checking market health (SPY)...")
        try:
            spy = yf.download("SPY", period="5d", progress=False)
            if spy.empty: return False
            
            # Robustly fetch Close price regardless of index type
            close = spy['Close']
            if isinstance(close, pd.DataFrame):
                close = close.squeeze()
                
            latest_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-4]) # 3 trading days ago
            three_day_ret = (latest_price - prev_price) / prev_price
            
            if three_day_ret < -0.05:
                logger.warning(f"[PANIC] Market is in a sharp 3-day sell-off ({round(three_day_ret*100, 2)}%). Stay cautious.")
                return True
            return False
        except Exception as e:
            logger.error(f"Market panic check failed: {e}")
            return False

    def run_discovery_scan(self):
        """Execute the full Scan & Fetch pipeline with Institutional Filters."""
        print("\n" + "═"*85)
        print(" SQUEEZE OS: UNIVERSAL DISCOVERY SCAN ".center(85))
        print("═"*85)
        
        # 1. MARKET REGIME CHECK
        is_panic = self.is_market_panicking()
        if is_panic:
            print("\n" + "!"*85)
            print(" CAUTION: MARKET IS IN AN AGGRESSIVE SELL-OFF. MEAN REVERSION RISK IS HIGH. ".center(85))
            print("!"*85 + "\n")
        
        # 2. DISCOVER: Get current market heat
        logger.info("Initializing Universal Discovery (Alpaca + Polygon)...")
        raw_universe = self.data_manager.discover_universe(limit=500)
        
        if not raw_universe:
            logger.error("No tickers discovered. Check your API keys in .env")
            return
        
        # 3. FILTER: Apply budget and liquidity rules
        logger.info(f"Filtering {len(raw_universe)} tickers for budget (${self.min_price}-${self.max_price})...")
        filtered_tickers = []
        for sym, data in raw_universe.items():
            price = data.get('price', 0)
            vol = data.get('volume', 0)
            
            if price > 0:
                if self.min_price <= price <= self.max_price and vol > 100000:
                    filtered_tickers.append(sym)
            else:
                filtered_tickers.append(sym)
                
        logger.info(f"Discovery complete. Universal Pool: {len(filtered_tickers)} tickers.")
        
        # 4. SCORE: Run Mean Reversion Engine
        print(f"\n[FETCHING] Scoring {len(filtered_tickers)} symbols with Institutional Edge Boosters...")
        opportunities = self.engine.scan_universe(filtered_tickers)
        
        # 5. REPORT: Show results
        self.engine.print_scanner_report(opportunities)

if __name__ == "__main__":
    # Check for API keys
    if not os.environ.get('ALPACA_API_KEY') and not os.environ.get('POLYGON_API_KEY'):
        print("\n[!] WARNING: No API keys found in .env. Discovery may be limited.")
        print("Ensure ALPACA_API_KEY or POLYGON_API_KEY is set for full Universal Scan.\n")

    scanner = UniversalScanner(max_price=50.0)
    scanner.run_discovery_scan()
