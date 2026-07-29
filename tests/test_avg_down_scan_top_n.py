"""
Regression test: avg_down_engine._get_symbols() must respect a
configurable AVG_DOWN_SCAN_TOP_N env var instead of a hardcoded [:40]
slice, matching the pattern every other scanner in this codebase already
uses (BREAKOUT_SCAN_TOP_N, SR_MATRIX_SCAN_TOP_N, DRUCK_SCAN_TOP_N,
CIE_SCAN_TOP_N, GAMMA_PIN_SCAN_TOP_N, IMO_SCAN_TOP_N, ORB_SCAN_TOP_N,
MM_INTEL_SCAN_TOP_N, IAM_SCAN_TOP_N).

CASCADE (avg_down_engine.py) was the one live-wired engine whose ticker
universe could not be widened without a code change -- everything else
was already operator-configurable via Render env vars. Per operator
directive (2026-07-29: "find and profit off of every squeeze play we can,
no cap on a daily basis, many stock tickers"), this closes that gap:
AVG_DOWN_SCAN_TOP_N now controls how many top-volume symbols CASCADE's
scanner considers per pass, with 0/negative meaning unlimited (every
symbol the market scanner currently has quoted).

This drives the real, unmodified _get_symbols(), mocking only the market
scanner's cache dict (the true I/O boundary).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import avg_down_engine as cascade  # noqa: E402


def _fake_quotes(n):
    return {f"SYM{i:03d}": {"volRatio": float(n - i)} for i in range(n)}


def test_default_caps_at_40():
    quotes = _fake_quotes(100)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AVG_DOWN_SYMBOLS", None)
        os.environ.pop("AVG_DOWN_SCAN_TOP_N", None)
        with patch("core.api.market_scanner._scan_cache", {"quotes": quotes}), \
             patch("core.api.market_scanner._scan_lock"):
            syms = cascade._get_symbols()
    assert len(syms) == 40, f"expected default cap of 40, got {len(syms)}"
    print("PASS: default AVG_DOWN_SCAN_TOP_N caps at 40 (backward compatible)")


def test_env_override_widens_universe():
    quotes = _fake_quotes(100)
    with patch.dict(os.environ, {"AVG_DOWN_SCAN_TOP_N": "75"}, clear=False):
        os.environ.pop("AVG_DOWN_SYMBOLS", None)
        with patch("core.api.market_scanner._scan_cache", {"quotes": quotes}), \
             patch("core.api.market_scanner._scan_lock"):
            syms = cascade._get_symbols()
    assert len(syms) == 75, f"expected AVG_DOWN_SCAN_TOP_N=75 to widen to 75, got {len(syms)}"
    print("PASS: AVG_DOWN_SCAN_TOP_N=75 widens the scan universe correctly")


def test_zero_means_unlimited():
    quotes = _fake_quotes(100)
    with patch.dict(os.environ, {"AVG_DOWN_SCAN_TOP_N": "0"}, clear=False):
        os.environ.pop("AVG_DOWN_SYMBOLS", None)
        with patch("core.api.market_scanner._scan_cache", {"quotes": quotes}), \
             patch("core.api.market_scanner._scan_lock"):
            syms = cascade._get_symbols()
    assert len(syms) == 100, f"expected AVG_DOWN_SCAN_TOP_N=0 to mean unlimited (100), got {len(syms)}"
    print("PASS: AVG_DOWN_SCAN_TOP_N=0 means unlimited -- every quoted symbol considered")


def test_avg_down_symbols_still_takes_priority():
    with patch.dict(os.environ, {"AVG_DOWN_SYMBOLS": "GME,AMC", "AVG_DOWN_SCAN_TOP_N": "5"}, clear=False):
        syms = cascade._get_symbols()
    assert syms == ["GME", "AMC"], f"explicit AVG_DOWN_SYMBOLS should override the scanner entirely, got {syms}"
    print("PASS: AVG_DOWN_SYMBOLS explicit override still takes priority over AVG_DOWN_SCAN_TOP_N")


if __name__ == "__main__":
    test_default_caps_at_40()
    test_env_override_widens_universe()
    test_zero_means_unlimited()
    test_avg_down_symbols_still_takes_priority()
    print("\nAll regression tests passed.")
