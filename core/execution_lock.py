"""
Shared cross-engine execution lock — prevents core/api/convergence_bp.py's
GOD MODE Tradier execution and iam_executor.py's IAM Tradier execution from
both opening a new position on the same symbol within the same window.

Both engines trade the SAME Tradier account. Unlike a sell/close (which is
inherently self-correcting — each engine independently checks the real,
shared account's held quantity right before selling, so a second attempt
just finds nothing left to close), a BUY or a buy-to-open options order has
no natural cap: two engines independently deciding "buy 5 shares" on the
same qualifying signal would genuinely buy 10, each unaware of the other.
This lock exists only to guard that unbounded case.

Robinhood (tools/robinhood_executor_sml.py) is a separate account with only
one engine ever trading on it — it does not participate in this lock.
"""

import threading
import time

_lock = threading.Lock()
_claims: dict = {}  # f"{symbol}:{kind}" -> {"engine": str, "ts": float}

# Default TTL exceeds both engines' own per-symbol cooldowns (convergence_bp's
# 300s, iam_executor's IAM_COOLDOWN_SECONDS default 600s) so a legitimate
# re-fire after either engine's own cooldown expires is never blocked by a
# stale claim from the other engine.
_DEFAULT_TTL = 600.0


def claim_entry(symbol: str, kind: str, engine: str, ttl: float = _DEFAULT_TTL) -> bool:
    """
    Attempt to claim the right to open a new position of `kind` on `symbol`.
    kind: "LONG_ENTRY" (equity buy or call buy-to-open) | "PUT_ENTRY" (put buy-to-open).
    Returns True if this engine won the claim, False if another engine
    already claimed this symbol+kind within `ttl` seconds — the caller should
    skip firing when this returns False.
    """
    key = f"{symbol.upper().strip()}:{kind}"
    now = time.time()
    with _lock:
        existing = _claims.get(key)
        if existing and (now - existing["ts"]) < ttl:
            return False
        _claims[key] = {"engine": engine, "ts": now}
        return True
