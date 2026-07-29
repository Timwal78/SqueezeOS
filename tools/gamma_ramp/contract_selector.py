#!/usr/bin/env python3
"""
Dynamic OPRA Delta Contract Selector — 0.30–0.40Δ sweet spot.

Picks the liquid OCC contract closest to target Δ=0.35 with:
  - absolute delta in [0.30, 0.40]
  - tight NBBO spread
  - open interest / volume floors
  - DTE window by style (index scalp vs HV equity)

Never invents a contract if chain/greeks missing.
"""
from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DELTA_MIN = 0.30
DELTA_MAX = 0.40
DELTA_TARGET = 0.35
MAX_SPREAD_PCT = 0.12          # (ask-bid)/mid <= 12%
MIN_OI = 50
MIN_MID = 0.05


@dataclass
class ContractPick:
    ok: bool
    symbol: str                 # OCC
    underlying: str
    side: str                   # CALL | PUT
    strike: float
    expiration: str
    dte: int
    delta: float
    gamma: float
    theta: float
    vega: float
    bid: float
    ask: float
    mid: float
    spread_pct: float
    open_interest: int
    volume: int
    score: float
    nbbo_buy: float             # bid + 0.01 pin (or mid if wide)
    nbbo_sell: float            # ask - 0.01 pin
    reason: str
    ts: float = field(default_factory=time.time)
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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


def _empty(underlying: str, side: str, reason: str, source: str = "") -> ContractPick:
    return ContractPick(
        ok=False, symbol="", underlying=underlying, side=side,
        strike=0.0, expiration="", dte=-1, delta=0.0, gamma=0.0,
        theta=0.0, vega=0.0, bid=0.0, ask=0.0, mid=0.0, spread_pct=1.0,
        open_interest=0, volume=0, score=-1e9, nbbo_buy=0.0, nbbo_sell=0.0,
        reason=reason, source=source,
    )


def _dte_window(style: str) -> Tuple[int, int]:
    """
    style:
      index_scalp → 0-3 DTE
      hv_swing    → 7-21 DTE
      auto        → 0-21 (prefer liquid front)
    """
    s = (style or "auto").lower()
    if s in ("index", "index_scalp", "0dte", "scalp"):
        return 0, 3
    if s in ("hv", "hv_swing", "swing", "equity"):
        return 7, 21
    return 0, 21


