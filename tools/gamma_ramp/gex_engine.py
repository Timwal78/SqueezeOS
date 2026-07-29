#!/usr/bin/env python3
"""
True Spot GEX Engine — OPRA / Tradier chain Net Dollar Gamma Exposure.

GEX_contract = Γ × OI × 100 × S² × 0.01 × D
  D = +1 CALL (MM short-call assumption on retail long flow)
  D = -1 PUT

total_gex < 0  →  MM SHORT gamma  →  accelerator / squeeze regime  →  PLAY
total_gex > 0  →  MM LONG gamma   →  stabilizer / fade regime      →  KILL longs

Also exposes call wall, put wall, zero-gamma line via existing gamma_flow_engine
when available; pure numpy/pandas-free path always works.
"""
from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# allow squeezeos root imports
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@dataclass
class SpotGEXResult:
    symbol: str
    spot: float
    total_gex: float
    is_short_gamma: bool
    call_gex: float
    put_gex: float
    call_wall: Optional[float]
    put_wall: Optional[float]
    zero_gamma_line: Optional[float]
    max_oi_strike: Optional[float]
    n_contracts: int
    n_strikes: int
    regime: str                 # SHORT_GAMMA | LONG_GAMMA | UNKNOWN
    playable: bool              # True only if short gamma
    source: str
    ts: float
    by_strike: Dict[float, float] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # compact strike map for logs
        if len(d.get("by_strike") or {}) > 40:
            items = sorted(d["by_strike"].items(), key=lambda kv: abs(kv[1]), reverse=True)[:40]
            d["by_strike"] = {str(k): v for k, v in items}
        else:
            d["by_strike"] = {str(k): v for k, v in (d.get("by_strike") or {}).items()}
        return d


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def _i(x: Any, default: int = 0) -> int:
    try:
        return int(float(x)) if x is not None else default
    except (TypeError, ValueError):
        return default


def estimate_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return math.exp(-0.5 * d1 ** 2) / (S * sigma * math.sqrt(2 * math.pi * T))
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def contract_dollar_gex(
    gamma: float,
    oi: int,
    spot: float,
    side: str,
    multiplier: float = 100.0,
) -> float:
    """
    Dollar GEX for one contract row.
    Standard desk form: Γ * OI * mult * S^2 * 0.01 * sign
    """
    if gamma <= 0 or oi <= 0 or spot <= 0:
        return 0.0
    sign = 1.0 if side.upper() == "CALL" else -1.0
    return gamma * oi * multiplier * (spot ** 2) * 0.01 * sign


