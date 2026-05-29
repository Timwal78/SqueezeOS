"""
ECHOLOCK-402 Behavioral Engine — Python runtime port.

Tracks per-wallet request patterns, computes an Economic Fingerprint Vector (EFV),
classifies agents into tiers T0–T4 via cosine similarity + softmax, and compresses
response payloads to the allowed depth for that tier.

No false data is ever returned — truth is compressed, not fabricated.

Public API
----------
record_access(wallet, endpoint)           — call after each verified payment
get_tier(wallet, jwt_tier=None) -> int    — returns 0–4
compress(data, tier, seed='') -> any      — depth-compress any JSON-serializable value
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Tier depth configuration (mirrors echolock/src/entropy.ts exactly)
# ---------------------------------------------------------------------------

_DEPTH: Dict[int, Dict[str, Any]] = {
    0: {"field_retention": 0.20, "numeric_precision": 0, "text_limit":  30, "array_limit":  2, "meta": False},
    1: {"field_retention": 0.40, "numeric_precision": 1, "text_limit":  60, "array_limit":  4, "meta": False},
    2: {"field_retention": 0.65, "numeric_precision": 2, "text_limit": 120, "array_limit": 12, "meta": False},
    3: {"field_retention": 0.85, "numeric_precision": 4, "text_limit": 400, "array_limit": 40, "meta": True},
    4: {"field_retention": 1.00, "numeric_precision": 6, "text_limit":  -1, "array_limit": -1, "meta": True},
}

# ---------------------------------------------------------------------------
# Tier profiles — cosine similarity targets per tier
# Order: [latency_score, fee_intelligence, consistency, correction_trend,
#         entropy_tolerance, sample_confidence]
# ---------------------------------------------------------------------------

_TIER_PROFILES: List[List[float]] = [
    [0.12, 0.04, 0.92, 0.30, 0.05, 0.05],   # T0
    [0.22, 0.28, 0.72, 0.42, 0.22, 0.22],   # T1
    [0.42, 0.58, 0.62, 0.58, 0.52, 0.52],   # T2
    [0.64, 0.78, 0.66, 0.74, 0.72, 0.72],   # T3
    [0.82, 0.92, 0.72, 0.88, 0.88, 0.88],   # T4
]

# Softmax temperature — lower = sharper winner-take-all distribution
_SOFTMAX_TEMP = 0.25

# Drop windows inactive for this many seconds
_WINDOW_TTL = 3600.0    # 1 hour

# Cleanup check interval
_CLEANUP_INTERVAL = 300.0  # 5 minutes

# ---------------------------------------------------------------------------
# Endpoint price registry — used for per-tier revenue attribution
# ---------------------------------------------------------------------------

_ENDPOINT_PRICES: Dict[str, float] = {
    '/api/council':             0.10,
    '/api/scan':                0.05,
    '/api/options':             0.05,
    '/api/iwm':                 0.03,
    '/api/marketplace/read':    0.02,
    # MCP tool names
    'council_verdict':          0.10,
    'market_scan':              0.05,
    'options_intelligence':     0.05,
    'iwm_odte':                 0.03,
    'marketplace_read_signal':  0.02,
    'oracle_query':             0.02,
}

# ---------------------------------------------------------------------------
# Revenue ledger — in-memory, resets on restart (by design)
# ---------------------------------------------------------------------------

_revenue_lock     = threading.Lock()
_revenue_by_tier: Dict[int, Dict[str, float]] = {i: {'calls': 0.0, 'rlusd': 0.0} for i in range(5)}
_revenue_total:   Dict[str, float] = {'calls': 0.0, 'rlusd': 0.0}

_TIER_LABELS = {0: 'SCRIPTED', 1: 'NAIVE', 2: 'ADAPTIVE', 3: 'STRATEGIC', 4: 'INSTITUTIONAL'}

# ---------------------------------------------------------------------------
# Tier name → int mapping (case-insensitive via .upper() before lookup)
# ---------------------------------------------------------------------------

_NAME_TO_INT: Dict[str, int] = {
    "BRONZE":   0,
    "SILVER":   1,
    "GOLD":     2,
    "PLATINUM": 3,
    "DIAMOND":  4,
    "T0": 0,
    "T1": 1,
    "T2": 2,
    "T3": 3,
    "T4": 4,
}

# ---------------------------------------------------------------------------
# BehaviorWindow — per-wallet sliding event log (thread-safe)
# ---------------------------------------------------------------------------

class _BehaviorWindow:
    """Thread-safe sliding window of access events for a single wallet."""

    # Bound memory; 200 events is well past EFV convergence asymptote
    _MAX_EVENTS = 200

    def __init__(self) -> None:
        # Store (monotonic_ts, endpoint) pairs
        self._events: deque[tuple[float, str]] = deque(maxlen=self._MAX_EVENTS)
        self._lock = threading.Lock()
        self.last_seen: float = time.monotonic()

    def record(self, endpoint: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._events.append((now, endpoint))
            self.last_seen = now

    def snapshot(self) -> List[tuple[float, str]]:
        """Return a stable copy for EFV computation (no lock held during computation)."""
        with self._lock:
            return list(self._events)

    def is_stale(self, now: float) -> bool:
        with self._lock:
            return (now - self.last_seen) > _WINDOW_TTL


# ---------------------------------------------------------------------------
# Global registry + background cleanup daemon
# ---------------------------------------------------------------------------

_windows: Dict[str, _BehaviorWindow] = {}
_registry_lock = threading.Lock()
_last_cleanup: float = 0.0
_cleanup_daemon_started = False


def _get_or_create_window(wallet: str) -> _BehaviorWindow:
    with _registry_lock:
        win = _windows.get(wallet)
        if win is None:
            win = _BehaviorWindow()
            _windows[wallet] = win
        return win


def _maybe_cleanup() -> None:
    """Lazily prune stale windows; checks at most every _CLEANUP_INTERVAL seconds."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    cutoff = now - _WINDOW_TTL
    with _registry_lock:
        stale = [w for w, win in _windows.items() if win.last_seen < cutoff]
        for w in stale:
            del _windows[w]


