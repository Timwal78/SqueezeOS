from mean_reversion_engine import MeanReversionEngine
import logging

# Disable verbose logging
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("MEAN_REVERSION_ENGINE").setLevel(logging.INFO)

def run_audit():
    # User's budget-friendly scanner
    # MAX_PRICE = $50 as discussed in the plan
    engine = MeanReversionEngine(max_price=50.0)
    
    # Selection of high-liquidity, lower-priced stocks (under $75 for diverse results)
    universe = [
        "AMD", "PLTR", "NIO", "SOFI", "PFE", "F", "BAC", "T", "VALE", "AAL",
        "CCL", "DAL", "ET", "KEY", "LYG", "MRO", "NOK", "NYCB", "RIG", "SWN",
        "WBD", "INTC", "UBER", "HOOD", "SNAP", "DKNG", "COIN", "MARA", "RIOT"
    ]
    
    print(f"\n[SCANNER] Auditing {len(universe)} symbols for Mean Reversion setups...")
    print(f"[FILTER]  Max Price: ${engine.max_price}")
    
    opps = engine.scan_universe(universe)
    engine.print_scanner_report(opps)

if __name__ == "__main__":
    run_audit()
