"""
Regression tests for squeeze_fuel_engine.py -- the new composite that
combines squeeze_analyzer's real ignition score, core/ftd_data.py's real
FTD/threshold-list data, finra_short_data.py's new real short-volume-ratio
proxy, and gamma_flow_engine.py's real dealer-gamma regime into one score.

Drives the real, unmodified compute_fuel()/analyze(), mocking only the
four true I/O/data-store boundaries (SqueezeAnalyzer.analyze_symbol,
core.ftd_data.get_store, finra_short_data.get_store,
gamma_flow_engine.calculate_gex_profile).
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

    with patch("core.ftd_data.get_store", return_value=fake_ftd_store), \
         patch("finra_short_data.get_store", return_value=fake_sv_store), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=fake_profile):
        out = sfe.analyze("SQZ", quote_data=quote, raw_chain={"underlyingPrice": 12.0})

    assert out["ftd_fuel"]["available"] is True
    assert out["ftd_fuel"]["on_reg_sho_threshold_list"] is True
    assert out["short_volume_fuel"]["available"] is True
    assert out["gamma_amplifier"]["available"] is True
    assert out["gamma_amplifier"]["regime"] == "short_gamma"
    assert out["composite_score"] >= sfe.ENTRY_THRESHOLD, out
    assert out["action"] == "BUY", out
    print(f"PASS: full real-data alignment (composite={out['composite_score']}) fires BUY")


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


if __name__ == "__main__":
    test_all_sources_unavailable_scores_zero_and_fires_nothing()
    test_ignition_only_below_threshold_no_action()
    test_full_stack_bullish_alignment_fires_buy()
    test_bearish_direction_never_fires_even_at_high_score()
    test_long_gamma_regime_dampens_amplifier_score()
    test_no_option_chain_gamma_unavailable_not_guessed()
    print("\nAll tests passed.")
