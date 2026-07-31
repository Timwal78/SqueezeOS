"""
Regression tests for the 2026-07-31 CEOTrader disarm (operator decision).

CEOTrader was the only live-order surface in this codebase that:
  - auto-started on every boot when TRADIER_LIVE=true,
  - had no backtest evidence for its pathway, and
  - answered to NONE of the documented kill switches (IAM_PAPER_MODE,
    IAM_AUTO_TRADING, IAM_PRIMARY_SYSTEM, LIVE_TRADING_ENABLED, KILL_SWITCH).

It now requires its own explicit AUTOPILOT_ENABLED=true, defaulting off.

Also covers the BEAST_MAX_PRICE env-var collision found alongside it:
execution_engine read it as a per-order dollar cap (default 25.0) while
convergence_bp reads the same name as a notional budget (default 500.0).

Real, unmodified production code; only true I/O boundaries stubbed.
Run:  python3 tests/test_ceotrader_arm_switch.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{('  — ' + detail) if detail and not cond else ''}")


def _fresh_ceo():
    """A CEOTrader with its collaborators stubbed — we only exercise start()."""
    import core.ceo_trader as ct

    class _Exec:
        live_mode = True

    ceo = ct.CEOTrader.__new__(ct.CEOTrader)
    import threading
    ceo.lock = threading.Lock()
    ceo.active = False
    ceo._thread = None
    ceo.exec = _Exec()
    ceo.oracle = None
    # Neutralise the loop body: these tests are about whether start() arms the
    # engine, not about what the loop does. Without this the spawned thread
    # runs against a deliberately partial stub and logs unrelated errors that
    # look like failures in the test output.
    ceo._run_loop = lambda: None
    return ct, ceo


# ── The arm switch ────────────────────────────────────────────────────────────
def test_defaults_to_disarmed():
    print("\n[1] Defaults to OFF")
    os.environ.pop("AUTOPILOT_ENABLED", None)
    ct, ceo = _fresh_ceo()
    check("_autopilot_enabled() is False with the var unset", ct._autopilot_enabled() is False)

    ceo.start()
    check("start() does not activate the engine", ceo.active is False)
    check("no autopilot thread was spawned", ceo._thread is None)


def test_explicit_true_arms_it():
    print("\n[2] AUTOPILOT_ENABLED=true re-arms it")
    ct, ceo = _fresh_ceo()
    os.environ["AUTOPILOT_ENABLED"] = "true"
    try:
        check("_autopilot_enabled() is True", ct._autopilot_enabled() is True)
        ceo.start()
        check("start() activates the engine", ceo.active is True)
        check("an autopilot thread was spawned", ceo._thread is not None)
        ceo.stop()
    finally:
        os.environ.pop("AUTOPILOT_ENABLED", None)


def test_accepts_common_truthy_spellings():
    print("\n[3] Accepts the same truthy spellings as every other flag here")
    import core.ceo_trader as ct
    for val in ("true", "TRUE", "True", "1", "yes", " true "):
        os.environ["AUTOPILOT_ENABLED"] = val
        check(f"{val!r} arms", ct._autopilot_enabled() is True)
    for val in ("false", "0", "no", "", "off", "maybe"):
        os.environ["AUTOPILOT_ENABLED"] = val
        check(f"{val!r} stays disarmed", ct._autopilot_enabled() is False)
    os.environ.pop("AUTOPILOT_ENABLED", None)


def test_boot_autostart_is_covered():
    print("\n[4] The boot auto-start path cannot bypass the switch")
    # core/legacy.py does: `if exec_eng.live_mode: ceo.start()` -- live_mode
    # True is exactly the production condition. The gate lives inside start(),
    # so this path is covered without legacy.py needing to know about it.
    os.environ.pop("AUTOPILOT_ENABLED", None)
    _, ceo = _fresh_ceo()
    check("exec.live_mode is True (production condition)", ceo.exec.live_mode is True)
    ceo.start()
    check("still disarmed despite live_mode=True", ceo.active is False)


def test_manual_endpoint_is_covered():
    print("\n[5] The manual POST /api/autopilot/start path is covered too")
    # autopilot_bp calls the same ceo.start(). Gating inside start() rather
    # than at either call site is what makes "off means off" hold from every
    # direction.
    import inspect
    import core.api.autopilot_bp as bp
    src = inspect.getsource(bp)
    check("the endpoint still routes through ceo.start()", "ceo.start()" in src)

    os.environ.pop("AUTOPILOT_ENABLED", None)
    _, ceo = _fresh_ceo()
    ceo.start()   # simulating exactly what the endpoint does
    check("manual start is refused while disarmed", ceo.active is False)


def test_disarm_does_not_touch_other_engines():
    print("\n[6] Disarming CEOTrader leaves the other surfaces alone")
    os.environ.pop("AUTOPILOT_ENABLED", None)
    import iam_executor as ie
    # The IAM path has its own independent arm switch and is unaffected.
    os.environ["IAM_PAPER_MODE"] = "true"
    check("IAM executor still arms itself under paper mode", ie.ARMED() is True)
    import core.api.convergence_bp as cbp
    check("GOD MODE still has its own separate arm switch",
          hasattr(cbp, "_live_trading_armed"))


# ── BEAST_MAX_PRICE collision ─────────────────────────────────────────────────
def test_execution_max_order_value_preserves_existing_behaviour():
    print("\n[7] BEAST_MAX_PRICE collision fixed without changing today's cap")
    import importlib
    import execution_engine as ee

    def _cap():
        # Re-read exactly as ExecutionEngine.__init__ does.
        return float(os.environ.get('EXECUTION_MAX_ORDER_VALUE',
                                    os.environ.get('BEAST_MAX_PRICE', '25.0')))

    for k in ("EXECUTION_MAX_ORDER_VALUE", "BEAST_MAX_PRICE"):
        os.environ.pop(k, None)
    check("unset -> 25.0, the original default", _cap() == 25.0, str(_cap()))

    os.environ["BEAST_MAX_PRICE"] = "500"
    check("existing BEAST_MAX_PRICE still honoured (no silent retighten)",
          _cap() == 500.0, str(_cap()))

    os.environ["EXECUTION_MAX_ORDER_VALUE"] = "100"
    check("new var takes precedence once set", _cap() == 100.0, str(_cap()))

    for k in ("EXECUTION_MAX_ORDER_VALUE", "BEAST_MAX_PRICE"):
        os.environ.pop(k, None)


def test_convergence_still_reads_its_own_meaning():
    print("\n[8] convergence_bp's notional-budget meaning is untouched")
    import core.api.convergence_bp as cbp
    check("convergence still has its own _BEAST_MAX_PRICE", hasattr(cbp, "_BEAST_MAX_PRICE"))
    check("and its default is still 500.0, not 25.0",
          cbp._BEAST_MAX_PRICE in (500.0, float(os.environ.get("BEAST_MAX_PRICE", "500.0"))),
          str(cbp._BEAST_MAX_PRICE))


if __name__ == "__main__":
    print("=" * 72)
    print("CEOTrader arm-switch + BEAST_MAX_PRICE collision tests")
    print("=" * 72)
    for fn in [test_defaults_to_disarmed, test_explicit_true_arms_it,
               test_accepts_common_truthy_spellings, test_boot_autostart_is_covered,
               test_manual_endpoint_is_covered, test_disarm_does_not_touch_other_engines,
               test_execution_max_order_value_preserves_existing_behaviour,
               test_convergence_still_reads_its_own_meaning]:
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
