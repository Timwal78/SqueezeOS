"""
Regression tests for the 2026-07-31 Robinhood options leg.

The inconsistency this closes: when the server's Tradier leg routed a primary-
system signal to OPTIONS (IAM_INSTRUMENT=options, the currently recommended
setting), the Robinhood leg still bought SHARES. One signal, two different
instruments, two different risk profiles, on two real accounts.

Fix: iam_executor now forwards the EXACT contract Tradier selected through
core/api/iam_pending_bp's queue, and tools/robinhood_executor_sml's
_poll_iam_primary() places that same contract via the already-existing
_execute_option(). Options are exchange-standardized, so underlying +
expiration + strike + type is the same contract on both brokers -- which is
why _execute_option deliberately never re-derives it.

Real, unmodified production code; only true I/O boundaries stubbed.
Run:  python3 tests/test_robinhood_options_leg.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["IAM_PAPER_MODE"] = "true"
os.environ["POSITION_MANAGER_ENABLED"] = "false"

import iam_executor as ie                      # noqa: E402
import core.api.iam_pending_bp as pending      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{('  — ' + detail) if detail and not cond else ''}")


CONTRACT = {
    "option_type": "call", "strike": 450.0, "expiration": "2026-08-07",
    "bid": 2.45, "ask": 2.50, "premium": 2.475, "limit_price": 2.50,
    "delta": 0.35, "occ": "SPY260807C00450000", "source": "iam_executor:SML_CASCADE",
}


# ── Contract extraction ───────────────────────────────────────────────────────
def test_extracts_contract_from_buy_result():
    print("\n[1] BUY result carries the contract at the top level")
    c = ie._contract_from_result({"status": "success", "contract": dict(CONTRACT)})
    check("contract extracted", c is not None and c["strike"] == 450.0, str(c))
    check("option_type preserved", c["option_type"] == "call")


def test_extracts_contract_from_sell_result():
    print("\n[2] SELL result nests the contract under the 'put' leg")
    put = dict(CONTRACT, option_type="put")
    result = {"mode": "bear_protect_and_put",
              "close": {"status": "success", "qty": 10},
              "put": {"status": "success", "contract": put}}
    c = ie._contract_from_result(result)
    check("contract found under 'put'", c is not None and c["option_type"] == "put", str(c))


def test_equity_result_yields_no_contract():
    print("\n[3] An equity fill forwards no contract (equity leg preserved)")
    check("plain equity result", ie._contract_from_result(
        {"status": "success", "side": "buy", "qty": 5, "price": 10.0}) is None)
    check("None result", ie._contract_from_result(None) is None)
    check("non-dict result", ie._contract_from_result("nope") is None)


def test_incomplete_contract_is_refused():
    print("\n[4] An incomplete contract degrades to equity rather than half-placing")
    check("missing strike -> None", ie._contract_from_result(
        {"contract": {"option_type": "call", "expiration": "2026-08-07"}}) is None)
    check("missing expiration -> None", ie._contract_from_result(
        {"contract": {"option_type": "call", "strike": 450.0}}) is None)


# ── Queue payload ─────────────────────────────────────────────────────────────
def test_queue_carries_contract():
    print("\n[5] The pending queue carries the contract to the PC executor")
    pending._QUEUE.clear()
    pending.push_iam_primary_signal("SPY", "BUY", "SML_CASCADE", 450.0, 85.0,
                                    contract=dict(CONTRACT))
    sigs = pending._pop_all()
    check("one signal queued", len(sigs) == 1)
    s = sigs[0]
    check("marked as an option signal", s.get("instrument") == "option", str(s.get("instrument")))
    check("contract round-trips intact", s["contract"]["strike"] == 450.0)
    check("expiration round-trips", s["contract"]["expiration"] == "2026-08-07")
    check("delta forwarded for the RH band check", s["contract"]["delta"] == 0.35)


def test_queue_without_contract_stays_equity():
    print("\n[6] No contract -> equity signal, exactly as before")
    pending._QUEUE.clear()
    pending.push_iam_primary_signal("AMC", "BUY", "SML_BREAKOUT", 4.0, 80.0)
    sigs = pending._pop_all()
    check("marked as equity", sigs[0].get("instrument") == "equity")
    check("no contract key", "contract" not in sigs[0])
    check("existing fields unchanged", sigs[0]["symbol"] == "AMC" and sigs[0]["action"] == "BUY")


def test_queue_still_rejects_bad_actions():
    print("\n[7] Queue guards are unchanged")
    pending._QUEUE.clear()
    pending.push_iam_primary_signal("SPY", "HOLD", "X", 1.0, 1.0, contract=dict(CONTRACT))
    pending.push_iam_primary_signal("", "BUY", "X", 1.0, 1.0, contract=dict(CONTRACT))
    check("HOLD and empty symbol both rejected", len(pending._pop_all()) == 0)


# ── Delta band interaction (a real divergence case, not hidden) ───────────────
def test_delta_band_divergence_is_real_and_documented():
    print("\n[8] Robinhood's own 0.30-0.40 delta band still applies")
    # iam_executor's default bracket (0.32-0.40) sits INSIDE Robinhood's
    # hard 0.30-0.40 band, so the normal path agrees on both brokers.
    os.environ.pop("IAM_DELTA_MIN", None)
    os.environ.pop("IAM_DELTA_MAX", None)
    check("IAM default min 0.32 is inside RH band", 0.30 <= ie.DELTA_MIN() <= 0.40,
          str(ie.DELTA_MIN()))
    check("IAM default max 0.40 is inside RH band", 0.30 <= ie.DELTA_MAX() <= 0.40,
          str(ie.DELTA_MAX()))

    # But a widened IAM bracket WOULD diverge: Tradier fills, Robinhood skips.
    # This is deliberate (RH's band is its own risk rail) and is documented
    # rather than silently widened.
    os.environ["IAM_DELTA_MIN"] = "0.20"
    check("widening IAM_DELTA_MIN below 0.30 creates a real divergence",
          ie.DELTA_MIN() < 0.30, str(ie.DELTA_MIN()))
    os.environ.pop("IAM_DELTA_MIN", None)


def test_missing_delta_soft_allows():
    print("\n[9] A contract with no greeks forwards delta=None (RH soft-allows)")
    c = dict(CONTRACT)
    c["delta"] = None
    pending._QUEUE.clear()
    pending.push_iam_primary_signal("SPY", "BUY", "SML_CASCADE", 450.0, 85.0, contract=c)
    s = pending._pop_all()[0]
    check("delta None round-trips rather than becoming 0.0",
          s["contract"]["delta"] is None, str(s["contract"]["delta"]))
    # _execute_option does abs(float(delta or 0)) -> 0.0, and its band check is
    # `if _ad > 0 and not (0.30 <= _ad <= 0.40)`, so 0.0 soft-allows. That is
    # the pre-existing "legacy pack" behaviour, unchanged by this work.


# ── The compound SELL (the bug this build almost introduced) ──────────────────
def test_sell_routes_both_close_and_put():
    print("\n[10] A SELL must close the long AND buy the put on Robinhood")
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "tools", "robinhood_executor_sml.py")).read()
    block = src[src.index("def _poll_iam_primary"):src.index("def _poll_oracle")]

    check("the options branch exists", "_execute_option(symbol, option_type" in block)
    check("SELL still runs the equity close first",
          re.search(r'if direction == "SELL":\s*\n\s*_execute\(symbol, "sell"', block) is not None,
          "close leg missing — a SELL would leave the RH long open")
    # Order matters: close before opening the put, mirroring the server's
    # bear_protect_and_put sequence.
    close_at = block.find('_execute(symbol, "sell"')
    put_at = block.find("_execute_option(symbol, option_type")
    check("close is sequenced before the put buy", 0 < close_at < put_at,
          f"close@{close_at} put@{put_at}")


def test_equity_fallback_still_present():
    print("\n[11] Signals without a contract still take the equity path")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "tools", "robinhood_executor_sml.py")).read()
    block = src[src.index("def _poll_iam_primary"):src.index("def _poll_oracle")]
    check("equity _execute still reachable", "_execute(symbol, side, sml_proxy, scan_counter)" in block)
    check("guarded on a real contract being present",
          'contract = sig.get("contract")' in block)
    check("option_type validated before routing",
          'option_type in ("call", "put")' in block)


if __name__ == "__main__":
    print("=" * 72)
    print("Robinhood options-leg tests")
    print("=" * 72)
    for fn in [test_extracts_contract_from_buy_result, test_extracts_contract_from_sell_result,
               test_equity_result_yields_no_contract, test_incomplete_contract_is_refused,
               test_queue_carries_contract, test_queue_without_contract_stays_equity,
               test_queue_still_rejects_bad_actions,
               test_delta_band_divergence_is_real_and_documented,
               test_missing_delta_soft_allows, test_sell_routes_both_close_and_put,
               test_equity_fallback_still_present]:
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
