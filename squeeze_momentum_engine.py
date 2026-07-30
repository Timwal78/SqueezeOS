"""
SML Squeeze Momentum Engine — Python port of the operator-submitted Pine v6
strategy "ScriptMaster - Squeeze Momentum Engine v6" (submitted 2026-07-30).

Faithful port of the SUBMITTED logic, bugs included, so its TradingView Strategy
Tester numbers can be independently checked against real bars. Where the port
must make a modelling choice, it matches Pine's DEFAULT strategy behaviour:

  * `strategy.entry()` places a MARKET order that fills at the NEXT bar's open
    (process_orders_on_close is not set in the submitted script, so it defaults
    to false). Same for strategy.close(). This is the single most important
    fidelity detail — filling at the signal bar's close instead would flatter
    the result.
  * default_qty_type=percent_of_equity, default_qty_value=2 -> each entry
    deploys 2% of CURRENT equity as notional.
  * commission_type=percent, commission_value=0.03 (%) per side.
  * slippage=1 tick, applied against the fill.

KNOWN ISSUES IN THE SUBMITTED SCRIPT (ported as-is, measured by
tests/backtest_squeeze_momentum.py rather than silently corrected):

  ISSUE A — the short trigger is semantically inverted relative to the long.
    sqzReleaseLong  = scolor == WHITE and scolor[1] == BLACK
        -> squeeze was ON, now OFF  = a squeeze RELEASE. Correct.
    sqzReleaseShort = scolor == BLACK and scolor[1] == WHITE
        -> squeeze was OFF, now ON  = a squeeze BEGINNING, not a release.
    Despite the name, shorts enter on the onset of compression while longs enter
    on its release. These are opposite events.

  ISSUE B — no stop loss exists anywhere in the strategy. The only exit is a
    one-bar momentum tick (val < val[1] for longs, val > val[1] for shorts), so
    a gap through the entry is unbounded relative to position notional. Any
    claim that this script "enforces real-world risk" refers to position SIZE,
    not to risk per trade.

  ISSUE C — `val > valLowest` / `val < valHighest` are tautologies in practice.
    valLowest = ta.lowest(val, 100)[1]; val exceeding its own trailing 100-bar
    minimum is essentially always true. MEASURED: across AMC 2D, AMC 1D, GME 1D
    and COSM 1D the term rejected 0.00% of otherwise-qualifying bars
    (`extreme_filter_bind_pct` == 0.0 on every one). It is decoration, and the
    same class of dead filter found in the CVD Regime script's conviction gate.

  ISSUE D — signals are derived by comparing COLOR values (`scolor == C_WHITE`).
    It works, but it couples signal logic to cosmetics: changing the palette
    silently changes the strategy. The port reads the underlying squeeze state
    directly and asserts the two agree.

  ISSUE E — `noSqz` (and its blue zero-cross) is UNREACHABLE. Dead code, not a
    behavioural bug, but it reveals the squeeze test is simpler than it looks:
        basis = ta.sma(source, lengthBB)   # BB centre
        ma    = ta.sma(source, lengthKC)   # KC centre
    With the default lengthBB == lengthKC == 20 these are the SAME series, so
    both channels are symmetric about one common centre. Then
        lowerBB > lowerKC  <=>  dev < rangema*multKC  <=>  upperBB < upperKC
    i.e. sqzOn and sqzOff are exact logical complements and `noSqz` can never be
    true. Confirmed empirically: over 4,166 GME daily bars the state is 'on' 747
    times and 'off' 3,400 times, 'none' zero times.
    A worthwhile consequence, because it falsifies a plausible-sounding worry:
    one might expect `scolor == WHITE and scolor[1] == BLACK` to miss most real
    squeeze releases (a release that lands in `noSqz` rather than jumping
    straight to `sqzOff`). It does not — measured, ON->OFF transitions equal
    ON->anything transitions exactly (41 of 41 on AMC 2D, 120 of 120 on GME 1D).
    The strategy's very low trade count comes from the CONJUNCTION of the other
    entry filters, not from missed transitions.

Position sizing note that dominates interpretation of the submitted results:
2% of equity per trade on $100k is a $2,000 position. Profit factor, win rate
and max-drawdown-% are all invariant to that choice; total dollar P&L is not.
A large PF next to a tiny drawdown and a tiny total return is the signature of
barely deploying capital, not of a risk-managed edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import math

SQZ_ON, SQZ_OFF, NO_SQZ = "on", "off", "none"


@dataclass
class SqueezeParams:
    length_bb: int = 20
    mult_bb: float = 2.0
    length_kc: int = 20
    mult_kc: float = 1.5
    use_true_range: bool = True
    ema_filter_len: int = 100
    extreme_len: int = 100        # the ta.lowest/highest(val, 100) window
    qty_pct_equity: float = 2.0   # default_qty_value
    commission_pct: float = 0.03  # per side, percent
    slippage_ticks: float = 1.0
    tick_size: float = 0.01
    initial_capital: float = 100_000.0
    allow_short: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# indicator primitives (causal, Pine-equivalent)
# ─────────────────────────────────────────────────────────────────────────────
def _sma(xs: list, n: int) -> list:
    out = [None] * len(xs)
    run = 0.0
    for i, x in enumerate(xs):
        run += x
        if i >= n:
            run -= xs[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def _stdev(xs: list, n: int) -> list:
    """Pine's ta.stdev is the POPULATION standard deviation (biased)."""
    out = [None] * len(xs)
    for i in range(len(xs)):
        if i < n - 1:
            continue
        w = xs[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / n)
    return out


