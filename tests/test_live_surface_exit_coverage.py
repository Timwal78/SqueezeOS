"""
Regression tests for the 2026-07-31 follow-up: extending real exit management
to the two live-order surfaces that had none.

Background — the three surfaces that place real Tradier orders, before this:

  iam_executor.py        GTC stop + ATR trail + giveback lock  (fixed in #421)
  convergence_bp.py      NO stop of any kind, NO exit path
  execution_engine.py    sl/tp computed and stored, but the only reader
                         (update_live_prices) is called by NOTHING in this
                         repo, and the closer it would call
                         (_close_trade_unsafe) places no broker order at all --
                         it drops the tracking row, books a P&L number off
                         current_price, and fires a "TRADE CLOSED" Discord
                         alert while the real position stays open.

Both facts above were verified by grep against the real tree, not assumed.

Real, unmodified production functions; only true I/O boundaries stubbed.
Run:  python3 tests/test_live_surface_exit_coverage.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["IAM_PAPER_MODE"] = "true"
os.environ["POSITION_MANAGER_ENABLED"] = "false"

import position_manager as pm          # noqa: E402
import execution_quality as eq         # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{('  — ' + detail) if detail and not cond else ''}")


def _stub_tradier(**overrides):
    m = types.ModuleType("tradier_api")
    m.get_quote = lambda s: {"bid": 99.95, "ask": 100.05, "last": 100.00}
    m.get_position = lambda s: {"symbol": s, "quantity": 10}
    m.get_positions = lambda: []
    m.place_equity_order = lambda *a, **k: {"status": "success", "order_id": "T1"}
    m.place_option_order = lambda *a, **k: {"status": "success", "order_id": "T2"}
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ── 1. The dead exit path in execution_engine ─────────────────────────────────
def test_execution_engine_exit_path_was_dead():
    print("\n[1] execution_engine's stored sl/tp had no live reader (documented fact)")
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(
        ["grep", "-rn", "--include=*.py", r"update_live_prices(", root],
        capture_output=True, text=True).stdout
    # Exclude the definition, this test file, and prose/comment mentions --
    # we are looking for an actual invocation, not the word appearing in text.
    real_callers = []
    for line in out.strip().splitlines():
        if "def update_live_prices" in line or "/tests/" in line:
            continue
        code = line.split(":", 2)[-1]
        stripped = code.strip()
        if stripped.startswith("#") or stripped.startswith("*"):
            continue
        real_callers.append(line)
    check("update_live_prices still has no production caller", real_callers == [],
          f"callers found: {real_callers}")


def test_close_trade_now_places_a_real_broker_order():
    print("\n[2] A LIVE bookkeeping close must place a real broker order")
    import execution_engine as ee

    eng = ee.ExecutionEngine.__new__(ee.ExecutionEngine)
    import threading
    eng.lock = threading.Lock()
    eng.active_trades = {}
    eng._trade_history = []
    eng.discord = None
    eng.tracker = None
    eng.live_mode = True
    eng.day_trades = []
    eng.save_trades = lambda: None

    import time as _t
    eng.active_trades["LIVE_SPY_1"] = {
        "id": "LIVE_SPY_1", "symbol": "SPY", "side": "BUY", "qty": 10,
        "entry_price": 100.0, "current_price": 97.0, "sl": 97.0, "tp": 112.0,
        "status": "OPEN", "opened_at": _t.time(), "mode": "LIVE",
    }

    closed = []
    real_close = pm.close_position
    pm.close_position = lambda s, r: (closed.append((s, r)), {"status": "success"})[1]
    try:
        trade = eng._close_trade_unsafe("LIVE_SPY_1")
    finally:
        pm.close_position = real_close

    check("a real broker close was requested", len(closed) == 1 and closed[0][0] == "SPY",
          f"closed={closed}")
    check("the broker result is recorded on the trade", trade.get("broker_close") is not None)
    check("bookkeeping still completes", trade["status"] == "CLOSED")


def test_shadow_close_does_not_touch_the_broker():
    print("\n[3] A SHADOW (paper) close must never reach the broker")
    import execution_engine as ee
    import threading, time as _t

    eng = ee.ExecutionEngine.__new__(ee.ExecutionEngine)
    eng.lock = threading.Lock()
    eng.active_trades = {}
    eng._trade_history = []
    eng.discord = None
    eng.tracker = None
    eng.live_mode = False
    eng.day_trades = []
    eng.save_trades = lambda: None
    eng.active_trades["SHADOW_SPY_1"] = {
        "id": "SHADOW_SPY_1", "symbol": "SPY", "side": "BUY", "qty": 10,
        "entry_price": 100.0, "current_price": 97.0, "sl": 97.0, "tp": 112.0,
        "status": "OPEN", "opened_at": _t.time(), "mode": "SHADOW",
    }

    closed = []
    real_close = pm.close_position
    pm.close_position = lambda s, r: (closed.append(s), {"status": "success"})[1]
    try:
        trade = eng._close_trade_unsafe("SHADOW_SPY_1")
    finally:
        pm.close_position = real_close

    check("no broker close for a shadow trade", closed == [], f"closed={closed}")
    check("shadow bookkeeping still completes", trade["status"] == "CLOSED")


def test_live_fill_is_registered_for_exit_management():
    print("\n[4] A LIVE fill registers with position_manager")
    import execution_engine as ee
    import threading

    eng = ee.ExecutionEngine.__new__(ee.ExecutionEngine)
    eng.lock = threading.Lock()
    eng.calculate_atr = lambda s, period=14: 2.5

    pm._positions.clear()
    eng._register_for_exit_management("SPY", 10, 100.0, 97.0)
    t = pm.tracked()

    check("position is tracked", "SPY" in t)
    check("entry price is the real fill", t["SPY"]["entry_price"] == 100.0)
    check("hard stop carried through", t["SPY"]["hard_stop"] == 97.0)
    check("real ATR carried through for the trail", t["SPY"]["atr"] == 2.5)
    check("attributed to CEO_TRADER", t["SPY"]["system"] == "CEO_TRADER")
    pm._positions.clear()


def test_registration_failure_never_breaks_the_order():
    print("\n[5] A registration failure must not roll back a placed order")
    import execution_engine as ee
    import threading

    eng = ee.ExecutionEngine.__new__(ee.ExecutionEngine)
    eng.lock = threading.Lock()

    def boom(s, period=14):
        raise RuntimeError("ATR provider down")
    eng.calculate_atr = boom

    raised = False
    try:
        eng._register_for_exit_management("SPY", 10, 100.0, 97.0)
    except Exception:
        raised = True
    check("swallows the failure instead of raising", raised is False)


# ── GOD MODE ──────────────────────────────────────────────────────────────────
def test_god_mode_uses_bounded_limit_not_market():
    """Drives the REAL _fire_execution() order path end to end, past every
    gate. Before this change the order was place_equity_order(symbol, qty,
    side) with no order_type, which defaults to "market" in tradier_api --
    unbounded slippage on a deliberately wide $1-$50 universe."""
    print("\n[6] GOD MODE places a bounded limit, not a raw market order")
    import core.api.convergence_bp as cbp

    orders = []

    def spy_place(symbol, qty, side, **kwargs):
        orders.append({"symbol": symbol, "qty": qty, "side": side, **kwargs})
        return {"status": "success", "order_id": "T1"}

    stub = _stub_tradier(place_equity_order=spy_place)
    saved_mod = sys.modules.get("tradier_api")
    sys.modules["tradier_api"] = stub

    saved = {
        "armed": cbp._live_trading_armed,
        "pdt": cbp._pdt_check_and_record,
        "breaker": cbp._breaker_tripped,
        "claim": cbp.claim_entry,
        "hook": cbp._fire_robinhood_webhook,
    }
    cbp._live_trading_armed = lambda: True
    cbp._pdt_check_and_record = lambda: True
    cbp._breaker_tripped = lambda: False
    cbp.claim_entry = lambda *a, **k: True
    cbp._fire_robinhood_webhook = lambda *a, **k: None
    cbp._last_execution.clear() if hasattr(cbp, "_last_execution") else None

    pm._positions.clear()
    try:
        cbp._fire_execution("SPY", {
            "symbol": "SPY",
            "price": 100.0,
            "sml_matrix": {
                "god_stacked": 6, "bear_god_stacked": 0,
                "execute_gate": True, "tier": "GOD_MODE",
            },
            "signal": "test",
        })
    finally:
        cbp._live_trading_armed = saved["armed"]
        cbp._pdt_check_and_record = saved["pdt"]
        cbp._breaker_tripped = saved["breaker"]
        cbp.claim_entry = saved["claim"]
        cbp._fire_robinhood_webhook = saved["hook"]
        if saved_mod is not None:
            sys.modules["tradier_api"] = saved_mod
        else:
            sys.modules.pop("tradier_api", None)

    check("an order actually reached the broker stub", len(orders) == 1, f"orders={orders}")
    if orders:
        o = orders[0]
        check("order is a LIMIT, not a market order", o.get("order_type") == "limit", str(o))
        check("limit price is bounded just past the ask (100.05)",
              o.get("limit_price") is not None and 100.05 <= o["limit_price"] <= 100.60,
              str(o.get("limit_price")))

    t = pm.tracked()
    check("the GOD MODE fill is now registered for exit management", "SPY" in t, str(t))
    if "SPY" in t:
        check("it carries a real hard stop (it had none before)",
              t["SPY"]["hard_stop"] is not None and t["SPY"]["hard_stop"] < 100.0,
              str(t["SPY"]["hard_stop"]))
        check("attributed to GOD_MODE", t["SPY"]["system"] == "GOD_MODE")
    pm._positions.clear()


def test_god_mode_stop_pct_defaults_to_iam_policy():
    print("\n[7] GOD MODE stop % shares the IAM stop policy unless split")
    import importlib
    import core.api.convergence_bp as cbp

    os.environ.pop("GOD_MODE_STOP_PCT", None)
    os.environ["IAM_STOP_LOSS_PCT"] = "3.0"
    check("defaults to IAM_STOP_LOSS_PCT", cbp._GOD_MODE_STOP_PCT() == 3.0,
          str(cbp._GOD_MODE_STOP_PCT()))

    os.environ["GOD_MODE_STOP_PCT"] = "5.0"
    check("explicit override wins", cbp._GOD_MODE_STOP_PCT() == 5.0,
          str(cbp._GOD_MODE_STOP_PCT()))

    os.environ["GOD_MODE_STOP_PCT"] = "not-a-number"
    check("garbage value falls back safely, never crashes",
          cbp._GOD_MODE_STOP_PCT() == 3.0, str(cbp._GOD_MODE_STOP_PCT()))
    os.environ.pop("GOD_MODE_STOP_PCT", None)


def test_god_mode_position_gets_a_real_stop():
    print("\n[8] A GOD MODE position now carries a hard stop it never had")
    import core.api.convergence_bp as cbp
    os.environ["IAM_STOP_LOSS_PCT"] = "3.0"
    pm._positions.clear()
    fill = 100.0
    pm.register_equity("AMC", 5, fill, "GOD_MODE", atr_value=None,
                       stop_price=round(fill * (1 - cbp._GOD_MODE_STOP_PCT() / 100.0), 2))
    t = pm.tracked()
    check("stop is set at entry-3%", t["AMC"]["hard_stop"] == 97.0, str(t["AMC"]["hard_stop"]))
    check("attributed to GOD_MODE", t["AMC"]["system"] == "GOD_MODE")

    r = pm.evaluate_exit(t["AMC"], 96.0)
    check("hard stop actually fires below the level", r is not None and "HARD_STOP" in r, str(r))
    pm._positions.clear()


def test_manual_positions_are_never_managed():
    print("\n[9] Positions nobody registered are never touched")
    pm._positions.clear()
    check("registry starts empty", pm.tracked() == {})
    check("closing an untracked symbol is a safe no-op",
          pm.close_position("HAND_BOUGHT", "test").get("status") == "skipped")
    check("still empty", pm.tracked() == {})


if __name__ == "__main__":
    print("=" * 72)
    print("Live-surface exit-coverage regression tests")
    print("=" * 72)
    for fn in [test_execution_engine_exit_path_was_dead,
               test_close_trade_now_places_a_real_broker_order,
               test_shadow_close_does_not_touch_the_broker,
               test_live_fill_is_registered_for_exit_management,
               test_registration_failure_never_breaks_the_order,
               test_god_mode_uses_bounded_limit_not_market,
               test_god_mode_stop_pct_defaults_to_iam_policy,
               test_god_mode_position_gets_a_real_stop,
               test_manual_positions_are_never_managed]:
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
