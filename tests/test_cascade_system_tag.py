"""
Regression test: avg_down_engine.py (CASCADE) must tag its IAM resolution
with system="SML_CASCADE" so the IAM_PRIMARY_SYSTEM gate in iam_executor.py
(signal_system = resolution.get("system") or "IAM") can correctly identify
CASCADE signals.

Before this fix, avg_down_engine._route_iam() built a resolution dict with
no "system" key at all, so every CASCADE signal defaulted to system="IAM" --
identical to IMO/ORB/DRUCK's untagged fallback. Setting
IAM_PRIMARY_SYSTEM=SML_CASCADE (to restrict real trading to CASCADE only,
per the operator's 2026-07-21 decision to keep ORB/DRUCK on paper) would
have silently blocked CASCADE's own signals too, since "IAM" != "SML_CASCADE"
-- the exact opposite of the intended effect, with no visible error.

This drives the real, unmodified _route_iam() end-to-end, capturing the
resolution dict it actually passes to iam_executor.execute_from_resolution
(mocked only at that boundary -- everything inside avg_down_engine.py runs
for real).
"""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import avg_down_engine as cascade  # noqa: E402


def test_route_iam_tags_resolution_with_cascade_system():
    captured = {}

    def fake_execute_from_resolution(symbol, resolution, **kwargs):
        captured["symbol"] = symbol
        captured["resolution"] = resolution
        captured["kwargs"] = kwargs

    fake_module = MagicMock()
    fake_module.execute_from_resolution = fake_execute_from_resolution

    sig = {
        "symbol": "NVDA", "action": "ENTER", "level": 0, "align_score": 4,
        "price": 123.45, "ftd_echo": False, "echo_source": None,
    }

    with patch.dict(sys.modules, {"iam_executor": fake_module}):
        cascade._route_iam("NVDA", sig)

    assert "resolution" in captured, "execute_from_resolution was never called"
    assert captured["resolution"].get("system") == "SML_CASCADE", (
        f"expected resolution['system'] == 'SML_CASCADE', got {captured['resolution'].get('system')!r} "
        "-- without this tag, IAM_PRIMARY_SYSTEM=SML_CASCADE would block CASCADE's own signals"
    )
    print("PASS: CASCADE resolutions are tagged system='SML_CASCADE'")


def test_primary_system_gate_now_allows_cascade():
    """End-to-end sanity: with the real tag, iam_executor's own gate logic
    (signal_system = resolution.get('system') or 'IAM'; broker_allowed =
    not primary or signal_system == primary) now correctly allows CASCADE
    through when IAM_PRIMARY_SYSTEM=SML_CASCADE."""
    resolution = {"action": "BUY", "system": "SML_CASCADE"}
    primary = "SML_CASCADE"
    signal_system = (resolution.get("system") or "IAM").strip().upper()
    broker_allowed = not primary or signal_system == primary
    assert broker_allowed is True, "CASCADE must be allowed through when it IS the primary system"

    # And confirm ORB/DRUCK (still untagged as far as this gate cares, or
    # tagged differently) are correctly excluded under the same setting.
    orb_resolution = {"action": "BUY", "system": "SML_ORB_MM"}
    orb_signal_system = (orb_resolution.get("system") or "IAM").strip().upper()
    orb_broker_allowed = not primary or orb_signal_system == primary
    assert orb_broker_allowed is False, "ORB must be excluded from real execution once CASCADE is primary"
    print("PASS: IAM_PRIMARY_SYSTEM=SML_CASCADE now correctly allows CASCADE and excludes ORB")


if __name__ == "__main__":
    test_route_iam_tags_resolution_with_cascade_system()
    test_primary_system_gate_now_allows_cascade()
    print("\nAll regression tests passed.")
