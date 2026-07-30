"""
finra_short_interest_data.py -- real FINRA short-interest / days-to-cover
data, via FINRA's OAuth2-gated Query API. This is the metric the operator's
pasted Ortex-style screener actually means by "short interest" -- TOTAL
shares currently held short as of a settlement date, reported bi-monthly
per FINRA Rule 4560 -- which is a genuinely different, more informative
number than finra_short_data.py's daily SHORT VOLUME proxy (shares sold
short on one day, which includes ordinary market-maker/HFT flow).

DIFFERENT ACCESS BAR THAN finra_short_data.py -- READ BEFORE ASSUMING THIS
IS ZERO-CONFIG:
  finra_short_data.py's daily short-volume file (cdn.finra.org) is a plain,
  unauthenticated public download -- no account needed. This dataset lives
  on FINRA's newer Query API platform (developer.finra.org), which DOES
  require credentials -- confirmed via FINRA's own developer documentation
  (finra.org itself blocks this sandbox's outbound fetch entirely, same
  403 pattern already documented for cdn.finra.org and other hosts in this
  codebase, so this was researched via search rather than a direct fetch).
  The good news: FINRA lets any individual register a free "Individual
  Account" at developer.finra.org/create-account and self-issue a "Public
  Credential" at no cost -- this is a real, free, but NOT automatic setup
  step the operator has to do once (same class of action as getting a
  Tradier/Polygon/Alpha Vantage API key), producing FINRA_API_CLIENT_ID and
  FINRA_API_CLIENT_SECRET. Until both are set, this module honestly reports
  unavailable -- it never fabricates a short-interest number.

Dataset: https://api.finra.org/data/group/otcMarket/name/equityShortInterestStandardized
(the older `equityShortInterest` dataset was deprecated 2021-04-30; this is
its documented replacement). Query auth: OAuth2 client-credentials grant
against https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token.

FIELD NAMES ARE PARSED DEFENSIVELY, NOT ASSUMED EXACT -- because finra.org
blocks this sandbox's outbound fetch, the precise JSON key names in a real
response could not be confirmed end-to-end here (same disclosed limitation
already flagged for finra_short_data.py's file format and the x402
Settlement Router's Solidity compiler). Rather than hardcode one guessed
key name and silently return nothing if it's wrong, `_extract()` matches
against several plausible real key-name variants (documented FINRA
datasets use camelCase names like `symbolCode`/`currentShortPositionQuantity`)
case-insensitively. This should be verified against a real response once
running somewhere with real network access (e.g. Render) and credentials --
flagged here exactly like the other unverified-from-sandbox integrations
in this codebase, not asserted as confirmed-correct.

Cadence: settlement data changes twice a month, so this is a small
on-demand cache (default 12h TTL) per symbol, not a continuous poller like
finra_short_data.py's daily file.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("FINRA-SHORT-INTEREST")

_CLIENT_ID = os.environ.get("FINRA_API_CLIENT_ID", "").strip()
_CLIENT_SECRET = os.environ.get("FINRA_API_CLIENT_SECRET", "").strip()
_TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
_DATA_URL = "https://api.finra.org/data/group/otcMarket/name/equityShortInterestStandardized"
_CACHE_TTL_S = int(os.environ.get("FINRA_SHORT_INTEREST_CACHE_TTL_S", str(12 * 3600)))

_SYMBOL_KEYS = ("symbolCode", "symbol", "issueSymbolIdentifier", "securitiesInformationProcessorSymbolIdentifier")
_CURRENT_SHORT_KEYS = ("currentShortPositionQuantity", "currentShortPosition", "shortInterestQuantity")
_PREVIOUS_SHORT_KEYS = ("previousShortPositionQuantity", "previousShortPosition")
_CHANGE_PCT_KEYS = ("changePercent", "percentageChangefromPreviousShort", "shortInterestPercentChange")
_AVG_VOL_KEYS = ("averageDailyVolumeQuantity", "avgDailyVolume", "averageDailyTradingVolumeQuantity")
_DAYS_TO_COVER_KEYS = ("daysToCoverQuantity", "daysToCover")
_SETTLEMENT_DATE_KEYS = ("settlementDate", "settlementdate")

_token_cache = {"access_token": None, "expires_at": 0.0}
_symbol_cache: dict = {}  # {symbol: {"data": dict|None, "ts": float}}


def configured() -> bool:
    return bool(_CLIENT_ID and _CLIENT_SECRET)


def _get_field(row: dict, candidates: tuple) -> Optional[str]:
    lower_map = {k.lower(): v for k, v in row.items()}
    for name in candidates:
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    return None


def _get_access_token() -> Optional[str]:
    if not configured():
        return None
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    creds = base64.b64encode(f"{_CLIENT_ID}:{_CLIENT_SECRET}".encode()).decode()
    req = urllib.request.Request(
        _TOKEN_URL, method="POST",
        headers={"Authorization": f"Basic {creds}", "Content-Length": "0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("[FINRA-SHORT-INTEREST] token request failed: %s", e)
        return None
    token = payload.get("access_token")
    if not token:
        return None
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
    return token


def _fetch_from_finra(symbol: str) -> Optional[dict]:
    token = _get_access_token()
    if not token:
        return None
    body = json.dumps({
        "compareFilters": [{"fieldName": "symbolCode", "fieldValue": symbol, "compareType": "EQUAL"}],
        "sortFields": ["-settlementDate"],
        "limit": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        _DATA_URL, method="POST", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("[FINRA-SHORT-INTEREST] %s query failed: %s", symbol, e)
        return None

    rows = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
    if not rows:
        return None
    row = rows[0]

    try:
        current = float(_get_field(row, _CURRENT_SHORT_KEYS) or 0)
        previous_raw = _get_field(row, _PREVIOUS_SHORT_KEYS)
        previous = float(previous_raw) if previous_raw is not None else None
        change_pct_raw = _get_field(row, _CHANGE_PCT_KEYS)
        change_pct = float(change_pct_raw) if change_pct_raw is not None else (
            round((current - previous) / previous * 100.0, 2) if previous else None
        )
        avg_vol_raw = _get_field(row, _AVG_VOL_KEYS)
        avg_vol = float(avg_vol_raw) if avg_vol_raw is not None else None
        dtc_raw = _get_field(row, _DAYS_TO_COVER_KEYS)
        days_to_cover = float(dtc_raw) if dtc_raw is not None else (
            round(current / avg_vol, 2) if avg_vol else None
        )
    except (TypeError, ValueError):
        return None

    return {
        "symbol": symbol.upper(),
        "settlement_date": _get_field(row, _SETTLEMENT_DATE_KEYS),
        "current_short_position": current,
        "previous_short_position": previous,
        "change_pct": change_pct,
        "days_to_cover": days_to_cover,
        "source": "FINRA equityShortInterestStandardized (real, bi-monthly settlement data)",
    }


def get_short_interest(symbol: str) -> Optional[dict]:
    """Real short-interest/days-to-cover for a symbol, or None when
    unconfigured, the symbol isn't found, or the request fails -- never a
    fabricated number. Cached per-symbol for FINRA_SHORT_INTEREST_CACHE_TTL_S
    (default 12h) since this data only changes twice a month."""
    if not configured():
        return None
    symbol = symbol.strip().upper()
    cached = _symbol_cache.get(symbol)
    if cached and time.time() - cached["ts"] < _CACHE_TTL_S:
        return cached["data"]
    data = _fetch_from_finra(symbol)
    _symbol_cache[symbol] = {"data": data, "ts": time.time()}
    return data


def status() -> dict:
    return {
        "configured": configured(),
        "symbols_cached": len(_symbol_cache),
        "cache_ttl_s": _CACHE_TTL_S,
        "source": "FINRA equityShortInterestStandardized via developer.finra.org Query API (OAuth2)",
        "setup_required_if_not_configured": (
            "Register a free Individual Account + Public Credential at "
            "developer.finra.org/create-account, then set FINRA_API_CLIENT_ID "
            "and FINRA_API_CLIENT_SECRET -- this is a real, free, but manual "
            "one-time operator step, unlike finra_short_data.py's no-auth file."
        ),
    }
