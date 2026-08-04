"""In-memory + optional Redis state store for swarm MM.

MVP defaults to process memory (survives only while the process lives).
When REDIS_URL is set, selected keys are mirrored for multi-instance durability.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("swarm-mm.state")

_REDIS_URL = os.environ.get("REDIS_URL", "")
_PREFIX = os.environ.get("SWARM_MM_REDIS_PREFIX", "swarmmm:")


class StateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mem: dict[str, Any] = {}
        self._redis = None
        if _REDIS_URL:
            try:
                import redis

                self._redis = redis.from_url(_REDIS_URL, decode_responses=True)
                self._redis.ping()
                logger.info("Redis connected for swarm-mm state")
            except Exception as exc:  # pragma: no cover
                logger.warning("Redis unavailable, memory-only: %s", exc)
                self._redis = None

    # ── primitives ───────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._mem:
                return self._mem[key]
            if self._redis is not None:
                try:
                    raw = self._redis.get(_PREFIX + key)
                    if raw is not None:
                        val = json.loads(raw)
                        self._mem[key] = val
                        return val
                except Exception as exc:  # pragma: no cover
                    logger.debug("redis get fail %s: %s", key, exc)
            return default

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            self._mem[key] = value
            if self._redis is not None:
                try:
                    payload = json.dumps(value, default=str)
                    rkey = _PREFIX + key
                    if ttl:
                        self._redis.setex(rkey, ttl, payload)
                    else:
                        self._redis.set(rkey, payload)
                except Exception as exc:  # pragma: no cover
                    logger.debug("redis set fail %s: %s", key, exc)

    def delete(self, key: str) -> None:
        with self._lock:
            self._mem.pop(key, None)
            if self._redis is not None:
                try:
                    self._redis.delete(_PREFIX + key)
                except Exception:
                    pass

    def keys_with_prefix(self, prefix: str) -> list[str]:
        with self._lock:
            found = [k for k in self._mem if k.startswith(prefix)]
            if self._redis is not None:
                try:
                    for rk in self._redis.scan_iter(match=_PREFIX + prefix + "*"):
                        bare = rk[len(_PREFIX) :]
                        if bare not in found:
                            found.append(bare)
                except Exception:
                    pass
            return found

    def incr(self, key: str, by: float = 1.0) -> float:
        with self._lock:
            cur = float(self.get(key, 0.0) or 0.0)
            nxt = cur + by
            self.set(key, nxt)
            return nxt

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"keys": len(self._mem), "redis": bool(self._redis), "ts": time.time()}


# Process-wide singleton
store = StateStore()
