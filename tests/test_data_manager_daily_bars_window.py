"""
Regression test: DataManager.get_bars() must request enough CALENDAR days
from Tradier to actually return close to the requested `limit` TRADING-day
bars for daily timeframes.

Before this fix, the daily branch passed `limit + 10` straight through as
tradier_api.get_history_df()'s `days` param, which is CALENDAR days. A
caller asking for limit=300 daily bars (the default for breakout_scanner.py,
sr_matrix_scanner.py, cie_scanner.py) actually got back only ~200-215 real
NYSE trading closes -- silently less history than every daily-bar caller
believed it was getting, with no error (`.tail(limit)` just returns fewer
rows). Same root-cause bug class as avg_down_engine._fetch_closes(), where
an exact-threshold guard turned this into CASCADE's live scanner never
firing a signal at all -- here it's a quieter data-quality degradation
rather than a hard failure.

This drives the real, unmodified DataManager.get_bars(), mocking only
tradier_api.get_history_df() to return a realistic NYSE business-day
DataFrame for whatever calendar window it's actually asked for.
"""
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import tradier_api  # noqa: E402
from data_providers import DataManager  # noqa: E402

_HOLIDAYS_PER_YEAR = 9.5


def _fake_get_history_df(symbol, days=100, interval="daily"):
    end = date.today()
    start = end - timedelta(days=days + 10)
    idx = pd.bdate_range(start=start, end=end)
    holidays_to_drop = round(len(idx) / 365 * _HOLIDAYS_PER_YEAR)
    idx = idx[holidays_to_drop:]
    df = pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0},
        index=idx,
    )
    return df


def test_get_bars_returns_close_to_requested_limit():
    dm = DataManager.__new__(DataManager)  # skip provider __init__ side effects
    with patch.object(tradier_api, "get_history_df", side_effect=_fake_get_history_df):
        bars = dm.get_bars("NVDA", timeframe="1D", limit=300)

    assert bars, "get_bars() returned no bars at all"
    # Allow a small margin below the requested limit (holiday-count estimate is
    # approximate) but this must NOT reproduce the ~30% shortfall the bug caused.
    assert len(bars) >= 280, (
        f"get_bars(limit=300) returned only {len(bars)} bars -- "
        "the calendar-vs-trading-day fetch window is under-sized again"
    )
    print(f"PASS: get_bars(limit=300) returned {len(bars)} bars")


if __name__ == "__main__":
    test_get_bars_returns_close_to_requested_limit()
    print("\nAll regression tests passed.")
