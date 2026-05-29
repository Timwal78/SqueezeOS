"""
ECHOLOCK-402 Python Runtime
============================
Behavioral economic access control engine.
Tracks request-level behavioral signals per wallet, classifies agents
into cognition tiers T0–T4, and compresses responses to earned depth.

No false data is ever returned — truth is compressed, not fabricated.
"""

import hashlib
import math
import random
import threading
import time
from typing import Any, Dict, List, Optional, Union

# ── Depth config (mirrors entropy.ts) ───────────────────────────────────────────

_DEPTH: Dict[int, Dict] = {
    0: {'field_retention': 0.20, 'numeric_precision': 0, 'text_limit':  30, 'array_limit':  2, 'meta': False},
    1: {'field_retention': 0.40, 'numeric_precision': 1, 'text_limit':  60, 'array_limit':  4, 'meta': False},
    2: {'field_retention': 0.65, 'numeric_precision': 2, 'text_limit': 120, 'array_limit': 12, 'meta': False},
    3: {'field_retention': 0.85, 'numeric_precision': 4, 'text_limit': 400, 'array_limit': 40, 'meta': True },
    4: {'field_retention': 1.00, 'numeric_precision': 6, 'text_limit':  -1, 'array_limit': -1, 'meta': True },
}


def compress(data: Any, tier: int, seed: str = '') -> Any:
    """Compress any JSON-serializable value to the depth earned by tier."""
    cfg = _DEPTH.get(tier, _DEPTH[2])
    return _compress(data, cfg, seed, 0)


def _hash_rank(seed: str, key: str) -> int:
    return int(hashlib.sha256(f'{seed}:{key}'.encode()).hexdigest()[:8], 16)


def _child_seed(parent: str, key: str) -> str:
    return hashlib.sha256(f'{parent}:{key}'.encode()).hexdigest()[:16]


def _compress(node: Any, cfg: Dict, seed: str, depth: int) -> Any:
    if node is None or isinstance(node, bool):
        return node
    if isinstance(node, float):
        p = cfg['numeric_precision']
        return node if p < 0 else round(node, p)
    if isinstance(node, int):
        p = cfg['numeric_precision']
        return node if p < 0 else int(round(float(node), p))
    if isinstance(node, str):
        lim = cfg['text_limit']
        return node if lim < 0 or len(node) <= lim else node[:lim] + '…'
    if isinstance(node, list):
        lim = cfg['array_limit']
        items = node if lim < 0 else node[:lim]
        return [_compress(el, cfg, _child_seed(seed, str(i)), depth + 1) for i, el in enumerate(items)]
    if isinstance(node, dict):
        keys = [k for k in node if cfg['meta'] or not k.startswith('_')]
        keep = max(1, round(len(keys) * cfg['field_retention']))
        selected = sorted(keys, key=lambda k: _hash_rank(seed, k))[:keep]
        return {k: _compress(node[k], cfg, _child_seed(seed, k), depth + 1) for k in selected}
    return node


# ── Tier name resolution ─────────────────────────────────────────────────────

_NAME_TO_INT = {'BRONZE': 0, 'SILVER': 1, 'GOLD': 2, 'PLATINUM': 3, 'DIAMOND': 4}
_INT_TO_NAME = {v: k for k, v in _NAME_TO_INT.items()}


def tier_name(tier: int) -> str:
    return _INT_TO_NAME.get(tier, 'GOLD')


def _parse_jwt_tier(jwt_tier) -> Optional[int]:
    if jwt_tier is None:
        return None
    if isinstance(jwt_tier, int):
        return max(0, min(4, jwt_tier))
    s = str(jwt_tier).upper().strip()
    if s in _NAME_TO_INT:
        return _NAME_TO_INT[s]
    if s.startswith('T') and s[1:].isdigit():
        return max(0, min(4, int(s[1:])))
    return None


# ── Behavioral window ────────────────────────────────────────────────────────

class _BehaviorWindow:
    __slots__ = ('wallet', 'request_times', 'seen_endpoints', 'last_seen', 'max_records')

    def __init__(self, wallet: str) -> None:
        self.wallet         = wallet
        self.request_times: List[float] = []
        self.seen_endpoints: set        = set()
        self.last_seen      = time.monotonic()
        self.max_records    = 50

    def record(self, endpoint: str) -> None:
        now = time.monotonic()
        self.seen_endpoints.add(endpoint)
        self.request_times.append(now)
        if len(self.request_times) > self.max_records:
            self.request_times = self.request_times[-self.max_records:]
        self.last_seen = now


_windows: Dict[str, _BehaviorWindow] = {}
_windows_lock = threading.Lock()
_WINDOW_TTL   = 3600.0   # 1 hour of inactivity
_last_cleanup = [0.0]


