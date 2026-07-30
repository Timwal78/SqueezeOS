"""
SML TTM Squeeze Engine — standalone Bollinger/Keltner squeeze-fire breakout engine
====================================================================================
Real Bollinger-inside-Keltner "squeeze" logic (John Carter's TTM Squeeze) already
exists in squeeze_analyzer.py's `_compression_score()` — but only as one 15-point
component buried inside an 8-module composite score, never isolated as its own
buy/sell signal and never independently backtested. This module extracts that
exact BB/KC math (same formulas: BB(20,2), KC(20,1.5*ATR)) into a standalone
walk-forward engine, same convention as breakout_engine.py/druck_engine.py
(Python is the single source of truth; compute_series() for backtesting,
analyze() for on-demand single-symbol reads).

Squeeze ON: Bollinger Bands sit entirely inside the Keltner Channel (low
volatility compression). Squeeze FIRES the bar volatility expands back out
(BB moves back outside KC) after being ON — the classic "coiled spring"
breakout trigger. Direction at fire comes from TTM's own momentum histogram:
linreg(close - avg(highest(high,20), lowest(low,20), sma(close,20)), 20) —
the real published formula, not an invented proxy.

Position state machine (compute_series) enters at the fire bar's close in the
momentum's direction, exits on an ATR-based stop/target (1.5x ATR stop, 3x ATR
target -- same 1.5x stop multiplier convention already used by
robinhood_executor_sml.py's ATR_STOP_MULTIPLIER, disclosed here rather than
independently re-invented). No claim of "sure fire" or guaranteed profitability
is made anywhere in this module -- see docs/TTM_SQUEEZE_BACKTEST_*.md for the
actual measured verdict before this is wired to any scanner or live trading.

Live-execution signal mapping is deliberately narrower than the full backtest
state machine, matching the exact precedent set by breakout_engine.py: only
ENTER_UP -> BUY and a long's exit -> SELL map to a live signal. A DOWN
(short/put) position's exit emits no live signal, since iam_executor has no
"close an existing put" mechanism -- inventing one here would add an
un-backtested action, the same reasoning breakout_engine.py's own docstring
already documents for this exact codebase.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class SqueezeParams:
    bb_length: int = 20
    bb_mult: float = 2.0
    kc_length: int = 20
    kc_mult: float = 1.5
    mom_length: int = 20
    atr_stop_mult: float = 1.5
    atr_target_mult: float = 3.0
    # Mechanical-rule refinements (operator-specified 2026-07-30): "wait for
    # at least 5-6 consecutive red dots", "momentum above zero AND rising"
    # (not just non-zero sign), optional HTF trend filter, optional
    # momentum-flip exit instead of a fixed ATR target. All additive/
    # togglable so the original simpler engine's behavior is reproducible
    # by setting min_squeeze_bars=1, require_momentum_slope=False,
    # use_htf_filter=False, exit_mode="atr_target" (the defaults tested in
    # docs/TTM_SQUEEZE_BACKTEST_2026-07-30.md).
    min_squeeze_bars: int = 5
    require_momentum_slope: bool = True
    use_htf_filter: bool = False
    htf_length: int = 50
    exit_mode: str = "atr_target"  # "atr_target" | "momentum_flip"
    momentum_flip_bars: int = 2

    @classmethod
    def from_env(cls) -> "SqueezeParams":
        return cls(
            bb_length=int(os.environ.get("TTM_BB_LENGTH", "20")),
            bb_mult=float(os.environ.get("TTM_BB_MULT", "2.0")),
            kc_length=int(os.environ.get("TTM_KC_LENGTH", "20")),
            kc_mult=float(os.environ.get("TTM_KC_MULT", "1.5")),
            mom_length=int(os.environ.get("TTM_MOM_LENGTH", "20")),
            atr_stop_mult=float(os.environ.get("TTM_ATR_STOP_MULT", "1.5")),
            atr_target_mult=float(os.environ.get("TTM_ATR_TARGET_MULT", "3.0")),
            min_squeeze_bars=int(os.environ.get("TTM_MIN_SQUEEZE_BARS", "5")),
            require_momentum_slope=os.environ.get("TTM_REQUIRE_MOM_SLOPE", "true").lower() == "true",
            use_htf_filter=os.environ.get("TTM_USE_HTF_FILTER", "false").lower() == "true",
            htf_length=int(os.environ.get("TTM_HTF_LENGTH", "50")),
            exit_mode=os.environ.get("TTM_EXIT_MODE", "atr_target"),
            momentum_flip_bars=int(os.environ.get("TTM_MOMENTUM_FLIP_BARS", "2")),
        )


def _bar_val(bar: dict, *keys, default=0.0) -> float:
    for k in keys:
        v = bar.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _sma(vals: list) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _stdev(vals: list, mean: float) -> float:
    if not vals:
        return 0.0
    return math.sqrt(sum((x - mean) ** 2 for x in vals) / len(vals))


def _true_range(h: float, l: float, prev_close: float) -> float:
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


def _linreg_slope_endpoint(vals: list) -> float:
    """Standard least-squares linear regression, returns the fitted value at
    the LAST point of the window -- the real formula TTM Squeeze's momentum
    histogram uses (Pine's ta.linreg(src, len, 0))."""
    n = len(vals)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(vals) / n
    num = sum((xs[i] - x_mean) * (vals[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    slope = num / den
    intercept = y_mean - slope * x_mean
    return slope * xs[-1] + intercept


def compute_series(bars: list, p: SqueezeParams = None) -> dict:
    """Full walk-forward position state machine. One open position at a time,
    entry at the fire bar's close, exit checked on each subsequent bar's
    close, no intrabar fills, no lookahead -- same convention as
    breakout_engine.py's compute_series()."""
    p = p or SqueezeParams.from_env()
    n = len(bars)
    highs  = [_bar_val(b, "high", "h") for b in bars]
    lows   = [_bar_val(b, "low", "l") for b in bars]
    closes = [_bar_val(b, "close", "c") for b in bars]

    # The momentum histogram itself needs a full mom_length window at EACH of
    # its mom_length regression points (mom_src builds one donchian-mid/sma
    # value per bar in the window), so the true warmup is 2x mom_length, not
    # just mom_length -- otherwise the earliest points in mom_src slice with
    # a negative/out-of-range start.
    win = max(p.bb_length, p.kc_length, 2 * p.mom_length, p.htf_length if p.use_htf_filter else 0) + 1

    in_squeeze  = [None] * n
    fired       = [False] * n
    momentum    = [None] * n
    events      = [None] * n   # "ENTER_UP" | "ENTER_DOWN" | "EXIT_TARGET" | "EXIT_STOP" | None
    live_signal = [None] * n   # "BUY" | "SELL" | None
    state_dir   = [None] * n
    pnl_pct     = [None] * n

    atr_cache: dict = {}

    def atr_at(i: int, length: int) -> float:
        if i in atr_cache:
            return atr_cache[i]
        start = i - length + 1
        trs = []
        for j in range(start, i + 1):
            pc = closes[j - 1] if j > 0 else closes[j]
            trs.append(_true_range(highs[j], lows[j], pc))
        val = _sma(trs)
        atr_cache[i] = val
        return val

    in_pos = False
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    flip_count = 0
    squeeze_streak = 0  # consecutive squeeze-ON bars counted INTO this bar

    htf_sma_cache: dict = {}

    def htf_sma_at(i: int) -> Optional[float]:
        if i < p.htf_length - 1:
            return None
        if i in htf_sma_cache:
            return htf_sma_cache[i]
        val = _sma(closes[i - p.htf_length + 1:i + 1])
        htf_sma_cache[i] = val
        return val

    for i in range(n):
        if i < win:
            continue

        bb_window = closes[i - p.bb_length + 1:i + 1]
        sma_bb = _sma(bb_window)
        std_bb = _stdev(bb_window, sma_bb)
        bb_upper = sma_bb + p.bb_mult * std_bb
        bb_lower = sma_bb - p.bb_mult * std_bb

        kc_window = closes[i - p.kc_length + 1:i + 1]
        sma_kc = _sma(kc_window)
        atr = atr_at(i, p.kc_length)
        kc_upper = sma_kc + p.kc_mult * atr
        kc_lower = sma_kc - p.kc_mult * atr

        squeeze_on = (bb_upper < kc_upper) and (bb_lower > kc_lower)
        in_squeeze[i] = squeeze_on

        prev_on = in_squeeze[i - 1] if i > 0 else None
        # "Wait for at least min_squeeze_bars consecutive red dots" -- prior
        # to updating the streak counter for THIS bar, squeeze_streak holds
        # the consecutive-ON count that just ended at bar i-1 (the actual
        # compression length that preceded this expansion). That's what the
        # minimum must be checked against, not the running count including
        # this (already-expanded) bar.
        prior_streak = squeeze_streak
        just_fired = bool(prev_on) and not squeeze_on and prior_streak >= p.min_squeeze_bars
        fired[i] = just_fired
        squeeze_streak = squeeze_streak + 1 if squeeze_on else 0

        hh = max(highs[i - p.mom_length + 1:i + 1])
        ll = min(lows[i - p.mom_length + 1:i + 1])
        mid_sma = _sma(closes[i - p.mom_length + 1:i + 1])
        donchian_mid = (hh + ll) / 2.0
        mom_src = [closes[j] - (( (max(highs[j - p.mom_length + 1:j + 1]) + min(lows[j - p.mom_length + 1:j + 1])) / 2.0
                                    + _sma(closes[j - p.mom_length + 1:j + 1])) / 2.0)
                   for j in range(i - p.mom_length + 1, i + 1)]
        mom = _linreg_slope_endpoint(mom_src)
        momentum[i] = round(mom, 5)

        close = closes[i]

        if in_pos:
            if direction == "up":
                pnl = (close - entry_price) / entry_price
            else:
                pnl = (entry_price - close) / entry_price
            pnl_pct[i] = round(pnl * 100, 4)

            hit_stop = (direction == "up" and close <= stop_price) or \
                       (direction == "down" and close >= stop_price)

            if hit_stop:
                events[i] = "EXIT_STOP"
                if direction == "up":
                    live_signal[i] = "SELL"
                in_pos = False
                direction = entry_price = stop_price = target_price = None
                flip_count = 0
                continue

            if p.exit_mode == "momentum_flip":
                # "Exit when the momentum histogram flips color for two
                # consecutive bars" -- opposite sign from the position's own
                # direction, held for momentum_flip_bars bars in a row.
                opposite = (direction == "up" and mom < 0) or (direction == "down" and mom > 0)
                flip_count = flip_count + 1 if opposite else 0
                if flip_count >= p.momentum_flip_bars:
                    events[i] = "EXIT_TARGET" if pnl > 0 else "EXIT_STOP"
                    if direction == "up":
                        live_signal[i] = "SELL"
                    in_pos = False
                    direction = entry_price = stop_price = target_price = None
                    flip_count = 0
                    continue
            else:
                hit_target = (direction == "up" and close >= target_price) or \
                             (direction == "down" and close <= target_price)
                if hit_target:
                    events[i] = "EXIT_TARGET"
                    if direction == "up":
                        live_signal[i] = "SELL"
                    in_pos = False
                    direction = entry_price = stop_price = target_price = None
                    continue

            state_dir[i] = direction
            continue

        if just_fired and mom != 0.0:
            # "Momentum above zero and rising -> long only; below zero and
            # falling -> short only" -- not just non-zero sign at the fire
            # bar, but the histogram must also be accelerating in that
            # direction (mom[i] vs mom[i-1]).
            prev_mom = momentum[i - 1] if i > 0 and momentum[i - 1] is not None else 0.0
            mom_rising = mom > prev_mom
            mom_falling = mom < prev_mom
            if p.require_momentum_slope:
                if mom > 0 and not mom_rising:
                    continue
                if mom < 0 and not mom_falling:
                    continue

            if p.use_htf_filter:
                htf_now = htf_sma_at(i)
                htf_prev = htf_sma_at(i - 1)
                if htf_now is None or htf_prev is None:
                    continue
                htf_rising = htf_now > htf_prev
                if mom > 0 and not (close > htf_now and htf_rising):
                    continue
                if mom < 0 and not (close < htf_now and not htf_rising):
                    continue

            entry_atr = atr_at(i, p.kc_length)
            if entry_atr <= 0:
                continue
            if mom > 0:
                direction = "up"
                stop_price = close - p.atr_stop_mult * entry_atr
                target_price = close + p.atr_target_mult * entry_atr
                live_signal[i] = "BUY"
                events[i] = "ENTER_UP"
            else:
                direction = "down"
                stop_price = close + p.atr_stop_mult * entry_atr
                target_price = close - p.atr_target_mult * entry_atr
                live_signal[i] = "SELL"
                events[i] = "ENTER_DOWN"
            in_pos = True
            entry_price = close
            state_dir[i] = direction
            pnl_pct[i] = 0.0
            flip_count = 0

    return {
        "events": events, "live_signal": live_signal,
        "state_dir": state_dir, "pnl_pct": pnl_pct,
        "in_squeeze": in_squeeze, "fired": fired, "momentum": momentum,
        "in_pos": in_pos, "direction": direction,
        "entry_price": entry_price, "stop_price": stop_price, "target_price": target_price,
    }


def analyze(symbol: str, bars: list, p: SqueezeParams = None) -> dict:
    """On-demand analysis of the LATEST bar -- same convention as
    breakout_engine.py/druck_engine.py's analyze(). Real bars only."""
    p = p or SqueezeParams.from_env()
    min_bars = max(p.bb_length, p.kc_length, p.mom_length) + 2
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    close = _bar_val(bars[-1], "close", "c")

    return {
        "symbol": symbol.upper(), "status": "success",
        "price": close,
        "in_squeeze": out["in_squeeze"][last],
        "just_fired": out["fired"][last],
        "momentum": out["momentum"][last],
        "event": out["events"][last],
        "signal": out["live_signal"][last],
        "position": {
            "in_position": out["in_pos"],
            "direction": out["direction"],
            "entry_price": out["entry_price"],
            "target_price": round(out["target_price"], 4) if out["target_price"] else None,
            "stop_price": round(out["stop_price"], 4) if out["stop_price"] else None,
            "unrealized_pct": out["pnl_pct"][last] if out["in_pos"] else None,
        },
        "params": {
            "bb_length": p.bb_length, "bb_mult": p.bb_mult,
            "kc_length": p.kc_length, "kc_mult": p.kc_mult,
            "mom_length": p.mom_length,
            "atr_stop_mult": p.atr_stop_mult, "atr_target_mult": p.atr_target_mult,
        },
    }