def _start_cleanup_daemon() -> None:
    """Start a background daemon thread for periodic cleanup (called once)."""
    global _cleanup_daemon_started
    if _cleanup_daemon_started:
        return
    _cleanup_daemon_started = True

    def _loop() -> None:
        while True:
            time.sleep(_CLEANUP_INTERVAL)
            _maybe_cleanup()

    t = threading.Thread(target=_loop, daemon=True, name="echolock-cleanup")
    t.start()


# ---------------------------------------------------------------------------
# EFV computation
# ---------------------------------------------------------------------------

def _compute_efv(events: List[tuple[float, str]]) -> List[float]:
    """
    Compute the 6-dimensional Economic Fingerprint Vector.

    Dimensions (spec order):
      0  latency_score      — mean_interval / 30.0, capped at 1.0
      1  fee_intelligence   — n_unique_endpoints / 5.0, capped at 1.0
      2  consistency        — Gaussian reward peaked at CV = 0.3
      3  correction_trend   — fraction of consecutive interval pairs that increase
      4  entropy_tolerance  — alias of fee_intelligence (profile symmetry)
      5  sample_confidence  — 1 − exp(−n / 5)
    """
    n = len(events)
    sample_confidence = 1.0 - math.exp(-n / 5.0)

    if n < 2:
        n_unique = len({ep for _, ep in events}) if events else 0
        fee_intel = min(n_unique / 5.0, 1.0)
        return [0.0, fee_intel, 0.5, 0.5, fee_intel, sample_confidence]

    timestamps = [ts for ts, _ in events]
    endpoints  = [ep for _, ep in events]

    intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
    mean_interval = sum(intervals) / len(intervals)

    # Dim 0: latency_score — 30 s cadence is the institutional baseline
    latency_score = min(mean_interval / 30.0, 1.0)

    # Dims 1 & 4: endpoint variety signals deliberate multi-feature usage
    n_unique = len(set(endpoints))
    fee_intelligence = min(n_unique / 5.0, 1.0)

    # Dim 2: consistency — Gaussian centred on CV=0.3 (σ=0.2)
    # CV=0 (perfectly metronomic) is slightly penalised; CV=0.3 (mild variation) is ideal
    if mean_interval > 0:
        variance = sum((iv - mean_interval) ** 2 for iv in intervals) / len(intervals)
        cv = math.sqrt(variance) / mean_interval
    else:
        cv = 0.0
    consistency = math.exp(-((cv - 0.3) ** 2) / (2 * 0.2 ** 2))

    # Dim 3: correction_trend — fraction of consecutive interval pairs that increase
    # (agent is "backing off" over time → more institutional pacing)
    if len(intervals) >= 2:
        n_increasing = sum(
            1 for i in range(1, len(intervals)) if intervals[i] > intervals[i - 1]
        )
        correction_trend = n_increasing / (len(intervals) - 1)
    else:
        correction_trend = 0.5   # neutral: only one interval, trend undefined

    return [
        latency_score,
        fee_intelligence,
        consistency,
        correction_trend,
        fee_intelligence,    # entropy_tolerance mirrors fee_intelligence per spec
        sample_confidence,
    ]


