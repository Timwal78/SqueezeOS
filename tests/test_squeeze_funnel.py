"""
Tests for squeeze_funnel.py — the gate-rejection diagnostics.

The point of this module is to answer "which gate is killing my squeeze
setups", so the tests that matter most are:

  1. classify() reads the REAL as_dict() key names. The first draft of this
     module guessed them ("composite", "rsi", "short_interest") and every one
     was wrong — which would have made every row report a zero composite and a
     uniform, false "composite_below_threshold". A silently-wrong diagnostic
     is worse than none, so this is pinned against the real engine output.
  2. classify() agrees with analyze()'s own fire/no-fire decision. classify()
     is a deliberately separate reading of the same fields (so the diagnostic
     can never alter the trading decision), which means the two could drift.
     This pins them together.

Real, unmodified production code; only the four true data-source boundaries
are stubbed.
Run:  python3 tests/test_squeeze_funnel.py
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SQUEEZE_FUNNEL_JSON_PATH"] = "/tmp/_test_squeeze_funnel.json"
os.environ["SQUEEZE_FUNNEL_ENABLED"] = "true"
os.environ.pop("REDIS_URL", None)

import squeeze_funnel as sf                    # noqa: E402
import squeeze_fuel_engine as sfe              # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{('  — ' + detail) if detail and not cond else ''}")


def _clean():
    sf._rows = []
    sf._loaded = True
    for p in ("/tmp/_test_squeeze_funnel.json",):
        if os.path.exists(p):
            os.remove(p)


def _real_analyze(**kw):
    """Run the REAL analyze() with the four data boundaries stubbed."""
    # Return shapes read off compute_fuel()'s real unpacking, not assumed:
    #   _ignition_score      -> (score, available, direction)
    #   _ftd_fuel_score      -> (score, available, on_threshold_list)
    #   _short_vol_fuel_score-> (score, available)
    #   _gamma_amp_score     -> (score, available, regime)
    defaults = dict(
        ignition=(0.0, False, "NEUTRAL"), ftd=(0.0, False, False),
        shortvol=(0.0, False), gamma=(0.0, False, None),
        #   _rsi_confirmation    -> (confirmed, value, available)
        #   _flow_confirmation   -> (confirmed, type, severity, available)
        rsi=(False, None, False), flow=(False, None, None, False),
    )
    defaults.update(kw)
    with patch.object(sfe, "_ignition_score", return_value=defaults["ignition"]), \
         patch.object(sfe, "_ftd_fuel_score", return_value=defaults["ftd"]), \
         patch.object(sfe, "_short_vol_fuel_score", return_value=defaults["shortvol"]), \
         patch.object(sfe, "_gamma_amp_score", return_value=defaults["gamma"]), \
         patch.object(sfe, "_rsi_confirmation", return_value=defaults["rsi"]), \
         patch.object(sfe, "_flow_confirmation", return_value=defaults["flow"]):
        return sfe.analyze("TEST")


# ── The key-name pin ──────────────────────────────────────────────────────────
def test_classify_reads_real_key_names():
    print("\n[1] classify() reads the REAL as_dict() keys (not guessed ones)")
    result = _real_analyze()
    row = sf.classify(result, sfe.ENTRY_THRESHOLD)

    check("composite read from 'composite_score'",
          row["composite"] == result["composite_score"],
          f"row={row['composite']} real={result['composite_score']}")

    # Every gate key classify() depends on must actually exist in as_dict().
    for key in ("composite_score", "rsi_confirmation", "flow_confirmation",
                "short_interest_check", "earnings_blackout_check", "iv_rank_check"):
        check(f"as_dict() really has '{key}'", key in result)

    for key in ("ignition", "ftd_fuel", "short_volume_fuel", "gamma_amplifier"):
        check(f"component key '{key}' exists", key in result)

    # And the component readings must be the real scores, not None.
    comps = row["components"]
    check("component values are read, not None",
          all(comps[k]["value"] is not None for k in ("ignition", "ftd", "short_vol", "gamma")),
          str(comps))


def test_classify_agrees_with_analyze_decision():
    print("\n[2] classify() agrees with analyze()'s own fire/no-fire call")
    cases = [
        ("all sources dead", {}),
        ("ignition only", {"ignition": (40.0, True, "BULLISH")}),
        ("full score, gates unconfirmed", {
            "ignition": (40.0, True, "BULLISH"), "ftd": (20.0, True, True),
            "shortvol": (20.0, True), "gamma": (20.0, True, "SHORT_GAMMA")}),
    ]
    for label, kw in cases:
        result = _real_analyze(**kw)
        row = sf.classify(result, sfe.ENTRY_THRESHOLD)
        engine_fired = result.get("action") == "BUY"
        check(f"{label}: classify fired=={engine_fired}", row["fired"] == engine_fired,
              f"classify={row['fired']} engine={engine_fired} gate={row['gate']}")

    # A genuinely FIRING case. Without this the agreement pin is vacuous — a
    # classify() hardwired to return False would pass every case above, since
    # the RSI and flow gates fail closed on absent data and nothing fires.
    firing = _real_analyze(
        ignition=(40.0, True, "BULLISH"), ftd=(20.0, True, True),
        shortvol=(20.0, True), gamma=(20.0, True, "SHORT_GAMMA"),
        rsi=(True, 53.7, True), flow=(True, "WHALE_PRINT", "HIGH", True),
    )
    row = sf.classify(firing, sfe.ENTRY_THRESHOLD)
    check("the real engine actually fires in this case", firing.get("action") == "BUY",
          f"action={firing.get('action')}")
    check("classify agrees it fired", row["fired"] is True, f"gate={row['gate']}")
    check("gate recorded as FIRED", row["gate"] == sf.FIRED, row["gate"])


# ── Gate attribution ──────────────────────────────────────────────────────────
def _synthetic(composite, direction="BULLISH", rsi=(True, True), flow=(True, True),
               si_blocked=False, earn_blocked=False, ivr_blocked=False):
    """A minimal as_dict()-shaped result for precise gate-attribution tests."""
    return {
        "composite_score": composite,
        "direction": direction,
        "rsi_confirmation": {"confirmed": rsi[0], "available": rsi[1]},
        "flow_confirmation": {"confirmed": flow[0], "available": flow[1]},
        "short_interest_check": {"blocked": si_blocked},
        "earnings_blackout_check": {"blocked": earn_blocked},
        "iv_rank_check": {"blocked": ivr_blocked},
        "ignition": {"score": 0, "available": True},
        "ftd_fuel": {"score": 0, "available": True},
        "short_volume_fuel": {"score": 0, "available": False},
        "gamma_amplifier": {"score": 0, "available": True},
    }


def test_first_blocking_gate_attribution():
    print("\n[3] Each rejection attributes to exactly one gate, in engine order")
    T = 70.0
    check("low composite", sf.classify(_synthetic(50), T)["gate"] == sf.GATE_COMPOSITE)
    check("bearish direction", sf.classify(_synthetic(80, direction="BEARISH"), T)["gate"] == sf.GATE_DIRECTION)
    check("rsi unconfirmed", sf.classify(_synthetic(80, rsi=(False, True)), T)["gate"] == sf.GATE_RSI)
    check("flow unconfirmed", sf.classify(_synthetic(80, flow=(False, True)), T)["gate"] == sf.GATE_FLOW)
    check("short interest weak", sf.classify(_synthetic(80, si_blocked=True), T)["gate"] == sf.GATE_SHORT_INT)
    check("earnings blackout", sf.classify(_synthetic(80, earn_blocked=True), T)["gate"] == sf.GATE_EARNINGS)
    check("iv rank out of band", sf.classify(_synthetic(80, ivr_blocked=True), T)["gate"] == sf.GATE_IV_RANK)
    check("all clear fires", sf.classify(_synthetic(80), T)["gate"] == sf.FIRED)

    # Precedence: composite is checked first even when later gates also fail.
    row = sf.classify(_synthetic(50, direction="BEARISH", rsi=(False, False)), T)
    check("earliest gate wins when several fail", row["gate"] == sf.GATE_COMPOSITE)
    check("but full gate state is still recorded",
          row["gates"][sf.GATE_DIRECTION] is False and row["gates"][sf.GATE_RSI] is False)


def test_no_data_vs_real_rejection():
    print("\n[4] 'No data' and 'data said no' are counted separately")
    T = 70.0
    nd = sf.classify(_synthetic(80, rsi=(False, False)), T)
    sn = sf.classify(_synthetic(80, rsi=(False, True)), T)
    check("unavailable -> no_real_data", nd["fail_reasons"][sf.GATE_RSI] == "no_real_data")
    check("available but false -> real_data_said_no",
          sn["fail_reasons"][sf.GATE_RSI] == "real_data_said_no")
    ok = sf.classify(_synthetic(80), T)
    check("confirmed -> no failure reason", ok["fail_reasons"][sf.GATE_RSI] is None)


def test_near_miss_distance():
    print("\n[5] Near-miss distance turns 'nothing fired' into a number")
    row = sf.classify(_synthetic(67.5), 70.0)
    check("distance computed", row["distance_to_threshold"] == 2.5, str(row["distance_to_threshold"]))
    fired = sf.classify(_synthetic(72.0), 70.0)
    check("negative distance when over the line", fired["distance_to_threshold"] == -2.0)


# ── Recording + summary ───────────────────────────────────────────────────────
def test_record_and_summary():
    print("\n[6] Recording and the summary report")
    _clean()
    T = 70.0
    for _ in range(10):
        sf.record("AAA", _synthetic(50), T)             # composite blocks
    for _ in range(5):
        sf.record("BBB", _synthetic(80, flow=(False, False)), T)   # flow, no data
    sf.record("CCC", _synthetic(80), T)                 # fires

    s = sf.summary()
    check("all evaluations counted", s["total_evaluations"] == 16, str(s["total_evaluations"]))
    check("one fire recorded", s["fired"] == 1, str(s["fired"]))
    check("top blocker is composite", s["top_blocker"]["gate"] == sf.GATE_COMPOSITE,
          str(s["top_blocker"]))
    check("blocker counts sum to non-fires",
          sum(v["count"] for v in s["blocked_by"].values()) == 15,
          str(s["blocked_by"]))
    check("flow no-data reason counted",
          s["fail_closed_reasons"][sf.GATE_FLOW]["no_real_data"] == 5,
          str(s["fail_closed_reasons"][sf.GATE_FLOW]))
    check("dead component surfaced as 0% available",
          s["component_availability"]["short_vol"]["available_pct"] == 0.0,
          str(s["component_availability"]["short_vol"]))
    check("backend disclosed", "backend" in s and s["backend"].startswith("local_json"))
    check("interpretation mentions the dead axis",
          any("Short-volume" in line for line in s["interpretation"]),
          str(s["interpretation"]))


def test_summary_with_zero_fires_says_so_plainly():
    print("\n[7] Zero fires is stated explicitly, not left to inference")
    _clean()
    for _ in range(30):
        sf.record("AAA", _synthetic(68), 70.0)
    s = sf.summary(near_miss_points=5.0)
    check("fire rate is 0", s["fire_rate_pct"] == 0.0)
    check("interpretation says ZERO fires",
          any("ZERO fires" in line for line in s["interpretation"]), str(s["interpretation"]))
    check("near misses counted", s["near_misses"]["count"] == 30, str(s["near_misses"]))


def test_empty_state_is_honest():
    print("\n[8] No data reports no data — never a fabricated report")
    _clean()
    s = sf.summary()
    check("status is no_data", s["status"] == "no_data")
    check("total is 0", s["total_evaluations"] == 0)
    check("explains that an empty window is itself a finding",
          "not running" in s["message"])


def test_recording_never_raises():
    print("\n[9] A diagnostic must never break the loop it measures")
    _clean()
    raised = False
    try:
        sf.record("X", None, 70.0)
        sf.record("X", {"garbage": True}, 70.0)
        sf.record(None, _synthetic(80), 70.0)
    except Exception:
        raised = True
    check("malformed input never raises into the scanner", raised is False)


def test_disabled_is_a_no_op():
    print("\n[10] Disabling stops recording entirely")
    _clean()
    os.environ["SQUEEZE_FUNNEL_ENABLED"] = "false"
    try:
        check("record returns None when disabled", sf.record("X", _synthetic(80), 70.0) is None)
        check("nothing was stored", len(sf._rows) == 0)
    finally:
        os.environ["SQUEEZE_FUNNEL_ENABLED"] = "true"


def test_rolling_cap():
    print("\n[11] The window is capped, not unbounded")
    _clean()
    os.environ["SQUEEZE_FUNNEL_MAX_ROWS"] = "100"
    try:
        for _ in range(150):
            sf.record("A", _synthetic(50), 70.0)
        check("rows capped at the configured max", len(sf._rows) == 100, str(len(sf._rows)))
    finally:
        os.environ.pop("SQUEEZE_FUNNEL_MAX_ROWS", None)


def test_blueprint_route_registered():
    print("\n[12] /api/squeeze-fuel/funnel is reachable and not shadowed")
    import core.api.squeeze_fuel_bp as bp
    rules = [r.rule for r in bp.squeeze_fuel_bp.deferred_functions] if False else None
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "api", "squeeze_fuel_bp.py")).read()
    check("funnel route defined", '@squeeze_fuel_bp.route("/funnel"' in src)
    # It must appear BEFORE the /<symbol> catch-all in the file.
    check("registered before the /<symbol> catch-all",
          src.index('route("/funnel"') < src.index('route("/<symbol>"'))
    check("scanner records into the funnel",
          "squeeze_funnel.record" in open(
              os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "squeeze_fuel_scanner.py")).read())


def test_reset():
    print("\n[13] reset() clears the window for a clean re-measurement")
    _clean()
    for _ in range(5):
        sf.record("A", _synthetic(50), 70.0)
    r = sf.reset()
    check("reports how many were cleared", r["cleared"] == 5, str(r))
    check("window is empty", sf.summary()["total_evaluations"] == 0)


if __name__ == "__main__":
    print("=" * 72)
    print("Squeeze funnel diagnostics tests")
    print("=" * 72)
    for fn in [test_classify_reads_real_key_names, test_classify_agrees_with_analyze_decision,
               test_first_blocking_gate_attribution, test_no_data_vs_real_rejection,
               test_near_miss_distance, test_record_and_summary,
               test_summary_with_zero_fires_says_so_plainly, test_empty_state_is_honest,
               test_recording_never_raises, test_disabled_is_a_no_op, test_rolling_cap,
               test_blueprint_route_registered, test_reset]:
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append(fn.__name__)
            print(f"  ❌ {fn.__name__} raised: {e}")
            traceback.print_exc()

    _clean()
    print("\n" + "=" * 72)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("Failures: " + ", ".join(FAIL))
    print("=" * 72)
    sys.exit(1 if FAIL else 0)
