"""
CIE — Cycle Intelligence Engine: Four-Layer Stress Test
══════════════════════════════════════════════════════════════════════
Exercises each layer independently and then validates the cross-layer
CIE_FIRE convergence signal across a synthetic meme-cycle run.

All synthetic inputs are labeled per AGENT_LAW §3.1.
Run:  python tests/test_cie_cycle.py
"""
from __future__ import annotations

import math
import os
import random
import sys
from datetime import date, timedelta
from pprint import pformat

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cycle_intelligence_engine as cie


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _dark_prints(spot: float, lean: str, n: int = 15) -> list:
    """[ESTIMATED_PROXY: synthetic dark prints] lean ∈ {bid, ask, neutral}"""
    if lean == "neutral":
        return []
    sign = +1 if lean == "bid" else -1
    return [
        {"price": spot + sign * 0.05, "size": random.randint(15000, 60000), "mid": spot}
        for _ in range(n)
    ]


def _price_series(start: float, n: int, drift: float, noise: float) -> list:
    """[ESTIMATED_PROXY: synthetic price series]"""
    prices = [start]
    for _ in range(n):
        prices.append(max(0.01, prices[-1] * (1 + random.gauss(drift, noise))))
    return prices


def _log_returns(prices: list) -> list:
    return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]


def _vol_series(adv: float, n: int, ratio: float, noise: float) -> list:
    """[ESTIMATED_PROXY: synthetic volume series]"""
    return [max(1.0, adv * ratio * (1 + random.gauss(0, noise))) for _ in range(n)]


# ──────────────────────────────────────────────────────────────
# Layer 1: Settlement Cycle Engine
# ──────────────────────────────────────────────────────────────
def test_settlement():
    print("=" * 68)
    print("LAYER 1: Settlement Cycle Engine")
    print("-" * 68)
    failures = []
    sce = cie.SettlementCycleEngine()
    today = date(2026, 5, 12)

    # 1a. No data → pressure_score should be 0, notes should flag proxy
    s0 = sce.evaluate("GME", today)
    print(f"  no-data state: score={s0.pressure_score} notes={s0.notes}")
    if s0.pressure_score != 0.0:
        failures.append("1a: no-data score should be 0.0")
    if not any("ftd_velocity_unavailable" in n for n in s0.notes):
        failures.append("1a: missing proxy note for ftd_velocity")

    # 1b. High FTD velocity → score should be elevated
    base_float = 300_000_000
    for i in range(5):
        sce.update_ftd("GME", today - timedelta(days=5 - i),
                       ftd_shares=int(base_float * 0.007),  # 0.7% > sett_ftd_high_pct
                       float_shares=base_float)
    s1 = sce.evaluate("GME", today)
    print(f"  high-FTD state: score={s1.pressure_score} vel={s1.ftd_velocity}")
    if s1.pressure_score < 0.5:
        failures.append(f"1b: high FTD should raise score above 0.5, got {s1.pressure_score}")

    # 1c. Threshold + T+35 proximity → score should be near max for SCE
    sce.update_threshold_status("GME", on_list=True,
                                since_date=today - timedelta(days=30))
    sce.update_ctb("GME", 0.45)   # 45% > sett_ctb_htb_pct (30%)
    s2 = sce.evaluate("GME", today)
    print(f"  full-pressure state: score={s2.pressure_score} t35_rem={s2.t35_days_remaining}")
    if s2.pressure_score < 1.0:
        failures.append(f"1c: full pressure should be ≥ 1.0, got {s2.pressure_score}")
    if s2.pressure_score > 1.5:
        failures.append(f"1c: score capped at 1.5, got {s2.pressure_score}")

    return failures