# ---------------------------------------------------------------------------
# Cosine similarity + softmax classification
# ---------------------------------------------------------------------------

def _cosine(a: List[float], b: List[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def _softmax(scores: List[float], temp: float) -> List[float]:
    scaled = [s / temp for s in scores]
    mx     = max(scaled)
    exps   = [math.exp(s - mx) for s in scaled]      # subtract max for numerical stability
    total  = sum(exps)
    return [e / total for e in exps]


def _classify_tier(efv: List[float]) -> int:
    """
    Return the argmax tier (0–4) for the given EFV.

    Steps:
      1. Compute cosine similarity between EFV and each tier profile.
      2. Apply softmax (T=0.25) to sharpen the distribution.
      3. Blend toward uniform weighted by (1 − sample_confidence) so that
         sparse windows don't over-commit to any tier.
      4. Return the tier with the highest blended probability (deterministic argmax).
    """
    n_tiers = len(_TIER_PROFILES)
    sample_confidence = efv[5]

    sims  = [_cosine(efv, prof) for prof in _TIER_PROFILES]
    probs = _softmax(sims, _SOFTMAX_TEMP)

    # Pull distribution toward uniform as sample count falls
    uniform = 1.0 / n_tiers
    blended = [
        sample_confidence * p + (1.0 - sample_confidence) * uniform
        for p in probs
    ]

    return blended.index(max(blended))


# ---------------------------------------------------------------------------
# JWT tier parsing
# ---------------------------------------------------------------------------

def _parse_jwt_tier(jwt_tier: Any) -> Optional[int]:
    """Parse a jwt_tier argument into an int 0–4, or None if unrecognised."""
    if jwt_tier is None:
        return None
    if isinstance(jwt_tier, int):
        return max(0, min(4, jwt_tier))
    if isinstance(jwt_tier, str):
        key = jwt_tier.strip().upper()
        if key in _NAME_TO_INT:
            return _NAME_TO_INT[key]
        # Accept bare integer strings ("3", "04")
        try:
            return max(0, min(4, int(key)))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Public API: record_access / get_tier
# ---------------------------------------------------------------------------

def record_access(wallet: str, endpoint: str,
                  price_rlusd: Optional[float] = None) -> None:
    """
    Record a verified-payment access event for the given wallet.

    Call this once per successful payment verification (after @require_payment
    passes) to feed the behavioral engine.  Thread-safe.

    price_rlusd is looked up from _ENDPOINT_PRICES when not supplied.
    """
    _start_cleanup_daemon()
    win = _get_or_create_window(wallet)
    win.record(endpoint)
    _maybe_cleanup()

    price = price_rlusd if price_rlusd is not None else _ENDPOINT_PRICES.get(endpoint, 0.0)
    if price > 0:
        tier = get_tier(wallet)
        with _revenue_lock:
            _revenue_by_tier[tier]['calls'] += 1
            _revenue_by_tier[tier]['rlusd'] = round(
                _revenue_by_tier[tier]['rlusd'] + price, 6
            )
            _revenue_total['calls'] += 1
            _revenue_total['rlusd'] = round(_revenue_total['rlusd'] + price, 6)


def get_tier(wallet: str, jwt_tier: Optional[Any] = None) -> int:
    """
    Return the ECHOLOCK cognition tier (0–4) for a wallet.

    Resolution order
    ----------------
    1. jwt_tier — takes full precedence when supplied.  Accepts:
          str  "DIAMOND" / "PLATINUM" / "GOLD" / "SILVER" / "BRONZE"
          str  "T0" – "T4"  (case-insensitive)
          int  0–4  (clamped to valid range)
    2. Behavioral window — deterministic EFV classification when ≥1 event exists.
    3. Default — T2 (GOLD) for verified payers with no recorded window.
    """
    _start_cleanup_daemon()

    explicit = _parse_jwt_tier(jwt_tier)
    if explicit is not None:
        return explicit

    with _registry_lock:
        win = _windows.get(wallet)

    if win is not None:
        events = win.snapshot()
        if events:
            efv = _compute_efv(events)
            return _classify_tier(efv)

    # Verified payer with no behavioral history → T2 (proven intent, unknown depth)
    return 2


# ---------------------------------------------------------------------------
# Field-selection helper (deterministic per seed)
# ---------------------------------------------------------------------------

def _select_keys(keys: List[str], retention: float, seed: str) -> List[str]:
    """
    Deterministically select the top `retention` fraction of `keys`.

    Keys are ranked by sha256(seed:key) digest — same (seed, key-set) always
    yields the same subset.  When retention >= 1.0 all keys are returned
    without hashing overhead (T4 fast path).
    """
    if retention >= 1.0:
        return keys
    n_keep = max(1, math.ceil(len(keys) * retention))
    ranked = sorted(
        keys,
        key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).digest(),
    )
    return ranked[:n_keep]


# ---------------------------------------------------------------------------
# Public API: compress
# ---------------------------------------------------------------------------

def compress(data: Any, tier: int, seed: str = "") -> Any:
    """
    Recursively depth-compress `data` to the allowed depth for `tier`.

    Rules applied bottom-up
    -----------------------
    dict   → keep only the deterministically-selected field subset (sha256 ranked);
              recurse into retained values.  For T3/T4 (meta=True), an
              ``_echolock_tier`` descriptor is injected at the outermost dict only.
    list   → truncate to array_limit (-1 = unlimited); recurse into items.
    float  → round to numeric_precision decimal places
              (precision 0 → cast to int to avoid trailing ".0").
    str    → truncate to text_limit chars (-1 = unlimited).
    other  → pass through unchanged (bool, int, None).

    `seed` is mixed into the field-selection hash so that different callers
    produce different — yet deterministic — field projections at the same tier.
    """
    cfg  = _DEPTH.get(max(0, min(4, tier)), _DEPTH[2])
    out  = _compress_node(data, cfg, seed)

    # Inject tier descriptor at the outermost dict level only (never in nested dicts)
    if cfg["meta"] and isinstance(out, dict):
        out["_echolock_tier"] = {
            "tier":              tier,
            "field_retention":   cfg["field_retention"],
            "numeric_precision": cfg["numeric_precision"],
            "text_limit":        cfg["text_limit"],
            "array_limit":       cfg["array_limit"],
        }

    return out


def tier_name(tier: int) -> str:
    return _TIER_LABELS.get(max(0, min(4, tier)), 'UNKNOWN')


def revenue_stats() -> Dict[str, Any]:
    """
    Return ECHOLOCK income metrics aggregated since the last server restart.

    Includes:
    - Total and per-tier revenue (calls + RLUSD)
    - Tier distribution of all active behavioral windows
    - Average calls per wallet per tier (retention proxy)
    - Compression metrics (calls served at reduced depth)
    - Machine-readable insight string
    """
    with _revenue_lock:
        total_calls = _revenue_total['calls']
        total_rlusd = _revenue_total['rlusd']
        tier_snap   = {i: dict(_revenue_by_tier[i]) for i in range(5)}

    by_tier: Dict[str, Any] = {}
    for i in range(5):
        calls = tier_snap[i]['calls']
        rlusd = tier_snap[i]['rlusd']
        by_tier[f'T{i}'] = {
            'label':       _TIER_LABELS[i],
            'calls':       int(calls),
            'rlusd':       round(rlusd, 4),
            'pct_calls':   round(calls / total_calls * 100, 1) if total_calls > 0 else 0.0,
            'pct_revenue': round(rlusd / total_rlusd * 100, 1) if total_rlusd > 0 else 0.0,
        }

    # Walk active windows to compute tier distribution + avg calls per wallet
    with _registry_lock:
        windows_snapshot = dict(_windows)

    dist:         Dict[int, int]       = {i: 0 for i in range(5)}
    wallet_calls: Dict[int, List[int]] = {i: [] for i in range(5)}
    for _wallet, win in windows_snapshot.items():
        events = win.snapshot()
        if not events:
            continue
        t = _classify_tier(_compute_efv(events))
        dist[t] += 1
        wallet_calls[t].append(len(events))

    tier_dist: Dict[str, Any] = {f'T{i}': dist[i] for i in range(5)}
    tier_dist['active_wallets'] = sum(dist.values())

    avg_calls_per_wallet: Dict[str, float] = {}
    for i in range(5):
        wc = wallet_calls[i]
        avg_calls_per_wallet[f'T{i}'] = round(sum(wc) / len(wc), 1) if wc else 0.0

    # Compression: T0–T3 received depth-compressed responses
    compressed_calls = int(sum(tier_snap[i]['calls'] for i in range(4)))
    full_depth_calls = int(tier_snap[4]['calls'])
    compression_rate = round(compressed_calls / total_calls * 100, 1) if total_calls > 0 else 0.0

    # Insight
    if total_calls > 0:
        t4 = by_tier['T4']
        t0 = by_tier['T0']
        insight = (
            f"T4 institutional agents generate {t4['pct_revenue']}% of revenue "
            f"from {t4['pct_calls']}% of calls — "
            f"{compression_rate}% of responses were depth-compressed (T0–T3). "
            f"T0 scripted agents: {t0['calls']} calls ({t0['pct_revenue']}% of revenue)."
        )
    else:
        insight = (
            "No ECHOLOCK-tracked revenue yet. "
            "Premium endpoint calls will populate this dashboard."
        )

    return {
        'period':                       'since_last_restart',
        'total_rlusd':                  round(total_rlusd, 4),
        'total_calls':                  int(total_calls),
        'by_tier':                      by_tier,
        'tier_distribution':            tier_dist,
        'avg_calls_per_wallet_by_tier': avg_calls_per_wallet,
        'compression': {
            'compressed_calls':     compressed_calls,
            'full_depth_calls':     full_depth_calls,
            'compression_rate_pct': compression_rate,
        },
        'insight': insight,
    }


def _compress_node(node: Any, cfg: Dict[str, Any], seed: str) -> Any:
    """Inner recursive worker — does NOT inject meta stubs."""
    if node is None or isinstance(node, bool):
        return node

    if isinstance(node, float):
        p = cfg["numeric_precision"]
        rounded = round(node, p)
        # Return int when precision=0 to avoid serialisation noise ("3.0" → 3)
        return int(rounded) if p == 0 else rounded

    if isinstance(node, int):
        # Ints are not rounded (only floats carry fractional precision)
        return node

    if isinstance(node, str):
        lim = cfg["text_limit"]
        return node if lim < 0 or len(node) <= lim else node[:lim]

    if isinstance(node, list):
        lim   = cfg["array_limit"]
        items = node if lim < 0 else node[:lim]
        return [_compress_node(item, cfg, seed) for item in items]

    if isinstance(node, dict):
        selected = _select_keys(list(node.keys()), cfg["field_retention"], seed)
        return {k: _compress_node(node[k], cfg, seed) for k in selected}

    # Fallback for unexpected types (e.g. Decimal, UUID) — pass through
    return node
