"""
Simple in-memory rate limiter for SqueezeOS endpoints.

Uses a fixed-window counter per (IP, route_key) pair.
Thread-safe via a lock.  Resets counters when the window expires.

Usage (in a blueprint or app factory):

    from core.rate_limiter import RateLimiter
    _rl = RateLimiter(limit=60, window=60)  # 60 req/min

    @blueprint.before_request
    def _check_rate():
        ip = request.remote_addr or "unknown"
        if not _rl.allow(ip, request.path):
            return jsonify({"error": "rate_limit_exceeded", "retry_after": _rl.window}), 429
"""

import time
import threading
import logging
from collections import defaultdict
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class RateLimiter:
    """Fixed-window in-memory rate limiter.

    Args:
        limit:  Maximum number of requests allowed per window per (ip, key).
        window: Window duration in seconds.
    """

    def __init__(self, limit: int = 60, window: int = 60) -> None:
        self.limit = limit
        self.window = window
        # _counters[(ip, key)] = (count, window_start_ts)
        self._counters: Dict[Tuple[str, str], Tuple[int, float]] = defaultdict(lambda: (0, time.time()))
        self._lock = threading.Lock()

    def allow(self, ip: str, key: str = "") -> bool:
        """Return True if the request should be allowed, False if rate-limited."""
        bucket = (ip, key)
        now = time.time()
        with self._lock:
            count, start = self._counters[bucket]
            if now - start >= self.window:
                # New window — reset
                self._counters[bucket] = (1, now)
                return True
            if count >= self.limit:
                return False
            self._counters[bucket] = (count + 1, start)
            return True

    def cleanup(self) -> None:
        """Remove stale buckets older than 2 windows.  Call periodically if needed."""
        cutoff = time.time() - self.window * 2
        with self._lock:
            stale = [k for k, (_, start) in self._counters.items() if start < cutoff]
            for k in stale:
                del self._counters[k]


# ── Shared rate limiter instances ────────────────────────────────────────────
# Premium endpoints: 30 req/min per IP (cost gate is the primary guard, this
# protects the invoice/payment verification machinery from DoS)
premium_limiter = RateLimiter(limit=30, window=60)

# Free compute-heavy endpoints: 120 req/min per IP
free_limiter = RateLimiter(limit=120, window=60)
