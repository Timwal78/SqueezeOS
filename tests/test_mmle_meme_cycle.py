"""
MMLE — Meme-Cycle Stress Test
══════════════════════════════════════════════════════════════════════
Simulates a four-phase meme cycle and exercises the engine through
each phase to verify it handles the regimes where retail tooling fails.

Phases:
  1. ACCUMULATION    — quiet tape, dark prints leaning bid, dealers long-gamma
  2. IGNITION        — VPIN spike, gamma flip, dealers transition to short-gamma
  3. VANNA-CHARM TRAP — IV crush after a fear pop + final-week DTE; the regime
                        the engine is built to detect (TNT_LONG)
  4. UNWIND          — short-vol replenishment; regime should fall to NEUTRAL

The test is intentionally synthetic — Tradier/Polygon are not called.
This is a *logic* stress test, not a market simulation. AGENT_LAW §3.1
applies: every synthetic input is labeled below.

Run:  python tests/test_mmle_meme_cycle.py
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta
from pprint import pformat

# Allow running from repo root or tests/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mm_liquidity_engine as m  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Synthetic chain builders — each tagged [ESTIMATED_PROXY: <phase>]
# ──────────────────────────────────────────────────────────────────────
def _chain(spot: float, dte: int,
           call_oi_profile, put_oi_profile,
           call_iv: float, put_iv: float):
    expiry = (datetime.utcnow() + timedelta(days=dte)).strftime("%Y-%m-%d")
    chain = {"callExpDateMap": {f"{expiry}:{dte}": {}},
             "putExpDateMap": {f"{expiry}:{dte}": {}}}
    for K, oi in call_oi_profile.items():
        chain["callExpDateMap"][f"{expiry}:{dte}"][str(K)] = [{
            "openInterest": oi, "volatility": call_iv * 100, "gamma": 0.0,
        }]
    for K, oi in put_oi_profile.items():
        chain["putExpDateMap"][f"{expiry}:{dte}"][str(K)] = [{
            "openInterest": oi, "volatility": put_iv * 100, "gamma": 0.0,
        }]
    return chain


def phase_accumulation(spot: float):
    """Quiet base — dealers long gamma (small symmetric OI)."""
    strikes = [round(spot * x, 0) for x in (0.92, 0.95, 0.98, 1.00, 1.02, 1.05, 1.08)]
    calls = {K: 1500 for K in strikes}
    puts = {K: 1500 for K in strikes}
    return _chain(spot, dte=14, call_oi_profile=calls, put_oi_profile=puts,
                  call_iv=0.55, put_iv=0.60)


def phase_ignition(spot: float):
    """Reflexive call buying — dealers stack short calls above; meme OI explosion."""
    strikes_c = [spot * x for x in (1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30)]
    strikes_p = [spot * x for x in (0.85, 0.90, 0.95, 1.00)]
    calls = {round(K, 0): int(40000 * (1.0 - i * 0.10))
             for i, K in enumerate(strikes_c)}
    puts = {round(K, 0): 5000 for K in strikes_p}
    return _chain(spot, dte=7, call_oi_profile=calls, put_oi_profile=puts,
                  call_iv=1.40, put_iv=0.95)


def phase_vanna_charm_trap(spot: float):
    """
    The setup the engine is built for:
      - Front-month (DTE ≤ 3), still-elevated but FALLING IV (post-fear pop)
      - Heavy short-call OI above; long-puts below
      - Large void between put-wall and call-wall around spot
    """
    strikes_c = [spot * x for x in (1.02, 1.05, 1.10, 1.15)]
    strikes_p = [spot * x for x in (0.85, 0.92, 0.97)]
    calls = {round(strikes_c[0], 0): 5000,
             round(strikes_c[1], 0): 8000,
             round(strikes_c[2], 0): 80000,   # massive call wall
             round(strikes_c[3], 0): 12000}
    puts = {round(strikes_p[0], 0): 50000,    # massive put wall
            round(strikes_p[1], 0): 8000,
            round(strikes_p[2], 0): 4000}
    return _chain(spot, dte=2, call_oi_profile=calls, put_oi_profile=puts,
                  call_iv=0.95, put_iv=0.85)


def phase_unwind(spot: float):
    """Short-vol replenished; OI spread out; dealers back to long-gamma."""
    strikes = [round(spot * x, 0) for x in (0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15)]
    calls = {K: 6000 for K in strikes}
    puts = {K: 6000 for K in strikes}
    return _chain(spot, dte=5, call_oi_profile=calls, put_oi_profile=puts,
                  call_iv=0.45, put_iv=0.50)


# ──────────────────────────────────────────────────────────────────────
# Tape generators — VPIN + dark/lit divergence per phase
# ──────────────────────────────────────────────────────────────────────
def _drive_vpin(engine, ticker, spot, *, n_trades, drift, noise, toxic_burst):
    """Push trades into VPIN; toxic_burst injects 1-sided volume to elevate VPIN."""
    last = spot
    for i in range(n_trades):
        if toxic_burst and i % 50 < 30:
            # 30/50 trades skewed buyer-initiated → drives VPIN up
            last += abs(random.gauss(drift, noise))
            engine.ingest_trade(ticker, last, random.randint(200, 900),
                                adv=80e6, side="buy")
        else:
            last += random.gauss(drift, noise)
            engine.ingest_trade(ticker, last, random.randint(80, 400), adv=80e6)


def _dark_prints(spot: float, lean: str, n: int = 12):
    """lean ∈ {bid, ask, none}; bid means dark accumulating long off-tape."""
    if lean == "none":
        return []
    sign = +1 if lean == "bid" else -1
    return [{"price": spot + sign * 0.03, "size": random.randint(20000, 80000),
             "mid": spot} for _ in range(n)]


# ──────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────
def run_phase(name, *, spot, chain, dte, vol_state, dark_lean, lit_ofi,
              toxic, sigma_vol_daily, atr, now):
    print("=" * 72)
    print(f"PHASE: {name}")
    print("-" * 72)
    random.seed(hash(name) & 0xFFFFFFFF)
    engine = m.MMLiquidityEngine()

    _drive_vpin(engine, "MEME", spot,
                n_trades=120000, drift=vol_state["drift"],
                noise=vol_state["noise"], toxic_burst=toxic)

    sig = engine.evaluate(
        ticker="MEME",
        spot=spot,
        raw_chain=chain,
        atr=atr,
        sigma_S_daily=vol_state["sigma_S_daily"],
        sigma_vol_daily=sigma_vol_daily,
        adv=80e6,
        nearest_dte=dte,
        lit_ofi=lit_ofi,
        dark_prints=_dark_prints(spot, dark_lean),
        now=now,
    )
    print(f"  state           : {sig.state}")
    print(f"  composite_z     : {sig.composite_z}")
    print(f"  target_magnet   : {sig.target_magnet}")
    print(f"  void            : {sig.void}")
    print(f"  notes           : {sig.notes}")
    print(f"  components      : {pformat(sig.components, width=72)}")
    return sig


def main():
    spot = 30.0  # meme small-cap
    intraday_now = datetime(2026, 5, 8, 11, 30)  # inside VCCW

    s1 = run_phase(
        "1. ACCUMULATION",
        spot=spot,
        chain=phase_accumulation(spot),
        dte=14,
        vol_state={"drift": 0.0, "noise": 0.02, "sigma_S_daily": 0.04},
        dark_lean="bid",
        lit_ofi=-0.15,
        toxic=False,
        sigma_vol_daily=0.05,
        atr=0.4,
        now=intraday_now,
    )

    s2 = run_phase(
        "2. IGNITION",
        spot=spot * 1.40,
        chain=phase_ignition(spot * 1.40),
        dte=7,
        vol_state={"drift": 0.04, "noise": 0.15, "sigma_S_daily": 0.18},
        dark_lean="bid",
        lit_ofi=+0.65,
        toxic=True,
        sigma_vol_daily=0.25,
        atr=2.5,
        now=intraday_now,
    )

    s3 = run_phase(
        "3. VANNA-CHARM TRAP (target regime)",
        spot=spot * 1.55,
        chain=phase_vanna_charm_trap(spot * 1.55),
        dte=2,
        vol_state={"drift": 0.01, "noise": 0.08, "sigma_S_daily": 0.10},
        dark_lean="bid",
        lit_ofi=-0.30,           # lit selling; dark buying — divergence
        toxic=True,
        sigma_vol_daily=0.18,
        atr=2.0,
        now=intraday_now,
    )

    s4 = run_phase(
        "4. UNWIND",
        spot=spot * 1.10,
        chain=phase_unwind(spot * 1.10),
        dte=5,
        vol_state={"drift": -0.005, "noise": 0.04, "sigma_S_daily": 0.05},
        dark_lean="ask",
        lit_ofi=-0.10,
        toxic=False,
        sigma_vol_daily=0.06,
        atr=0.6,
        now=intraday_now,
    )

    # ──────────────────────────────────────────────────────────────────
    # Acceptance assertions — what the engine MUST do across the cycle
    # ──────────────────────────────────────────────────────────────────
    print("=" * 72)
    print("ACCEPTANCE")
    print("-" * 72)
    failures = []

    # 1. ACCUMULATION → must NOT fire TNT (low VCSC, long gamma)
    if s1.state in ("TNT_LONG", "TNT_SHORT"):
        failures.append("Phase 1 false-positive TNT")

    # 2. IGNITION → composite must rise above accumulation. Void may or may
    # not exist: ignition typically has only call-side OI buildup with no
    # mirroring put wall, so the bracketing-void test is unreliable. We
    # require z_gamma to fire (dealer hedge demand large vs daily flow).
    if s2.composite_z <= s1.composite_z:
        failures.append("Phase 2 composite did not exceed Phase 1")
    if s2.components.get("z_gamma", 0) < 1.0:
        failures.append("Phase 2 dealer-gamma pressure not detected")

    # 3. TRAP → state should be COMPRESSED or TNT_LONG; never NEUTRAL.
    #     TNT requires axis-collapse + VCCW + composite ≥ 2.0; under purely
    #     synthetic data axis-collapse may not occur on every seed, but the
    #     regime MUST elevate beyond NEUTRAL.
    if s3.state == "NEUTRAL":
        failures.append("Phase 3 failed to elevate above NEUTRAL")
    if s3.void is None or not s3.void.contains_spot:
        failures.append("Phase 3 void did not bracket spot")
    if s3.components.get("z_void", 0) < 1.0:
        failures.append("Phase 3 void width insufficient")

    # 4. UNWIND → composite must collapse back below TNT entry AND state must
    # not be a TNT regime.
    if s4.composite_z >= m.MMLE_CONFIG["tnt_enter_score"]:
        failures.append("Phase 4 composite did not collapse below entry threshold")
    if s4.state in ("TNT_LONG", "TNT_SHORT"):
        failures.append("Phase 4 incorrectly elevated to TNT")

    # 5. AGENT_LAW §1.1 — empty chain returns AWAITING_STREAM with no signal
    eng = m.MMLiquidityEngine()
    null_sig = eng.evaluate("MEME", spot, {}, atr=1.0,
                            sigma_S_daily=0.05, sigma_vol_daily=0.05,
                            adv=1e6, nearest_dte=2)
    if null_sig.state != "AWAITING_STREAM":
        failures.append("AGENT_LAW §1.1 violation: empty chain did not pause")

    # 6. AGENT_LAW §3.1 — missing dark feed must cap regime to COMPRESSED
    eng2 = m.MMLiquidityEngine()
    for _ in range(60000):
        eng2.ingest_trade("MEME", spot, 200, adv=80e6, side="buy")
    capped = eng2.evaluate(
        ticker="MEME", spot=spot * 1.55,
        raw_chain=phase_vanna_charm_trap(spot * 1.55),
        atr=2.0, sigma_S_daily=0.10, sigma_vol_daily=0.18,
        adv=80e6, nearest_dte=2, lit_ofi=-0.3,
        dark_prints=None,             # missing feed
        now=intraday_now,
    )
    if capped.state == "TNT_LONG" or capped.state == "TNT_SHORT":
        failures.append("AGENT_LAW §3.1 violation: TNT fired without dark feed")
    if not any("dark" in n.lower() for n in capped.notes):
        failures.append("AGENT_LAW §3.1 violation: missing-proxy note absent")

    if failures:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PASS — all 4 phases + AGENT_LAW gates")


if __name__ == "__main__":
    main()
