"""
Regression test for mmle_engine.py's unreachable ACTIVE_AXES_FIRE gate
(2026-07-20).

`active_axes` can only ever be 0, 1, or 2 — AxisCollapseEngine.update() has
exactly two axes implemented (vanna_proxy needs VIX+VVIX, charm_proxy needs
VIX9D+VIX; see the `if vanna_proxy is not None: active_axes += 1` /
`if charm_proxy is not None: active_axes += 1` block). `ACTIVE_AXES_FIRE`
used to default to 3, which the TNT-state alternate ignition path
(`active_axes >= ACTIVE_AXES_FIRE` in analyze()'s local_long/local_short)
could never satisfy — that OR-branch was permanently dead, and TNT states
could only ever fire via the other branch (`ax_collapse and ret20` aligned).
Fixed by lowering the default to 2, matching the /2.0 normalization
`_composite()` already uses elsewhere in the same file for the same
active_axes value.

This drives the real, unmodified AxisCollapseEngine with genuine VIX-complex
inputs to prove active_axes actually reaches 2 in practice, and evaluates
the real production gate expression (copied verbatim from analyze(), against
the real imported ACTIVE_AXES_FIRE constant — not a hardcoded stand-in) to
prove the alternate ignition path is reachable now and was not before.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmle_engine import ACTIVE_AXES_FIRE, AxisCollapseEngine  # noqa: E402


def _gate(trend_ok: bool, vpin_ready: bool, ax_collapse: bool, ret20_sign: int, active_axes: int) -> bool:
    """The exact local_long expression from mmle_engine.py's analyze(), with
    ret20 abstracted to just its sign (>0 for the LONG side)."""
    return trend_ok and vpin_ready and (
        (ax_collapse and ret20_sign > 0) or active_axes >= ACTIVE_AXES_FIRE
    )


def test_active_axes_fire_default_is_actually_reachable():
    assert ACTIVE_AXES_FIRE <= 2, (
        f"ACTIVE_AXES_FIRE={ACTIVE_AXES_FIRE} but active_axes can never exceed 2 "
        "(only vanna_proxy + charm_proxy are implemented) — the alternate "
        "ignition path is unreachable at this default, same bug as before the fix"
    )
    print(f"PASS: ACTIVE_AXES_FIRE={ACTIVE_AXES_FIRE} is within the achievable range (<=2)")


def test_axis_collapse_engine_really_reaches_two_active_axes():
    """Real VIX-complex inputs (contango term structure, elevated VVIX/VIX
    ratio) — both axes must populate from genuine market-shape data, not
    stubbed values."""
    engine = AxisCollapseEngine(vanna_sma_len=5, ret20_bars=5)
    closes = [100.0 + i * 0.5 for i in range(10)]  # steady uptrend, ret20 > 0

    result = None
    for i in range(2, len(closes) + 1):
        # Seed a short vanna SMA history, then feed real-shaped VIX9D/VIX/VVIX
        result = engine.update(closes[:i], vix=18.0, vix9d=17.0, vvix=95.0 + i)

    assert result["active_axes"] == 2, result
    assert result["vanna_proxy"] is not None and result["charm_proxy"] is not None, result
    print(f"PASS: AxisCollapseEngine genuinely reaches active_axes=2 — {result}")


def test_alternate_ignition_path_fires_at_new_default_axes_agreement_without_collapse():
    """With ax_collapse False (vanna/charm/ret20 signs don't all agree) but
    both axes active, the gate must now fire at ACTIVE_AXES_FIRE=2 — this is
    the exact branch that was dead when the default was 3."""
    fires = _gate(trend_ok=True, vpin_ready=True, ax_collapse=False, ret20_sign=1, active_axes=2)
    assert fires is True, "alternate ignition path (active_axes>=ACTIVE_AXES_FIRE) must fire when both axes agree"
    print("PASS: local_long's active_axes alternate path fires with active_axes=2 at the new default")


def test_single_axis_still_does_not_fire_the_alternate_path():
    """Sanity: only ONE active axis must never be enough — the alternate
    path is specifically about both real axes agreeing, not any signal."""
    fires = _gate(trend_ok=True, vpin_ready=True, ax_collapse=False, ret20_sign=1, active_axes=1)
    assert fires is False, "a single active axis must not satisfy the 2-axis alternate ignition path"
    print("PASS: a single active axis correctly does not fire the alternate path")


def test_old_default_of_three_would_have_stayed_dead():
    """Documents the bug precisely: at the old default (3), even genuine
    full axis agreement (active_axes=2, the maximum achievable) could never
    satisfy the alternate ignition path."""
    old_default = 3
    active_axes = 2  # the maximum ever achievable
    assert not (active_axes >= old_default), (
        "sanity check that the old default really was unreachable at the max achievable active_axes"
    )
    print("PASS: confirmed the old default=3 was mathematically unreachable given max active_axes=2")


if __name__ == "__main__":
    test_active_axes_fire_default_is_actually_reachable()
    test_axis_collapse_engine_really_reaches_two_active_axes()
    test_alternate_ignition_path_fires_at_new_default_axes_agreement_without_collapse()
    test_single_axis_still_does_not_fire_the_alternate_path()
    test_old_default_of_three_would_have_stayed_dead()
    print("\nAll regression tests passed.")
