"""
SML Intraday Compression Detector — Tactical Matrix (15m)
==========================================================
Python companion to the Pine Script Tactical Matrix (EMA 6/33/66/99/123).

Polls Tradier 15m bars, computes the five Tactical Matrix EMAs, and
detects micro-coil compression — the same signal that fires on the
TradingView 15m chart but now available in Python for programmatic routing.

EMA periods loaded from TACTICAL_EMA_CSV env var (default: 6,33,66,99,123).
Coil threshold loaded from TACTICAL_COIL_PCT env var (default: 0.8%).

A coil is detected when the spread between the fastest and slowest EMA
compresses below TACTICAL_COIL_PCT of the slowest EMA. This mirrors the
`micro_coil` signal in SML_Proprietary_EMA_Suite.pine.

Integration:
  from core.intraday_compression import detect_compression, scan_compression

  result = detect_compression("GME")
  if result["is_coil"]:
      print(result["spread_pct"], result["signal"])

  coils = scan_compression(["GME", "AMC", "NVDA", "TSLA"])
"""

from __future__ import annotations

import os
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("SML-IntradayCoil")

# ── Config ─────────────────────────────────────────────────────────────────────

def _load_tactical_periods() -> List[int]:
    raw = os.environ.get("TACTICAL_EMA_CSV", "6,33,66,99,123")
    try:
        periods = [int(x.strip()) for x in raw.split(",") if x.strip()]
        if len(periods) != 5:
            raise ValueError("TACTICAL_EMA_CSV must have exactly 5 values")
        return sorted(periods)
    except Exception as e:
        logger.error(f"[COIL] Bad TACTICAL_EMA_CSV: {e}")
        raise

def _coil_threshold() -> float:
    try:
        return float(os.environ.get("TACTICAL_COIL_PCT", "0.8"))
    except Exception:
        return 0.8

