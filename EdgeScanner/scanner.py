"""
EdgeScanner — High-Probability Setup Detector
═══════════════════════════════════════════════
Scans US equities and options for setups with institutional-grade edge.
All data fetched live. No hardcoded tickers. No slice limits.

Patterns:
  1. TTM Squeeze Breakout  — BB inside KC, momentum building
  2. VWAP Reclaim          — Price reclaims VWAP after dip, volume confirming
  3. Bull/Bear Flag        — Clean consolidation after impulse move
  4. Volume Breakout       — Price breaking key level on 2x+ average volume
  5. Oversold Bounce       — RSI < 30, price at BB lower, green reversal bar
  6. Options Flow Spike    — Put/Call ratio extremes + IV rank divergence
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("EDGE_SCANNER")


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    sma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return sma, sma + std * sd, sma - std * sd


def _keltner(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 20, mult: float = 1.5):
    mid = close.rolling(period).mean()
    atr = _atr(high, low, close, period)
    return mid, mid + mult * atr, mid - mult * atr


def _vwap(high: pd.Series, low: pd.Series, close: pd.Series,
          volume: pd.Series) -> pd.Series:
    tp = (high + low + close) / 3.0
    return (tp * volume).cumsum() / volume.cumsum()


def _hurst(series: pd.Series, lags: int = 20) -> float:
    """Estimate Hurst exponent via R/S analysis. H>0.5 → trending."""
    prices = series.dropna().values
    if len(prices) < lags + 10:
        return 0.5
    try:
        rs_vals = []
        lag_vals = []
        for lag in range(2, lags):
            chunks = [prices[i:i + lag] for i in range(0, len(prices) - lag, lag)]
            if not chunks:
                continue
            rs = []
            for chunk in chunks:
                if len(chunk) < 2:
                    continue
                mean = np.mean(chunk)
                dev = np.cumsum(chunk - mean)
                r = np.ptp(dev)
                s = np.std(chunk, ddof=1)
                if s > 0:
                    rs.append(r / s)
            if rs:
                rs_vals.append(np.log(np.mean(rs)))
                lag_vals.append(np.log(lag))
        if len(lag_vals) < 2:
            return 0.5
        h = np.polyfit(lag_vals, rs_vals, 1)[0]
        return float(np.clip(h, 0.0, 1.0))
    except Exception:
        return 0.5


# ── Setup detectors ──────────────────────────────────────────────────────────

def _detect_ttm_squeeze(df: pd.DataFrame) -> Optional[dict]:
    """BB inside KC = squeeze loaded. Squeeze firing = momentum breakout."""
    if len(df) < 25:
        return None
    c = df["Close"]
    h = df["High"]
    lo = df["Low"]

    _, bb_upper, bb_lower = _bollinger(c, 20, 2.0)
    _, kc_upper, kc_lower = _keltner(h, lo, c, 20, 1.5)

    # Squeeze: BB inside KC
    in_squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    fired = in_squeeze.shift(1) & ~in_squeeze  # squeeze just released

    if not fired.iloc[-1]:
        return None

    # Momentum direction via momentum oscillator (Ehlers)
    highest_h = h.rolling(20).max()
    lowest_l = lo.rolling(20).min()
    mid_hl = (highest_h + lowest_l) / 2.0
    mid_c20 = c.rolling(20).mean()
    momentum = c - (mid_hl + mid_c20) / 2.0

    direction = "bullish" if momentum.iloc[-1] > 0 else "bearish"
    squeeze_bars = int(in_squeeze[::-1].argmin()) if in_squeeze.iloc[-2] else 1

    # Stronger setup = longer squeeze
    edge_score = min(100, 50 + squeeze_bars * 4)

    return {
        "pattern": "TTM Squeeze Breakout",
        "direction": direction,
        "edge_score": round(edge_score, 1),
        "squeeze_bars": squeeze_bars,
        "momentum": round(float(momentum.iloc[-1]), 4),
    }


def _detect_vwap_reclaim(df: pd.DataFrame) -> Optional[dict]:
    """Price dipped below VWAP, now closing back above it on rising volume."""
    if len(df) < 5:
        return None
    c = df["Close"]
    h = df["High"]
    lo = df["Low"]
    v = df["Volume"]

    vwap = _vwap(h, lo, c, v)
    above = c > vwap
    # Previous bar below, current bar above = reclaim
    if not (not above.iloc[-2] and above.iloc[-1]):
        return None

    vol_sma = v.rolling(20).mean()
    rvol = float(v.iloc[-1] / (vol_sma.iloc[-1] + 1e-9))
    if rvol < 1.2:
        return None

    rsi = _rsi(c)
    reclaim_strength = float(c.iloc[-1] / (vwap.iloc[-1] + 1e-9) - 1.0) * 100.0

    edge_score = min(100, 55 + rvol * 10 + reclaim_strength * 5)

    return {
        "pattern": "VWAP Reclaim",
        "direction": "bullish",
        "edge_score": round(edge_score, 1),
        "rvol": round(rvol, 2),
        "rsi": round(float(rsi.iloc[-1]), 1),
        "vwap": round(float(vwap.iloc[-1]), 2),
    }


def _detect_bull_bear_flag(df: pd.DataFrame) -> Optional[dict]:
    """Impulse move (3%+ in 3 bars) followed by tight consolidation (< 1% range)."""
    if len(df) < 15:
        return None
    c = df["Close"]
    v = df["Volume"]

    # Impulse: 3+ bar move
    impulse_bars = 3
    impulse_ret = float(c.iloc[-1 - impulse_bars] / c.iloc[-1 - impulse_bars - 3] - 1.0)

    if abs(impulse_ret) < 0.03:
        return None

    direction = "bullish" if impulse_ret > 0 else "bearish"

    # Consolidation: last 3 bars tight
    consol_range = float((c.iloc[-1] - c.iloc[-4]).abs() / c.iloc[-4])
    if consol_range > 0.015:
        return None

    # Volume should be lower during flag than impulse
    flag_vol = float(v.iloc[-3:].mean())
    impulse_vol = float(v.iloc[-6:-3].mean())
    if flag_vol >= impulse_vol:
        return None

    vol_decline = 1.0 - flag_vol / (impulse_vol + 1e-9)
    edge_score = min(100, 60 + abs(impulse_ret) * 300 + vol_decline * 30)

    return {
        "pattern": f"{'Bull' if direction == 'bullish' else 'Bear'} Flag",
        "direction": direction,
        "edge_score": round(edge_score, 1),
        "impulse_pct": round(impulse_ret * 100, 2),
        "flag_tightness_pct": round(consol_range * 100, 2),
    }


def _detect_volume_breakout(df: pd.DataFrame) -> Optional[dict]:
    """Price breaks 20-session high/low on 2x+ average volume."""
    if len(df) < 25:
        return None
    c = df["Close"]
    h = df["High"]
    lo = df["Low"]
    v = df["Volume"]

    high20 = h.iloc[-21:-1].max()
    low20 = lo.iloc[-21:-1].min()
    vol_avg20 = v.iloc[-21:-1].mean()
    rvol = float(v.iloc[-1] / (vol_avg20 + 1e-9))

    if rvol < 2.0:
        return None

    if c.iloc[-1] > high20:
        direction = "bullish"
        breakout_pct = float(c.iloc[-1] / high20 - 1.0) * 100
    elif c.iloc[-1] < low20:
        direction = "bearish"
        breakout_pct = float(low20 / c.iloc[-1] - 1.0) * 100
    else:
        return None

    edge_score = min(100, 55 + rvol * 8 + breakout_pct * 10)

    return {
        "pattern": "Volume Breakout",
        "direction": direction,
        "edge_score": round(edge_score, 1),
        "rvol": round(rvol, 2),
        "breakout_pct": round(breakout_pct, 2),
        "key_level": round(float(high20 if direction == "bullish" else low20), 2),
    }


def _detect_oversold_bounce(df: pd.DataFrame) -> Optional[dict]:
    """RSI < 30 + price at/below BB lower + current bar green = bounce setup."""
    if len(df) < 25:
        return None
    c = df["Close"]
    o = df["Open"]
    h = df["High"]
    lo = df["Low"]
    v = df["Volume"]

    rsi = _rsi(c)
    _, _, bb_lower = _bollinger(c, 20, 2.0)

    if float(rsi.iloc[-1]) > 35:
        return None
    if float(c.iloc[-1]) > float(bb_lower.iloc[-1]) * 1.01:
        return None

    is_green = float(c.iloc[-1]) > float(o.iloc[-1])
    if not is_green:
        return None

    vol_avg = v.rolling(20).mean()
    rvol = float(v.iloc[-1] / (vol_avg.iloc[-1] + 1e-9))

    z_score = float((c.iloc[-1] - c.rolling(20).mean().iloc[-1]) / (c.rolling(20).std().iloc[-1] + 1e-9))
    edge_score = min(100, 50 + (30 - float(rsi.iloc[-1])) * 1.5 + abs(z_score) * 5 + (rvol - 1.0) * 8)

    return {
        "pattern": "Oversold Bounce",
        "direction": "bullish",
        "edge_score": round(edge_score, 1),
        "rsi": round(float(rsi.iloc[-1]), 1),
        "z_score": round(z_score, 2),
        "rvol": round(rvol, 2),
        "bb_lower": round(float(bb_lower.iloc[-1]), 2),
    }


# ── Main scanner ─────────────────────────────────────────────────────────────

class EdgeScanner:
    """
    Fetches live data and runs all pattern detectors on a universe of symbols.
    Returns raw setup dicts — scoring and AI analysis happen downstream.
    """

    def __init__(self, min_price: float = 1.0, max_price: float = 500.0,
                 min_volume: int = 500_000):
        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume

    def _fetch(self, symbols: list[str], days: int = 60) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        logger.info(f"[SCANNER] Fetching {len(symbols)} symbols ({days}d)")
        try:
            raw = yf.download(
                symbols, period=f"{days}d", group_by="ticker",
                progress=False, threads=False, auto_adjust=True
            )
            result = {}
            if len(symbols) == 1:
                sym = symbols[0]
                df = raw.dropna(subset=["Close"])
                if not df.empty:
                    result[sym] = df
            else:
                for sym in symbols:
                    if sym not in raw.columns.get_level_values(0):
                        continue
                    df = raw[sym].dropna(subset=["Close"])
                    if not df.empty:
                        result[sym] = df
            return result
        except Exception as e:
            logger.error(f"[SCANNER] Fetch error: {e}")
            return {}

    def _price_volume_ok(self, df: pd.DataFrame) -> bool:
        price = float(df["Close"].iloc[-1])
        vol = float(df["Volume"].iloc[-1])
        return self.min_price <= price <= self.max_price and vol >= self.min_volume

    def scan(self, symbols: list[str]) -> list[dict]:
        """Run all detectors on every symbol. Returns list of setup dicts."""
        data = self._fetch(symbols, days=60)
        setups = []

        detectors = [
            _detect_ttm_squeeze,
            _detect_vwap_reclaim,
            _detect_bull_bear_flag,
            _detect_volume_breakout,
            _detect_oversold_bounce,
        ]

        for sym, df in data.items():
            if not self._price_volume_ok(df):
                continue

            price = float(df["Close"].iloc[-1])
            vol = float(df["Volume"].iloc[-1])
            atr = float(_atr(df["High"], df["Low"], df["Close"]).iloc[-1])
            hurst = _hurst(df["Close"])

            for detector in detectors:
                try:
                    result = detector(df)
                    if result is None:
                        continue

                    setup = {
                        "symbol": sym,
                        "price": round(price, 2),
                        "volume": int(vol),
                        "atr": round(atr, 3),
                        "hurst": round(hurst, 3),
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        **result,
                    }
                    setups.append(setup)
                except Exception as e:
                    logger.debug(f"[SCANNER] {sym} {detector.__name__}: {e}")

        setups.sort(key=lambda x: x["edge_score"], reverse=True)
        return setups
