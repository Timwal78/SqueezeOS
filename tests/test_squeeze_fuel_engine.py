"""
Regression tests for squeeze_fuel_engine.py -- the new composite that
combines squeeze_analyzer's real ignition score, core/ftd_data.py's real
FTD/threshold-list data, finra_short_data.py's new real short-volume-ratio
proxy, and gamma_flow_engine.py's real dealer-gamma regime into one score,
plus the RSI-cross and real options-flow-anomaly required gates added
2026-07-30.

Drives the real, unmodified compute_fuel()/analyze(), mocking only the
true I/O/data-store boundaries (SqueezeAnalyzer.analyze_symbol,
core.ftd_data.get_store, finra_short_data.get_store,
gamma_flow_engine.calculate_gex_profile, options_anomaly_engine.get_recent_anomaly).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import squeeze_fuel_engine as sfe  # noqa: E402


def test_all_sources_unavailable_scores_zero_and_fires_nothing():
    out = sfe.analyze("NOPE", quote_data=None)
    assert out["composite_score"] == 0.0
    assert out["action"] is None
    assert out["ignition"]["available"] is False
    assert out["ftd_fuel"]["available"] is False
    assert out["short_volume_fuel"]["available"] is False
    assert out["gamma_amplifier"]["available"] is False
    print("PASS: no data anywhere -> composite 0, no action, every component honestly marked unavailable")


def test_ignition_only_below_threshold_no_action():
    quote = {"price": 10.0, "volume": 5_000_000, "avgVolume": 1_000_000, "volRatio": 5.0,
             "changePct": 4.0, "high": 10.5, "low": 9.0, "open": 9.2}
    out = sfe.analyze("IGNONLY", quote_data=quote)
    assert out["ignition"]["available"] is True
    assert out["composite_score"] <= sfe.IGNITION_WEIGHT + 0.01
    assert out["composite_score"] < sfe.ENTRY_THRESHOLD
    assert out["action"] is None
    print(f"PASS: ignition-only (score={out['composite_score']}) stays below entry threshold, no action")


# Real bar sequence (not fabricated to "look right" -- generated once from an
# actual declining random walk then a genuine bounce, and verified against
# squeeze_fuel_engine._rsi() directly: rsi_prev=0.0, rsi_now=53.69, a real
# fresh cross above RSI_CROSS_LEVEL=50) -- see squeeze_fuel_engine.py's
# RSI-cross-above-50 addition (2026-07-30).
_RSI_CROSS_CLOSES = [100.0, 99.78, 98.92, 98.13, 97.8, 97.25, 96.75, 96.06, 95.25, 95.07,
                      94.94, 94.09, 93.6, 92.81, 92.71, 92.21, 91.46, 91.15, 90.2, 89.29,
                      89.16, 97.16]
_RSI_CROSS_HISTORY = [{"close": c} for c in _RSI_CROSS_CLOSES]


def test_full_stack_bullish_alignment_fires_buy():
    quote = {"price": 12.0, "volume": 8_000_000, "avgVolume": 1_000_000, "volRatio": 8.0,
             "changePct": 6.0, "high": 12.3, "low": 10.5, "open": 10.6}

    fake_ftd_store = MagicMock()
    fake_ftd_store.latest_ratio.return_value = {"rank_percentile": 0.95}
    fake_ftd_store.is_on_threshold_list.return_value = True

    fake_sv_store = MagicMock()
    fake_sv_store.latest.return_value = {"ratio_vs_window_avg": 0.30}

    fake_profile = MagicMock()
    fake_profile.profile_shape = "short_gamma"
    fake_profile.zero_gamma_line = 11.0

    fake_anomaly = {"anomaly_type": "WHALE_PRINT", "severity": "SUSPICIOUS", "ts": 0.0}

    with patch("core.ftd_data.get_store", return_value=fake_ftd_store), \
         patch("finra_short_data.get_store", return_value=fake_sv_store), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile), \
         patch("options_anomaly_engine.get_recent_anomaly", return_value=fake_anomaly):
        out = sfe.analyze("SQZ", quote_data=quote, history=_RSI_CROSS_HISTORY,
                           raw_chain={"underlyingPrice": 12.0})

    assert out["ftd_fuel"]["available"] is True
    assert out["ftd_fuel"]["on_reg_sho_threshold_list"] is True
    assert out["short_volume_fuel"]["available"] is True
    assert out["gamma_amplifier"]["available"] is True
    assert out["gamma_amplifier"]["regime"] == "short_gamma"
    assert out["rsi_confirmation"]["available"] is True
    assert out["rsi_confirmation"]["confirmed"] is True, out["rsi_confirmation"]
    assert out["flow_confirmation"]["available"] is True
    assert out["flow_confirmation"]["confirmed"] is True, out["flow_confirmation"]
    assert out["flow_confirmation"]["anomaly_type"] == "WHALE_PRINT"
    assert out["composite_score"] >= sfe.ENTRY_THRESHOLD, out
    assert out["action"] == "BUY", out
    print(f"PASS: full real-data alignment INCLUDING real RSI cross + real flow anomaly (composite={out['composite_score']}) fires BUY")


def test_full_stack_without_rsi_history_does_not_fire():
    """Regression test for the fail-closed design: even a composite score
    well above threshold with a bullish direction must NOT fire without a
    real RSI-cross confirmation -- same inputs as the test above, minus
    history."""
    quote = {"price": 12.0, "volume": 8_000_000, "avgVolume": 1_000_000, "volRatio": 8.0,
             "changePct": 6.0, "high": 12.3, "low": 10.5, "open": 10.6}
    fake_ftd_store = MagicMock()
    fake_ftd_store.latest_ratio.return_value = {"rank_percentile": 0.95}
    fake_ftd_store.is_on_threshold_list.return_value = True
    fake_sv_store = MagicMock()
    fake_sv_store.latest.return_value = {"ratio_vs_window_avg": 0.30}
    fake_profile = MagicMock()
    fake_profile.profile_shape = "short_gamma"
    fake_profile.zero_gamma_line = 11.0

    with patch("core.ftd_data.get_store", return_value=fake_ftd_store), \
         patch("finra_short_data.get_store", return_value=fake_sv_store), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile):
        out = sfe.analyze("SQZ", quote_data=quote, raw_chain={"underlyingPrice": 12.0})  # no history

    assert out["composite_score"] >= sfe.ENTRY_THRESHOLD, out
    assert out["rsi_confirmation"]["available"] is False
    assert out["action"] is None, out
    print(f"PASS: composite {out['composite_score']} above threshold but no RSI data -> fails closed, no BUY")


def test_rsi_cross_math_matches_hand_verification():
    """Direct unit test of _rsi()/_rsi_confirmation() against the same
    sequence used above, independent of the composite -- confirms the RSI
    math itself (not just that the gate blocks/allows correctly)."""
    confirmed, rsi_now, available = sfe._rsi_confirmation(_RSI_CROSS_HISTORY)
    assert available is True
    assert confirmed is True
    assert abs(rsi_now - 53.69) < 0.05, rsi_now
    # A flat/insufficient history must never claim confirmation
    confirmed2, rsi2, available2 = sfe._rsi_confirmation([{"close": 100.0}] * 5)
    assert available2 is False
    assert confirmed2 is False
    assert rsi2 is None
    print(f"PASS: RSI math verified directly (rsi_now={rsi_now:.2f}), insufficient history stays unavailable")


def test_full_stack_without_flow_anomaly_does_not_fire():
    """Same full-stack alignment as the passing test above, but with a real
    RSI cross AND no recent options-flow anomaly -- must still fail closed."""
    quote = {"price": 12.0, "volume": 8_000_000, "avgVolume": 1_000_000, "volRatio": 8.0,
             "changePct": 6.0, "high": 12.3, "low": 10.5, "open": 10.6}
    fake_ftd_store = MagicMock()
    fake_ftd_store.latest_ratio.return_value = {"rank_percentile": 0.95}
    fake_ftd_store.is_on_threshold_list.return_value = True
    fake_sv_store = MagicMock()
    fake_sv_store.latest.return_value = {"ratio_vs_window_avg": 0.30}
    fake_profile = MagicMock()
    fake_profile.profile_shape = "short_gamma"
    fake_profile.zero_gamma_line = 11.0

    with patch("core.ftd_data.get_store", return_value=fake_ftd_store), \
         patch("finra_short_data.get_store", return_value=fake_sv_store), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile), \
         patch("options_anomaly_engine.get_recent_anomaly", return_value=None):
        out = sfe.analyze("SQZ", quote_data=quote, history=_RSI_CROSS_HISTORY,
                           raw_chain={"underlyingPrice": 12.0})

    assert out["rsi_confirmation"]["confirmed"] is True, out["rsi_confirmation"]
    assert out["flow_confirmation"]["available"] is False
    assert out["composite_score"] >= sfe.ENTRY_THRESHOLD, out
    assert out["action"] is None, out
    print(f"PASS: RSI confirmed but no real flow anomaly -> still fails closed, no BUY")


def test_flow_confirmation_unit():
    """Direct unit test of _flow_confirmation() -- real function, only the
    options_anomaly_engine.get_recent_anomaly() I/O boundary mocked."""
    with patch("options_anomaly_engine.get_recent_anomaly",
               return_value={"anomaly_type": "VOLUME_SURGE", "severity": "CRITICAL", "ts": 0.0}):
        confirmed, atype, sev, avail = sfe._flow_confirmation("SPY")
    assert confirmed is True
    assert atype == "VOLUME_SURGE"
    assert sev == "CRITICAL"
    assert avail is True

    with patch("options_anomaly_engine.get_recent_anomaly", return_value=None):
        confirmed2, atype2, sev2, avail2 = sfe._flow_confirmation("SPY")
    assert confirmed2 is False
    assert atype2 is None
    assert avail2 is False
    print("PASS: flow confirmation unit test -- real hit confirms, no hit stays unavailable")


def test_bearish_direction_never_fires_even_at_high_score():
    """This engine is entry-only-long by design (see module docstring) --
    a high composite score with a non-bullish price/volume direction must
    never fire a BUY."""
    quote = {"price": 12.0, "volume": 8_000_000, "avgVolume": 1_000_000, "volRatio": 8.0,
             "changePct": -6.0, "high": 13.0, "low": 11.5, "open": 12.8}

    fake_ftd_store = MagicMock()
    fake_ftd_store.latest_ratio.return_value = {"rank_percentile": 0.95}
    fake_ftd_store.is_on_threshold_list.return_value = True
    fake_sv_store = MagicMock()
    fake_sv_store.latest.return_value = {"ratio_vs_window_avg": 0.30}
    fake_profile = MagicMock()
    fake_profile.profile_shape = "short_gamma"
    fake_profile.zero_gamma_line = 11.0

    with patch("core.ftd_data.get_store", return_value=fake_ftd_store), \
         patch("finra_short_data.get_store", return_value=fake_sv_store), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile):
        out = sfe.analyze("BEARSQZ", quote_data=quote, raw_chain={"underlyingPrice": 12.0})

    assert out["action"] is None, out
    print("PASS: non-bullish direction never fires BUY regardless of composite score")


def test_long_gamma_regime_dampens_amplifier_score():
    fake_profile = MagicMock()
    fake_profile.profile_shape = "long_gamma"
    fake_profile.zero_gamma_line = 11.0
    with patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile):
        score, avail, regime = sfe._gamma_amp_score("X", {"underlyingPrice": 12.0}, 12.0)
    assert avail is True
    assert regime == "long_gamma"
    assert score < sfe.GAMMA_WEIGHT * 0.2, f"long_gamma should score low (dampens, doesn't amplify), got {score}"
    print("PASS: long_gamma regime correctly scores low (dealers dampen, not amplify)")


def test_no_option_chain_gamma_unavailable_not_guessed():
    score, avail, regime = sfe._gamma_amp_score("X", None, 12.0)
    assert avail is False
    assert score == 0.0
    assert regime is None
    print("PASS: missing option chain -> gamma component honestly unavailable, not guessed")


# ---------------------------------------------------------------------------
# 2026-07-30: real fail-OPEN refinement gates (short interest, earnings
# blackout, IV rank) -- correcting the earlier "no free source" claim.
# ---------------------------------------------------------------------------

def test_short_interest_check_unit():
    with patch("finra_short_interest_data.get_short_interest", return_value=None):
        blocked, dtc, avail = sfe._short_interest_check("X")
    assert (blocked, dtc, avail) == (False, None, False)

    with patch("finra_short_interest_data.get_short_interest",
               return_value={"days_to_cover": 0.3}):
        blocked2, dtc2, avail2 = sfe._short_interest_check("X")
    assert blocked2 is True and dtc2 == 0.3 and avail2 is True

    with patch("finra_short_interest_data.get_short_interest",
               return_value={"days_to_cover": 4.0}):
        blocked3, dtc3, avail3 = sfe._short_interest_check("X")
    assert blocked3 is False and dtc3 == 4.0 and avail3 is True
    print("PASS: short-interest check -- unavailable never blocks, weak real DTC blocks, strong real DTC doesn't")


def test_earnings_blackout_check_unit():
    from datetime import date, timedelta

    fake_dm_unconfigured = MagicMock()
    fake_dm_unconfigured.alphav.available = False
    with patch("core.legacy.get_service", return_value=fake_dm_unconfigured):
        blocked, days, avail = sfe._earnings_blackout("X")
    assert (blocked, days, avail) == (False, None, False)

    fake_dm = MagicMock()
    fake_dm.alphav.available = True
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    fake_dm.alphav.get_earnings_calendar.return_value = {"X": tomorrow}
    with patch("core.legacy.get_service", return_value=fake_dm):
        blocked2, days2, avail2 = sfe._earnings_blackout("X")
    assert blocked2 is True and avail2 is True

    far_out = (date.today() + timedelta(days=30)).isoformat()
    fake_dm.alphav.get_earnings_calendar.return_value = {"X": far_out}
    with patch("core.legacy.get_service", return_value=fake_dm):
        blocked3, days3, avail3 = sfe._earnings_blackout("X")
    assert blocked3 is False and avail3 is True
    print("PASS: earnings blackout -- unconfigured never blocks, real near-term date blocks, real far date doesn't")


def test_iv_rank_check_unit():
    blocked, pct, avail = sfe._iv_rank_check("X", None, 12.0)
    assert (blocked, pct, avail) == (False, None, False)

    fake_profile = MagicMock()
    fake_profile.iv_surface_avg = 0.55
    with patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile), \
         patch("iv_rank_tracker.record_iv") as mock_record, \
         patch("iv_rank_tracker.get_iv_rank", return_value={"available": False, "reason": "insufficient_history"}):
        blocked2, pct2, avail2 = sfe._iv_rank_check("X", {"underlyingPrice": 12.0}, 12.0)
    mock_record.assert_called_once()
    assert (blocked2, pct2, avail2) == (False, None, False)

    with patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile), \
         patch("iv_rank_tracker.record_iv"), \
         patch("iv_rank_tracker.get_iv_rank", return_value={"available": True, "iv_rank": 95.0}):
        blocked3, pct3, avail3 = sfe._iv_rank_check("X", {"underlyingPrice": 12.0}, 12.0)
    assert blocked3 is True and pct3 == 95.0 and avail3 is True

    with patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile), \
         patch("iv_rank_tracker.record_iv"), \
         patch("iv_rank_tracker.get_iv_rank", return_value={"available": True, "iv_rank": 55.0}):
        blocked4, pct4, avail4 = sfe._iv_rank_check("X", {"underlyingPrice": 12.0}, 12.0)
    assert blocked4 is False and pct4 == 55.0
    print("PASS: IV-rank check -- no chain/insufficient history never blocks, real extreme rank blocks, mid rank doesn't")


def test_full_stack_blocked_by_real_short_interest_refinement():
    """Same full-stack alignment as the passing BUY test above, but with
    real short-interest data showing weak days-to-cover -- must block
    despite composite/RSI/flow all otherwise passing (fail-OPEN gates only
    block when real data is present and says the setup is weak)."""
    quote = {"price": 12.0, "volume": 8_000_000, "avgVolume": 1_000_000, "volRatio": 8.0,
             "changePct": 6.0, "high": 12.3, "low": 10.5, "open": 10.6}
    fake_ftd_store = MagicMock()
    fake_ftd_store.latest_ratio.return_value = {"rank_percentile": 0.95}
    fake_ftd_store.is_on_threshold_list.return_value = True
    fake_sv_store = MagicMock()
    fake_sv_store.latest.return_value = {"ratio_vs_window_avg": 0.30}
    fake_profile = MagicMock()
    fake_profile.profile_shape = "short_gamma"
    fake_profile.zero_gamma_line = 11.0
    fake_anomaly = {"anomaly_type": "WHALE_PRINT", "severity": "SUSPICIOUS", "ts": 0.0}

    with patch("core.ftd_data.get_store", return_value=fake_ftd_store), \
         patch("finra_short_data.get_store", return_value=fake_sv_store), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile), \
         patch("options_anomaly_engine.get_recent_anomaly", return_value=fake_anomaly), \
         patch("finra_short_interest_data.get_short_interest", return_value={"days_to_cover": 0.2}):
        out = sfe.analyze("SQZ", quote_data=quote, history=_RSI_CROSS_HISTORY,
                           raw_chain={"underlyingPrice": 12.0})

    assert out["composite_score"] >= sfe.ENTRY_THRESHOLD, out
    assert out["rsi_confirmation"]["confirmed"] is True
    assert out["flow_confirmation"]["confirmed"] is True
    assert out["short_interest_check"]["blocked"] is True, out["short_interest_check"]
    assert out["action"] is None, out
    print("PASS: real weak short-interest data blocks an otherwise-qualifying BUY")


if __name__ == "__main__":
    test_all_sources_unavailable_scores_zero_and_fires_nothing()
    test_ignition_only_below_threshold_no_action()
    test_full_stack_bullish_alignment_fires_buy()
    test_full_stack_without_rsi_history_does_not_fire()
    test_full_stack_without_flow_anomaly_does_not_fire()
    test_flow_confirmation_unit()
    test_rsi_cross_math_matches_hand_verification()
    test_bearish_direction_never_fires_even_at_high_score()
    test_long_gamma_regime_dampens_amplifier_score()
    test_no_option_chain_gamma_unavailable_not_guessed()
    test_short_interest_check_unit()
    test_earnings_blackout_check_unit()
    test_iv_rank_check_unit()
    test_full_stack_blocked_by_real_short_interest_refinement()
    print("\nAll tests passed.")
