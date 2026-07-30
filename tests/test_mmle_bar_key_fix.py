"""
Regression test for the live MMLE 'close' KeyError found in production logs
2026-07-30 (market open): every single IAM obligation resolution logged
"[IAM] MMLE fetch failed for {symbol}: 'close'" during real Tradier-live
trading, with zero exceptions across 26+ symbols in one scan pass.

Root cause: data_providers.DataManager.get_bars() returns a DIFFERENT bar
shape depending which provider actually served the data -- Tradier and
Alpaca's raw REST bars use abbreviated keys (c/h/l/v), Polygon's wrapper
translates to full words (close/high/low/volume). mmle_engine.py's
MMLeEngine.analyze() hardcoded b["close"]/b["high"]/b["low"]/b["volume"],
which only ever worked when Polygon happened to be the active source.

Consequence (bounded, not the AVTR-class garbage-price bug): the exception
was caught by iam_engine.py's _fetch_mmle() and turned into vpin=0.0 on every
call -- a valid in-range VPIN value, so no price/quantity was corrupted, but
the dark-pool-toxicity term of every live "Stress: X%" obligation score was
silently missing, with no disclosure, for as long as this was live.

This test proves the bug against the OLD single-key logic, then proves the
fix against the REAL, unmodified MMLeEngine.analyze().
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmle_engine import MMLeEngine  # noqa: E402


def _tradier_shaped_bars(n=60, start=100.0):
    """Exact shape data_providers.py's Tradier branch returns:
    {"date","o","h","l","c","v"} -- no "close" key anywhere."""
    bars = []
    px = start
    for i in range(n):
        px += 0.1
        bars.append({"date": f"2026-06-{(i % 28) + 1:02d}", "o": px - 0.05,
                     "h": px + 0.2, "l": px - 0.2, "c": px, "v": 1_000_000 + i})
    return bars


def _alpaca_shaped_bars(n=60, start=100.0):
    """Exact shape Alpaca's raw REST response uses (untranslated pass-through
    in data_providers.py's AlpacaProvider.get_historical_bars)."""
    bars = []
    px = start
    for i in range(n):
        px += 0.1
        bars.append({"t": f"2026-06-{(i % 28) + 1:02d}T00:00:00Z", "o": px - 0.05,
                     "h": px + 0.2, "l": px - 0.2, "c": px, "v": 1_000_000 + i,
                     "n": 500, "vw": px})
    return bars


def _polygon_shaped_bars(n=60, start=100.0):
    """Exact shape data_providers.py's get_aggregates() wrapper returns --
    the ONE shape the old hardcoded b["close"] actually worked against."""
    bars = []
    px = start
    for i in range(n):
        px += 0.1
        bars.append({"timestamp": 1700000000 + i * 86400, "open": px - 0.05,
                     "high": px + 0.2, "low": px - 0.2, "close": px,
                     "volume": 1_000_000 + i, "vwap": px})
    return bars


def test_bug_reproduced_against_old_single_key_logic():
    """Faithfully reproduces the exact code that was live in production
    (hardcoded b["close"]) and shows it raises KeyError on Tradier- and
    Alpaca-shaped bars -- the two providers actually configured on this
    deployment (sources_tradier=True in the live market-scanner log)."""
    for label, bars in (("tradier", _tradier_shaped_bars()),
                        ("alpaca", _alpaca_shaped_bars())):
        raised = False
        try:
            _ = [float(b["close"]) for b in bars]  # the OLD line, verbatim
        except KeyError as e:
            raised = True
            assert str(e) == "'close'", f"unexpected KeyError: {e}"
        assert raised, (
            f"expected the old hardcoded b['close'] to KeyError on "
            f"{label}-shaped bars, but it didn't")
        print(f"PASS (bug reproduced): old logic raises KeyError: 'close' "
              f"on {label}-shaped bars, matching the live production log")


def test_fix_handles_all_three_provider_shapes():
    """The real, unmodified MMLeEngine.analyze() must now succeed on every
    bar shape DataManager.get_bars() can actually return."""
    engine = MMLeEngine()
    for label, bars in (("tradier", _tradier_shaped_bars()),
                        ("alpaca", _alpaca_shaped_bars()),
                        ("polygon", _polygon_shaped_bars())):
        result = engine.analyze(f"TEST_{label.upper()}", bars)
        assert result.get("symbol") == f"TEST_{label.upper()}"
        assert "state" in result and result["state"] in (
            "NEUTRAL", "COMPRESSED", "TNT_LONG", "TNT_SHORT"), result
        # The composite/magnet fields prove closes/highs/lows/volumes were
        # actually parsed as real floats, not silently zeroed -- a magnet
        # (VWAP proxy = avg close) near 0 would mean every close came back 0.
        assert result.get("magnet") and result["magnet"] > 50, (
            f"{label}: magnet={result.get('magnet')!r} -- closes were not "
            f"parsed correctly")
        print(f"PASS (fix verified): analyze() succeeds on {label}-shaped "
              f"bars, magnet={result['magnet']:.2f}")


def test_vpin_no_longer_silently_zeroed_on_tradier_or_alpaca_bars():
    """Directly closes the loop on the actual live symptom: iam_engine.py's
    _fetch_vpin() reads mmle_result.get('vpin') and falls back to 0.0 only
    when the dict is empty (i.e. only when analyze() raised). Before the fix,
    that fallback fired on every Tradier/Alpaca-sourced call; after the fix,
    analyze() returns a real vpin (possibly None if VPIN itself has
    insufficient bars, but the dict is populated, not empty)."""
    engine = MMLeEngine()
    for label, bars in (("tradier", _tradier_shaped_bars()),
                        ("alpaca", _alpaca_shaped_bars())):
        result = engine.analyze(f"TEST_{label.upper()}", bars)
        assert result != {}, f"{label}: analyze() returned {{}} -- still broken"
        assert "vpin" in result, f"{label}: no vpin key in a real result"
    print("PASS: MMLE result dict is populated (not {}) on Tradier- and "
          "Alpaca-shaped bars, so iam_engine._fetch_vpin() no longer silently "
          "falls back to 0.0 on every call")


if __name__ == "__main__":
    test_bug_reproduced_against_old_single_key_logic()
    test_fix_handles_all_three_provider_shapes()
    test_vpin_no_longer_silently_zeroed_on_tradier_or_alpaca_bars()
    print("\nAll tests passed.")
