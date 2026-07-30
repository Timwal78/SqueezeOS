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

from dataclasses import dataclass
from typing import Optional


@dataclass
class ZonePatternParams:
    bars: int = 10
    no_of_pivots: int = 2       # 2, 3, or 4 -- how many clustering pivots confirm a zone
    zone_expiry: int = 200      # 0 = never expires
    exit_mode: str = "opposite_zone"  # "opposite_zone" | "atr_target"
    atr_stop_mult: float = 1.5
    atr_target_mult: float = 3.0


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
                if not z["broken"] and z["l"] <= c[i] <= z["h"]:
                    bullish_at_support = True
                    break
        if bear_pat:
            for z in res_zones:
                if not z["broken"] and z["l"] <= c[i] <= z["h"]:
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
                atr = _true_range(h[i], l[i], c[i - 1] if i > 0 else c[i])
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
                atr = _true_range(h[i], l[i], c[i - 1] if i > 0 else c[i])
                if atr > 0:
                    stop_price = close - p.atr_stop_mult * atr
                    target_price = close + p.atr_target_mult * atr

    return {"events": events, "live_signal": live_signal, "pnl_pct": pnl_pct}
