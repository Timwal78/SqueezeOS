import sys
import json
from core.legacy import get_service
from core.convergence_engine import ConvergenceEngine
from core.api.convergence_bp import _fetch_bars
from core.counsel_agent import generate_ai_counsel

def run_test(symbol):
    dm = get_service("dm")
    closes, volumes, bars = _fetch_bars(dm, symbol)
    engine = ConvergenceEngine()
    result = engine.analyze(symbol, closes, volumes, bars_with_dates=bars, run_sniper=True)
    counsel = generate_ai_counsel(result)
    print(counsel)

if __name__ == "__main__":
    run_test("GME")
    print("-" * 50)
    run_test("AMC")