# ──────────────────────────────────────────────────────────────
# Layer 2: Dark Pool Cycle Analyzer
# ──────────────────────────────────────────────────────────────
def test_dark_pool():
    print("=" * 68)
    print("LAYER 2: Dark Pool Cycle Analyzer")
    print("-" * 68)
    failures = []
    random.seed(42)

    # 2a. Empty analyzer → AWAITING_STREAM behavior
    dpca = cie.DarkPoolCycleAnalyzer(ticker="AMC")
    d0 = dpca.evaluate()
    print(f"  empty state: oer={d0.oer} score={d0.pressure_score}")
    if d0.pressure_score != 0.0:
        failures.append("2a: empty DPCA should have score=0")
    if d0.oer is not None:
        failures.append("2a: empty DPCA oer should be None")

    # 2b. Sustained bid-lean dark accumulation → high HOI, cluster, high score
    spot = 15.0
    for _ in range(20):
        dpca.ingest_bar(
            dark_prints=_dark_prints(spot, "bid", n=20),
            lit_volume=500_000,
            spot=spot,
        )
    d1 = dpca.evaluate()
    print(f"  bid-lean state: oer={d1.oer} hoi={d1.hoi} dlmd={d1.dlmd} "
          f"cluster={d1.cluster_bars} score={d1.pressure_score}")
    if d1.hoi is None or d1.hoi < 0.55:
        failures.append(f"2b: bid-lean HOI should be ≥ 0.55, got {d1.hoi}")
    if not d1.cluster_active:
        failures.append("2b: sustained bid-lean should activate cluster")
    if d1.pressure_score < 0.8:
        failures.append(f"2b: bid-lean pressure should be ≥ 0.8, got {d1.pressure_score}")

    # 2c. Ask-lean → DLMD should be negative
    dpca2 = cie.DarkPoolCycleAnalyzer(ticker="AMC2")
    for _ in range(20):
        dpca2.ingest_bar(
            dark_prints=_dark_prints(spot, "ask", n=20),
            lit_volume=500_000,
            spot=spot,
        )
    d2 = dpca2.evaluate()
    print(f"  ask-lean state: dlmd={d2.dlmd} hoi={d2.hoi}")
    if d2.dlmd >= 0:
        failures.append(f"2c: ask-lean DLMD should be negative, got {d2.dlmd}")

    # 2d. None dark_prints → bar must be skipped (no crash, no invented data)
    dpca3 = cie.DarkPoolCycleAnalyzer(ticker="AMC3")
    for _ in range(5):
        dpca3.ingest_bar(dark_prints=None, lit_volume=100_000, spot=spot)
    d3 = dpca3.evaluate()
    if d3.oer is not None:
        failures.append("2d: None dark_prints should yield oer=None")

    return failures


# ──────────────────────────────────────────────────────────────
# Layer 3: Historical Fractal Matcher
# ──────────────────────────────────────────────────────────────
def test_fractal():
    print("=" * 68)
    print("LAYER 3: Historical Fractal Matcher")
    print("-" * 68)
    failures = []
    random.seed(7)
    cfg = dict(cie.CIE_CONFIG)
    w = cfg["hfm_window"]

    hfm = cie.HistoricalFractalMatcher(cfg=cfg, ticker="GME")

    # 3a. Unfilled window → AWAITING_STREAM
    f0 = hfm.evaluate()
    print(f"  unfilled: window_bars={f0.window_bars} score={f0.pressure_score}")
    if f0.pressure_score != 0.0:
        failures.append("3a: unfilled window score should be 0")

    # 3b. Add a known historical signature and feed a close-match current window
    template_rets = [random.gauss(0.005, 0.02) for _ in range(w)]
    template_vols = [random.gauss(1.0, 0.1) for _ in range(w)]
    template_ivs = [random.gauss(0.8, 0.05) for _ in range(w)]
    hfm.add_historical_signature(
        label="2024-05-10",
        price_returns=template_rets,
        volume_ratios=template_vols,
        iv_series=template_ivs,
        forward_return=0.14,   # +14% forward return
    )

    # Feed a nearly-identical current window (same template ± small noise)
    fake_close = 30.0
    for i in range(w + 1):
        noise = random.gauss(0, 0.003)
        vol_noise = random.gauss(0, 0.05)
        iv_noise = random.gauss(0, 0.01)
        r = (template_rets[i - 1] + noise) if i > 0 else 0.0
        fake_close *= math.exp(r)
        v = max(1.0, (template_vols[i - 1] if i > 0 else 1.0) + vol_noise) * 1_000_000
        iv = max(0.01, (template_ivs[i - 1] if i > 0 else 0.8) + iv_noise)
        hfm.ingest_bar(close=fake_close, volume=v, iv_atm=iv, adv=1_000_000)

    f1 = hfm.evaluate()
    print(f"  matched: best_sim={f1.best_similarity} score={f1.pressure_score} "
          f"fwd_return={f1.median_forward_return}%")
    if f1.best_similarity < cfg["hfm_min_corr"]:
        failures.append(f"3b: near-identical window should match at ≥ {cfg['hfm_min_corr']}, "
                        f"got {f1.best_similarity}")
    if not f1.top_matches:
        failures.append("3b: top_matches should not be empty for a clear match")
    if f1.pressure_score < 1.0:
        failures.append(f"3b: pressure should be ≥ 1.0 for high similarity, got {f1.pressure_score}")

    # 3c. Empty library → labeled note, score=0
    hfm2 = cie.HistoricalFractalMatcher(cfg=cfg, ticker="AMC")
    for _ in range(w + 1):
        hfm2.ingest_bar(close=5.0, volume=1_000_000, iv_atm=0.6)
    f2 = hfm2.evaluate()
    if f2.pressure_score != 0.0:
        failures.append("3c: empty library should give score=0")
    if not any("library_empty" in n for n in f2.notes):
        failures.append("3c: empty library should emit proxy note")

    return failures


