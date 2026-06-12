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


def _post(path: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    headers = _headers()
    if not headers:
        return None
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    _rate_limit()
    url = f"{_base_url()}{path}"
    try:
        r = requests.post(url, headers=headers, data=data, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 401:
            logger.error("[TRADIER] 401 Unauthorized — TRADIER_API_KEY rejected")
            return None
        logger.warning(f"[TRADIER] POST {path} HTTP {r.status_code}: {r.text[:400]}")
    except requests.RequestException as e:
        logger.warning(f"[TRADIER] POST {path} network error: {e}")
    return None


def _account_id() -> Optional[str]:
    acct = os.environ.get("TRADIER_ACCOUNT_ID")
    return acct.strip() if acct and acct.strip() else None


def get_account_balance() -> Optional[float]:
    """
    Return the total cash/equity balance for the configured account.
    Used by PDT shield: if balance < $2,100 → enforce 3-trade-per-5-day PDT rule.
    Returns None if unavailable.
    """
    acct = _account_id()
    if not acct:
        logger.error("[TRADIER] TRADIER_ACCOUNT_ID not set — cannot fetch balance (PDT shield will fail-safe to restricted)")
        return None
    data = _get(f"/accounts/{acct}/balances", {})
    if not data:
        logger.warning(f"[TRADIER] /accounts/{acct}/balances returned no data")
        return None
    balances = data.get("balances") or {}
    # Tradier returns total_equity for margin accounts, total_cash for cash accounts
    equity = balances.get("total_equity") or balances.get("total_cash") or balances.get("equity")
    try:
        return float(equity)
    except (TypeError, ValueError):
        return None


def place_equity_order(symbol: str, quantity: int, side: str,
                       order_type: str = "market", duration: str = "day") -> Dict[str, Any]:
    """
    Place a live equity order via Tradier.
    side: 'buy' | 'sell'
    Returns {'status': 'success', 'order_id': ...} or {'status': 'error', 'message': ...}
    """
    acct = _account_id()
    if not acct:
        return {"status": "error", "message": "TRADIER_ACCOUNT_ID not set"}
    if not _api_key():
        return {"status": "error", "message": "TRADIER_API_KEY not set"}

    payload = {
        "class":    "equity",
        "symbol":   symbol.upper(),
        "side":     side.lower(),
        "quantity": str(quantity),
        "type":     order_type,
        "duration": duration,
    }
    logger.info(f"[TRADIER] Placing equity order: {side.upper()} {quantity}x {symbol} ({order_type})")
    resp = _post(f"/accounts/{acct}/orders", payload)
    if resp and resp.get("order", {}).get("id"):
        order_id = resp["order"]["id"]
        logger.info(f"[TRADIER] Order placed ✅ order_id={order_id}")
        return {"status": "success", "order_id": order_id, "raw": resp}
    err = (resp or {}).get("errors", {}).get("error", "unknown error")
    logger.error(f"[TRADIER] Order failed: {err}")
    return {"status": "error", "message": str(err)}


def place_option_order(option_symbol: str, quantity: int, side: str,
                       limit_price: Optional[float] = None,
                       duration: str = "day") -> Dict[str, Any]:
    """
    Place a 0DTE option order via Tradier.
    option_symbol: OCC format e.g. 'IWM260610C00210000'
    side: 'buy_to_open' | 'sell_to_close'
    """
    acct = _account_id()
    if not acct:
        return {"status": "error", "message": "TRADIER_ACCOUNT_ID not set"}
    if not _api_key():
        return {"status": "error", "message": "TRADIER_API_KEY not set"}

    order_type = "limit" if limit_price else "market"
    payload = {
        "class":    "option",
        "symbol":   option_symbol,
        "side":     side.lower(),
        "quantity": str(quantity),
        "type":     order_type,
        "duration": duration,
    }
    if limit_price:
        payload["price"] = f"{limit_price:.2f}"

    logger.info(f"[TRADIER] Placing option order: {side} {quantity}x {option_symbol} ({order_type})")
    resp = _post(f"/accounts/{acct}/orders", payload)
    if resp and resp.get("order", {}).get("id"):
        order_id = resp["order"]["id"]
        logger.info(f"[TRADIER] Option order placed ✅ order_id={order_id}")
        return {"status": "success", "order_id": order_id, "raw": resp}
    err = (resp or {}).get("errors", {}).get("error", "unknown error")
    logger.error(f"[TRADIER] Option order failed: {err}")
    return {"status": "error", "message": str(err)}


class TradierBroker:
    """
    Thin broker wrapper so ExecutionEngine can call self.broker.place_order()
    without knowing the underlying provider.
    """
    def __init__(self):
        self.available = bool(_api_key() and _account_id())

    def place_order(self, symbol: str, quantity: int, side: str) -> Dict[str, Any]:
        return place_equity_order(symbol, quantity, side)


def get_quotes_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch quotes for multiple symbols in a single API call."""
    if not symbols:
        return {}
    data = _get("/markets/quotes", {"symbols": ",".join(symbols), "greeks": "false"})
    if not data:
        return {}
    raw = (data.get("quotes") or {}).get("quote") or []
    if isinstance(raw, dict):
        raw = [raw]
    return {q["symbol"]: q for q in raw if isinstance(q, dict) and "symbol" in q}


def get_history_df(symbol: str, days: int = 100, interval: str = "daily"):
    """
    Fetch OHLCV history for a symbol from Tradier.
    Returns a pandas DataFrame with columns Open/High/Low/Close/Volume
    and a DatetimeIndex — same shape as yfinance.download(symbol).
    Returns None if unavailable.
    """
    try:
        import pandas as pd
        from datetime import date, timedelta
    except ImportError:
        return None

    end   = date.today()
    start = end - timedelta(days=days + 10)  # small buffer for weekends

    # Tradier interval: daily | weekly | monthly
    tradier_interval = "daily" if interval in ("1d", "daily", "1Day") else interval

    data = _get("/markets/history", {
        "symbol":   symbol,
        "interval": tradier_interval,
        "start":    start.strftime("%Y-%m-%d"),
        "end":      end.strftime("%Y-%m-%d"),
    })
    if not data:
        return None

    days_data = (data.get("history") or {}).get("day") or []
    if isinstance(days_data, dict):
        days_data = [days_data]
    if not days_data:
        return None

    df = pd.DataFrame(days_data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(columns={
        "open":   "Open",
        "high":   "High",
        "low":    "Low",
        "close":  "Close",
        "volume": "Volume",
    })
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_history_batch(symbols: List[str], days: int = 100) -> Dict[str, Any]:
    """
    Fetch historical DataFrames for multiple symbols sequentially.
    Returns { symbol: DataFrame } — same shape as yf.download(symbols, group_by='ticker').
    """
    result = {}
    for sym in symbols:
        df = get_history_df(sym, days=days)
        if df is not None and not df.empty:
            result[sym] = df
    return result


__all__ = [
    "is_available",
    "get_expirations",
    "get_chain",
    "get_quote",
    "get_quotes_batch",
    "get_history_df",
    "get_history_batch",
    "get_option_chain_schwab_format",
    "SANDBOX_BASE",
    "PRODUCTION_BASE",
]
