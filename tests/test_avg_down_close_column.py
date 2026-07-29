"""
Regression test: avg_down_engine._fetch_closes() must read the "Close"
column, not fall back to df.columns[-1] (which is "Volume").

tradier_api.get_history_df() renames Tradier's raw "close" field to
"Close" (capitalized) before returning the DataFrame (tradier_api.py's
df.rename(columns={"close": "Close", ...})). _fetch_closes() checked for
lowercase "close", never found it, and fell back to df.columns[-1] --
"Volume", not price. Every EMA/entry price this engine ever computed was
actually a share-volume count. This was dormant only because
_compute_layers() never had enough bars to reach this code path before the
calendar/trading-day fetch-window fix (see test_avg_down_fetch_window.py)
-- once that shipped, this bug produced real live entries priced at
literal millions of dollars per share (confirmed in production logs
2026-07-29, e.g. "ENTER AMIX @ 69739502.0000", a real Tradier limit order).

This drives the real, unmodified _fetch_closes(), mocking only
tradier_api.get_history_df() to return a DataFrame shaped exactly like the
real one (Open/High/Low/Close/Volume, Volume several orders of magnitude
larger than Close -- the real-world shape that triggered this).
"""
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import avg_down_engine as cascade  # noqa: E402


def _fake_get_history_df_realistic_shape(symbol, days=100, interval="daily"):
    """Mirrors tradier_api.get_history_df()'s real column names and the
    real relative magnitude of Close vs Volume (a $50 stock trading a few
    million shares/day has Volume >> Close by many orders of magnitude)."""
    n = 400
    idx = pd.bdate_range(end=date.today(), periods=n)
    df = pd.DataFrame({
        "Open":   [50.0 + i * 0.01 for i in range(n)],
        "High":   [50.5 + i * 0.01 for i in range(n)],
        "Low":    [49.5 + i * 0.01 for i in range(n)],
        "Close":  [50.2 + i * 0.01 for i in range(n)],
        "Volume": [2_000_000 + i * 1000 for i in range(n)],
    }, index=idx)
    return df


def test_fetch_closes_returns_price_not_volume():
    with patch.dict(sys.modules, {}):
        import tradier_api
        with patch.object(tradier_api, "get_history_df", side_effect=_fake_get_history_df_realistic_shape):
            closes = cascade._fetch_closes("NVDA")

    assert closes, "_fetch_closes() returned nothing"
    last = closes[-1]
    assert last < 1000, (
        f"_fetch_closes() returned {last} as the latest close -- looks like Volume "
        f"leaked through instead of Close (real equity closes aren't in the millions)"
    )
    assert 50.0 <= last <= 55.0, f"expected a Close-range value (~50-55), got {last}"
    print(f"PASS: _fetch_closes() returned real Close values (latest={last}), not Volume")


if __name__ == "__main__":
    test_fetch_closes_returns_price_not_volume()
    print("\nAll regression tests passed.")