def calculate_spot_gex_from_rows(
    rows: List[Dict[str, Any]],
    spot: float,
    symbol: str = "",
    band: float = 0.15,
    source: str = "rows",
) -> SpotGEXResult:
    """
    rows item keys (flexible):
      strike, gamma, oi|open_interest, side|option_type|putCall (CALL/PUT),
      optional iv|volatility (decimal or percent), dte
    """
    if spot <= 0 or not rows:
        return SpotGEXResult(
            symbol=symbol, spot=spot, total_gex=0.0, is_short_gamma=False,
            call_gex=0.0, put_gex=0.0, call_wall=None, put_wall=None,
            zero_gamma_line=None, max_oi_strike=None, n_contracts=0, n_strikes=0,
            regime="UNKNOWN", playable=False, source=source, ts=time.time(),
            note="empty_chain_or_spot",
        )

    lo, hi = spot * (1.0 - band), spot * (1.0 + band)
    by_strike: Dict[float, float] = {}
    oi_by_strike: Dict[float, int] = {}
    call_gex = put_gex = 0.0
    n = 0

    for r in rows:
        strike = _f(r.get("strike") or r.get("strikePrice"))
        if strike <= 0 or strike < lo or strike > hi:
            continue
        side = (r.get("side") or r.get("option_type") or r.get("putCall") or "").upper()
        if side in ("C",):
            side = "CALL"
        if side in ("P",):
            side = "PUT"
        if side not in ("CALL", "PUT"):
            continue
        oi = _i(r.get("oi") or r.get("open_interest") or r.get("openInterest"))
        gamma = _f(r.get("gamma"))
        if gamma <= 0:
            iv = _f(r.get("iv") or r.get("volatility") or r.get("mid_iv"))
            # percent → decimal if needed
            if iv > 1.5:
                iv = iv / 100.0
            dte = _f(r.get("dte"), 7.0)
            T = max(0.0001, dte / 365.0)
            if iv > 0:
                gamma = estimate_gamma(spot, strike, T, 0.04, iv)
        if gamma <= 0 or oi <= 0:
            continue
        g = contract_dollar_gex(gamma, oi, spot, side)
        by_strike[strike] = by_strike.get(strike, 0.0) + g
        oi_by_strike[strike] = oi_by_strike.get(strike, 0) + oi
        if side == "CALL":
            call_gex += g
        else:
            put_gex += g
        n += 1

    total = call_gex + put_gex
    is_short = total < 0
    # walls
    pos = {k: v for k, v in by_strike.items() if v > 0}
    neg = {k: v for k, v in by_strike.items() if v < 0}
    call_wall = max(pos.items(), key=lambda kv: kv[1])[0] if pos else None
    put_wall = min(neg.items(), key=lambda kv: kv[1])[0] if neg else None
    max_oi = max(oi_by_strike.items(), key=lambda kv: kv[1])[0] if oi_by_strike else None

    # zero gamma line — first sign flip nearest spot
    zgl = None
    strikes_sorted = sorted(by_strike.keys())
    for a, b in zip(strikes_sorted, strikes_sorted[1:]):
        ga, gb = by_strike[a], by_strike[b]
        if ga == 0 or gb == 0 or (ga > 0) == (gb > 0):
            continue
        # linear interpolate
        t = abs(ga) / (abs(ga) + abs(gb))
        z = a + (b - a) * t
        if zgl is None or abs(z - spot) < abs(zgl - spot):
            zgl = z

    regime = "SHORT_GAMMA" if is_short else ("LONG_GAMMA" if total > 0 else "UNKNOWN")
    return SpotGEXResult(
        symbol=symbol,
        spot=spot,
        total_gex=float(total),
        is_short_gamma=bool(is_short),
        call_gex=float(call_gex),
        put_gex=float(put_gex),
        call_wall=float(call_wall) if call_wall is not None else None,
        put_wall=float(put_wall) if put_wall is not None else None,
        zero_gamma_line=float(zgl) if zgl is not None else None,
        max_oi_strike=float(max_oi) if max_oi is not None else None,
        n_contracts=n,
        n_strikes=len(by_strike),
        regime=regime,
        playable=bool(is_short and n > 0),
        source=source,
        ts=time.time(),
        by_strike=by_strike,
        note="play" if is_short else "KILL_positive_gex_stabilizer",
    )


def flatten_schwab_chain(chain: Dict[str, Any], spot: float) -> List[Dict[str, Any]]:
    """Flatten Tradier/Schwab-shape chain to row list for GEX."""
    rows: List[Dict[str, Any]] = []
    for side_key, side_name in (("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")):
        m = chain.get(side_key) or {}
        for exp_key, strikes in m.items():
            dte = 7
            if isinstance(exp_key, str) and ":" in exp_key:
                try:
                    dte = int(exp_key.split(":")[1])
                except Exception:
                    dte = 7
            if not isinstance(strikes, dict):
                continue
            for strike_str, contracts in strikes.items():
                if not isinstance(contracts, list):
                    contracts = [contracts]
                for c in contracts:
                    if not isinstance(c, dict):
                        continue
                    rows.append({
                        "strike": _f(c.get("strikePrice") or strike_str),
                        "gamma": _f(c.get("gamma")),
                        "oi": _i(c.get("openInterest")),
                        "side": side_name,
                        "iv": _f(c.get("volatility")),
                        "dte": dte,
                        "delta": _f(c.get("delta")),
                        "bid": _f(c.get("bid")),
                        "ask": _f(c.get("ask")),
                        "volume": _i(c.get("totalVolume")),
                        "symbol": c.get("symbol"),
                        "expiration": (exp_key.split(":")[0] if isinstance(exp_key, str) else None),
                    })
    return rows


def calculate_spot_gex_from_schwab_chain(
    chain: Dict[str, Any],
    spot: Optional[float] = None,
    symbol: str = "",
    band: float = 0.15,
) -> SpotGEXResult:
    spot = float(spot or chain.get("underlyingPrice") or 0.0)
    sym = symbol or chain.get("symbol") or ""
    rows = flatten_schwab_chain(chain, spot)
    return calculate_spot_gex_from_rows(rows, spot, symbol=sym, band=band, source=chain.get("_provider") or "schwab_chain")


