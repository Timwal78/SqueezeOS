"""
Tests for scan_budget.py's dynamic scan-width allocator -- the shared
Tradier-daily queue budget should split evenly across whichever secondary
scanners are actually enabled, reserve CASCADE's own fixed allotment first,
and always defer to an explicit per-scanner override when one is set.
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


def test_splits_evenly_across_all_five_active_by_default(monkeypatch):
    _reset_env(monkeypatch)
    # 5 active scanners, CASCADE reserved 40 (default): (142-40)//5 == 20
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 20
    assert sb.dynamic_top_n("QUAD_SCORE", "QUAD_SCORE_SCAN_TOP_N") == 20


def test_disabling_a_sibling_widens_the_remaining_scanners_share(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("SR_MATRIX_SCAN_ENABLED", "false")
    # 4 active now: (142-40)//4 == 25
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 25


def test_cascade_reservation_is_respected(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("AVG_DOWN_SCAN_TOP_N", "100")
    # (142-100)//5 == 8
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == 8


def test_never_goes_below_minimum_even_if_cascade_reservation_exceeds_budget(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("AVG_DOWN_SCAN_TOP_N", "10000")
    assert sb.dynamic_top_n("BREAKOUT", "BREAKOUT_SCAN_TOP_N") == sb.MIN_PER_SCANNER


def test_active_secondary_scanners_reports_only_enabled_ones(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("QUAD_SCORE_SCAN_ENABLED", "false")
    active = sb.active_secondary_scanners()
    assert "QUAD_SCORE" not in active
    assert "BREAKOUT" in active
    assert len(active) == 4