# ── EMA calculation ─────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1)
    out, e = [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def _compute_tactical_emas(closes: List[float]) -> Optional[Dict[str, float]]:
    """
    Compute the five Tactical Matrix EMAs on the provided close series.
    Returns {T1..T5: latest_value} or None if insufficient bars.
    """
    periods = _load_tactical_periods()
    if len(closes) < periods[-1]:
        return None
    result = {}
    for i, period in enumerate(periods, start=1):
        series = _ema(closes, period)
        result[f"T{i}"] = series[-1]
    return result


# ── Alignment logic ─────────────────────────────────────────────────────────────

def _alignment(emas: Dict[str, float], close: float) -> dict:
    """
    Returns bull/bear alignment and spread metrics.
    Mirrors the tact_bull / tact_bear / micro_coil logic in Pine Script.
    """
    vals = [emas["T1"], emas["T2"], emas["T3"], emas["T4"], emas["T5"]]
    bull = all(vals[i] > vals[i+1] for i in range(4))
    bear = all(vals[i] < vals[i+1] for i in range(4))
    bull_pairs = sum(1 for i in range(4) if vals[i] > vals[i+1])
    bear_pairs = sum(1 for i in range(4) if vals[i] < vals[i+1])

    # Spread = (fastest - slowest) / slowest × 100
    spread_pct = abs((vals[0] - vals[4]) / vals[4] * 100) if vals[4] != 0 else 0.0
    threshold  = _coil_threshold()
    is_coil    = spread_pct < threshold

    # Ignition / breakdown — fast EMA crossing second EMA
    # (single-bar snapshot only — callers wanting crossover events
    #  must track prior bar state themselves)
    above_fastest = close > vals[0]

    return {
        "bull":        bull,
        "bear":        bear,
        "bull_pairs":  bull_pairs,
        "bear_pairs":  bear_pairs,
        "spread_pct":  round(spread_pct, 4),
        "is_coil":     is_coil,
        "threshold":   threshold,
        "above_T1":    above_fastest,
        "T1": round(vals[0], 4),
        "T2": round(vals[1], 4),
        "T3": round(vals[2], 4),
        "T4": round(vals[3], 4),
        "T5": round(vals[4], 4),
    }


# ── Data fetch ──────────────────────────────────────────────────────────────────

def _fetch_15m_closes(symbol: str, days_back: int = 5) -> List[float]:
    """
    Pull 15m close prices from Tradier.
    5 trading days × 26 bars/day = ~130 bars (enough for T5=EMA123 warmup).
    """
    try:
        import tradier_api as ta
        if not ta.is_available():
            return []
        bars = ta.get_timesales(symbol, interval="15min", days_back=days_back)
        return [float(b["close"]) for b in bars if b.get("close") is not None]
    except Exception as e:
        logger.debug(f"[COIL] fetch_15m_closes failed {symbol}: {e}")
        return []


# ── Per-symbol detection ─────────────────────────────────────────────────────────

def detect_compression(symbol: str, days_back: int = 5) -> dict:
    """
    Compute the Tactical Matrix state for one symbol on 15m bars.

    Returns:
      symbol       — ticker
      is_coil      — True when spread < TACTICAL_COIL_PCT
      spread_pct   — current spread between T1 and T5
      threshold    — configured coil threshold
      signal       — COIL | BULL_STACK | BEAR_STACK | PARTIAL_BULL | PARTIAL_BEAR | NEUTRAL
      bull / bear  — full 5-level alignment
      bull_pairs / bear_pairs — partial alignment count (0–4)
      T1..T5       — latest EMA values
      bars_used    — number of 15m bars in the input series
      error        — error message if fetch or compute failed (signal="UNAVAILABLE")
    """
    symbol = symbol.upper().strip()

    periods = _load_tactical_periods()
    closes = _fetch_15m_closes(symbol, days_back=days_back)

    if not closes:
        return {
            "symbol": symbol, "is_coil": False, "spread_pct": None,
            "signal": "UNAVAILABLE", "error": "no 15m bars from Tradier",
            "bars_used": 0,
        }
    if len(closes) < periods[-1]:
        return {
            "symbol": symbol, "is_coil": False, "spread_pct": None,
            "signal": "INSUFFICIENT_BARS",
            "error": f"need {periods[-1]} bars, got {len(closes)}",
            "bars_used": len(closes),
        }

    emas = _compute_tactical_emas(closes)
    if not emas:
        return {
            "symbol": symbol, "is_coil": False, "spread_pct": None,
            "signal": "COMPUTE_ERROR", "error": "EMA compute returned None",
            "bars_used": len(closes),
        }

    close = closes[-1]
    align = _alignment(emas, close)

    if align["is_coil"]:
        signal = "COIL"
    elif align["bull"]:
        signal = "BULL_STACK"
    elif align["bear"]:
        signal = "BEAR_STACK"
    elif align["bull_pairs"] >= 3:
        signal = "PARTIAL_BULL"
    elif align["bear_pairs"] >= 3:
        signal = "PARTIAL_BEAR"
    else:
        signal = "NEUTRAL"

    return {
        "symbol":     symbol,
        "is_coil":    align["is_coil"],
        "spread_pct": align["spread_pct"],
        "threshold":  align["threshold"],
        "signal":     signal,
        "bull":       align["bull"],
        "bear":       align["bear"],
        "bull_pairs": align["bull_pairs"],
        "bear_pairs": align["bear_pairs"],
        "above_T1":   align["above_T1"],
        "T1":         align["T1"],
        "T2":         align["T2"],
        "T3":         align["T3"],
        "T4":         align["T4"],
        "T5":         align["T5"],
        "close_15m":  round(close, 4),
        "bars_used":  len(closes),
    }


# ── Batch scan ─────────────────────────────────────────────────────────────────

_SCAN_CACHE: dict = {}
_SCAN_TTL_S = 300  # 5-min cache matches avg_down_engine scan cadence


def scan_compression(symbols: List[str], days_back: int = 5) -> List[dict]:
    """
    Scan a list of symbols and return results sorted:
      1. COIL signals first (strongest timing alignment)
      2. BULL_STACK
      3. BEAR_STACK
      4. PARTIAL_BULL / PARTIAL_BEAR
      5. NEUTRAL / error states

    Results are cached for SCAN_TTL_S seconds to avoid hammering Tradier.
    """
    now    = time.time()
    cached = _SCAN_CACHE.get("last_run")
    if (cached and now - cached["ts"] < _SCAN_TTL_S
            and set(cached["symbols"]) == set(s.upper() for s in symbols)):
        return cached["results"]

    results = []
    for sym in symbols:
        try:
            r = detect_compression(sym, days_back=days_back)
            results.append(r)
        except Exception as e:
            results.append({
                "symbol": sym.upper(), "is_coil": False,
                "signal": "ERROR", "error": str(e), "bars_used": 0,
            })

    _ORDER = {"COIL": 0, "BULL_STACK": 1, "BEAR_STACK": 2,
               "PARTIAL_BULL": 3, "PARTIAL_BEAR": 4, "NEUTRAL": 5,
               "INSUFFICIENT_BARS": 6, "UNAVAILABLE": 7, "ERROR": 8, "COMPUTE_ERROR": 9}
    results.sort(key=lambda r: _ORDER.get(r.get("signal", "ERROR"), 99))

    _SCAN_CACHE["last_run"] = {"ts": now, "symbols": [s.upper() for s in symbols], "results": results}
    return results


def get_coils(symbols: List[str], days_back: int = 5) -> List[dict]:
    """Convenience wrapper — returns only COIL signals from the scan."""
    return [r for r in scan_compression(symbols, days_back=days_back) if r.get("is_coil")]