# ──────────────────────────────────────────────────────────────
# Layer 4: Meme Cycle Phase Detector
# ──────────────────────────────────────────────────────────────
def test_meme_cycle():
    print("=" * 68)
    print("LAYER 4: Meme Cycle Phase Detector")
    print("-" * 68)
    failures = []
    random.seed(99)

    mcpd = cie.MemeCycleDetector(ticker="GME")

    # 4a. Low volume (0.3× ADV), low IV → DORMANT
    # Feed a baseline ADV at high volume first, then drop to dormant level
    for _ in range(20):
        mcpd.ingest_bar(volume=1_000_000, iv_atm=0.50)  # establishes ADV=1M, IV history
    for _ in range(5):
        mcpd.ingest_bar(volume=300_000, iv_atm=0.30)    # 0.3× ADV, low IV → DORMANT
    m0 = mcpd.evaluate("NEUTRAL")
    print(f"  dormant: phase={m0.phase} score={m0.phase_score} vol_ratio={m0.volume_ratio}")
    if m0.phase != "DORMANT":
        failures.append(f"4a: low vol/IV should be DORMANT, got {m0.phase}")

    # 4b. Ignition: high volume spike + elevated IV + TNT_LONG
    mcpd2 = cie.MemeCycleDetector(ticker="GME2")
    for _ in range(20):
        mcpd2.ingest_bar(volume=500_000, iv_atm=0.40)   # establish ADV and IV history
    mcpd2.update_short_interest(20.0)   # extreme short interest
    for _ in range(3):
        mcpd2.ingest_bar(volume=3_000_000, iv_atm=0.85)  # 6× ADV spike + high IV
    m1 = mcpd2.evaluate("TNT_LONG")
    print(f"  ignition/parabolic: phase={m1.phase} score={m1.phase_score} "
          f"vol_ratio={m1.volume_ratio} iv_pct={m1.iv_percentile}")
    if m1.phase not in ("IGNITION", "PARABOLIC"):
        failures.append(f"4b: high vol + TNT + extreme SIR should be IGNITION/PARABOLIC, got {m1.phase}")
    if m1.pressure_score < 1.0:
        failures.append(f"4b: ignition/parabolic pressure should be ≥ 1.0, got {m1.pressure_score}")

    # 4c. SIR proxy note when not supplied
    mcpd3 = cie.MemeCycleDetector(ticker="AMC")
    for _ in range(5):
        mcpd3.ingest_bar(volume=1_000_000, iv_atm=0.50)
    m2 = mcpd3.evaluate("NEUTRAL")
    if not any("sir_unavailable" in n for n in m2.notes):
        failures.append("4c: missing SIR should emit proxy note")

    return failures


