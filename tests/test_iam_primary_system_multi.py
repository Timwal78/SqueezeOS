"""
Regression test: IAM_PRIMARY_SYSTEM must support a comma-separated list of
systems (so e.g. CASCADE and BREAKOUT can both trade live at once), while
staying exactly backward compatible with a single value (existing deploys
setting IAM_PRIMARY_SYSTEM=SML_CASCADE must keep behaving identically).

Drives the real, unmodified iam_executor.PRIMARY_SYSTEM() against real env
vars -- not a reimplementation of the parsing logic.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import iam_executor  # noqa: E402


def _set_primary(value):
    if value is None:
        os.environ.pop("IAM_PRIMARY_SYSTEM", None)
    else:
        os.environ["IAM_PRIMARY_SYSTEM"] = value


def test_empty_primary_system_is_open_gate():
    _set_primary(None)
    assert iam_executor.PRIMARY_SYSTEM() == set()
    print("PASS: unset IAM_PRIMARY_SYSTEM -> empty set (gate open)")


def test_single_value_backward_compatible():
    _set_primary("SML_CASCADE")
    primary = iam_executor.PRIMARY_SYSTEM()
    assert primary == {"SML_CASCADE"}
    assert ("SML_CASCADE" in primary) is True
    assert ("SML_ORB_MM" in primary) is False
    print("PASS: single-value IAM_PRIMARY_SYSTEM behaves identically to the old string-equality gate")


def test_comma_separated_allows_multiple_live_systems():
    _set_primary("SML_CASCADE,SML_BREAKOUT")
    primary = iam_executor.PRIMARY_SYSTEM()
    assert primary == {"SML_CASCADE", "SML_BREAKOUT"}
    assert "SML_CASCADE" in primary
    assert "SML_BREAKOUT" in primary
    assert "SML_ORB_MM" not in primary
    assert "SML_DRUCK" not in primary
    print("PASS: IAM_PRIMARY_SYSTEM=SML_CASCADE,SML_BREAKOUT allows both, excludes ORB/DRUCK")


def test_whitespace_and_case_tolerant():
    _set_primary(" sml_cascade , SML_Breakout ")
    primary = iam_executor.PRIMARY_SYSTEM()
    assert primary == {"SML_CASCADE", "SML_BREAKOUT"}
    print("PASS: whitespace/case normalized on both sides of the comma")


if __name__ == "__main__":
    try:
        test_empty_primary_system_is_open_gate()
        test_single_value_backward_compatible()
        test_comma_separated_allows_multiple_live_systems()
        test_whitespace_and_case_tolerant()
        print("\nAll regression tests passed.")
    finally:
        _set_primary(None)