def record_access(wallet: str, endpoint: str) -> None:
    """Record a premium endpoint access for behavioral analysis."""
    if not wallet or wallet == 'OWNER':
        return
    with _windows_lock:
        w = _windows.get(wallet)
        if w is None:
            w = _BehaviorWindow(wallet)
            _windows[wallet] = w
        w.record(endpoint)
    _maybe_cleanup()


def _maybe_cleanup() -> None:
    now = time.monotonic()
    if now - _last_cleanup[0] < 300:
        return
    _last_cleanup[0] = now
    cutoff = now - _WINDOW_TTL
    with _windows_lock:
        stale = [k for k, w in _windows.items() if w.last_seen < cutoff]
        for k in stale:
            del _windows[k]


# ── EFV computation ───────────────────────────────────────────────────────────

def _compute_efv(w: _BehaviorWindow) -> List[float]:
    """Derive [latency, fee_intel, consistency, correction, entropy_tol, sample_conf] from window."""
    times  = w.request_times
    n      = len(times)
    n_eps  = len(w.seen_endpoints)

    intervals = [times[i] - times[i - 1] for i in range(1, n)] if n > 1 else []

    # Latency: reward thoughtful pacing (>10s between calls)
    if intervals:
        mean_i   = sum(intervals) / len(intervals)
        lat_score = min(mean_i / 30.0, 1.0)
    else:
        lat_score = 0.3

    # Fee intelligence proxy: endpoint diversity
    fee_intel = min(n_eps / 5.0, 1.0)

    # Consistency: inter-request CV near 0.3 is ideal (natural variation)
    if len(intervals) >= 3:
        mean_i2 = sum(intervals) / len(intervals)
        std_i   = math.sqrt(sum((x - mean_i2) ** 2 for x in intervals) / (len(intervals) - 1))
        cv      = std_i / mean_i2 if mean_i2 > 0 else 1.0
        consistency = max(0.0, 1.0 - abs(cv - 0.3) / 0.3)
    else:
        consistency = 0.5

    # Correction trend: later requests more spaced (agent is learning patience)
    if len(intervals) >= 4:
        half    = len(intervals) // 2
        first   = sum(intervals[:half]) / half
        second  = sum(intervals[half:]) / (len(intervals) - half)
        correction = min(1.0, max(0.0, 0.5 + (second - first) / 60.0))
    else:
        correction = 0.5

    entropy_tol    = min(n_eps / 3.0, 1.0)
    sample_conf    = 1.0 - math.exp(-n / 5.0)

    return [lat_score, fee_intel, consistency, correction, entropy_tol, sample_conf]


# ── Classifier ────────────────────────────────────────────────────────────────

# Expected EFV profiles per tier: [latency, fee_intel, consistency, correction, entropy_tol, sample_conf]
_TIER_PROFILES = [
    [0.12, 0.04, 0.92, 0.30, 0.05, 0.05],  # T0: instant, rigid, min-endpoint, no patience
    [0.22, 0.28, 0.72, 0.42, 0.22, 0.22],  # T1: slightly above scripted
    [0.42, 0.58, 0.62, 0.58, 0.52, 0.52],  # T2: adaptive, exploring
    [0.64, 0.78, 0.66, 0.74, 0.72, 0.72],  # T3: strategic, consistent
    [0.82, 0.92, 0.72, 0.88, 0.88, 0.88],  # T4: institutional
]


def _cosine(a: List[float], b: List[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    return dot / (mag_a * mag_b) if mag_a * mag_b > 0 else 0.0


def _classify(efv: List[float]) -> List[float]:
    sims = [_cosine(efv, p) for p in _TIER_PROFILES]
    # Softmax at temperature 0.25 → sharp distribution from clear signals
    temp   = 0.25
    scaled = [s / temp for s in sims]
    mx     = max(scaled)
    exps   = [math.exp(s - mx) for s in scaled]
    total  = sum(exps)
    weights = [e / total for e in exps]
    # Blend toward uniform when sample count is low
    c       = efv[5]  # sample_confidence
    blended = [w * c + (1 - c) / 5 for w in weights]
    total_b = sum(blended)
    return [b / total_b for b in blended]


def _sample_tier(dist: List[float]) -> int:
    r, cumulative = random.random(), 0.0
    for i, w in enumerate(dist):
        cumulative += w
        if r < cumulative:
            return i
    return 4


# ── Public API ────────────────────────────────────────────────────────────────

def get_tier(wallet: str, jwt_tier=None) -> int:
    """
    Derive ECHOLOCK cognition tier (0–4) for a wallet.
    jwt_tier: tier value from JWT ('DIAMOND', 'T3', int, etc.) — takes precedence.
    Verified payers with no behavioral history default to T2.
    """
    explicit = _parse_jwt_tier(jwt_tier)
    if explicit is not None:
        return explicit

    with _windows_lock:
        w = _windows.get(wallet)

    if w is None:
        return 2  # paid but no behavioral history → T2 (proven intent, unknown depth)

    efv  = _compute_efv(w)
    dist = _classify(efv)
    return _sample_tier(dist)