# ──────────────────────────────────────────────────────────────
# Full CIE convergence test
# ──────────────────────────────────────────────────────────────
def test_convergence():
    print("=" * 68)
    print("FULL CIE: Convergence Signal Test")
    print("-" * 68)
    failures = []
    random.seed(2026)

    engine = cie.CycleIntelligenceEngine()
    ticker = "GME"
    spot = 22.0
    today = date(2026, 5, 12)
    w = cie.CIE_CONFIG["hfm_window"]

    # Prime SCE: threshold list + high FTD + HTB
    base_float = 300_000_000
    for i in range(5):
        engine.ingest_ftd(ticker, today - timedelta(days=5 - i),
                          int(base_float * 0.008), base_float)
    engine.update_threshold_status(ticker, on_list=True,
                                   since_date=today - timedelta(days=28))
    engine.update_ctb(ticker, 0.50)

    # Prime DPCA: 20 bars of bid-lean dark accumulation
    for _ in range(20):
        engine.ingest_dark_bar(ticker, _dark_prints(spot, "bid", 18), 600_000, spot)

    # Prime HFM: add a historical analog then feed close-match current window
    template_rets = [random.gauss(0.004, 0.015) for _ in range(w)]
    template_vols = [random.gauss(1.0, 0.08) for _ in range(w)]
    template_ivs = [random.gauss(0.75, 0.04) for _ in range(w)]
    engine.add_historical_signature(
        ticker, "2024-05-10",
        price_returns=template_rets,
        volume_ratios=template_vols,
        iv_series=template_ivs,
        forward_return=0.30,
    )
    fake_close = spot
    for i in range(w + 1):
        r = (template_rets[i - 1] + random.gauss(0, 0.002)) if i > 0 else 0.0
        fake_close *= math.exp(r)
        v = max(1.0, (template_vols[i - 1] if i > 0 else 1.0) + random.gauss(0, 0.03)) * 1_200_000
        iv = max(0.01, (template_ivs[i - 1] if i > 0 else 0.75) + random.gauss(0, 0.01))
        engine.ingest_price_bar(ticker, fake_close, v, iv, adv=1_200_000)

    # Prime MCPD: establish ADV baseline then spike
    engine.update_short_interest(ticker, 18.0)

    # Evaluate with TNT_LONG (from MMLE, passed in)
    sig = engine.evaluate(ticker, tnt_state="TNT_LONG", today=today)
    print(f"  state          : {sig.state}")
    print(f"  composite_z    : {sig.composite_z}")
    print(f"  components     : {pformat(sig.components, width=68)}")
    print(f"  settlement     : score={sig.settlement.pressure_score if sig.settlement else 'N/A'}")
    print(f"  dark_pool      : score={sig.dark_pool.pressure_score if sig.dark_pool else 'N/A'}")
    print(f"  fractal        : score={sig.fractal.pressure_score if sig.fractal else 'N/A'}")
    print(f"  meme_cycle     : phase={sig.meme_cycle.phase if sig.meme_cycle else 'N/A'} "
          f"score={sig.meme_cycle.pressure_score if sig.meme_cycle else 'N/A'}")

    if sig.composite_z <= 0:
        failures.append("convergence: composite_z should be > 0 with primed inputs")

    # Settlement layer should have fired
    if sig.settlement and sig.settlement.pressure_score < 0.5:
        failures.append(f"convergence: settlement score too low: {sig.settlement.pressure_score}")

    # Dark pool cluster should be active
    if sig.dark_pool and not sig.dark_pool.cluster_active:
        failures.append("convergence: dark pool cluster should be active")

    # AGENT_LAW §1: missing dark feed → score contributions still bounded
    engine2 = cie.CycleIntelligenceEngine()
    for _ in range(25):
        engine2.ingest_dark_bar("MEME", None, 0, 10.0)   # all None — skipped
    sig2 = engine2.evaluate("MEME")
    if sig2.dark_pool and sig2.dark_pool.pressure_score != 0.0:
        failures.append("law §1: None dark prints should produce zero dark score")

    return failures


# ──────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────
def main():
    all_failures = []
    all_failures += test_settlement()
    all_failures += test_dark_pool()
    all_failures += test_fractal()
    all_failures += test_meme_cycle()
    all_failures += test_convergence()

    print("=" * 68)
    print("ACCEPTANCE")
    print("-" * 68)
    if all_failures:
        print("FAIL")
        for f in all_failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PASS — all 4 layers + AGENT_LAW gates + convergence signal")


if __name__ == "__main__":
    main()
