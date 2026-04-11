from mean_reversion_engine import MeanReversionEngine
import logging

# Disable yfinance and other verbose loggers for testing
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

def test_engine():
    engine = MeanReversionEngine()
    
    tickers = ["SPY", "QQQ", "AAPL", "DIA"]
    
    print("\nStarting Mean Reversion Engine Audit...\n")
    
    for ticker in tickers:
        try:
            engine.analyze(ticker)
        except Exception as e:
            print(f"Error analyzing {ticker}: {e}")

if __name__ == "__main__":
    test_engine()
