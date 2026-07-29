"""
Regression test: tools/robinhood_executor_sml.py's _poll_gamma_ramp() must
actually process SELL_TO_CLOSE (exit) intents from the gamma-ramp desk
without crashing.

Before this fix, `symbol` was referenced inside the SELL_TO_CLOSE branch
(the log line and the call to _execute_option_sell()) but only ever
ASSIGNED further down in the function, in code reached exclusively by the
BUY_TO_OPEN path. Every exit intent -- every hard stop, scale-out, bank,
giveback-lock, trail, delta-expansion exit this desk ever generates --
raised UnboundLocalError before the sell order was placed. The crash was
swallowed by run_loop()'s outer try/except (the process kept running), so
this failed completely silently in production: no gamma-ramp option
position could ever be automatically closed by this engine.

This drives the real, unmodified _poll_gamma_ramp() against a real intent
file shaped exactly like rh_route.py's RHOptionIntent.to_dict() output,
mocking only the true I/O boundary (_execute_option_sell).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOG_DIR", "/tmp/gamma_test_logs")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import robinhood_executor_sml as rex  # noqa: E402


def test_sell_to_close_intent_does_not_crash_and_calls_execute_option_sell():
    with tempfile.TemporaryDirectory() as tmp:
        outbox = Path(tmp)
        intent = {
            "id": "grx_test_1",
            "action": "SELL_TO_CLOSE",
            "underlying": "SPY",
            "option_type": "call",
            "side": "CALL",
            "strike": 550.0,
            "expiration": "2026-08-01",
            "occ": "SPY260801C00550000",
            "qty": 1,
            "bid": 4.10,
            "ask": 4.20,
            "mid": 4.15,
            "limit_price": 4.19,
            "reason": "bank_300",
            "status": "pending",
        }
        (outbox / "gr_test_1.json").write_text(json.dumps(intent))

        calls = []

        def fake_execute_option_sell(symbol, option_type, strike, expiration, qty, limit_price, reason):
            calls.append((symbol, option_type, strike, expiration, qty, limit_price, reason))
            return {"placed": True, "paper": False}

        with patch.object(rex, "GAMMA_RAMP_OUTBOX_DIR", str(outbox)), \
             patch.object(rex, "GAMMA_RAMP_POLL_ENABLED", True), \
             patch.object(rex, "_execute_option_sell", side_effect=fake_execute_option_sell), \
             patch.object(rex, "_load_option_book", return_value={"positions": {}}), \
             patch.object(rex, "_save_option_book", return_value=None):
            placed = rex._poll_gamma_ramp()

        assert len(calls) == 1, f"_execute_option_sell should have been called exactly once, got {calls}"
        symbol_arg = calls[0][0]
        assert symbol_arg == "SPY", f"expected symbol='SPY' passed through, got {symbol_arg!r}"
        assert placed == 1, f"expected 1 order placed, got {placed}"

        # The intent file should have been acked and moved to done/, not left pending
        done_files = list((outbox / "done").glob("*.json"))
        assert len(done_files) == 1, f"expected the intent to be acked+moved to done/, got {done_files}"
        acked = json.loads(done_files[0].read_text())
        assert acked["status"] == "acked", acked

        print("PASS: SELL_TO_CLOSE intent processed without crashing, symbol passed through correctly")


if __name__ == "__main__":
    test_sell_to_close_intent_does_not_crash_and_calls_execute_option_sell()
    print("\nAll regression tests passed.")
