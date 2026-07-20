"""
Regression test for orb_engine.py's inverted `mm_position` display label
(2026-07-20).

compute_series()'s own docstring and BUY/SELL logic are unambiguous about
the sign convention: `mm_position = -(buy_flow - sell_flow)` — negative
means dealers are net SHORT (aggressive buying pressure was absorbed by
dealers selling into it), positive means dealers are net LONG. `inv_z` is
the Kalman-smoothed z-score of that same series, so it must carry the same
sign. The BUY signal fires exactly when `inv_z <= -z_critical` (dealers
deeply short, must cover by buying — see the docstring: "BUY = ... while
inventory z ≤ −z_critical"), yet the state dict's `mm_position` label used
to read `"LONG"` for negative inv_z and `"SHORT"` for positive — backwards,
contradicting the very code three lines above it and the sibling
implementation in gamma_flow_engine.py (`critical_short` → recommend LONG
because "MM must buy", i.e. negative inventory z = dealers short).

This drives the real, unmodified compute_series() end-to-end with crafted
real-shape intraday bars that produce genuine BUY and SELL signals, and
proves the `mm_position` label now matches the dealer state that actually
triggered each signal.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orb_engine import OrbParams, compute_series  # noqa: E402

_OPEN = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)  # 9:30 ET (DST)


def _bar(i, o, h, l, c, v):
    return {
        "date": (_OPEN + timedelta(minutes=i)).isoformat(),
        "open": o, "high": h, "low": l, "close": c, "volume": v,
    }


def _params():
    # Small inv_lookback so the test doesn't need hundreds of bars; z_critical
    # relaxed slightly since the synthetic outlier is deliberately extreme.
    return OrbParams(or_minutes=15, inv_lookback=20, z_critical=1.0,
                      min_price=1.0, lam=0.15, q_process=0.5, r_measurement=1.0)


def test_buy_signal_correctly_labels_dealers_short_not_long():
    bars = []
    # Opening range: 15 flat bars at 100 -> or_h = or_l = 100
    for i in range(15):
        bars.append(_bar(i, 100, 100, 100, 100, 100))
    # Flat bars to populate the Kalman inventory history with a stable baseline
    for i in range(15, 34):
        bars.append(_bar(i, 100, 100, 100, 100, 100))
    # One violent up-bar: heavy real buying -> dealers absorb it -> deeply
    # short -> also breaks above the OR high -> should fire BUY.
    bars.append(_bar(34, 100, 105, 100, 104, 100_000))

    result = compute_series(bars, _params())
    state = result["state"]

    assert state["signal"] == "BUY", state
    assert state["inventory_z"] < -1.0, state
    assert state["mm_position"] == "SHORT", (
        "dealers who absorbed the buying that triggered this BUY signal "
        f"must be labeled SHORT, not {state['mm_position']!r}"
    )
    print(f"PASS: BUY signal correctly paired with mm_position=SHORT — state={state}")


def test_sell_signal_correctly_labels_dealers_long_not_short():
    bars = []
    for i in range(15):
        bars.append(_bar(i, 100, 100, 100, 100, 100))
    for i in range(15, 34):
        bars.append(_bar(i, 100, 100, 100, 100, 100))
    # One violent down-bar: heavy real selling -> dealers absorb it (buy) ->
    # deeply long -> also breaks below the OR low -> should fire SELL.
    bars.append(_bar(34, 100, 100, 95, 96, 100_000))

    result = compute_series(bars, _params())
    state = result["state"]

    assert state["signal"] == "SELL", state
    assert state["inventory_z"] > 1.0, state
    assert state["mm_position"] == "LONG", (
        "dealers who absorbed the selling that triggered this SELL signal "
        f"must be labeled LONG, not {state['mm_position']!r}"
    )
    print(f"PASS: SELL signal correctly paired with mm_position=LONG — state={state}")


def test_balanced_label_for_near_zero_inventory_z():
    bars = [_bar(i, 100, 100, 100, 100, 100) for i in range(40)]
    result = compute_series(bars, _params())
    state = result["state"]
    assert state["signal"] is None, state
    assert state["mm_position"] == "BALANCED", state
    print(f"PASS: flat/no-flow tape correctly labeled BALANCED — state={state}")


if __name__ == "__main__":
    test_buy_signal_correctly_labels_dealers_short_not_long()
    test_sell_signal_correctly_labels_dealers_long_not_short()
    test_balanced_label_for_near_zero_inventory_z()
    print("\nAll regression tests passed.")
