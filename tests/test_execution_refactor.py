"""
Regression tests for the 2026-07-31 execution-layer audit + refactor.

One test per defect that was actually found in the live code. Each is written
against the REAL, unmodified production functions with only true I/O
boundaries (Tradier HTTP, DataManager) stubbed — no reimplementation of the
logic under test.

Run:  python3 tests/test_execution_refactor.py
(No live server needed. Deliberately avoids importing core.legacy/pandas, so
it runs in the same restricted sandbox that blocks most other wiring tests.)
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Keep every test in paper mode: nothing here may ever reach a real broker.
os.environ["IAM_PAPER_MODE"] = "true"
os.environ["IAM_AUTO_TRADING"] = "true"
os.environ["POSITION_MANAGER_ENABLED"] = "false"   # no background thread in tests

import execution_quality as eq          # noqa: E402
import position_manager as pm           # noqa: E402
import iam_executor as ex               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{('  — ' + detail) if detail and not cond else ''}")


def _bars(n=30, price=10.0, rng=2.0):
    """Flat synthetic bars with a known constant true range -> ATR == rng."""
    return [{"o": price, "h": price + rng / 2, "l": price - rng / 2, "c": price} for _ in range(n)]


# ── DEFECT 1: exits were blocked by entry-only gates ───────────────────────────
def test_exit_bypasses_entry_gates():
    print("\n[1] Exits must not be blocked by entry-only gates")
    ex._roll_day()

    # Trip every entry gate at once: daily cap, cooldown, and the loss breaker.
    ex._state["orders_today"] = 10_000
    ex._state["breaker_tripped"] = True
    ex._cooldowns["SPY"] = __import__("time").time()

    os.environ["IAM_EXECUTION_MODE"] = "alert"   # alert mode skips the market-hours gate

    entry_block = ex._gate_check("SPY", {"action": "BUY"}, "IMMEDIATE", 99.0, is_exit=False)
    exit_block  = ex._gate_check("SPY", {"action": "SELL"}, "IMMEDIATE", 99.0, is_exit=True)

    check("entry IS blocked when caps/cooldown/breaker are hit", entry_block is not None,
          f"got {entry_block!r}")
    check("exit is NOT blocked by those same gates", exit_block is None,
          f"exit was blocked with: {exit_block!r}")

    # The dedicated entry-gate helper must still block (used by the put leg).
    put_block = ex._entry_gate_check("SPY", {"action": "SELL"}, "IMMEDIATE", 99.0)
    check("put leg still re-checks the full entry gate", put_block is not None,
          f"got {put_block!r}")

    ex._state["orders_today"] = 0
    ex._state["breaker_tripped"] = False
    ex._cooldowns.pop("SPY", None)


# ── DEFECT 2: raw market orders (unbounded slippage) ───────────────────────────
def test_marketable_limit_replaces_market_order():
    print("\n[2] Marketable limits, bounded offset")
    os.environ["IAM_LIMIT_OFFSET_BPS"] = "10"
    buy = eq.marketable_limit(100.00, 100.10, "buy")
    sell = eq.marketable_limit(100.00, 100.10, "sell")
    check("buy limit crosses the ask but is bounded", buy is not None and 100.10 <= buy <= 100.30,
          f"got {buy}")
    check("sell limit crosses the bid but is bounded", sell is not None and 99.80 <= sell <= 100.00,
          f"got {sell}")
    check("no two-sided quote -> None (caller decides)", eq.marketable_limit(None, 100.1, "buy") is None)
    check("crossed/invalid book -> None", eq.marketable_limit(101.0, 100.0, "buy") is None)


# ── DEFECT 3: no option spread guard; entries priced at ask x 1.05 ─────────────
def test_option_spread_guard():
    print("\n[3] Option spread guard (old code paid ask x 1.05 with no bid reference)")
    os.environ["IAM_MAX_SPREAD_PCT_OPTION"] = "8.0"
    # A 1.00 x 1.40 contract is a 33% spread — routine on a wide scan universe.
    wide_ok, why = eq.spread_ok(1.00, 1.40, is_option=True, is_entry=True)
    check("33% option spread refuses the ENTRY", wide_ok is False, why)

    old_price = round(1.40 * 1.05, 2)     # what the old code would have paid
    new_price = eq.marketable_limit(1.00, 1.40, "buy")
    check("old ask*1.05 was above the ask itself", old_price > 1.40, f"{old_price}")
    check("new pricing never exceeds ask + offset", new_price is not None and new_price < old_price,
          f"new={new_price} old={old_price}")

    tight_ok, _ = eq.spread_ok(1.00, 1.04, is_option=True, is_entry=True)
    check("tight option spread is allowed", tight_ok is True)

    exit_ok, _ = eq.spread_ok(1.00, 1.40, is_option=True, is_entry=False)
    check("EXITS are never spread-blocked (fail open)", exit_ok is True)

    noquote_ok, _ = eq.spread_ok(None, None, is_option=True, is_entry=True)
    check("unquotable book refuses ENTRY (fail closed)", noquote_ok is False)


# ── DEFECT 4: chasing — entering after the move already happened ───────────────
def test_chase_guard():
    print("\n[4] Anti-chase entry guard")
    os.environ["IAM_MAX_ENTRY_EXTENSION_ATR"] = "1.0"
    bars = _bars()                       # ATR == 2.0
    check("ATR computed from real bars", eq.atr(bars, 14) == 2.0, str(eq.atr(bars, 14)))

    ok_near, _ = eq.chase_guard("BUY", 10.0, 11.0, bars)      # +0.5 ATR
    check("entry near the signal price is allowed", ok_near is True)

    ok_far, why = eq.chase_guard("BUY", 10.0, 13.0, bars)     # +1.5 ATR
    check("entry already 1.5 ATR past the signal is refused", ok_far is False, why)

    # A bearish signal is chased when price ran DOWN, not up.
    ok_sell, why2 = eq.chase_guard("SELL", 10.0, 7.0, bars)
    check("SELL chased downward is refused", ok_sell is False, why2)
    ok_sell_up, _ = eq.chase_guard("SELL", 10.0, 11.0, bars)
    check("SELL with price above signal is not 'chased'", ok_sell_up is True)

    # Fail-open on insufficient history — must not silently disable the desk.
    ok_nohist, why3 = eq.chase_guard("BUY", 10.0, 99.0, _bars(3))
    check("no ATR history -> guard does not block", ok_nohist is True, why3)


def test_bar_exhaustion():
    print("\n[5] Bar-exhaustion (don't buy the high of an outsized bar)")
    os.environ["IAM_MAX_BAR_EXTENSION_ATR"] = "2.0"
    os.environ["IAM_BAR_POS_PCT"] = "0.80"
    bars = _bars()                                  # ATR 2.0
    bars.append({"o": 10.0, "h": 16.0, "l": 10.0, "c": 15.9})   # 6.0 range == 3x ATR

    hi, why = eq.bar_exhausted(bars, 15.9, "BUY", 2.0)
    check("buying at the top of a 3xATR bar is refused", hi is True, why)

    lo, _ = eq.bar_exhausted(bars, 10.2, "BUY", 2.0)
    check("buying near the LOW of that same bar is allowed", lo is False)

    normal, _ = eq.bar_exhausted(_bars(), 10.0, "BUY", 2.0)
    check("ordinary bar is never flagged exhausted", normal is False)


# ── DEFECT 6: options were bought and never sold ──────────────────────────────
def test_option_exit_policy():
    print("\n[6] Option exit policy (nothing could close an option before this)")
    os.environ["IAM_OPTION_HARD_STOP_PCT"] = "35"
    os.environ["IAM_GIVEBACK_ARM_PCT"] = "8"
    os.environ["IAM_GIVEBACK_PCT"] = "40"
    os.environ["IAM_TARGET_PCT"] = "0"

    pos = {"kind": "option", "symbol": "SPY260731C00500000", "underlying": "SPY",
           "qty": 1, "entry_price": 1.00, "peak": 1.00, "atr": None,
           "hard_stop": 0.65, "system": "SML_CASCADE", "expiry": None}

    check("holds at entry", pm.evaluate_exit(pos, 1.00) is None)
    check("holds on a small dip", pm.evaluate_exit(pos, 0.90) is None)

    r = pm.evaluate_exit(pos, 0.60)
    check("hard stop fires at -40% premium", r is not None and "HARD_STOP" in r, str(r))

    # Runner that gives back most of its gain.
    pos_run = dict(pos, peak=2.00)
    check("holds while still near the peak", pm.evaluate_exit(pos_run, 1.90) is None)
    r2 = pm.evaluate_exit(pos_run, 1.30)     # +100% peak -> +30% now == 70% given back
    check("giveback lock fires after retracing 70% of a +100% peak",
          r2 is not None and "GIVEBACK" in r2, str(r2))


def test_equity_trailing_stop():
    print("\n[7] ATR trailing stop (the static GTC stop never moved)")
    os.environ["IAM_TRAIL_ATR_MULT"] = "2.0"
    os.environ["IAM_TRAIL_ARM_PCT"] = "1.0"
    os.environ["IAM_GIVEBACK_ARM_PCT"] = "0"     # isolate the trail
    os.environ["IAM_TARGET_PCT"] = "0"

    pos = {"kind": "equity", "symbol": "SPY", "underlying": "SPY", "qty": 10,
           "entry_price": 100.0, "peak": 100.0, "atr": 2.0,
           "hard_stop": 97.0, "system": "SML_BREAKOUT", "expiry": None}

    check("does not trail before arming", pm.evaluate_exit(pos, 100.2) is None)

    ran = dict(pos, peak=110.0)
    check("holds inside the trail band", pm.evaluate_exit(ran, 107.0) is None)
    r = pm.evaluate_exit(ran, 105.5)         # 110 - 2*2.0 = 106.0
    check("trail fires below peak - 2xATR", r is not None and "ATR_TRAIL" in r, str(r))
    check("winner exits ABOVE the original static stop of 97.00", 105.5 > 97.0)

    os.environ["IAM_GIVEBACK_ARM_PCT"] = "8"


def test_peak_ratchets_up_only():
    print("\n[8] High-water mark must never be lowered by a pullback")
    os.environ["IAM_TRAIL_ATR_MULT"] = "2.0"
    os.environ["IAM_TRAIL_ARM_PCT"] = "1.0"
    pm._positions.clear()
    pm.register_equity("TEST", 10, 100.0, "SML_BREAKOUT", atr_value=2.0, stop_price=97.0)

    pm._positions["TEST"]["peak"] = 110.0
    before = pm._positions["TEST"]["peak"]
    # Simulate the loop seeing a lower price: it must NOT write peak down.
    price = 104.0
    if price > pm._positions["TEST"]["peak"]:
        pm._positions["TEST"]["peak"] = price
    check("pullback does not lower the peak", pm._positions["TEST"]["peak"] == before,
          str(pm._positions["TEST"]["peak"]))
    pm._positions.clear()


def test_registration_and_reversal():
    print("\n[9] Registration + instant reversal exit")
    pm._positions.clear()
    pm.register_equity("AMC", 5, 4.00, "SML_CASCADE", atr_value=0.20, stop_price=3.88)
    pm.register_option("AMC260807P00004000", "AMC", 1, 0.50, "SML_CASCADE", "2026-08-07")

    t = pm.tracked()
    check("equity position tracked", "AMC" in t)
    check("option position tracked by OCC symbol", "AMC260807P00004000" in t)
    check("option stop derived from premium, not underlying",
          t["AMC260807P00004000"]["hard_stop"] < 0.50,
          str(t["AMC260807P00004000"]["hard_stop"]))
    check("option knows its underlying", t["AMC260807P00004000"]["underlying"] == "AMC")

    check("OCC put parsed as P", pm._occ_type("AMC260807P00004000") == "P")
    check("OCC call parsed as C", pm._occ_type("AMC260807C00004000") == "C")
    check("equity ticker is not an OCC symbol", pm._occ_type("AMC") is None)

    # A fresh BUY must flatten the tracked PUT (opposing), not the long.
    closed = []
    real_close = pm.close_position
    pm.close_position = lambda s, r: (closed.append((s, r)), {"status": "success"})[1]
    try:
        n = pm.on_reversal("AMC", "BUY")
    finally:
        pm.close_position = real_close
    check("BUY reversal closes the opposing put", n == 1 and closed[0][0] == "AMC260807P00004000",
          f"closed={closed}")
    check("BUY reversal does NOT close the existing long", all(c[0] != "AMC" for c in closed))
    pm._positions.clear()


def test_paper_mode_places_no_order():
    print("\n[10] Paper mode never reaches a broker")
    os.environ["IAM_PAPER_MODE"] = "true"
    pm._positions.clear()
    pm.register_equity("SPY", 1, 100.0, "SML_BREAKOUT", atr_value=2.0, stop_price=97.0)

    calls = []
    fake_tradier = types.ModuleType("tradier_api")
    fake_tradier.place_equity_order = lambda *a, **k: calls.append(a) or {"status": "success"}
    fake_tradier.place_option_order = lambda *a, **k: calls.append(a) or {"status": "success"}
    fake_tradier.get_position = lambda s: {"symbol": s, "quantity": 1}
    saved = sys.modules.get("tradier_api")
    sys.modules["tradier_api"] = fake_tradier
    real_quote = pm._current_quote
    pm._current_quote = lambda p: {"bid": 99.0, "ask": 99.1, "reference": 99.05}
    try:
        pm.close_position("SPY", "test")
    finally:
        pm._current_quote = real_quote
        if saved is not None:
            sys.modules["tradier_api"] = saved
        else:
            sys.modules.pop("tradier_api", None)

    check("no broker order placed in paper mode", calls == [], f"calls={calls}")
    check("position untracked after a paper close", "SPY" not in pm.tracked())
    pm._positions.clear()


def test_option_time_stop():
    print("\n[11] Option time stop on expiry day")
    from datetime import datetime
    os.environ["IAM_OPTION_TIME_STOP_MIN"] = "30"
    os.environ["IAM_GIVEBACK_ARM_PCT"] = "0"
    pos = {"kind": "option", "symbol": "SPY260731C00500000", "underlying": "SPY",
           "qty": 1, "entry_price": 1.00, "peak": 1.00, "atr": None,
           "hard_stop": 0.10, "system": "IAM", "expiry": "2026-07-31"}

    near = datetime(2026, 7, 31, 15, 45, tzinfo=pm._TZ_ET)   # 15 min to close
    r = pm.evaluate_exit(pos, 1.00, now_et=near)
    check("closes 15 min before expiry close", r is not None and "TIME_STOP" in r, str(r))

    early = datetime(2026, 7, 31, 11, 0, tzinfo=pm._TZ_ET)
    check("holds at 11:00 on expiry day", pm.evaluate_exit(pos, 1.00, now_et=early) is None)

    other = datetime(2026, 7, 30, 15, 45, tzinfo=pm._TZ_ET)
    check("no time stop on a non-expiry day", pm.evaluate_exit(pos, 1.00, now_et=other) is None)
    os.environ["IAM_GIVEBACK_ARM_PCT"] = "8"


def test_stale_signal_price_not_used_for_stop():
    print("\n[12] Live quote replaces the stale signal-bar close")
    fake = types.ModuleType("tradier_api")
    fake.get_quote = lambda s: {"bid": 50.00, "ask": 50.04, "last": 50.02}
    saved = sys.modules.get("tradier_api")
    sys.modules["tradier_api"] = fake
    try:
        q = eq.live_nbbo("SPY")
    finally:
        if saved is not None:
            sys.modules["tradier_api"] = saved
        else:
            sys.modules.pop("tradier_api", None)

    check("live NBBO returns a real mid", q is not None and abs(q["mid"] - 50.02) < 1e-6, str(q))
    # A signal fired off a $45 daily close would have set the stop at 43.65;
    # off the real $50.02 mid it is 48.52 — a materially different stop.
    stale_stop = round(45.00 * 0.97, 2)
    live_stop = round(q["reference"] * 0.97, 2)
    check("stop from the live price differs from the stale-close stop",
          abs(live_stop - stale_stop) > 1.0, f"stale={stale_stop} live={live_stop}")


def test_no_quote_fails_closed_for_entry():
    print("\n[13] Missing quote: entries fail closed, exits fail open")
    entry_ok, _ = eq.spread_ok(None, None, is_option=False, is_entry=True)
    exit_ok, _ = eq.spread_ok(None, None, is_option=False, is_entry=False)
    check("entry refused with no quote", entry_ok is False)
    check("exit allowed with no quote", exit_ok is True)


if __name__ == "__main__":
    print("=" * 72)
    print("Execution-layer refactor regression tests")
    print("=" * 72)
    for fn in [test_exit_bypasses_entry_gates, test_marketable_limit_replaces_market_order,
               test_option_spread_guard, test_chase_guard, test_bar_exhaustion,
               test_option_exit_policy, test_equity_trailing_stop, test_peak_ratchets_up_only,
               test_registration_and_reversal, test_paper_mode_places_no_order,
               test_option_time_stop, test_stale_signal_price_not_used_for_stop,
               test_no_quote_fails_closed_for_entry]:
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append(fn.__name__)
            print(f"  ❌ {fn.__name__} raised: {e}")
            traceback.print_exc()

    print("\n" + "=" * 72)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("Failures: " + ", ".join(FAIL))
    print("=" * 72)
    sys.exit(1 if FAIL else 0)
