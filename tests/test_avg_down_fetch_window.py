"""
Regression test: avg_down_engine._fetch_closes() must request enough
CALENDAR days from Tradier to reliably return at least BARS_NEEDED trading
closes -- the actual daily-bar count _compute_layers() needs to satisfy its
`len(closes) >= layers[-1]` (365, for the default 5-EMA L5 anchor) guard.

Before this fix, _fetch_closes() passed BARS_NEEDED + 20 (420) straight
through as `days` to tradier_api.get_history_df(), whose `days` parameter is
CALENDAR days (see tradier_api.py: `start = end - timedelta(days=days+10)`).
A 430-calendar-day window only contains ~296-307 actual NYSE trading days
(weekends + ~10 market holidays/year removed) -- always short of the 365
bars _compute_layers() requires. That meant CASCADE's live scanner could
never produce a single ENTER/ADD/EXIT/STOP signal in production, even though
tests/backtest_engines.py had already shown the underlying _evaluate() math
to be profitable -- that backtest calls _evaluate() directly with real CSV
bars and never exercises this fetch path at all.

This test drives the real, unmodified _fetch_closes(), mocking only
tradier_api.get_history_df() to return a realistic NYSE-calendar business-day
DataFrame for whatever date range it's actually asked for -- proving the
fix requests a wide enough window rather than asserting an implementation
detail of the conversion math.
"""
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import avg_down_engine as cascade  # noqa: E402

# Rough US market holiday rate used only to build a realistic fake calendar
# for this test -- not a claim about the exact real holiday count.
_HOLIDAYS_PER_YEAR = 9.5


def _fake_get_history_df(symbol, days=100, interval="daily"):
    """Simulate Tradier: given a CALENDAR-day window, return only real NYSE
    business-day rows within it (weekends + a proportional holiday count
    removed), exactly like the real bug this test guards against."""
    end = date.today()
    start = end - timedelta(days=days + 10)  # mirrors tradier_api.py's own +10 buffer
    idx = pd.bdate_range(start=start, end=end)  # business days only (no weekends)
    holidays_to_drop = round(len(idx) / 365 * _HOLIDAYS_PER_YEAR)
    idx = idx[holidays_to_drop:]  # drop from the front -- doesn't matter which end for a count check
    df = pd.DataFrame({"Close": range(len(idx))}, index=idx)
    df.columns = ["close"]
    return df


def test_fetch_closes_returns_enough_bars_for_l5_ema():
    with patch.dict(sys.modules, {}):
        import tradier_api
        with patch.object(tradier_api, "get_history_df", side_effect=_fake_get_history_df):
            closes = cascade._fetch_closes("NVDA")

    layers = cascade._load_layers()
    needed = layers[-1]  # 365 by default (AVG_DOWN_EMA_CSV's largest period)
    assert len(closes) >= needed, (
        f"_fetch_closes() returned {len(closes)} bars, need >= {needed} for the L5 EMA -- "
        "the calendar-vs-trading-day fetch window is under-sized again"
    )
    print(f"PASS: _fetch_closes() returned {len(closes)} bars (>= {needed} required)")


def test_compute_layers_succeeds_on_fetched_window():
    """End-to-end: the actual bars _fetch_closes() returns must be enough for
    _compute_layers() to return real EMA values instead of None (which is
    what silently killed every live CASCADE evaluation before this fix)."""
    with patch.dict(sys.modules, {}):
        import tradier_api
        with patch.object(tradier_api, "get_history_df", side_effect=_fake_get_history_df):
            closes = cascade._fetch_closes("NVDA")

    lv = cascade._compute_layers(closes)
    assert lv is not None, "_compute_layers() returned None -- _evaluate() would never fire a signal"
    assert set(lv.keys()) == {"L1", "L2", "L3", "L4", "L5"}
    print("PASS: _compute_layers() returns real EMA values from the fetched window")


if __name__ == "__main__":
    test_fetch_closes_returns_enough_bars_for_l5_ema()
    test_compute_layers_succeeds_on_fetched_window()
    print("\nAll regression tests passed.")
