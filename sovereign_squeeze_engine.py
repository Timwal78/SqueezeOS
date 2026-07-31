"""
SML Sovereign Squeeze Finder Engine — Python port of
indicators/SML_Sovereign_Squeeze_Finder_v6.pine ("ScriptMaster - Sovereign
Squeeze Setup Finder v6", operator-submitted 2026-07-31). Same convention as
breakout_engine.py/sr_matrix_engine.py — Pine script is a visual of this
math, this module is the single source of truth, no drift.

Signal logic (a classic TTM-squeeze-style compression/release, NOT a
duplicate of squeeze_analyzer.py's price/volume ignition score or
squeeze_fuel_engine.py's FTD/short-vol/gamma composite — this one is pure
Bollinger-vs-Keltner compression + linear-regression momentum + RVOL +
200-EMA trend filter, entirely self-contained):

1. Squeeze ON when the Bollinger Bands (bbLength/bbMult) sit fully inside
   the Keltner Channel (kcLength/kcMult); squeeze OFF when BB expands
   outside KC again ("fires").
2. `val` is Pine's ta.linreg(...) momentum term — the linear-regression
   endpoint of price's deviation from the midline of (highest/lowest,
   sma(close)) over the KC window. Implemented here via closed-form
   least-squares (see `_linreg_endpoint()`), which is exactly what Pine's
   ta.linreg(source, length, 0) computes.
3. A CALL setup fires the bar the squeeze releases (`sqzFired`), provided
   the squeeze held for at least `min_sqz_bars`, momentum is accelerating
   upward (`val > val[1]` and `val > 0`), RVOL clears `min_rvol`, and
   (optionally) price is above the 200-EMA. PUT is the mirror image.
4. Entry stop/target (only meaningful for the backtest state machine in
   `compute_series()`, not literal live executor levels — see
   breakout_engine.py's docstring for why): stop = lowest(low, 3) for a
   CALL / highest(high, 3) for a PUT at the entry bar, target = entry +/-
   (entry - stop) * rr_ratio.

No lookahead: `sqzBarCount`/`sqzFired`/RVOL/EMA are all computed strictly
from bars up to and including the current index — same walk-forward
discipline as every other engine here.

Live-execution signal mapping is DELIBERATELY NARROWER than the full
backtest state machine, same reasoning as breakout_engine.py: only fresh
ENTRY events map to a live signal (ENTER_CALL -> BUY, ENTER_PUT -> SELL,
matching iam_executor's existing bearish-resolution convention). An open
CALL's EXIT_TARGET/EXIT_STOP also emits SELL (closes the long, matching
_close_equity_position). A PUT position's exit emits NO live signal —
iam_executor has no "close an existing put" mechanism (same gap Breakout's
and MM-Intel's docstrings already document), so inventing one here would
add an un-backtested action. Downside on live CALL positions still comes
from iam_executor's own real stop-loss order (IAM_STOP_LOSS_PCT).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class SovereignSqueezeParams:
    """Defaults below are the TRAIN/VALID-validated config from
    docs/SOVEREIGN_SQUEEZE_OPTIMIZATION_2026-07-31.md, NOT the operator's
    originally-pasted Pine script defaults. The script's own submitted
    defaults (bb_length=20/mult=2.0, kc_length=20/mult=1.5, min_sqz_bars=3,
    min_rvol=1.5, rr_ratio=2.5) measured PF 0.34 on the real 2021-2026
    dataset in docs/SOVEREIGN_SQUEEZE_BACKTEST_2026-07-31.md — not
    profitable. A chronological TRAIN(67%)/VALID(33%) parameter search
    (tests/optimize_sovereign_squeeze.py) found this config instead:
    96 real trades across 6 symbols, PF 2.70 aggregate, and — the part that
    actually matters against overfitting — VALID PF *exceeded* TRAIN PF
    (2.52->3.56) and stayed >1.0 across four different split points
    (50/60/67/75%) and across single-parameter perturbations in five of
    six tuned dimensions. The one axis that is narrow rather than broadly
    robust is bb_length/kc_length itself (only 10 tested well; 14/15/20 did
    not) — disclosed, not hidden. See the optimization doc for the full
    robustness writeup before changing these again without re-validating."""
    bb_length: int = 10
    bb_mult: float = 2.5
    kc_length: int = 10
    kc_mult: float = 2.0
    min_sqz_bars: int = 2
    use_rvol: bool = True
    min_rvol: float = 1.0
    use_macro_ema: bool = True
    macro_ema_len: int = 200
    rr_ratio: float = 2.0

    @classmethod
    def from_env(cls) -> "SovereignSqueezeParams":
        return cls(
            bb_length=int(os.environ.get("SOVEREIGN_SQZ_BB_LENGTH", "10")),
            bb_mult=float(os.environ.get("SOVEREIGN_SQZ_BB_MULT", "2.5")),
            kc_length=int(os.environ.get("SOVEREIGN_SQZ_KC_LENGTH", "10")),
            kc_mult=float(os.environ.get("SOVEREIGN_SQZ_KC_MULT", "2.0")),
            min_sqz_bars=int(os.environ.get("SOVEREIGN_SQZ_MIN_BARS", "2")),
            use_rvol=os.environ.get("SOVEREIGN_SQZ_USE_RVOL", "true").strip().lower() == "true",
            min_rvol=float(os.environ.get("SOVEREIGN_SQZ_MIN_RVOL", "1.0")),
            use_macro_ema=os.environ.get("SOVEREIGN_SQZ_USE_MACRO_EMA", "true").strip().lower() == "true",
            macro_ema_len=int(os.environ.get("SOVEREIGN_SQZ_MACRO_EMA_LEN", "200")),
            rr_ratio=float(os.environ.get("SOVEREIGN_SQZ_RR_RATIO", "2.0")),
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


def _bar_key(bar: dict, idx: int) -> str:
    return str(bar.get("date") or bar.get("t") or bar.get("timestamp") or idx)


def _sma(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    running = 0.0
    for i in range(n):
        running += vals[i]
        if i >= length:
            running -= vals[i - length]
        if i >= length - 1:
            out[i] = running / length
    return out


def _stdev(vals: list, length: int, means: list) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if means[i] is None:
            continue
        window = vals[i - length + 1:i + 1]
        m = means[i]
        var = sum((v - m) ** 2 for v in window) / length
        out[i] = var ** 0.5
    return out


def _ema(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    if n == 0:
        return out
    k = 2.0 / (length + 1)
    seed = None
    for i in range(n):
        if seed is None:
            if i >= length - 1:
                seed = sum(vals[i - length + 1:i + 1]) / length
                out[i] = seed
            continue
        seed = vals[i] * k + seed * (1 - k)
        out[i] = seed
    return out


def _rolling_max(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if i < length - 1:
            continue
        out[i] = max(vals[i - length + 1:i + 1])
    return out


def _rolling_min(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if i < length - 1:
            continue
        out[i] = min(vals[i - length + 1:i + 1])
    return out


def _true_range(highs: list, lows: list, closes: list, i: int) -> float:
    if i == 0:
        return highs[i] - lows[i]
    return max(
        highs[i] - lows[i],
        abs(highs[i] - closes[i - 1]),
        abs(lows[i] - closes[i - 1]),
    )


def _linreg_endpoint(vals: list) -> Optional[float]:
    """Closed-form least-squares endpoint value — equivalent to Pine's
    ta.linreg(source, length, 0) evaluated over `vals` (oldest first)."""
    n = len(vals)
    if n == 0:
        return None
    sum_x = n * (n - 1) / 2.0
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6.0
    sum_y = sum(vals)
    sum_xy = sum(i * v for i, v in enumerate(vals))
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return sum_y / n
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return intercept + slope * (n - 1)


def compute_series(bars: list, p: SovereignSqueezeParams = None) -> dict:
    """Full walk-forward position state machine, same discipline as
    breakout_engine.compute_series() — one open position at a time, entry
    at the setup bar's close, stop/target checked on each subsequent bar's
    close, no intrabar fills, no lookahead."""
    p = p or SovereignSqueezeParams.from_env()
    n = len(bars)
    highs   = [_bar_val(b, "high", "h") for b in bars]
    lows    = [_bar_val(b, "low", "l") for b in bars]
    closes  = [_bar_val(b, "close", "c") for b in bars]
    volumes = [_bar_val(b, "volume", "v") for b in bars]

    basis_bb = _sma(closes, p.bb_length)
    dev_bb = _stdev(closes, p.bb_length, basis_bb)
    upper_bb = [None if basis_bb[i] is None else basis_bb[i] + p.bb_mult * dev_bb[i] for i in range(n)]
    lower_bb = [None if basis_bb[i] is None else basis_bb[i] - p.bb_mult * dev_bb[i] for i in range(n)]

    ma_kc = _sma(closes, p.kc_length)
    tr = [_true_range(highs, lows, closes, i) for i in range(n)]
    range_kc = _sma(tr, p.kc_length)
    upper_kc = [None if ma_kc[i] is None else ma_kc[i] + range_kc[i] * p.kc_mult for i in range(n)]
    lower_kc = [None if ma_kc[i] is None else ma_kc[i] - range_kc[i] * p.kc_mult for i in range(n)]

    vol_ema = _ema(volumes, 20)
    macro_ema = _ema(closes, p.macro_ema_len)

    sqz_on = [False] * n
    sqz_off = [False] * n
    for i in range(n):
        if lower_bb[i] is None or upper_kc[i] is None:
            continue
        sqz_on[i] = lower_bb[i] > lower_kc[i] and upper_bb[i] < upper_kc[i]
        sqz_off[i] = lower_bb[i] < lower_kc[i] and upper_bb[i] > upper_kc[i]

    sqz_bar_count = [0] * n
    running = 0
    for i in range(n):
        if sqz_on[i]:
            running += 1
        elif sqz_off[i]:
            running = 0
        sqz_bar_count[i] = running

    # BUG FIX (2026-07-31, found after the operator reported real TradingView
    # backtests looking far better than this engine's first port): Pine's
    # `source - math.avg(math.avg(ta.highest(high,kcLength), ta.lowest(low,
    # kcLength)), ta.sma(close,kcLength))` is a SERIES expression — at every
    # bar k, ta.highest/ta.lowest/ta.sma are each evaluated using THEIR OWN
    # rolling kc_length window ending at k. `ta.linreg(that_series,
    # kcLength, 0)` then regresses the trailing kc_length values of that
    # already-per-bar-computed deviation series.
    #
    # The original port instead computed one "mid" reference level ONLY at
    # the current bar i (using hh/ll/sma_c as of i) and subtracted that SAME
    # constant from every raw close in the window before regressing. That is
    # a materially different, wrong quantity: it regresses (close[j] - a
    # constant) rather than the correct per-bar deviation dev[j], which
    # flattens/distorts the momentum term's real slope and mislabeled
    # otherwise-good setups. Fixed by building the real `dev` series first
    # (using rolling highest/lowest/sma at every bar, matching Pine's own
    # per-bar evaluation), then regressing the trailing kc_length window of
    # THAT series — exactly what ta.linreg(dev, kcLength, 0) computes.
    highest_kc = _rolling_max(highs, p.kc_length)
    lowest_kc = _rolling_min(lows, p.kc_length)
    dev = [None] * n
    for i in range(n):
        if highest_kc[i] is None or ma_kc[i] is None:
            continue
        mid = ((highest_kc[i] + lowest_kc[i]) / 2.0 + ma_kc[i]) / 2.0
        dev[i] = closes[i] - mid

    val = [None] * n
    for i in range(n):
        if i < 2 * p.kc_length - 2 or dev[i - p.kc_length + 1] is None:
            continue
        window = dev[i - p.kc_length + 1:i + 1]
        val[i] = _linreg_endpoint(window)

    events      = [None] * n   # "ENTER_CALL" | "ENTER_PUT" | "EXIT_TARGET" | "EXIT_STOP" | None
    live_signal = [None] * n   # "BUY" | "SELL" | None
    state_dir   = [None] * n   # "call" | "put"
    pnl_pct     = [None] * n
    score       = [0] * n

    in_pos = False
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None

    for i in range(n):
        if in_pos:
            close = closes[i]
            if direction == "call":
                pnl = (close - entry_price) / entry_price
            else:
                pnl = (entry_price - close) / entry_price
            pnl_pct[i] = round(pnl * 100, 4)

            hit_target = close >= target_price if direction == "call" else close <= target_price
            hit_stop = close <= stop_price if direction == "call" else close >= stop_price
            if hit_target:
                events[i] = "EXIT_TARGET"
                if direction == "call":
                    live_signal[i] = "SELL"
                in_pos = False
                direction = None
                entry_price = stop_price = target_price = None
                continue
            if hit_stop:
                events[i] = "EXIT_STOP"
                if direction == "call":
                    live_signal[i] = "SELL"
                in_pos = False
                direction = None
                entry_price = stop_price = target_price = None
                continue
            state_dir[i] = direction
            continue

        if val[i] is None or i < 1 or val[i - 1] is None:
            continue

        prev_sqz_bars = sqz_bar_count[i - 1]
        sqz_fired = sqz_off[i] and sqz_on[i - 1]
        valid_len = prev_sqz_bars >= p.min_sqz_bars
        rvol = (volumes[i] / vol_ema[i]) if vol_ema[i] else 1.0
        rvol_pass = (not p.use_rvol) or (rvol >= p.min_rvol)

        call_setup = (
            sqz_fired and valid_len and val[i] > val[i - 1] and val[i] > 0
            and rvol_pass and (not p.use_macro_ema or macro_ema[i] is None or closes[i] > macro_ema[i])
        )
        put_setup = (
            sqz_fired and valid_len and val[i] < val[i - 1] and val[i] < 0
            and rvol_pass and (not p.use_macro_ema or macro_ema[i] is None or closes[i] < macro_ema[i])
        )

        if call_setup or put_setup:
            score_len = min(prev_sqz_bars * 10, 40)
            score_vol = min(round(rvol * 20), 40)
            score_trend = 20 if p.use_macro_ema and macro_ema[i] is not None else 10
            score[i] = min(score_len + score_vol + score_trend, 100)

        if call_setup:
            entry_price = closes[i]
            stop_price = min(lows[max(0, i - 2):i + 1])
            target_price = entry_price + (entry_price - stop_price) * p.rr_ratio
            in_pos, direction = True, "call"
            events[i] = "ENTER_CALL"
            live_signal[i] = "BUY"
            state_dir[i] = "call"
            pnl_pct[i] = 0.0
        elif put_setup:
            entry_price = closes[i]
            stop_price = max(highs[max(0, i - 2):i + 1])
            target_price = entry_price - (stop_price - entry_price) * p.rr_ratio
            in_pos, direction = True, "put"
            events[i] = "ENTER_PUT"
            live_signal[i] = "SELL"
            state_dir[i] = "put"
            pnl_pct[i] = 0.0

    return {
        "events": events, "live_signal": live_signal,
        "state_dir": state_dir, "pnl_pct": pnl_pct, "score": score,
        "sqz_on": sqz_on, "sqz_off": sqz_off, "sqz_bar_count": sqz_bar_count, "val": val,
        "in_pos": in_pos, "direction": direction,
        "entry_price": entry_price, "stop_price": stop_price, "target_price": target_price,
    }


def analyze(symbol: str, bars: list, p: SovereignSqueezeParams = None) -> dict:
    """On-demand analysis of the LATEST bar — same convention as
    breakout_engine.analyze()/sr_matrix_engine.analyze()."""
    p = p or SovereignSqueezeParams.from_env()
    min_bars = max(p.bb_length, p.kc_length, p.macro_ema_len if p.use_macro_ema else 0) + 2
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    close = _bar_val(bars[-1], "close", "c")

    return {
        "symbol": symbol.upper(), "status": "success",
        "price": close,
        "event": out["events"][last],
        "signal": out["live_signal"][last],
        "score": out["score"][last],
        "squeeze_state": "COILING" if out["sqz_on"][last] else ("RELEASED" if out["sqz_off"][last] else "NEUTRAL"),
        "squeeze_bars": out["sqz_bar_count"][last],
        "position": {
            "in_position": out["in_pos"],
            "direction": out["direction"],
            "entry_price": out["entry_price"],
            "stop_price": out["stop_price"],
            "target_price": out["target_price"],
            "unrealized_pct": out["pnl_pct"][last] if out["in_pos"] else None,
        },
        "params": {
            "bb_length": p.bb_length, "bb_mult": p.bb_mult,
            "kc_length": p.kc_length, "kc_mult": p.kc_mult,
            "min_sqz_bars": p.min_sqz_bars, "min_rvol": p.min_rvol,
            "use_macro_ema": p.use_macro_ema, "rr_ratio": p.rr_ratio,
        },
    }
