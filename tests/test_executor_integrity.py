"""
Tests for tools/executor_integrity.py.

Context: stale executor behaviour returned for a FIFTH time, with a live
banner showing `Poll every : 300s`, `MIN_GOD : 4/6`,
`Daily cap : 25 orders / $1500 notional`, `stop-loss 5.0%`.

Two independent causes, and conflating them is why it kept recurring:
  1. the .py was old (the banner was missing hardcoded literal rows);
  2. tools/executor.env carried stale overrides AND is deliberately preserved
     by FORCE_UPDATE_EXECUTOR.ps1's `git clean -e tools/executor.env`, so a
     `git reset --hard` fixes (1) and leaves (2) fully intact.

Run:  python3 tests/test_executor_integrity.py
"""

import os
import sys
import logging

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import executor_integrity as ei   # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{('  — ' + detail) if detail and not cond else ''}")


RISK_KEYS = list(ei.RISK_INTENT.keys()) + list(ei.UNLOCK_FLAGS)


def _clear():
    for k in RISK_KEYS:
        os.environ.pop(k, None)


class _Cap:
    """Captures log output so the report's actual text can be asserted."""
    def __init__(self):
        self.info, self.warning, self.error = [], [], []
    def __getattr__(self, name):
        raise AttributeError(name)


class _Logger:
    def __init__(self):
        self.lines = []
        self.warnings = []
    def info(self, msg):
        self.lines.append(str(msg))
    def warning(self, msg):
        self.lines.append(str(msg))
        self.warnings.append(str(msg))
    def error(self, msg):
        self.lines.append(str(msg))


def test_clean_env_reports_ok():
    print("\n[1] A clean environment reports no divergence")
    _clear()
    findings = ei.stale_env_report()
    check("no findings with nothing set", findings == [], str(findings))

    log = _Logger()
    ok = ei.report(log)
    check("report() returns True", ok is True)
    check("says settings match", any("match repo intent" in l for l in log.lines))
    check("no warnings emitted", log.warnings == [])


def test_reproduces_the_real_stale_banner():
    print("\n[2] The operator's ACTUAL stale values are each named")
    _clear()
    os.environ["MAX_ORDERS_PER_DAY"] = "25"
    os.environ["MAX_DAILY_NOTIONAL_USD"] = "1500"
    os.environ["STOP_LOSS_PCT"] = "5.0"
    os.environ["POLL_INTERVAL_S"] = "300"
    try:
        findings = {f["setting"]: f for f in ei.stale_env_report()}
        check("daily order cap flagged", "MAX_ORDERS_PER_DAY" in findings)
        check("daily notional flagged", "MAX_DAILY_NOTIONAL_USD" in findings)
        check("stop loss flagged", "STOP_LOSS_PCT" in findings)
        check("poll interval flagged", "POLL_INTERVAL_S" in findings)
        check("shows both live and intended values",
              findings["STOP_LOSS_PCT"]["live_value"] == "5.0"
              and findings["STOP_LOSS_PCT"]["repo_intent"] == "3.0",
              str(findings["STOP_LOSS_PCT"]))

        log = _Logger()
        ok = ei.report(log)
        check("report() returns False on divergence", ok is False)
        check("warns about executor.env specifically",
              any("executor.env" in w for w in log.warnings))
        check("explains git reset does not clear it",
              any("git reset" in w for w in log.warnings))
    finally:
        _clear()


def test_unlock_flags_are_reported():
    print("\n[3] An unlock flag left ON is itself a finding")
    _clear()
    os.environ["ALLOW_SLOW_POLL"] = "true"
    try:
        findings = {f["setting"]: f for f in ei.stale_env_report()}
        check("ALLOW_SLOW_POLL reported", "ALLOW_SLOW_POLL" in findings)
        check("explains it re-opens a lock",
              "re-opens" in findings["ALLOW_SLOW_POLL"]["note"])
    finally:
        _clear()


def test_unset_is_not_a_finding():
    print("\n[4] Unset means the repo default is in force — not a finding")
    _clear()
    check("nothing reported when unset", ei.stale_env_report() == [])
    # And a value that MATCHES intent is likewise not a finding.
    os.environ["STOP_LOSS_PCT"] = "3.0"
    try:
        check("matching value is not flagged",
              not any(f["setting"] == "STOP_LOSS_PCT" for f in ei.stale_env_report()))
        os.environ["STOP_LOSS_PCT"] = "3"
        check("numeric equality, not string equality ('3' == '3.0')",
              not any(f["setting"] == "STOP_LOSS_PCT" for f in ei.stale_env_report()))
        os.environ["MAX_DAILY_NOTIONAL_USD"] = "0.0"
        check("'0.0' equals intent '0'",
              not any(f["setting"] == "MAX_DAILY_NOTIONAL_USD" for f in ei.stale_env_report()))
    finally:
        _clear()


def test_build_fingerprint():
    print("\n[5] Build fingerprint identifies the exact source")
    h = ei.source_hash()
    check("hash computed for the real executor", h is not None and len(h) == 12, str(h))
    check("stable across calls", h == ei.source_hash())
    check("missing file returns None, never a fake hash",
          ei.source_hash("/nonexistent/path.py") is None)

    log = _Logger()
    ei.report(log)
    check("fingerprint appears in the report",
          any("executor source" in l for l in log.lines))
    check("report explains the v3.x string is unreliable",
          any("hand-maintained" in l for l in log.lines))


def test_report_never_raises():
    print("\n[6] The check can never crash the desk it protects")
    class Exploding:
        def info(self, m):
            raise RuntimeError("logger exploded")
        def warning(self, m):
            raise RuntimeError("logger exploded")
        def error(self, m):
            raise RuntimeError("logger exploded")
    raised = False
    try:
        ei.report(Exploding())
    except Exception:
        raised = True
    check("swallows even a broken logger", raised is False)


def test_strict_mode_opt_in():
    print("\n[7] Strict refusal is opt-in, never the default")
    os.environ.pop("EXECUTOR_STRICT_INTEGRITY", None)
    check("defaults to off", ei.strict_mode() is False)
    os.environ["EXECUTOR_STRICT_INTEGRITY"] = "true"
    try:
        check("opt-in works", ei.strict_mode() is True)
    finally:
        os.environ.pop("EXECUTOR_STRICT_INTEGRITY", None)


def test_wired_into_executor_startup():
    print("\n[8] The executor actually calls it at startup")
    src = open(os.path.join(_ROOT, "tools", "robinhood_executor_sml.py")).read()
    check("imports the module", "executor_integrity" in src)
    check("calls report()", "executor_integrity.report(logger)" in src)
    check("strict mode wired", "strict_mode()" in src)
    # It must run AFTER the banner, so the fingerprint sits with the settings
    # it qualifies rather than scrolling past above them.
    check("runs after the banner block",
          src.index("Kill switch") < src.index("executor_integrity.report(logger)"))


if __name__ == "__main__":
    print("=" * 72)
    print("Executor integrity / stale-env detection tests")
    print("=" * 72)
    for fn in [test_clean_env_reports_ok, test_reproduces_the_real_stale_banner,
               test_unlock_flags_are_reported, test_unset_is_not_a_finding,
               test_build_fingerprint, test_report_never_raises,
               test_strict_mode_opt_in, test_wired_into_executor_startup]:
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append(fn.__name__)
            print(f"  ❌ {fn.__name__} raised: {e}")
            traceback.print_exc()
    _clear()
    print("\n" + "=" * 72)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("Failures: " + ", ".join(FAIL))
    print("=" * 72)
    sys.exit(1 if FAIL else 0)
