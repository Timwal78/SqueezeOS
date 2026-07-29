#!/usr/bin/env python3
"""
Intraday VPIN — Volume-Synchronized Probability of Informed Trading
with Bulk Volume Classification (BVC) on 1m / 5m bars.

Target gates (desk):
  VPIN >= 0.28  → toxicity confirmed
  VPIN >= 0.40  → full size

signed_flow > 0 → buy toxicity (CALL bias)
signed_flow < 0 → sell toxicity (PUT bias)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    from scipy.stats import norm as _scipy_norm
    def _cdf(x: float) -> float:
        return float(_scipy_norm.cdf(x))
except Exception:
    # erf fallback
    def _cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


VPIN_ENTRY = 0.28
VPIN_FULL = 0.40


@dataclass
class VPINResult:
    vpin: float
    signed_flow: float          # (buy-sell)/(buy+sell) in window, -1..+1
    buy_vol: float
    sell_vol: float
    bucket_volume: float
    window_n: int
    n_bars: int
    toxic: bool                 # vpin >= ENTRY
    full_size: bool             # vpin >= FULL
    side_bias: str              # CALL | PUT | NONE
    ts: float
    source: str = "bvc"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _as_arrays(
    bars: Sequence[Dict[str, Any]] | Dict[str, Sequence[float]],
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Accept list[{close,volume}] or dict{close:[], volume:[]}.
    """
    if isinstance(bars, dict):
        c_raw = bars["close"] if "close" in bars else bars.get("c")
        v_raw = bars["volume"] if "volume" in bars else bars.get("v")
        c = np.asarray(c_raw if c_raw is not None else [], dtype=float)
        v = np.asarray(v_raw if v_raw is not None else [], dtype=float)
        return c, v
    closes = []
    vols = []
    for b in bars:
        try:
            closes.append(float(b.get("close") if isinstance(b, dict) else b[3]))
            vols.append(float(b.get("volume") if isinstance(b, dict) else b[4]))
        except Exception:
            continue
    return np.asarray(closes, dtype=float), np.asarray(vols, dtype=float)


