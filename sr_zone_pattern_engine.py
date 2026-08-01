"""
SML S/R Zone + Candlestick Pattern Engine
====================================================================================
Python port of the operator-submitted Pine v6 script "Best S&R Indicator With
Candlestick Patterns". Distinct from sr_matrix_engine.py (which trades on a
SINGLE confirmed pivot) -- this script's real, defined mechanic is TWO-TOUCH
ZONE CONFIRMATION (a resistance/support zone only forms once NoOfPivots
consecutive pivots cluster at a similar price level) PLUS CANDLESTICK PATTERN
CONFLUENCE (a bullish reversal pattern -- Morning Star, Tweezer Bottom, or
Inside Bar -- occurring specifically inside an active support zone; a bearish
one -- Evening Star, Tweezer Top, Inside Bar -- inside an active resistance
zone). The original script has NO defined buy/sell alertcondition at all --
only zone-formation and proximity alerts -- so "buy at bottom, sell at top"
(the operator's own framing) is implemented directly: BUY on a qualifying
bullish pattern at an active support zone, SELL (close the long) on the next
qualifying bearish pattern at an active resistance zone.

Zone timing has the same no-lookahead property as sr_matrix_engine.py: a
pivot at bar i is only knowable at bar i+Bars (ta.pivothigh/pivotlow(Bars,Bars)
semantics), ported here as a real Bars-bar delay, not assumed.

Candlestick pattern formulas are ported byte-for-byte from the Pine source
(EvnCan/BInBar/MorCan/BullInBar/tbc/ttc), not re-derived or approximated.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ZonePatternParams:
    bars: int = 10
    no_of_pivots: int = 2       # 2, 3, or 4 -- how many clustering pivots confirm a zone
    # 400 (was 200, 2026-08-01): a real chronological TRAIN/VALID search
    # (docs/SR_ZONE_PATTERN_OPTIMIZATION_2026-08-01.md) found 400 combined
    # with zone_buffer_pct=2.0/atr_length=21/atr_stop_mult=2.0 below produces
    # 52 real trades (vs the prior 12) holding VALID PF >1.0 across all 4
    # tested split points. Operator directive 2026-08-01: adopted for the
    # already-live engine after the evidence was disclosed plainly, same
    # "state the evidence, operator decides" pattern as every other engine.
    # zone_expiry itself is one of the search's disclosed FRAGILE axes (0
    # and 400 both hold, 100/200 do not) -- kept here because it's the one
    # this search actually validated, not because the dimension is robust.
    zone_expiry: int = 400      # 0 = never expires
    exit_mode: str = "opposite_zone"  # "opposite_zone" | "atr_target"
    # 2.0 (was 1.5, 2026-08-01) -- part of the same validated config above.
    atr_stop_mult: float = 2.0
    atr_target_mult: float = 3.0
    # 21 (was 1, 2026-08-01): the 2026-08-01 search found a genuine multi-bar
    # Wilder ATR (matching every other engine's convention) tested robustly
    # positive across the ENTIRE range searched (1-28) -- one of only two
    # dimensions (with zone_buffer_pct below) that held up everywhere tested,
    # not just at this one value. See docs/SR_ZONE_PATTERN_OPTIMIZATION_2026-08-01.md.
    atr_length: int = 21
    # 2.0 (was 3.0, 2026-08-01): the search found 1.0-3.0 all hold VALID PF
    # >1.0 (only the wide extreme, 4.0, breaks) -- one of the two genuinely
    # robust dimensions in this search, not a single-point overfit. Original
    # rationale for the concept (a real proximity buffer, not zero) unchanged
    # from the 2026-07-30 note below -- only the specific value changed.
    zone_buffer_pct: float = 2.0

    @classmethod
    def from_env(cls) -> "ZonePatternParams":
        return cls(
            bars=int(os.environ.get("SR_ZONE_PATTERN_BARS", "10")),
            no_of_pivots=int(os.environ.get("SR_ZONE_PATTERN_NO_OF_PIVOTS", "2")),
            zone_expiry=int(os.environ.get("SR_ZONE_PATTERN_ZONE_EXPIRY", "400")),
            exit_mode=os.environ.get("SR_ZONE_PATTERN_EXIT_MODE", "atr_target"),
            atr_stop_mult=float(os.environ.get("SR_ZONE_PATTERN_ATR_STOP_MULT", "2.0")),
            atr_target_mult=float(os.environ.get("SR_ZONE_PATTERN_ATR_TARGET_MULT", "3.0")),
            zone_buffer_pct=float(os.environ.get("SR_ZONE_PATTERN_ZONE_BUFFER_PCT", "2.0")),
            atr_length=int(os.environ.get("SR_ZONE_PATTERN_ATR_LENGTH", "21")),
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


def _true_range(h, l, pc):
    return max(h - l, abs(h - pc), abs(l - pc))


def _atr_series(h: list, l: list, c: list, length: int) -> list:
    """Wilder-smoothed ATR over `length` bars, same convention as every
    other engine in this codebase. length=1 degenerates to exactly the
    original single-bar true-range-per-bar behavior (no smoothing at all),
    preserving backward compatibility with the shipped default."""
    n = len(h)
    tr = [_true_range(h[i], l[i], c[i - 1] if i > 0 else c[i]) for i in range(n)]
    if length <= 1:
        return tr
    out = [None] * n
    running = None
    for i in range(n):
        if running is None:
            if i >= length - 1:
                running = sum(tr[i - length + 1:i + 1]) / length
                out[i] = running
            continue
        running = running - (running / length) + tr[i]
        out[i] = running / length
    return out


def _bar_key(bar: dict, idx: int) -> str:
    return str(bar.get("date") or bar.get("t") or bar.get("timestamp") or idx)


def _detect_patterns(o, h, l, c, i):
    """Faithful port of the Pine script's 6 candlestick pattern booleans at
    bar i (needs bars i, i-1, i-2). Returns (bullish, bearish) booleans."""
    if i < 2:
        return False, False

    def candle(k): return abs(h[k] - l[k])
    def body(k): return abs(o[k] - c[k])
    def body_pct(k):
        cd = candle(k)
        return (body(k) / cd * 100.0) if cd > 0 else 0.0

    evn_can = (body(i) > candle(i) * 0.6 and o[i] > c[i] and
               body(i - 1) < candle(i - 1) * 0.3 and
               body(i - 2) > candle(i - 2) * 0.6 and o[i - 2] < c[i - 2])
    mor_can = (body(i) > candle(i) * 0.6 and o[i] < c[i] and
               body(i - 1) < candle(i - 1) * 0.3 and
               body(i - 2) > candle(i - 2) * 0.6 and o[i - 2] > c[i - 2])
    # BInBar / BullInBar share the identical Pine condition -- direction comes
    # only from which zone type it's checked against downstream.
    inside_bar = (h[i] < h[i - 1] and l[i] > l[i - 1] and body(i - 1) > candle(i - 1) * 0.4)

    bperc = (h[i - 1] - l[i - 1]) / 100.0 * 5.0
    bpercc = (h[i - 1] - l[i - 1]) / 100.0 * 60.0
    tbc = (l[i] > l[i - 1] - bperc and l[i] < l[i - 1] + bperc and
           c[i] > l[i - 1] + bpercc and o[i - 1] > c[i - 1] and
           c[i - 1] - l[i - 1] < bperc and o[i] - l[i] < bperc and
           body_pct(i) > 60 and body_pct(i - 1) > 60)
    ttc = (h[i] > h[i - 1] - bperc and h[i] < h[i - 1] + bperc and
           c[i] < h[i - 1] - bpercc and o[i - 1] < c[i - 1] and
           h[i - 1] - c[i - 1] < bperc and h[i] - o[i] < bperc and
           body_pct(i) > 60 and body_pct(i - 1) > 60)

    bullish = mor_can or inside_bar or tbc
    bearish = evn_can or inside_bar or ttc
    return bullish, bearish


def compute_series(bars: list, p: ZonePatternParams = None) -> dict:
    p = p or ZonePatternParams()
    n = len(bars)
    o = [_bar_val(b, "open", "o") for b in bars]
    h = [_bar_val(b, "high", "h") for b in bars]
    l = [_bar_val(b, "low", "l") for b in bars]
    c = [_bar_val(b, "close", "c") for b in bars]

    events = [None] * n
    live_signal = [None] * n
    pnl_pct = [None] * n
    atr_series = _atr_series(h, l, c, p.atr_length)

    # ── Pivot detection (no lookahead: known only Bars bars later) ──
    pivot_high_body = []  # list of (bar_idx, high, upper_body) in chronological order
    pivot_low_body = []   # list of (bar_idx, low, lower_body)

    res_zones = []  # each: {"h":, "l":, "start":, "broken": bool, "was_away": bool}
    sup_zones = []

    # Bar index of the newest pivot in the cluster that triggered the last
    # created zone, per zone type. A new zone is only created when the
    # newest pivot in the current window is a pivot we haven't already used
    # -- without this, the clustering condition stays true on every
    # subsequent bar (nothing about `recent`/`ref` changes until a new pivot
    # is appended) and the same zone gets re-appended as a duplicate on
    # every bar until the next real pivot arrives.
    last_res_zone_pivot_idx: Optional[int] = None
    last_sup_zone_pivot_idx: Optional[int] = None

    in_pos = False
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price = target_price = None

    for i in range(n):
        # Pivot confirmation happens Bars bars after the actual extreme bar.
        if i >= 2 * p.bars:
            piv_i = i - p.bars
            window = range(piv_i - p.bars, piv_i + p.bars + 1)
            if all(0 <= w < n for w in window):
                if h[piv_i] == max(h[w] for w in window):
                    pivot_high_body.append((piv_i, h[piv_i], max(c[piv_i], o[piv_i])))
                if l[piv_i] == min(l[w] for w in window):
                    pivot_low_body.append((piv_i, l[piv_i], min(c[piv_i], o[piv_i])))

        # ── New resistance zone: NoOfPivots clustering pivot highs ──
        # Only create once per genuinely new triggering pivot -- otherwise the
        # clustering condition stays true on every subsequent bar (nothing
        # about `recent`/`ref` changes until a new pivot is appended) and the
        # same zone gets re-appended as a duplicate on every bar.
        if len(pivot_high_body) >= p.no_of_pivots:
            recent = pivot_high_body[-p.no_of_pivots:]
            newest = recent[-1]
            ref = recent[0]  # the earliest of the cluster anchors the zone
            clustered = all(pv[1] < ref[1] and pv[1] > ref[2] for pv in recent[1:])
            if clustered and newest[0] != last_res_zone_pivot_idx:
                res_zones.append({"h": ref[1], "l": ref[2], "start": ref[0], "broken": False, "was_away": True})
                last_res_zone_pivot_idx = newest[0]

        # ── New support zone: NoOfPivots clustering pivot lows ──
        if len(pivot_low_body) >= p.no_of_pivots:
            recent = pivot_low_body[-p.no_of_pivots:]
            newest = recent[-1]
            ref = recent[0]
            clustered = all(pv[1] > ref[1] and pv[1] < ref[2] for pv in recent[1:])
            if clustered and newest[0] != last_sup_zone_pivot_idx:
                sup_zones.append({"h": ref[2], "l": ref[1], "start": ref[0], "broken": False, "was_away": True})
                last_sup_zone_pivot_idx = newest[0]

        # ── Update zones: break / expire, and detect pattern-confluence signals ──
        bullish_at_support = False
        bearish_at_resistance = False

        for z in res_zones:
            if z["broken"]:
                continue
            if c[i] > z["h"]:
                z["broken"] = True
                continue
            if p.zone_expiry > 0 and (i - z["start"]) > p.zone_expiry:
                z["broken"] = True
                continue
            if c[i] < z["l"]:
                z["was_away"] = True

        for z in sup_zones:
            if z["broken"]:
                continue
            if c[i] < z["l"]:
                z["broken"] = True
                continue
            if p.zone_expiry > 0 and (i - z["start"]) > p.zone_expiry:
                z["broken"] = True
                continue
            if c[i] > z["h"]:
                z["was_away"] = True

        bull_pat, bear_pat = _detect_patterns(o, h, l, c, i)

        if bull_pat:
            for z in sup_zones:
                if z["broken"]:
                    continue
                buf = (z["h"] - z["l"]) * p.zone_buffer_pct
                if z["l"] - buf <= c[i] <= z["h"] + buf:
                    bullish_at_support = True
                    break
        if bear_pat:
            for z in res_zones:
                if z["broken"]:
                    continue
                buf = (z["h"] - z["l"]) * p.zone_buffer_pct
                if z["l"] - buf <= c[i] <= z["h"] + buf:
                    bearish_at_resistance = True
                    break

        close = c[i]

        # ── Position management ──
        if in_pos:
            pnl = (close - entry_price) / entry_price if direction == "up" else (entry_price - close) / entry_price
            pnl_pct[i] = round(pnl * 100, 4)

            exit_now = False
            reason = None
            if p.exit_mode == "opposite_zone":
                if direction == "up" and bearish_at_resistance:
                    exit_now, reason = True, "EXIT_OPPOSITE_ZONE"
            else:
                # stop_price/target_price were already fixed at entry time
                # from that bar's ATR -- no per-bar ATR recompute needed here.
                hit_target = direction == "up" and close >= target_price
                hit_stop = direction == "up" and close <= stop_price
                if hit_target:
                    exit_now, reason = True, "EXIT_TARGET"
                elif hit_stop:
                    exit_now, reason = True, "EXIT_STOP"

            if exit_now:
                events[i] = reason
                live_signal[i] = "SELL"
                in_pos = False
                direction = entry_price = stop_price = target_price = None
                continue
            continue

        if bullish_at_support:
            in_pos = True
            direction = "up"
            entry_price = close
            events[i] = "ENTER_UP"
            live_signal[i] = "BUY"
            pnl_pct[i] = 0.0
            if p.exit_mode == "atr_target":
                atr = atr_series[i] if atr_series[i] is not None else _true_range(h[i], l[i], c[i - 1] if i > 0 else c[i])
                if atr > 0:
                    stop_price = close - p.atr_stop_mult * atr
                    target_price = close + p.atr_target_mult * atr

    return {"events": events, "live_signal": live_signal, "pnl_pct": pnl_pct}


def analyze(symbol: str, bars: list, p: ZonePatternParams = None) -> dict:
    """On-demand latest-bar wrapper, same convention as breakout_engine.py/
    sr_matrix_engine.py -- used by both the scanner and the status blueprint."""
    p = p or ZonePatternParams.from_env()
    if not bars or len(bars) < p.bars * 2 + 2:
        return {"status": "error", "message": "insufficient daily bars", "symbol": symbol}
    out = compute_series(bars, p)
    last = len(bars) - 1
    return {
        "status": "success",
        "symbol": symbol,
        "event": out["events"][last],
        "live_signal": out["live_signal"][last],
        "bars": len(bars),
    }
