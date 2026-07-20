"""
Regression tests for whale_stalker_engine.py's dead OFI/block-trade detection
(2026-07-20).

Two compounding bugs found:

1. core/legacy.py's start_whale_stalker() worker called
   `ws.run_scan(quotes)` with no `recent_trades` argument — ever. Since
   run_scan()'s "Trade Flow Analysis (OFI + Blocks)" branch is gated on
   `if recent_trades:`, that entire code path (analyze_blocks +
   get_ofi_signal) was permanently dead in production; only the naive
   volume-vs-average INSTITUTIONAL_FOOTPRINT alert ever fired.

2. Even when fed real trades, calculate_ofi()'s buy/sell classification
   (`t.get('price') >= t.get('mid', 0)`) silently broke on real trade prints
   that don't carry a 'mid' field (e.g. Polygon's /v3/trades, which has no
   'side' or 'mid' key at all) — `t.get('mid', 0)` defaults to 0, so
   `price >= 0` is true for every trade with a positive price, meaning
   EVERY trade was classified as a buy regardless of actual side. OFI would
   always read as maximally bullish whenever there was any volume at all.

This test drives the real, unmodified calculate_ofi() with realistic trade
sequences that have no 'side'/'mid' fields (mirroring what
data_providers.PolygonProvider.get_recent_trades() now actually returns),
and drives run_scan() end-to-end proving the OFI/block branch now executes
when trades are supplied.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whale_stalker_engine import WhaleStalkerEngine  # noqa: E402


def _tape(prices_and_sizes):
    """Real-shape trade prints: price + size + timestamp only, no side/mid —
    exactly what PolygonProvider.get_recent_trades() returns."""
    return [
        {"price": p, "size": s, "timestamp": i}
        for i, (p, s) in enumerate(prices_and_sizes)
    ]


def test_calculate_ofi_no_longer_classifies_every_trade_as_a_buy():
    """The old `price >= mid_default_0` logic made this always +30 (all-buy).
    A tape with more down-ticks than up-ticks must now read net negative."""
    # 100 (baseline) -> 99 (downtick=SELL,10) -> 98 (downtick=SELL,10) -> 99 (uptick=BUY,10)
    trades = _tape([(100, 5), (99, 10), (98, 10), (99, 10)])
    ofi = WhaleStalkerEngine(None).calculate_ofi(trades)
    # first trade has no prior price -> classified buy (+5); then two downticks (-10,-10); then one uptick (+10)
    assert ofi == 5 - 10 - 10 + 10, ofi
    assert ofi < 0, "tape with more real selling pressure than buying must read net negative"
    print(f"PASS: calculate_ofi() on a side-less real tape correctly reads net negative — ofi={ofi}")


def test_calculate_ofi_pure_uptick_tape_is_positive():
    trades = _tape([(100, 10), (101, 10), (102, 10)])
    ofi = WhaleStalkerEngine(None).calculate_ofi(trades)
    assert ofi == 30, ofi  # every trade an uptick (or the seed trade) -> all buy
    print(f"PASS: pure uptick tape reads fully bullish — ofi={ofi}")


def test_calculate_ofi_zero_tick_inherits_prior_side():
    # 100 -> 101 (uptick=BUY) -> 101 (zero-tick, inherits BUY) -> 99 (downtick=SELL)
    trades = _tape([(100, 10), (101, 10), (101, 10), (99, 10)])
    ofi = WhaleStalkerEngine(None).calculate_ofi(trades)
    assert ofi == 10 + 10 + 10 - 10, ofi
    print(f"PASS: zero-tick trades correctly inherit the prior trade's side — ofi={ofi}")


def test_calculate_ofi_explicit_side_still_overrides_tick_rule():
    """Callers that already have a real side field (e.g. the module's own
    __main__ self-test) must not be broken by the tick-rule rewrite."""
    trades = [
        {"price": 175.5, "size": 10000, "side": "buy"},
        {"price": 175.52, "size": 50000, "side": "buy"},
        {"price": 175.48, "size": 2000, "side": "sell"},
    ]
    ofi = WhaleStalkerEngine(None).calculate_ofi(trades)
    assert ofi == 10000 + 50000 - 2000, ofi
    print(f"PASS: explicit side field still wins over the tick rule — ofi={ofi}")


def test_run_scan_ofi_and_block_branch_now_actually_executes_when_fed_trades():
    """End-to-end: run_scan() must produce OFI_RESONANCE / block alerts when
    given real trades — the exact branch that was permanently unreachable
    while core/legacy.py never passed recent_trades at all."""
    ws = WhaleStalkerEngine(None)
    quotes = {"TSLA": {"price": 175.5, "volume": 1000000, "avg_volume": 1000000}}
    # Heavy, consistently-upticking real tape -> imbalance far over the 40% OFI threshold,
    # plus one $8.7M print well over the megalodon threshold.
    trades = {"TSLA": _tape([
        (175.0, 1000), (175.1, 1000), (175.2, 1000), (175.3, 1000),
        (175.4, 50000),  # ~$8.77M block, all upticks so far
    ])}

    results = ws.run_scan(quotes, trades)

    types = {r["type"] for r in results}
    assert "OFI_RESONANCE" in types, results
    assert "MEGALODON_BLOCK" in types, results
    ofi_alert = next(r for r in results if r["type"] == "OFI_RESONANCE")
    assert ofi_alert["side"] == "BULLISH", ofi_alert
    print(f"PASS: run_scan() with real trades supplied now produces OFI + block alerts — {types}")


def test_run_scan_without_trades_still_only_reports_footprint_not_a_crash():
    """Backward-compat: run_scan(quotes) with no trades arg must not crash —
    this was the only path that ever actually ran in production before the fix."""
    ws = WhaleStalkerEngine(None)
    quotes = {"TSLA": {"price": 175.5, "volume": 5000000, "avg_volume": 1000000}}
    results = ws.run_scan(quotes)
    types = {r["type"] for r in results}
    assert types == {"INSTITUTIONAL_FOOTPRINT"}, results
    print("PASS: run_scan() with no trades supplied degrades gracefully (no OFI/block alerts, no crash)")


if __name__ == "__main__":
    test_calculate_ofi_no_longer_classifies_every_trade_as_a_buy()
    test_calculate_ofi_pure_uptick_tape_is_positive()
    test_calculate_ofi_zero_tick_inherits_prior_side()
    test_calculate_ofi_explicit_side_still_overrides_tick_rule()
    test_run_scan_ofi_and_block_branch_now_actually_executes_when_fed_trades()
    test_run_scan_without_trades_still_only_reports_footprint_not_a_crash()
    print("\nAll regression tests passed.")
