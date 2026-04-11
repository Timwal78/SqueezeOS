import pandas as pd
import numpy as np
from sml_engine import SMLEngine, SMLRegime, SMLLifecycle

def mock_history(symbol, length=220, trend=0.0, volatility=1.0, close_val=100.0):
    prices = [close_val]
    for _ in range(length - 1):
        ret = np.random.normal(trend / 252.0, volatility / np.sqrt(252.0))
        prices.append(prices[-1] * (1 + ret))
    
    df = pd.DataFrame({
        'close': pd.Series(prices),
        'high': pd.Series(prices) * 1.01,
        'low': pd.Series(prices) * 0.99,
        'volume': pd.Series([1000000] * length)
    })
    return df

def test_engine_scenarios():
    engine = SMLEngine()
    symbols = ["SPY", "VIX", "TLT", "DXY", "QQQ", "IWM", "IJR", "XRT", "AMC"]
    
    print("Scenario 1: Squeeze Setup (AMC)")
    market_history = {s: mock_history(s) for s in symbols}
    
    # Force a squeeze setup for AMC
    # High compression (low BB width), neutral target_rs_spy, neutral basket_score, not extended.
    # In sml_engine.py: squeeze_setup = compression_score > 0.65 and target_rs_spy > -0.05 and basket_score > -0.20 and target_stretch < 0.95
    
    results = engine.compute_all("AMC", market_history)
    
    if results:
        print(f"  Symbol: {results['symbol']}")
        print(f"  Regime: {results['regime_text']} ({results['regime']})")
        print(f"  Lifecycle: {results['lifecycle_text']} ({results['lifecycle']})")
        print(f"  Precursor Score: {results['precursor_score']}")
        print(f"  Squeeze Score: {results['squeeze_score']}")
        print(f"  Net Pressure: {results['net_pressure']}")
        print(f"  Decision: {results['decision']}")
    else:
        print("  Failed to compute results")

if __name__ == "__main__":
    test_engine_scenarios()
