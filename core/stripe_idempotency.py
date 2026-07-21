"""
Shared Stripe webhook idempotency guard.

Stripe retries webhook deliveries on timeout/5xx — documented, not rare
(a slow Redis write or a cold-starting Render dyno is enough to trigger
one). None of this repo's Stripe webhook handlers (aeo_stripe_bp,
cascade_bp, deltaforge_bp, keys_bp, trade_desk_stripe_bp) tracked which
event IDs they'd already processed, so a retried delivery re-ran the same
handler logic again — double-crediting internal ledgers (e.g. AEO
Treasury's 5% revenue accrual), re-issuing/re-revoking API keys, etc. This
never touches real Stripe charges (Stripe itself is the source of truth for
money actually moved) — it only protects this app's own internal
bookkeeping and side effects from running twice for one real payment.
"""
import logging
import time

logger = logging.getLogger("StripeIdempotency")

_PREFIX = "stripe:processed_event:"
_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days — comfortably longer than Stripe's retry window


def already_processed(redis_client, event_id: str) -> bool:
    """
    Atomically marks `event_id` as processed and returns True if it had
    ALREADY been marked before this call (a duplicate delivery — the caller
    should skip re-running its handler logic). Returns False for a
    genuinely new event id.

    Fails OPEN (returns False, i.e. "go ahead and process it") when
    event_id or redis_client is missing, or on any Redis error — a webhook
    occasionally double-processing during a real Redis outage is a lesser
    risk than every webhook silently being dropped because idempotency
    tracking itself is down.
    """
    if not event_id or not redis_client:
        return False
    try:
        # SET key value NX EX ttl is atomic: only sets if the key doesn't
        # already exist. redis-py returns True when it set the key, None
        # when the key already existed (so the SET was a no-op) — "already
        # existed" is exactly the duplicate-delivery case.
        was_set = redis_client.set(
            f"{_PREFIX}{event_id}", str(int(time.time())), nx=True, ex=_TTL_SECONDS
        )
        if not was_set:
            logger.info(f"[STRIPE-IDEMPOTENCY] duplicate delivery of {event_id} — skipping")
        return not was_set
    except Exception as e:
        logger.warning(f"[STRIPE-IDEMPOTENCY] Redis check failed for {event_id}: {e} — processing normally")
        return False
