"""
Regression test for the inverted direction-label bug in options_anomaly_engine.py
(2026-07-20).

Root cause (two parts, both fixed here):

1. options_intelligence.py's compute_flow_summary() computed call_vol/put_vol
   locally but never put them in the returned summary dict. options_anomaly_
   engine.py's _build_snapshot() reads flow.get("total_call_vol")/
   flow.get("total_put_vol") — keys that never existed — so those always read
   as 0, forcing every snapshot down the "derive from sweeps" fallback path
   (which itself rarely populates total_put_vol either).

2. That fallback then computed cp_ratio = pc_ratio (put_call_vol_ratio, i.e.
   PUT/CALL) with no inversion, but call_put_vol_ratio is supposed to be
   CALL/PUT. _generate_thesis() reads snap.call_put_vol_ratio > 1.2 as
   "BULLISH" — so heavy PUT flow (pc_ratio > 1.2) was being read directly as
   call_put_vol_ratio > 1.2 and mislabeled BULLISH instead of BEARISH.

This drives the real, unmodified compute_flow_summary() and _build_snapshot()
end-to-end against a synthetic-but-realistic Schwab-shape option chain
(heavy real put volume, light real call volume) and proves the resulting
snapshot/thesis now correctly reads BEARISH, not BULLISH.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options_intelligence import OptionsIntelligence  # noqa: E402
from options_anomaly_engine import _build_snapshot, _generate_thesis  # noqa: E402


def _heavy_put_chain(spot: float = 100.0):
    """Real Schwab-shape chain: 5000 contracts of PUT volume vs 500 of CALL —
    unambiguous bearish order flow, unambiguous which label should win."""
    def contract(vol, oi=1000, iv=30.0, last=1.5, bid=1.4, ask=1.6, delta=0.3, gamma=0.02):
        return {"totalVolume": vol, "openInterest": oi, "volatility": iv,
                "lastPrice": last, "bid": bid, "ask": ask, "delta": delta, "gamma": gamma}

    strike = str(round(spot))
    return {
        "callExpDateMap": {"2026-08-15:26": {strike: [contract(vol=500)]}},
        "putExpDateMap": {"2026-08-15:26": {strike: [contract(vol=5000, delta=-0.3)]}},
    }


def test_compute_flow_summary_now_exposes_real_call_and_put_volume():
    oi = OptionsIntelligence()
    chain = _heavy_put_chain()
    summary = oi.compute_flow_summary("TESTPUT", chain)

    assert summary["total_call_vol"] == 500, summary
    assert summary["total_put_vol"] == 5000, summary
    # put_call_vol_ratio is PUT/CALL by construction (unchanged, pre-existing field)
    assert summary["put_call_vol_ratio"] == 10.0, summary
    print(f"PASS: compute_flow_summary() now exposes real volumes — {summary}")


def test_build_snapshot_root_cause_path_labels_heavy_put_flow_bearish():
    """With the producer fix, _build_snapshot() should take the real total_call_vol/
    total_put_vol path (not the fallback) and get the sign right without even
    needing the fallback-inversion fix."""
    oi = OptionsIntelligence()
    chain = _heavy_put_chain()
    flow_summary = oi.compute_flow_summary("TESTPUT", chain)
    scan_result = {"flow_summary": flow_summary, "sweeps": []}

    snap = _build_snapshot("TESTPUT", chain, scan_result)

    assert snap is not None
    assert snap.total_call_vol == 500, snap
    assert snap.total_put_vol == 5000, snap
    assert snap.call_put_vol_ratio == 500 / 5000, snap
    assert snap.call_put_vol_ratio < 0.8, "must be in the BEARISH band for the thesis check below"

    thesis = _generate_thesis(
        "TESTPUT", "WHALE_PRINT", snap, mean=1.0, current=3.0, z=3.0,
        supporting={"size_class": "WHALE", "premium": 500_000},
    )
    assert "BEARISH" in thesis, thesis
    assert "BULLISH" not in thesis, thesis
    print(f"PASS: real-volume snapshot correctly drives a BEARISH thesis — ratio={snap.call_put_vol_ratio:.3f}")


def test_build_snapshot_fallback_path_still_labels_heavy_put_flow_bearish():
    """Even if total_call_vol/total_put_vol are unavailable (old data, or a
    provider that never fills them), the pc_ratio fallback must invert
    correctly instead of passing PUT/CALL straight through as if it were
    CALL/PUT — this is the second half of the original bug."""
    oi = OptionsIntelligence()
    chain = _heavy_put_chain()
    flow_summary = oi.compute_flow_summary("TESTPUT", chain)

    # Simulate the pre-fix producer: strip the newly-exposed volume keys so
    # _build_snapshot() is forced down the pc_ratio fallback branch, while the
    # PUT/CALL ratio itself (the only signal the fallback ever had) survives.
    flow_summary_no_vols = dict(flow_summary)
    flow_summary_no_vols.pop("total_call_vol", None)
    flow_summary_no_vols.pop("total_put_vol", None)
    scan_result = {"flow_summary": flow_summary_no_vols, "sweeps": []}

    snap = _build_snapshot("TESTPUT", chain, scan_result)

    assert snap is not None
    # pc_ratio (PUT/CALL) was 10.0 → correctly inverted call_put_vol_ratio (CALL/PUT) is 0.1
    assert abs(snap.call_put_vol_ratio - 0.1) < 1e-9, snap
    assert snap.call_put_vol_ratio < 0.8, "must be in the BEARISH band for the thesis check below"

    thesis = _generate_thesis(
        "TESTPUT", "WHALE_PRINT", snap, mean=1.0, current=3.0, z=3.0,
        supporting={"size_class": "WHALE", "premium": 500_000},
    )
    assert "BEARISH" in thesis, thesis
    assert "BULLISH" not in thesis, thesis
    print(f"PASS: fallback path now correctly inverts PUT/CALL into CALL/PUT — ratio={snap.call_put_vol_ratio:.3f}")


def test_heavy_call_flow_still_labels_bullish_both_paths():
    """Sanity check the fix didn't break the opposite (correct) case."""
    def contract(vol, oi=1000, iv=30.0, last=1.5, bid=1.4, ask=1.6, delta=0.3, gamma=0.02):
        return {"totalVolume": vol, "openInterest": oi, "volatility": iv,
                "lastPrice": last, "bid": bid, "ask": ask, "delta": delta, "gamma": gamma}

    chain = {
        "callExpDateMap": {"2026-08-15:26": {"100": [contract(vol=5000)]}},
        "putExpDateMap": {"2026-08-15:26": {"100": [contract(vol=500, delta=-0.3)]}},
    }
    oi = OptionsIntelligence()
    flow_summary = oi.compute_flow_summary("TESTCALL", chain)
    scan_result = {"flow_summary": flow_summary, "sweeps": []}
    snap = _build_snapshot("TESTCALL", chain, scan_result)

    assert snap.call_put_vol_ratio > 1.2, snap
    thesis = _generate_thesis(
        "TESTCALL", "WHALE_PRINT", snap, mean=1.0, current=3.0, z=3.0,
        supporting={"size_class": "WHALE", "premium": 500_000},
    )
    assert "BULLISH" in thesis, thesis
    print(f"PASS: heavy call flow still correctly labeled BULLISH — ratio={snap.call_put_vol_ratio:.3f}")


if __name__ == "__main__":
    test_compute_flow_summary_now_exposes_real_call_and_put_volume()
    test_build_snapshot_root_cause_path_labels_heavy_put_flow_bearish()
    test_build_snapshot_fallback_path_still_labels_heavy_put_flow_bearish()
    test_heavy_call_flow_still_labels_bullish_both_paths()
    print("\nAll regression tests passed.")
