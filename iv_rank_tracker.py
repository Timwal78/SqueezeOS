"""
iv_rank_tracker.py -- self-mining, real IV-rank tracker.

No free source for historical per-symbol options-chain / implied-volatility
data exists anywhere in this codebase (confirmed by search, same gap
already documented for Gamma Pin/Gamma Ramp/CVD Regime -- Tradier only
ever serves the CURRENT live chain). The only honest way to build a real
IV rank is to start recording it, today, and let genuine history
accumulate -- the same self-mining pattern cycle_intelligence_engine.py's
HistoricalFractalMatcher already uses for its own signature library.

Feeds off gamma_flow_engine.calculate_gex_profile()'s already-live
`iv_surface_avg` field (average IV across ATM strikes, computed from a
real Tradier chain) -- this module does not re-parse an option chain
itself, it just persists one real number per (symbol, trading day) that a
caller already computed, and later reports where today's reading sits in
that symbol's own accumulated real history.

NEVER FABRICATES A RANK: reports available=False with an honest reason
(no_history / insufficient_history) until IV_RANK_MIN_HISTORY_DAYS (default
20) real daily readings exist for that symbol. A full, textbook 52-week IV
rank needs ~252 readings -- this reports a real (if statistically thinner)
percentile once the minimum is hit, and always discloses history_days so a
caller can judge how much to trust it.

Storage: Redis (REDIS_URL, shared with paper_trade_ledger.py/CASCADE/AEO)
when configured, local JSON file otherwise -- same durability caveat as
paper_trade_ledger.py: the JSON-file fallback does NOT survive a Render
redeploy (fresh container, no persistent disk attached), Redis does.
Disclosed via a `backend` field on every read, never silently ambiguous.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from threading import Lock
from typing import Optional

logger = logging.getLogger("IV-RANK-TRACKER")

_REDIS_URL = os.environ.get("REDIS_URL", "")
_JSON_PATH = os.environ.get("IV_RANK_JSON_PATH", "iv_rank_history.json")
_MAX_HISTORY = int(os.environ.get("IV_RANK_MAX_HISTORY", "280"))  # a bit over 252 trading days
IV_RANK_MIN_HISTORY_DAYS = int(os.environ.get("IV_RANK_MIN_HISTORY_DAYS", "20"))

_lock = Lock()
_local_state: dict = {}  # {symbol: [[date_iso, iv], ...]}
_local_loaded = False


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _load_local():
    global _local_loaded
    if _local_loaded:
        return
    _local_loaded = True
    if os.path.exists(_JSON_PATH):
        try:
            with open(_JSON_PATH, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _local_state.update(loaded)
        except Exception as e:
            logger.error(f"[IV-RANK] local load error: {e}")


def _save_local():
    try:
        tmp_path = _JSON_PATH + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(_local_state, f, indent=2)
        os.replace(tmp_path, _JSON_PATH)
    except Exception as e:
        logger.error(f"[IV-RANK] local save error: {e}")


def record_iv(symbol: str, iv: float, as_of: Optional[date] = None) -> None:
    """Append today's real ATM IV reading. No-op on invalid input. Dedups
    same-day re-recordings (keeps the latest value for that date -- a
    symbol scanned multiple times in one session shouldn't inflate the
    window with duplicate days)."""
    try:
        iv = float(iv)
    except (TypeError, ValueError):
        return
    if iv <= 0:
        return
    symbol = symbol.strip().upper()
    day = (as_of or date.today()).isoformat()

    with _lock:
        r = _get_redis()
        if r:
            try:
                key = f"iv_rank:{symbol}"
                raw = r.get(key)
                series = json.loads(raw) if raw else []
                series = [p for p in series if p[0] != day]
                series.append([day, iv])
                series = series[-_MAX_HISTORY:]
                r.set(key, json.dumps(series))
                return
            except Exception as e:
                logger.warning(f"[IV-RANK] Redis record failed, falling back to local file: {e}")

        _load_local()
        series = _local_state.get(symbol, [])
        series = [p for p in series if p[0] != day]
        series.append([day, iv])
        series = series[-_MAX_HISTORY:]
        _local_state[symbol] = series
        _save_local()


def get_iv_rank(symbol: str) -> dict:
    """Real percentile rank of the most recently recorded IV within this
    symbol's own accumulated real history. Never fabricates a rank --
    reports available=False (reason='no_history' or 'insufficient_history')
    until IV_RANK_MIN_HISTORY_DAYS real readings exist."""
    symbol = symbol.strip().upper()
    r = _get_redis()
    series = None
    backend = "local_json_no_redis_configured"
    if r:
        try:
            raw = r.get(f"iv_rank:{symbol}")
            series = json.loads(raw) if raw else []
            backend = "redis"
        except Exception as e:
            logger.warning(f"[IV-RANK] Redis read failed, falling back to local file: {e}")
    if series is None:
        _load_local()
        series = _local_state.get(symbol, [])

    if not series:
        return {"available": False, "reason": "no_history", "history_days": 0, "backend": backend}
    if len(series) < IV_RANK_MIN_HISTORY_DAYS:
        return {"available": False, "reason": "insufficient_history", "history_days": len(series),
                "min_required": IV_RANK_MIN_HISTORY_DAYS, "backend": backend}

    ivs = [p[1] for p in series]
    current = ivs[-1]
    below_or_equal = sum(1 for v in ivs if v <= current)
    percentile = round((below_or_equal / len(ivs)) * 100.0, 1)
    return {
        "available": True, "iv_rank": percentile, "current_iv": round(current, 4),
        "history_days": len(series), "backend": backend,
        "note": f"real percentile within this symbol's own {len(series)} self-mined daily readings "
                f"(not a full 252-day/52-week rank until history_days reaches ~252)",
    }