def fetch_spot_gex(symbol: str, max_expirations: int = 6, band: float = 0.15) -> SpotGEXResult:
    """
    Live path: Tradier chain → spot GEX.
    Returns UNKNOWN/not playable if no key / no chain (never invents).
    """
    try:
        import tradier_api as t
    except ImportError:
        return SpotGEXResult(
            symbol=symbol, spot=0.0, total_gex=0.0, is_short_gamma=False,
            call_gex=0.0, put_gex=0.0, call_wall=None, put_wall=None,
            zero_gamma_line=None, max_oi_strike=None, n_contracts=0, n_strikes=0,
            regime="UNKNOWN", playable=False, source="none", ts=time.time(),
            note="tradier_api_import_fail",
        )
    if not t.is_available():
        return SpotGEXResult(
            symbol=symbol, spot=0.0, total_gex=0.0, is_short_gamma=False,
            call_gex=0.0, put_gex=0.0, call_wall=None, put_wall=None,
            zero_gamma_line=None, max_oi_strike=None, n_contracts=0, n_strikes=0,
            regime="UNKNOWN", playable=False, source="tradier", ts=time.time(),
            note="TRADIER_API_KEY missing",
        )
    chain = t.get_option_chain_schwab_format(symbol, max_expirations=max_expirations)
    if not chain:
        return SpotGEXResult(
            symbol=symbol, spot=0.0, total_gex=0.0, is_short_gamma=False,
            call_gex=0.0, put_gex=0.0, call_wall=None, put_wall=None,
            zero_gamma_line=None, max_oi_strike=None, n_contracts=0, n_strikes=0,
            regime="UNKNOWN", playable=False, source="tradier", ts=time.time(),
            note="chain_unavailable",
        )
    # Prefer full gamma_flow_engine profile when importable (walls/ZGL parity)
    try:
        from gamma_flow_engine import calculate_gex_profile
        spot = float(chain.get("underlyingPrice") or 0.0)
        if spot <= 0:
            q = t.get_quote(symbol) or {}
            spot = float(q.get("last") or q.get("close") or 0.0)
        prof = calculate_gex_profile(chain, spot, ticker=symbol)
        if prof is not None:
            is_short = prof.profile_shape == "short_gamma" or prof.total_gex < 0
            return SpotGEXResult(
                symbol=symbol,
                spot=float(prof.spot_price),
                total_gex=float(prof.total_gex),
                is_short_gamma=bool(is_short),
                call_gex=float(sum(v for v in prof.by_strike.values() if v > 0)),
                put_gex=float(sum(v for v in prof.by_strike.values() if v < 0)),
                call_wall=float(prof.call_wall) if prof.call_wall else None,
                put_wall=float(prof.put_wall) if prof.put_wall else None,
                zero_gamma_line=float(prof.zero_gamma_line) if prof.zero_gamma_line else None,
                max_oi_strike=float(prof.max_oi_strike) if prof.max_oi_strike else None,
                n_contracts=len(prof.by_strike),
                n_strikes=len(prof.by_strike),
                regime="SHORT_GAMMA" if is_short else "LONG_GAMMA",
                playable=bool(is_short),
                source="gamma_flow_engine+tradier",
                ts=time.time(),
                by_strike=dict(prof.by_strike),
                note="play" if is_short else "KILL_positive_gex_stabilizer",
            )
    except Exception:
        pass
    return calculate_spot_gex_from_schwab_chain(chain, symbol=symbol, band=band)


if __name__ == "__main__":
    import json
    # unit self-check with synthetic chain
    spot = 100.0
    rows = []
    for k in range(90, 111):
        # Short-gamma demo: large put OI (put GEX negative) dominates near spot
        rows.append({"strike": float(k), "gamma": 0.05, "oi": 400 if k >= 100 else 200, "side": "CALL", "dte": 5, "iv": 0.4})
        rows.append({"strike": float(k), "gamma": 0.05, "oi": 5000 if k <= 102 else 800, "side": "PUT", "dte": 5, "iv": 0.4})
    r = calculate_spot_gex_from_rows(rows, spot, symbol="TEST")
    print(json.dumps(r.to_dict(), indent=2)[:1200])
    print("playable", r.playable, "regime", r.regime)