def select_optimal_option_contract(
    chain_rows: Sequence[Dict[str, Any]],
    underlying: str,
    target_side: str = "CALL",
    target_delta: float = DELTA_TARGET,
    style: str = "auto",
    spot: Optional[float] = None,
    max_spread_pct: float = MAX_SPREAD_PCT,
    min_oi: int = MIN_OI,
) -> ContractPick:
    """
    chain_rows: iterable of contract dicts with keys:
      symbol, side/option_type/putCall, strike, expiration, dte,
      delta, gamma, theta, vega, bid, ask, oi/open_interest, volume
    """
    side = (target_side or "CALL").upper()
    if side not in ("CALL", "PUT"):
        return _empty(underlying, side, "bad_side")

    dte_lo, dte_hi = _dte_window(style)
    td = abs(float(target_delta))
    eligible: List[ContractPick] = []

    for r in chain_rows:
        rside = (r.get("side") or r.get("option_type") or r.get("putCall") or "").upper()
        if rside in ("C",):
            rside = "CALL"
        if rside in ("P",):
            rside = "PUT"
        if rside != side:
            continue

        occ = (r.get("symbol") or r.get("occ") or "").strip()
        if not occ:
            continue

        delta = _f(r.get("delta"))
        # puts often negative delta
        ad = abs(delta)
        if ad < DELTA_MIN or ad > DELTA_MAX:
            continue

        dte = _i(r.get("dte"), -1)
        exp = str(r.get("expiration") or r.get("expiration_date") or "")
        if dte < 0 and exp:
            try:
                from datetime import datetime, timezone
                d = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                dte = (d - datetime.now(timezone.utc).date()).days
            except Exception:
                dte = -1
        if dte < dte_lo or dte > dte_hi:
            continue

        bid = _f(r.get("bid"))
        ask = _f(r.get("ask"))
        if ask <= 0 and bid <= 0:
            continue
        if ask <= 0:
            ask = bid
        if bid <= 0:
            bid = max(0.01, ask * 0.9)
        mid = (bid + ask) / 2.0
        if mid < MIN_MID:
            continue
        spread_pct = (ask - bid) / mid if mid > 0 else 1.0
        if spread_pct > max_spread_pct:
            continue

        oi = _i(r.get("oi") or r.get("open_interest") or r.get("openInterest"))
        vol = _i(r.get("volume") or r.get("totalVolume"))
        if oi < min_oi and vol < max(10, min_oi // 2):
            continue

        # optional moneyness sanity if spot known
        strike = _f(r.get("strike") or r.get("strikePrice"))
        if spot and strike > 0:
            # calls should be near/OTM; puts near/OTM
            if side == "CALL" and strike < spot * 0.85:
                continue
            if side == "PUT" and strike > spot * 1.15:
                continue

        delta_diff = abs(ad - td)
        # score: closer delta, tighter spread, more OI/volume, prefer moderate DTE liquidity
        score = 0.0
        score += max(0.0, 40.0 - delta_diff * 400.0)          # delta proximity
        score += max(0.0, 25.0 - spread_pct * 200.0)          # tight NBBO
        score += min(20.0, math.log10(max(oi, 1)) * 6.0)      # OI
        score += min(10.0, math.log10(max(vol, 1)) * 4.0)     # volume
        if 0 <= dte <= 3:
            score += 5.0  # scalp gamma
        elif 7 <= dte <= 14:
            score += 4.0

        nbbo_buy = round(min(ask, bid + 0.01), 2)
        if nbbo_buy < bid:
            nbbo_buy = bid
        nbbo_sell = round(max(bid, ask - 0.01), 2)
        if nbbo_sell > ask:
            nbbo_sell = ask

        eligible.append(ContractPick(
            ok=True,
            symbol=occ,
            underlying=underlying,
            side=side,
            strike=strike,
            expiration=exp,
            dte=int(dte),
            delta=delta if side == "CALL" else -ad if delta >= 0 else delta,
            gamma=_f(r.get("gamma")),
            theta=_f(r.get("theta")),
            vega=_f(r.get("vega")),
            bid=bid,
            ask=ask,
            mid=round(mid, 4),
            spread_pct=round(spread_pct, 4),
            open_interest=oi,
            volume=vol,
            score=float(score),
            nbbo_buy=float(nbbo_buy),
            nbbo_sell=float(nbbo_sell),
            reason="ok",
            source=str(r.get("source") or ""),
        ))

    if not eligible:
        return _empty(underlying, side, "no_contract_in_0.30_0.40_window")

    eligible.sort(key=lambda c: (-c.score, c.spread_pct, -c.open_interest))
    best = eligible[0]
    best.reason = f"best_of_{len(eligible)}"
    return best


def rows_from_schwab_chain(chain: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for side_key, side_name in (("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")):
        m = chain.get(side_key) or {}
        for exp_key, strikes in m.items():
            dte = -1
            exp = ""
            if isinstance(exp_key, str):
                parts = exp_key.split(":")
                exp = parts[0]
                if len(parts) > 1:
                    try:
                        dte = int(parts[1])
                    except Exception:
                        dte = -1
            if not isinstance(strikes, dict):
                continue
            for _ks, contracts in strikes.items():
                if not isinstance(contracts, list):
                    contracts = [contracts]
                for c in contracts:
                    if not isinstance(c, dict):
                        continue
                    rows.append({
                        "symbol": c.get("symbol"),
                        "side": side_name,
                        "strike": c.get("strikePrice"),
                        "expiration": exp or c.get("expirationDate"),
                        "dte": dte,
                        "delta": c.get("delta"),
                        "gamma": c.get("gamma"),
                        "theta": c.get("theta"),
                        "vega": c.get("vega"),
                        "bid": c.get("bid"),
                        "ask": c.get("ask"),
                        "oi": c.get("openInterest"),
                        "volume": c.get("totalVolume"),
                        "source": chain.get("_provider") or "chain",
                    })
    return rows


def select_from_tradier(
    underlying: str,
    target_side: str = "CALL",
    style: str = "auto",
    max_expirations: int = 8,
) -> ContractPick:
    try:
        import tradier_api as t
    except ImportError:
        return _empty(underlying, target_side, "tradier_import_fail")
    if not t.is_available():
        return _empty(underlying, target_side, "TRADIER_API_KEY missing", source="tradier")
    chain = t.get_option_chain_schwab_format(underlying, max_expirations=max_expirations)
    if not chain:
        return _empty(underlying, target_side, "chain_unavailable", source="tradier")
    spot = _f(chain.get("underlyingPrice"))
    if spot <= 0:
        q = t.get_quote(underlying) or {}
        spot = _f(q.get("last") or q.get("close"))
    # style auto: index ETFs prefer 0-3 DTE
    if style == "auto" and underlying.upper() in {"SPY", "QQQ", "IWM", "DIA", "SPX", "NDX"}:
        style = "index_scalp"
    elif style == "auto":
        style = "hv_swing"
    pick = select_optimal_option_contract(
        rows_from_schwab_chain(chain),
        underlying=underlying,
        target_side=target_side,
        style=style,
        spot=spot or None,
    )
    pick.source = chain.get("_provider") or "tradier"
    return pick


if __name__ == "__main__":
    import json
    # synthetic chain around spot 100
    rows = []
    # explicit sweet-spot contracts near 0.35Δ
    for i, (k, d) in enumerate([(98, 0.42), (99, 0.38), (100, 0.35), (101, 0.32), (102, 0.28), (103, 0.25)]):
        rows.append({
            "symbol": f"TEST260821C00{k}000",
            "side": "CALL",
            "strike": float(k),
            "expiration": "2026-08-21",
            "dte": 10,
            "delta": d,
            "gamma": 0.04,
            "theta": -0.05,
            "vega": 0.1,
            "bid": round(max(0.20, d * 2.0) - 0.02, 2),
            "ask": round(max(0.20, d * 2.0) + 0.02, 2),
            "oi": 500 + i * 10,
            "volume": 100 + i,
        })
        rows.append({
            "symbol": f"TEST260821P00{k}000",
            "side": "PUT",
            "strike": float(k),
            "expiration": "2026-08-21",
            "dte": 10,
            "delta": -d,
            "gamma": 0.04,
            "theta": -0.05,
            "vega": 0.1,
            "bid": 0.5,
            "ask": 0.6,
            "oi": 400,
            "volume": 80,
        })
    p = select_optimal_option_contract(rows, "TEST", "CALL", style="hv_swing", spot=100.0)
    print(json.dumps(p.to_dict(), indent=2))
