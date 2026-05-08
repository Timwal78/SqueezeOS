"""
Tradier API Adapter — SqueezeOS / MMLE
══════════════════════════════════════════════════════════════════
Provides Schwab-shape option chains so the rest of SqueezeOS
(gamma_flow_engine, mm_liquidity_engine, options_intelligence) keeps
working unchanged.

Environment variables (read from process env / .env):
  TRADIER_API_KEY   — bearer token. NEVER hard-code this in source.
  TRADIER_ENV       — "sandbox" (default) or "production"

Sandbox limitations (per Tradier):
  • Market data delayed 15 minutes
  • Account activity unavailable
  • No streaming
  → fine for 5-min cadence research; not for live execution.

Bound by AGENT_LAW.md:
  §1.1 — return None when the API is unreachable or the key is missing.
         Never invent a chain.
  §3.1 — when greek-fields are absent, the downstream engine
         (mm_liquidity_engine) computes them via Black-Scholes from IV;
         a [ESTIMATED_PROXY] note is emitted by the engine in that path.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────
SANDBOX_BASE = "https://sandbox.tradier.com/v1"
PRODUCTION_BASE = "https://api.tradier.com/v1"

# Per-process rate-limit guard (Tradier sandbox: 60 req/min; prod higher)
_LAST_CALL_TS = 0.0
_MIN_INTERVAL_SEC = 1.05


def _base_url() -> str:
    env = (os.environ.get("TRADIER_ENV") or "sandbox").strip().lower()
    return PRODUCTION_BASE if env == "production" else SANDBOX_BASE


def _api_key() -> Optional[str]:
    key = os.environ.get("TRADIER_API_KEY")
    return key.strip() if key and key.strip() else None


def _headers() -> Optional[Dict[str, str]]:
    key = _api_key()
    if not key:
        return None
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def _rate_limit() -> None:
    global _LAST_CALL_TS
    delta = time.time() - _LAST_CALL_TS
    if delta < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - delta)
    _LAST_CALL_TS = time.time()


def is_available() -> bool:
    """Quick readiness check: API key present in environment."""
    return _api_key() is not None


# ──────────────────────────────────────────────────────────────────
# Raw Tradier endpoints
# ──────────────────────────────────────────────────────────────────
def _get(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    headers = _headers()
    if not headers:
        return None
    _rate_limit()
    url = f"{_base_url()}{path}"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            logger.error("[TRADIER] 401 Unauthorized — TRADIER_API_KEY rejected")
            return None
        logger.warning(f"[TRADIER] {path} HTTP {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        logger.warning(f"[TRADIER] {path} network error: {e}")
    return None


def get_expirations(symbol: str) -> List[str]:
    """List option expiration dates (YYYY-MM-DD) for a symbol."""
    data = _get("/markets/options/expirations", {
        "symbol": symbol,
        "includeAllRoots": "true",
        "strikes": "false",
    })
    if not data:
        return []
    exps = (data.get("expirations") or {}).get("date") or []
    if isinstance(exps, str):
        exps = [exps]
    return [e for e in exps if isinstance(e, str)]


def get_chain(symbol: str, expiration: str, greeks: bool = True) -> List[Dict[str, Any]]:
    """Return the raw option list for one expiration, with greeks included."""
    data = _get("/markets/options/chains", {
        "symbol": symbol,
        "expiration": expiration,
        "greeks": "true" if greeks else "false",
    })
    if not data:
        return []
    options = (data.get("options") or {}).get("option") or []
    if isinstance(options, dict):
        options = [options]
    return options


def get_quote(symbol: str) -> Optional[Dict[str, Any]]:
    data = _get("/markets/quotes", {"symbols": symbol, "greeks": "false"})
    if not data:
        return None
    quotes = (data.get("quotes") or {}).get("quote")
    if isinstance(quotes, dict):
        return quotes
    if isinstance(quotes, list) and quotes:
        return quotes[0]
    return None


# ──────────────────────────────────────────────────────────────────
# Schwab-shape adapter
#
# Schwab format expected by gamma_flow_engine / mm_liquidity_engine:
# {
#   "callExpDateMap": {
#     "2026-05-15:5": {                 # "<date>:<dte>"
#       "100.0": [                      # strike → list of contracts
#         {
#           "openInterest": 1234,
#           "totalVolume": 567,
#           "volatility":  25.3,        # IV as percent (NOT 0..1)
#           "gamma": 0.0421,
#           "delta": 0.52,
#           "theta": -0.05,
#           "vega":  0.11,
#         }
#       ]
#     }
#   },
#   "putExpDateMap": { ... }
# }
# ──────────────────────────────────────────────────────────────────
def _dte_for(expiration: str) -> int:
    from datetime import datetime, timezone
    try:
        d = datetime.strptime(expiration, "%Y-%m-%d").replace(tzinfo=timezone.utc).date()
        today = datetime.now(timezone.utc).date()
        return (d - today).days
    except Exception:
        return 0


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def _convert_contract(opt: Dict[str, Any]) -> Dict[str, Any]:
    """Tradier option contract → Schwab-shape contract dict."""
    greeks = opt.get("greeks") or {}
    # Tradier IV is decimal (0.25 = 25%). Schwab convention is percent.
    iv_dec = _to_float(greeks.get("mid_iv") or greeks.get("smv_vol"))
    iv_pct = iv_dec * 100.0 if iv_dec > 0 else 0.0
    return {
        "openInterest": _to_int(opt.get("open_interest")),
        "totalVolume":  _to_int(opt.get("volume")),
        "volatility":   iv_pct,
        "gamma":        _to_float(greeks.get("gamma")),
        "delta":        _to_float(greeks.get("delta")),
        "theta":        _to_float(greeks.get("theta")),
        "vega":         _to_float(greeks.get("vega")),
        "rho":          _to_float(greeks.get("rho")),
        "bid":          _to_float(opt.get("bid")),
        "ask":          _to_float(opt.get("ask")),
        "last":         _to_float(opt.get("last")),
        "strikePrice":  _to_float(opt.get("strike")),
        "symbol":       opt.get("symbol"),
        "expirationDate": opt.get("expiration_date"),
        "putCall":      (opt.get("option_type") or "").upper(),
    }


def get_option_chain_schwab_format(
    symbol: str,
    max_expirations: int = 8,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the full option chain for `symbol` and reshape to Schwab format.

    Iterates the first `max_expirations` expirations (front-month-first).
    Returns None if API unavailable / key missing / no expirations
    (AGENT_LAW §1.1: never invents data).
    """
    if not is_available():
        logger.debug("[TRADIER] TRADIER_API_KEY not set — skipping Tradier path")
        return None

    expirations = get_expirations(symbol)
    if not expirations:
        return None

    call_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    put_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for exp in expirations[:max_expirations]:
        dte = _dte_for(exp)
        key = f"{exp}:{dte}"
        contracts = get_chain(symbol, exp, greeks=True)
        if not contracts:
            continue
        for c in contracts:
            converted = _convert_contract(c)
            strike_str = f"{converted['strikePrice']:.1f}"
            target = call_map if converted["putCall"] == "CALL" else put_map
            target.setdefault(key, {}).setdefault(strike_str, []).append(converted)

    if not call_map and not put_map:
        return None

    # Underlying spot for downstream consumers (Schwab includes this).
    spot = 0.0
    q = get_quote(symbol)
    if q:
        spot = _to_float(q.get("last") or q.get("close") or q.get("bid"))

    return {
        "symbol": symbol,
        "underlyingPrice": spot,
        "callExpDateMap": call_map,
        "putExpDateMap": put_map,
        "_provider": f"tradier:{(os.environ.get('TRADIER_ENV') or 'sandbox')}",
    }


__all__ = [
    "is_available",
    "get_expirations",
    "get_chain",
    "get_quote",
    "get_option_chain_schwab_format",
    "SANDBOX_BASE",
    "PRODUCTION_BASE",
]
