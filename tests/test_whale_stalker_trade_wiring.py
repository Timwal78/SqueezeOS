"""
Regression test for core/legacy.py's _collect_whale_stalker_trades() (2026-07-20).

This is the other half of the whale-stalker OFI fix: start_whale_stalker()'s
worker used to call `ws.run_scan(quotes)` with no recent_trades argument at
all, ever — so even after fixing calculate_ofi()'s broken tick classification
(see tests/test_whale_stalker_ofi.py), nothing would change in production
unless something actually fetched real trades and passed them through.

Proves: (1) it's a real no-op (returns {}) when Polygon isn't configured —
no fabricated trades, no crash; (2) when Polygon is available, it only pulls
trades for symbols that actually tripped the volume-footprint condition, not
the whole universe; (3) it respects WHALE_STALKER_MAX_TRADE_LOOKUPS so a busy
market day can't monopolize the shared PolygonRateGuard budget.
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.legacy as legacy  # noqa: E402


def _quotes(footprint_syms, quiet_syms):
    q = {}
    for sym in footprint_syms:
        q[sym] = {"volume": 5_000_000, "avg_volume": 1_000_000}  # 5x -> tripped
    for sym in quiet_syms:
        q[sym] = {"volume": 900_000, "avg_volume": 1_000_000}    # below threshold
    return q


def test_no_polygon_configured_returns_empty_no_fabrication():
    dm = MagicMock()
    dm.polygon.available = False
    result = legacy._collect_whale_stalker_trades(_quotes(["TSLA"], ["AAPL"]), dm)
    assert result == {}
    print("PASS: no Polygon configured -> empty dict, no fake trades")


def test_dm_none_returns_empty():
    result = legacy._collect_whale_stalker_trades(_quotes(["TSLA"], []), None)
    assert result == {}
    print("PASS: dm=None (DataManager not yet initialized) -> empty dict, no crash")


def test_only_footprint_symbols_get_real_trade_lookups():
    dm = MagicMock()
    dm.polygon.available = True
    dm.polygon.get_recent_trades.return_value = [{"price": 100.0, "size": 10, "timestamp": 1}]

    quotes = _quotes(footprint_syms=["TSLA"], quiet_syms=["AAPL", "MSFT"])
    result = legacy._collect_whale_stalker_trades(quotes, dm)

    assert set(result.keys()) == {"TSLA"}, result
    called_symbols = [c.args[0] for c in dm.polygon.get_recent_trades.call_args_list]
    assert called_symbols == ["TSLA"], called_symbols
    print(f"PASS: only the volume-footprint symbol got a real trade lookup — {called_symbols}")


def test_lookup_count_is_capped_at_the_configured_max():
    dm = MagicMock()
    dm.polygon.available = True
    dm.polygon.get_recent_trades.return_value = [{"price": 100.0, "size": 10, "timestamp": 1}]

    many_footprint_syms = [f"SYM{i}" for i in range(10)]
    quotes = _quotes(footprint_syms=many_footprint_syms, quiet_syms=[])
    result = legacy._collect_whale_stalker_trades(quotes, dm)

    assert len(result) <= legacy.WHALE_STALKER_MAX_TRADE_LOOKUPS, result
    assert dm.polygon.get_recent_trades.call_count == legacy.WHALE_STALKER_MAX_TRADE_LOOKUPS
    print(f"PASS: capped at WHALE_STALKER_MAX_TRADE_LOOKUPS={legacy.WHALE_STALKER_MAX_TRADE_LOOKUPS} "
          f"even with {len(many_footprint_syms)} qualifying symbols")


if __name__ == "__main__":
    test_no_polygon_configured_returns_empty_no_fabrication()
    test_dm_none_returns_empty()
    test_only_footprint_symbols_get_real_trade_lookups()
    test_lookup_count_is_capped_at_the_configured_max()
    print("\nAll regression tests passed.")