def _ema(xs: list, n: int) -> list:
    """Pine's ta.ema seeds from an SMA of the first n values."""
    out = [None] * len(xs)
    k = 2.0 / (n + 1.0)
    if len(xs) < n:
        return out
    seed = sum(xs[:n]) / n
    out[n - 1] = seed
    prev = seed
    for i in range(n, len(xs)):
        prev = prev + k * (xs[i] - prev)
        out[i] = prev
    return out


def _highest(xs: list, n: int) -> list:
    return [None if i < n - 1 else max(xs[i - n + 1:i + 1]) for i in range(len(xs))]


def _lowest(xs: list, n: int) -> list:
    return [None if i < n - 1 else min(xs[i - n + 1:i + 1]) for i in range(len(xs))]


def _true_range(highs: list, lows: list, closes: list) -> list:
    out = []
    for i in range(len(closes)):
        if i == 0:
            out.append(highs[i] - lows[i])
        else:
            pc = closes[i - 1]
            out.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return out


def _linreg(xs: list, n: int) -> list:
    """ta.linreg(src, n, 0) — value of the least-squares line at the current bar."""
    out = [None] * len(xs)
    # x = 0..n-1 with the CURRENT bar at x = n-1
    sx = sum(range(n))
    sxx = sum(i * i for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return out
    for i in range(n - 1, len(xs)):
        w = xs[i - n + 1:i + 1]
        sy = sum(w)
        sxy = sum(j * w[j] for j in range(n))
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        out[i] = intercept + slope * (n - 1)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# the strategy
# ─────────────────────────────────────────────────────────────────────────────
def compute_signals(bars: list, p: SqueezeParams = None) -> dict:
    """Indicator + entry/exit conditions per bar. No orders yet — pure signal."""
    p = p or SqueezeParams()
    n = len(bars)
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]

    basis = _sma(closes, p.length_bb)
    dev = _stdev(closes, p.length_bb)
    ma = _sma(closes, p.length_kc)
    rng = _true_range(highs, lows, closes) if p.use_true_range else \
        [highs[i] - lows[i] for i in range(n)]
    rangema = _sma(rng, p.length_kc)

    hh = _highest(highs, p.length_kc)
    ll = _lowest(lows, p.length_kc)
    sma_c = _sma(closes, p.length_kc)
    src = [None] * n
    for i in range(n):
        if hh[i] is None or ll[i] is None or sma_c[i] is None:
            continue
        src[i] = closes[i] - ((hh[i] + ll[i]) / 2.0 + sma_c[i]) / 2.0
    first = next((i for i, v in enumerate(src) if v is not None), n)
    val_partial = _linreg([v for v in src if v is not None], p.length_kc)
    val = [None] * n
    for j, v in enumerate(val_partial):
        val[first + j] = v

    ema_f = _ema(closes, p.ema_filter_len)

    state = [None] * n
    for i in range(n):
        if None in (basis[i], dev[i], ma[i], rangema[i]):
            continue
        ubb, lbb = basis[i] + p.mult_bb * dev[i], basis[i] - p.mult_bb * dev[i]
        ukc, lkc = ma[i] + rangema[i] * p.mult_kc, ma[i] - rangema[i] * p.mult_kc
        on = lbb > lkc and ubb < ukc
        off = lbb < lkc and ubb > ukc
        state[i] = SQZ_ON if on else (SQZ_OFF if off else NO_SQZ)

    val_low = [None] * n   # ta.lowest(val, extreme_len)[1]
    val_high = [None] * n
    vals_seen = [v for v in val if v is not None]
    off0 = n - len(vals_seen)
    lo = _lowest(vals_seen, p.extreme_len)
    hi = _highest(vals_seen, p.extreme_len)
    for j in range(1, len(vals_seen)):
        if lo[j - 1] is not None:
            val_low[off0 + j] = lo[j - 1]
        if hi[j - 1] is not None:
            val_high[off0 + j] = hi[j - 1]

    long_cond = [False] * n
    short_cond = [False] * n
    # how often the near-tautological extreme filter actually blocks a bar
    extreme_blocked = 0
    extreme_eligible = 0

    for i in range(1, n):
        if None in (val[i], val[i - 1], ema_f[i], val_low[i], val_high[i]):
            continue
        if state[i] is None or state[i - 1] is None:
            continue
        release_long = state[i] == SQZ_OFF and state[i - 1] == SQZ_ON
        # ISSUE A: this is a squeeze ONSET, not a release — ported as submitted
        release_short = state[i] == SQZ_ON and state[i - 1] == SQZ_OFF

        base_long = (release_long and val[i] > val[i - 1]
                     and closes[i] > closes[i - 1] and closes[i] > ema_f[i])
        base_short = (release_short and val[i] < val[i - 1]
                      and closes[i] < closes[i - 1] and closes[i] < ema_f[i])
        if base_long or base_short:
            extreme_eligible += 1
            passes = (val[i] > val_low[i]) if base_long else (val[i] < val_high[i])
            if not passes:
                extreme_blocked += 1
        long_cond[i] = base_long and val[i] > val_low[i]
        short_cond[i] = base_short and val[i] < val_high[i]

    return {"val": val, "state": state, "ema": ema_f,
            "long_cond": long_cond, "short_cond": short_cond,
            "extreme_eligible": extreme_eligible,
            "extreme_blocked": extreme_blocked}


