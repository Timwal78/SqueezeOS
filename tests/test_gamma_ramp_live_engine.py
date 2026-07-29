"""
Regression tests: tools/gamma_ramp/live_engine.py's manage_open() position
tracking.

Bug 1 -- "bank_300" orphaned the leftover contract. bank_300 is a
deliberate partial exit (flattens most of a runner at +300%, leaves 1
"lottery ticket" contract still open) -- same shape as scale_50/scale_150.
But the post-exit bookkeeping only kept tracking a position with contracts
remaining when `reason.startswith("scale")`, which "bank_300" never
matches. That silently dropped the leftover contract from st.open --  a
real, still-open broker position the engine would never manage again (no
stop-loss, no trail, nothing).

Bug 2 -- pos.peak was overwritten to the current mark at every scale event,
even when the current mark was BELOW an already-recorded higher peak (e.g.
peak was $1.80, price pulled back to exactly $1.60 which still crosses the
+50% scale threshold) -- silently lowering the true peak used by the
giveback-lock protection. Fixed by splitting into `peak` (true all-time
high since entry, never overwritten) and `stage_peak` (reset at each scale,
used only by the post-scale trailing stop).

Both tests drive the real, unmodified manage_open(), mocking only the
tradier_api.get_quote() I/O boundary.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "gamma_ramp"))

import tradier_api  # noqa: E402
import live_engine as ge  # noqa: E402


def _mk_pos(entry=1.00, peak=1.00, stage_peak=1.00, scaled=False, scale_frac=0.0, contracts=4):
    return ge.OpenPos(
        occ="TEST240101C00100000", underlying="TEST", side="CALL",
        qty=contracts, entry=entry, peak=peak, stage_peak=stage_peak,
        scaled=scaled, scale_frac=scale_frac, contracts_remaining=contracts,
    )


def _fake_place_exit(*a, **k):
    return {"status": "queued_rh"}


def test_bank_300_keeps_tracking_leftover_lottery_contract():
    """4 contracts, already through both scale stages (scale_frac=0.75,
    i.e. scale_50 and scale_150 already fired on earlier ticks), price now
    hits +300% -- bank_300 should sell 3, leave 1 tracked in st.open, NOT
    drop it."""
    pos = _mk_pos(entry=1.00, peak=1.00, stage_peak=1.00, scaled=True, scale_frac=0.75, contracts=4)
    st = ge.EngineState(open=[__import__("dataclasses").asdict(pos)])

    def fake_get_quote(occ):
        return {"bid": 3.98, "ask": 4.02, "last": 4.00}  # ret = +300%

    with patch.object(tradier_api, "get_quote", side_effect=fake_get_quote), \
         patch.object(ge, "place_exit", side_effect=_fake_place_exit):
        st2 = ge.manage_open(st, {"live_orders_allowed": False})

    assert len(st2.open) == 1, (
        f"expected the leftover lottery contract to still be tracked, "
        f"got {len(st2.open)} open positions -- bank_300 orphaned it"
    )
    remaining = st2.open[0]
    assert remaining["contracts_remaining"] == 1, remaining
    print("PASS: bank_300 keeps tracking the leftover lottery contract")


def test_peak_survives_a_pullback_scale_trigger():
    """Peak was $1.80 (true all-time high). Price pulls back to $1.60,
    which still crosses the +50% scale threshold (entry $1.00) -- pos.peak
    must stay $1.80 (true peak, used by giveback-lock), only stage_peak
    should reset to the $1.60 scale-trigger mark."""
    pos = _mk_pos(entry=1.00, peak=1.80, stage_peak=1.80, scaled=False, scale_frac=0.0, contracts=4)
    st = ge.EngineState(open=[__import__("dataclasses").asdict(pos)])

    def fake_get_quote(occ):
        return {"bid": 1.58, "ask": 1.62, "last": 1.60}  # ret = +60%, triggers scale_50

    with patch.object(tradier_api, "get_quote", side_effect=fake_get_quote), \
         patch.object(ge, "place_exit", side_effect=_fake_place_exit):
        st2 = ge.manage_open(st, {"live_orders_allowed": False})

    assert len(st2.open) == 1
    remaining = st2.open[0]
    assert remaining["peak"] == 1.80, (
        f"true peak was overwritten: expected 1.80, got {remaining['peak']} -- "
        f"giveback-lock protection is now measuring against a fake, lower peak"
    )
    assert remaining["stage_peak"] == 1.60, remaining
    print("PASS: true peak survives a scale event triggered on a pullback")


if __name__ == "__main__":
    test_bank_300_keeps_tracking_leftover_lottery_contract()
    test_peak_survives_a_pullback_scale_trigger()
    print("\nAll regression tests passed.")
