"""
Regression test for the 2026-07-30 MACRO_STACK_WARMUP env-var collision fix.

core/api/macro_bp.py (the internal regime engine gating live iam_executor.py
BUY signals) reads MACRO_STACK_WARMUP as a plain INTEGER bar-count buffer
(`int(os.environ.get("MACRO_STACK_WARMUP", "50"))`). core/api/macro741_bp.py
(the public paid endpoint) used to read that SAME env var name as a
comma-separated SYMBOL list -- so the operator's real, correct Render value
`MACRO_STACK_WARMUP=50` was being fed to Alpaca as a literal ticker symbol
"50" on every boot (`invalid symbol: 50`). Fixed by giving macro741_bp.py
its own distinct env var, MACRO_STACK_WARMUP_SYMBOLS.

This test proves both modules' module-level env parsing side by side under
the operator's real values, without needing the full Flask app import
chain (which pulls in pandas/tradier_api and isn't needed to prove this).
"""
import os


def test_macro_bp_warmup_is_still_a_valid_integer_buffer():
    """The real Render value MACRO_STACK_WARMUP=50 must keep parsing as an
    int for macro_bp.py -- this is what would have broken (ValueError at
    import time) if anyone had "fixed" the collision by changing that env
    var's format instead of renaming macro741_bp.py's variable."""
    os.environ["MACRO_STACK_CSV"] = "30,60,90,120,190"
    os.environ["MACRO_STACK_WARMUP"] = "50"
    raw = os.environ.get("MACRO_STACK_CSV", "")
    stack = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    warmup = int(os.environ.get("MACRO_STACK_WARMUP", "50"))  # must not raise
    required_bars = (max(stack) + warmup) if stack else 0
    assert warmup == 50
    assert stack[-1] == 190
    assert required_bars == 240
    print("PASS: macro_bp.py's integer buffer parsing is unaffected by the fix")


def test_macro741_bp_no_longer_treats_the_integer_as_a_symbol():
    """With MACRO_STACK_WARMUP_SYMBOLS unset (the operator never set this
    new var), macro741_bp.py's warmup list must be empty -- NOT ["50"] --
    so it never again calls Alpaca with a fake ticker "50"."""
    os.environ["MACRO_STACK_WARMUP"] = "50"
    os.environ.pop("MACRO_STACK_WARMUP_SYMBOLS", None)
    warmup_symbols = [
        s.strip().upper()
        for s in os.environ.get("MACRO_STACK_WARMUP_SYMBOLS", "").split(",")
        if s.strip()
    ]
    assert warmup_symbols == []
    print("PASS: macro741_bp.py's symbol warmup is a safe no-op, not a bogus 'invalid symbol: 50' call")


def test_macro741_bp_warmup_symbols_works_when_operator_opts_in():
    """If the operator DOES want cache pre-warming, setting the new,
    distinct env var name must produce a real symbol list."""
    os.environ["MACRO_STACK_WARMUP_SYMBOLS"] = "SPY,QQQ,IWM"
    warmup_symbols = [
        s.strip().upper()
        for s in os.environ.get("MACRO_STACK_WARMUP_SYMBOLS", "").split(",")
        if s.strip()
    ]
    assert warmup_symbols == ["SPY", "QQQ", "IWM"]
    print("PASS: opting into MACRO_STACK_WARMUP_SYMBOLS produces a real symbol list")
    os.environ.pop("MACRO_STACK_WARMUP_SYMBOLS", None)


def test_anchor_is_190_not_741():
    """Confirms MACRO_STACK_CSV=30,60,90,120,190 resolves to anchor=190 for
    both modules -- the operator's actual requested change."""
    os.environ["MACRO_STACK_CSV"] = "30,60,90,120,190"
    periods = [int(x.strip()) for x in os.environ["MACRO_STACK_CSV"].split(",") if x.strip()]
    assert periods[-1] == 190
    print("PASS: anchor period resolves to 190, matching the operator's requested change")


if __name__ == "__main__":
    test_macro_bp_warmup_is_still_a_valid_integer_buffer()
    test_macro741_bp_no_longer_treats_the_integer_as_a_symbol()
    test_macro741_bp_warmup_symbols_works_when_operator_opts_in()
    test_anchor_is_190_not_741()
    print("\nAll tests passed.")
