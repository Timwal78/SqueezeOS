import os
import sys

from data_providers import DataManager

dm = DataManager()
print(f"Alpaca available: {dm.alpaca.available}")
print(f"Polygon available: {dm.polygon.available}")

bars = dm.get_bars("AMC", timeframe="1D", limit=400)
print(f"Fetched {len(bars)} bars for AMC via get_bars")
