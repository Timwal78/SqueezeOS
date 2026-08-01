"""
Tests for scan_budget.py's dynamic scan-width allocator -- the shared
Tradier-daily queue budget should split evenly across whichever secondary
scanners are actually enabled, reserve CASCADE's own fixed allotment first,
and always defer to an explicit per-scanner override when one is set.

SR_ZONE_PATTERN's own default flipped false->true->false on 2026-08-01
(operator directive: "remove it altogether" from live trading, see
sr_zone_pattern_scanner.py's docstring and CLAUDE.md) -- this file's
"default" baseline is now 4 active secondary scanners, not 5, and that
change is itself the thing under test in
test_sr_zone_pattern_defaults_disabled_and_widens_the_others below.
"""
import importlib

import scan_budget as sb


def _reset_env(monkeypatch):
    for var in list(sb._SECONDARY_ENABLED_VARS.values()) + [
        "AVG_DOWN_SCAN_TOP_N", "BREAKOUT_SCAN_TOP_N", "SR_MATRIX_SCAN_TOP_N",
        "SR_ZONE_PATTERN_SCAN_TOP_N", "SOVEREIGN_SQZ_SCAN_TOP_N", "QUAD_SCORE_SCAN_TOP_N",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_explicit_override_always_wins(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("BREAKOUT_SCAN_TOP_N", "99")
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 99


def test_splits_evenly_across_four_active_by_default():
    """SR_ZONE_PATTERN now defaults OFF (2026-08-01) -- the real default
    active set is BREAKOUT/SR_MATRIX/SOVEREIGN_SQZ/QUAD_SCORE, 4 scanners,
    not 5. (142-40)//4 == 25."""
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 25
    assert sb.dynamic_top_n("QUAD_SCORE", "QUAD_SCORE_SCAN_TOP_N") == 25


def test_sr_zone_pattern_defaults_disabled_and_widens_the_others(monkeypatch):
    """The actual regression this file exists to prove: with nothing set,
    SR_ZONE_PATTERN must not appear in the active set, and its absence must
    genuinely widen its 4 siblings' share -- not just report disabled while
    still being budgeted for."""
    _reset_env(monkeypatch)
    active = sb.active_secondary_scanners()
    assert "SR_ZONE_PATTERN" not in active
    assert len(active) == 4
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 25


def test_sr_zone_pattern_can_be_explicitly_re_enabled(monkeypatch):
    """Setting SR_ZONE_PATTERN_SCAN_ENABLED=true must restore it to the
    active set and the 5-way split -- the disable is a reversible default,
    not a removed capability."""
    _reset_env(monkeypatch)
    monkeypatch.setenv("SR_ZONE_PATTERN_SCAN_ENABLED", "true")
    active = sb.active_secondary_scanners()
    assert "SR_ZONE_PATTERN" in active
    assert len(active) == 5
    # (142-40)//5 == 20
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 20


def test_disabling_a_sibling_widens_the_remaining_scanners_share(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("SR_MATRIX_SCAN_ENABLED", "false")
    # Default active is already 4 (SR_ZONE_PATTERN off); disabling SR_MATRIX
    # too leaves 3: (142-40)//3 == 34
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 34


def test_cascade_reservation_is_respected(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("AVG_DOWN_SCAN_TOP_N", "100")
    # (142-100)//4 == 10 (4 active by default, SR_ZONE_PATTERN off)
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 10


def test_never_goes_below_minimum_even_if_cascade_reservation_exceeds_budget(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("AVG_DOWN_SCAN_TOP_N", "10000")
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == sb.MIN_PER_SCANNER


def test_active_secondary_scanners_reports_only_enabled_ones(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("QUAD_SCORE_SCAN_ENABLED", "false")
    active = sb.active_secondary_scanners()
    assert "QUAD_SCORE" not in active
    assert "SR_ZONE_PATTERN" not in active  # off by default, not because of this test
    assert "BREAKOUT" in active
    assert len(active) == 3