def bulk_volume_classify(
    closes: np.ndarray,
    volumes: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    BVC: P(buy) = Φ(ΔP / σ) per Easley et al. style bulk classification.
    """
    n = len(closes)
    buy = np.zeros(n)
    sell = np.zeros(n)
    if n < 3:
        return buy, sell
    rets = np.diff(closes, prepend=closes[0])
    # use robust sigma on nonzero moves
    sig = float(np.std(rets[1:])) if n > 2 else 0.0
    if sig <= 1e-12:
        sig = float(np.mean(np.abs(rets[1:]))) if n > 2 else 1e-5
    if sig <= 1e-12:
        sig = 1e-5
    for i in range(n):
        v = float(volumes[i]) if i < len(volumes) else 0.0
        if v <= 0:
            continue
        if i == 0:
            buy[i] = v * 0.5
            sell[i] = v * 0.5
            continue
        z = rets[i] / sig
        # clip extreme z for numerical stability
        z = max(-8.0, min(8.0, z))
        p_buy = _cdf(z)
        p_buy = min(1.0, max(0.0, p_buy))
        buy[i] = v * p_buy
        sell[i] = v * (1.0 - p_buy)
    return buy, sell


def calculate_intraday_vpin(
    bars: Sequence[Dict[str, Any]] | Dict[str, Sequence[float]],
    bucket_volume: Optional[float] = None,
    window_n: int = 50,
) -> VPINResult:
    """
    VPIN ≈ sum(|buy-sell|) / sum(buy+sell) over last window_n bars
    (volume-synchronized when bucket_volume set; else bar-window proxy).

    If bucket_volume is None, uses total volume / window as bucket scale.
    """
    closes, volumes = _as_arrays(bars)
    n = len(closes)
    if n < max(5, window_n // 5):
        return VPINResult(
            vpin=0.0, signed_flow=0.0, buy_vol=0.0, sell_vol=0.0,
            bucket_volume=float(bucket_volume or 0), window_n=window_n,
            n_bars=n, toxic=False, full_size=False, side_bias="NONE",
            ts=time.time(), note="insufficient_bars",
        )

    buy, sell = bulk_volume_classify(closes, volumes)
    w = min(window_n, n)
    b = float(np.sum(buy[-w:]))
    s = float(np.sum(sell[-w:]))
    tot = b + s
    if tot <= 0:
        return VPINResult(
            vpin=0.0, signed_flow=0.0, buy_vol=0.0, sell_vol=0.0,
            bucket_volume=float(bucket_volume or 0), window_n=w,
            n_bars=n, toxic=False, full_size=False, side_bias="NONE",
            ts=time.time(), note="zero_volume",
        )

    imbalance = abs(b - s)
    if bucket_volume and bucket_volume > 0:
        # classic VPIN normalization by n buckets of equal volume
        vpin = imbalance / (bucket_volume * max(1, w))
        # also report volume-fraction toxicity (more stable across names)
        vpin_frac = imbalance / tot
        vpin = max(vpin, vpin_frac)  # use the more conservative elevated read via frac floor
        # Prefer fraction form as primary desk gate (0-1 bounded)
        vpin = vpin_frac
    else:
        vpin = imbalance / tot

    signed = (b - s) / tot
    vpin = float(min(1.0, max(0.0, vpin)))
    signed = float(max(-1.0, min(1.0, signed)))

    if signed > 0.05:
        bias = "CALL"
    elif signed < -0.05:
        bias = "PUT"
    else:
        bias = "NONE"

    return VPINResult(
        vpin=vpin,
        signed_flow=signed,
        buy_vol=b,
        sell_vol=s,
        bucket_volume=float(bucket_volume or (tot / max(w, 1))),
        window_n=w,
        n_bars=n,
        toxic=vpin >= VPIN_ENTRY,
        full_size=vpin >= VPIN_FULL,
        side_bias=bias,
        ts=time.time(),
        note="ok",
    )


def vpin_from_tradier_timesales(
    symbol: str,
    interval: str = "5min",
    days_back: int = 5,
    window_n: int = 50,
) -> VPINResult:
    """Live fetch Tradier timesales → VPIN. Never invents if API down."""
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import tradier_api as t
    except ImportError:
        return VPINResult(
            vpin=0.0, signed_flow=0.0, buy_vol=0.0, sell_vol=0.0,
            bucket_volume=0.0, window_n=window_n, n_bars=0,
            toxic=False, full_size=False, side_bias="NONE",
            ts=time.time(), source="tradier", note="import_fail",
        )
    if not t.is_available():
        return VPINResult(
            vpin=0.0, signed_flow=0.0, buy_vol=0.0, sell_vol=0.0,
            bucket_volume=0.0, window_n=window_n, n_bars=0,
            toxic=False, full_size=False, side_bias="NONE",
            ts=time.time(), source="tradier", note="TRADIER_API_KEY missing",
        )
    bars = t.get_timesales(symbol, interval=interval, days_back=days_back) or []
    # normalize keys
    norm = []
    for b in bars:
        if not isinstance(b, dict):
            continue
        norm.append({
            "close": float(b.get("close") or b.get("price") or 0),
            "volume": float(b.get("volume") or 0),
        })
    res = calculate_intraday_vpin(norm, window_n=window_n)
    res.source = f"tradier_timesales:{interval}"
    return res


if __name__ == "__main__":
    import json
    rng = np.random.default_rng(0)
    n = 100
    px = 100 + np.cumsum(rng.normal(0.05, 0.2, n))  # grind up
    vol = rng.integers(5000, 15000, n).astype(float)
    vol[-10:] *= 3
    bars = {"close": px, "volume": vol}
    r = calculate_intraday_vpin(bars, window_n=30)
    print(json.dumps(r.to_dict(), indent=2))
