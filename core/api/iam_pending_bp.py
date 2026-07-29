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
  GET https://squeezeos-api.onrender.com/api/webhooks/iam_pending
  Returns and clears all signals queued in the last 10 minutes.
"""
import time
import threading
from collections import deque
from flask import Blueprint, jsonify

iam_pending_bp = Blueprint("iam_pending", __name__)

# Same shape/TTL as tradingview_webhook_bp._TV_QUEUE -- kept as a separate
# queue (not reused) so IAM primary-system signals and raw TradingView Pine
# alerts stay independently attributable in logs, even though the consumer
# (tools/robinhood_executor_sml.py) treats both the same way once popped.
_QUEUE: deque = deque(maxlen=50)
_QUEUE_LOCK = threading.Lock()
_SIGNAL_TTL = 600  # 10 minutes, same as tv_pending


def push_iam_primary_signal(sym: str, action: str, system: str, price: float, confidence: float):
    """Called by iam_executor.execute_from_resolution() for primary-system,
    non-paper BUY/SELL resolutions -- after the real Tradier order, so
    Robinhood gets the same directive independent of Tradier's fill result."""
    if action not in ("BUY", "SELL") or not sym:
        return
    with _QUEUE_LOCK:
        _QUEUE.append({
            "symbol":     sym.upper().strip(),
            "action":     action,
            "system":     system,
            "price":      float(price or 0.0),
            "confidence": float(confidence or 0.0),
            "ts":         time.time(),
        })


def _pop_all() -> list:
    """Return all non-expired signals and clear the queue."""
    now = time.time()
    with _QUEUE_LOCK:
        fresh = [s for s in _QUEUE if now - s["ts"] < _SIGNAL_TTL]
        _QUEUE.clear()
    return fresh


@iam_pending_bp.route("/iam_pending", methods=["GET"])
def iam_pending():
    """Robinhood executor polls this to pick up IAM primary-system signals
    (CASCADE/SR-Matrix/Breakout/MM-V4). Clears on read; expires after 10 min."""
    signals = _pop_all()
    return jsonify({
        "status":  "success",
        "signals": signals,
        "count":   len(signals),
        "ts":      time.time(),
    })
