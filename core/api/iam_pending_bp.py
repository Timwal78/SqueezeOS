"""
IAM Primary-System -> Robinhood Pending Queue
==============================================
Lets iam_executor.execute_from_resolution() surface a primary-system signal
(CASCADE / SR-Matrix / Breakout / MM-V4 -- whatever IAM_PRIMARY_SYSTEM lists)
to the Robinhood PC executor, IN ADDITION to the real Tradier order it
already places via _execute_tradier(). Both brokers place the same trade
independently on their own accounts -- explicit operator decision
(2026-07-29): Robinhood holds the funds and has no PDT rule, and doubled
exposure across two separate brokerage accounts is accepted, not a bug.

Mirrors core/api/tradingview_webhook_bp.py's exact queue pattern (in-memory
deque, TTL, lock) so tools/robinhood_executor_sml.py's polling convention
stays consistent across every signal source it consumes.

Robinhood executor polls:
  GET https://squeezeos-api.onrender.com/api/webhooks/iam_pending?limit=N
  Returns and pops up to N (default: all) oldest non-expired signals,
  FIFO. Anything not popped stays queued for the next poll.

BUG FIX (2026-08-01, found during the 7-engine profitability audit): this
route used to pop-and-clear the ENTIRE queue on every single GET,
regardless of how many of the returned signals the client actually went on
to execute. tools/robinhood_executor_sml.py's _poll_iam_primary() only
executes up to MAX_PER_SCAN (default 3, shared across ALL 7 primary
systems) per poll via one shared counter -- so any signal beyond the 3rd
in a single 45s cycle was being permanently discarded, not "deferred to
next cycle" as that function's own log message implied, since the
server-side queue backing it had already been wiped by the act of fetching
it. Fixed by adding an optional `limit` query param: the route only pops
what it actually returns, leaving the remainder queued (in original order)
for a later poll -- safe within the existing 10-minute TTL given the 45s
poll cadence.
"""
import time
import threading
from collections import deque
from flask import Blueprint, jsonify, request

iam_pending_bp = Blueprint("iam_pending", __name__)

# Same shape/TTL as tradingview_webhook_bp._TV_QUEUE -- kept as a separate
# queue (not reused) so IAM primary-system signals and raw TradingView Pine
# alerts stay independently attributable in logs, even though the consumer
# (tools/robinhood_executor_sml.py) treats both the same way once popped.
_QUEUE: deque = deque(maxlen=50)
_QUEUE_LOCK = threading.Lock()
_SIGNAL_TTL = 600  # 10 minutes, same as tv_pending


def push_iam_primary_signal(sym: str, action: str, system: str, price: float,
                            confidence: float, contract: dict = None):
    """Called by iam_executor.execute_from_resolution() for primary-system,
    non-paper BUY/SELL resolutions -- after the real Tradier order, so
    Robinhood gets the same directive independent of Tradier's fill result.

    `contract`, when present, is the EXACT option contract the Tradier leg just
    selected (see iam_executor._contract_from_result). Passing it through is
    what closes the long-standing inconsistency where a signal that bought a
    CALL on Tradier bought SHARES on Robinhood: options are
    exchange-standardized, so the same underlying + expiration + strike + type
    is literally the same contract on both brokers. The Robinhood executor
    deliberately never re-derives it (see _execute_option's docstring) -- if
    each side picked its own contract they could silently diverge.

    Omitted/None keeps the previous equity behaviour exactly, so an older PC
    executor that doesn't understand the field is unaffected.
    """
    if action not in ("BUY", "SELL") or not sym:
        return
    signal = {
        "symbol":     sym.upper().strip(),
        "action":     action,
        "system":     system,
        "price":      float(price or 0.0),
        "confidence": float(confidence or 0.0),
        "ts":         time.time(),
    }
    if contract:
        signal["contract"] = contract
        signal["instrument"] = "option"
    else:
        signal["instrument"] = "equity"
    with _QUEUE_LOCK:
        _QUEUE.append(signal)


def _pop_all(limit: int = None) -> list:
    """Return up to `limit` (default: all) oldest non-expired signals, FIFO.
    Anything not returned this call stays queued -- in its original order --
    for a later poll, instead of being discarded. This is the crux of the
    2026-08-01 fix: a consumer-side per-cycle throttle (MAX_PER_SCAN) must
    never sit downstream of a queue that unconditionally clears everything
    on every read, or unconsumed signals are lost forever rather than
    merely delayed."""
    now = time.time()
    with _QUEUE_LOCK:
        fresh = [s for s in _QUEUE if now - s["ts"] < _SIGNAL_TTL]
        if limit is None or limit >= len(fresh):
            _QUEUE.clear()
            return fresh
        limit = max(limit, 0)
        to_return, remaining = fresh[:limit], fresh[limit:]
        _QUEUE.clear()
        _QUEUE.extend(remaining)
        return to_return


@iam_pending_bp.route("/iam_pending", methods=["GET"])
def iam_pending():
    """Robinhood executor polls this to pick up IAM primary-system signals
    (CASCADE/SR-Matrix/Breakout/MM-V4/Sovereign Squeeze/Quad-Score/S-R Zone
    +Pattern). Optional ?limit=N pops only the oldest N fresh signals,
    leaving the rest queued; omitted or invalid pops everything (prior
    behavior, still the default). Expires after 10 min regardless."""
    limit = None
    raw = request.args.get("limit")
    if raw:
        try:
            limit = int(raw)
        except ValueError:
            limit = None
    signals = _pop_all(limit)
    return jsonify({
        "status":  "success",
        "signals": signals,
        "count":   len(signals),
        "ts":      time.time(),
    })