def run_strategy(bars: list, p: SqueezeParams = None) -> dict:
    """Order simulation matching Pine strategy defaults: market orders submitted
    on the signal bar fill at the NEXT bar's open."""
    p = p or SqueezeParams()
    sig = compute_signals(bars, p)
    opens = [float(b.get("open", b["close"])) for b in bars]
    closes = [float(b["close"]) for b in bars]
    val = sig["val"]

    equity = p.initial_capital
    peak = equity
    max_dd_pct = 0.0
    pos = 0            # +1 long, -1 short, 0 flat
    qty = 0.0
    entry_px = 0.0
    trades = []
    pending = None     # ("entry_long"|"entry_short"|"close", signal_bar_index)
    slip = p.slippage_ticks * p.tick_size

    for i in range(len(bars)):
        # ── fill anything submitted on the previous bar, at THIS bar's open ──
        if pending is not None:
            kind = pending
            px = opens[i]
            if kind == "entry_long":
                fill = px + slip
                qty = (equity * p.qty_pct_equity / 100.0) / fill
                entry_px = fill
                equity -= abs(qty * fill) * p.commission_pct / 100.0
                pos = 1
            elif kind == "entry_short":
                fill = px - slip
                qty = (equity * p.qty_pct_equity / 100.0) / fill
                entry_px = fill
                equity -= abs(qty * fill) * p.commission_pct / 100.0
                pos = -1
            elif kind == "close" and pos != 0:
                fill = px - slip if pos == 1 else px + slip
                gross = (fill - entry_px) * qty if pos == 1 else (entry_px - fill) * qty
                equity -= abs(qty * fill) * p.commission_pct / 100.0
                equity += gross
                trades.append({
                    "dir": "long" if pos == 1 else "short",
                    "entry": round(entry_px, 6), "exit": round(fill, 6),
                    "pnl": round(gross, 4),
                    "pnl_pct_move": round(100.0 * (fill - entry_px) / entry_px *
                                          (1 if pos == 1 else -1), 4),
                    "exit_idx": i,
                    "ts": bars[i].get("ts") or bars[i].get("begins_at"),
                })
                pos, qty, entry_px = 0, 0.0, 0.0
            pending = None

        # ── mark equity, track drawdown ──
        mtm = equity
        if pos == 1:
            mtm = equity + (closes[i] - entry_px) * qty
        elif pos == -1:
            mtm = equity + (entry_px - closes[i]) * qty
        peak = max(peak, mtm)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, 100.0 * (peak - mtm) / peak)

        # ── submit orders for next bar's open ──
        if i + 1 >= len(bars):
            continue
        if pos == 0:
            if sig["long_cond"][i]:
                pending = "entry_long"
            elif p.allow_short and sig["short_cond"][i]:
                pending = "entry_short"
        else:
            if val[i] is None or val[i - 1] is None:
                continue
            if pos == 1 and val[i] < val[i - 1]:
                pending = "close"
            elif pos == -1 and val[i] > val[i - 1]:
                pending = "close"

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    bh = 100.0 * (closes[-1] - closes[0]) / closes[0] if closes else 0.0
    eb = sig["extreme_eligible"]
    return {
        "trades": trades,
        "n_trades": len(trades),
        "n_long": len([t for t in trades if t["dir"] == "long"]),
        "n_short": len([t for t in trades if t["dir"] == "short"]),
        "win_rate": round(100.0 * len(wins) / len(trades), 2) if trades else 0.0,
        "profit_factor": round(gw / gl, 3) if gl > 0 else (float("inf") if gw > 0 else 0.0),
        "net_pnl": round(equity - p.initial_capital, 2),
        "net_pct_of_equity": round(100.0 * (equity - p.initial_capital) / p.initial_capital, 3),
        "max_dd_pct": round(max_dd_pct, 3),
        "buy_hold_pct": round(bh, 2),
        "final_equity": round(equity, 2),
        # ISSUE C evidence: share of otherwise-qualifying bars the extreme
        # filter actually rejected. Near 0% => the term is decoration.
        "extreme_filter_bind_pct": round(100.0 * sig["extreme_blocked"] / eb, 2) if eb else None,
    }
