"""
Tests for the 2026-07-30 live-arming changes to squeeze_fuel_scanner.py --
the "1 buy for now" real, self-healing open-position cap -- and for
options_anomaly_engine.py's new get_recent_anomaly() query function.

Real, unmodified code; only true I/O boundaries (tradier_api.get_position,
iam_executor.execute_async/PAPER_MODE, options_anomaly_engine's internal
state which is set up directly rather than mocked since it's just a dict)
are mocked/seeded.
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import options_anomaly_engine as oae  # noqa: E402


def test_get_recent_anomaly_returns_within_window():
    oae._last_anomaly.clear()
    oae._last_anomaly["SPY"] = {"anomaly_type": "WHALE_PRINT", "severity": "CRITICAL", "ts": time.time()}
    hit = oae.get_recent_anomaly("spy", max_age_s=1800)  # lowercase input must still match
    assert hit is not None
    assert hit["anomaly_type"] == "WHALE_PRINT"
    print("PASS: get_recent_anomaly finds a fresh real anomaly, case-insensitive symbol lookup")


def test_get_recent_anomaly_expires_outside_window():
    oae._last_anomaly.clear()
    oae._last_anomaly["SPY"] = {"anomaly_type": "WHALE_PRINT", "severity": "CRITICAL", "ts": time.time() - 3600}
    hit = oae.get_recent_anomaly("SPY", max_age_s=1800)
    assert hit is None
    print("PASS: get_recent_anomaly correctly expires a stale anomaly outside the window")


def test_get_recent_anomaly_none_when_never_scanned():
    oae._last_anomaly.clear()
    hit = oae.get_recent_anomaly("NEVERSCANNED")
    assert hit is None
    print("PASS: get_recent_anomaly honestly returns None for a symbol it has never flagged")


def test_prune_open_symbols_self_heals_on_real_flat_position():
    import squeeze_fuel_scanner as sfs
    sfs._open_symbols.clear()
    sfs._open_symbols.add("GME")
    sfs._open_symbols.add("AMC")

    def fake_get_position(sym):
        if sym == "GME":
            return {"quantity": 5}  # still real and open
        return {"quantity": 0}  # AMC is flat now -- e.g. a stop-loss closed it

    with patch("tradier_api.get_position", side_effect=fake_get_position):
        sfs._prune_open_symbols()

    assert sfs._open_symbols == {"GME"}
    print("PASS: prune self-heals -- a symbol the real account shows flat is dropped, real open one stays")


def test_cap_blocks_second_symbol_when_at_limit():
    import squeeze_fuel_scanner as sfs
    sfs._open_symbols.clear()
    sfs._open_symbols.add("GME")
    sfs._MAX_OPEN = 1

    fake_result = {
        "action": "BUY", "composite_score": 90.0,
        "ignition": {"score": 40}, "ftd_fuel": {"score": 20, "on_reg_sho_threshold_list": False},
        "short_volume_fuel": {"score": 20}, "gamma_amplifier": {"score": 10, "regime": "short_gamma"},
        "rsi_confirmation": {"value": 55.0, "cross_level": 50.0},
        "flow_confirmation": {"anomaly_type": "WHALE_PRINT", "severity": "CRITICAL"},
        "direction": "BULLISH",
    }
    dm = MagicMock()
    dm.get_bars.return_value = [{"close": 100.0}] * 20

    with patch("squeeze_fuel_engine.analyze", return_value=fake_result), \
         patch("squeeze_fuel_scanner._symbols", return_value=["AMC"]), \
         patch("core.state.state") as fake_state, \
         patch("core.legacy.get_service", return_value=dm), \
         patch("iam_executor.PAPER_MODE", return_value=False), \
         patch("tradier_api.get_position", return_value={"quantity": 5}), \
         patch("iam_executor.execute_async") as mock_exec:
        fake_state.quotes = {"AMC": {"price": 5.0}}
        fake_state.lock.__enter__ = MagicMock(return_value=None)
        fake_state.lock.__exit__ = MagicMock(return_value=False)
        sfs._last_fired.clear()
        fired = sfs.scan_once()

    assert fired == 0
    mock_exec.assert_not_called()
    print("PASS: a second symbol's BUY is skipped while the cap (1) is already occupied by a real position")


if __name__ == "__main__":
    test_get_recent_anomaly_returns_within_window()
    test_get_recent_anomaly_expires_outside_window()
    test_get_recent_anomaly_none_when_never_scanned()
    test_prune_open_symbols_self_heals_on_real_flat_position()
    test_cap_blocks_second_symbol_when_at_limit()
    print("\nAll tests passed.")
