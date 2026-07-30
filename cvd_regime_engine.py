"""
SML CVD Regime Desk Engine — Python port of
indicators/SML_CVD_Regime_Desk_v6.pine
================================================================================
Single source of truth for the CVD-regime math, same convention as
imo_engine.py / orb_engine.py / druck_engine.py / breakout_engine.py /
mm_intel_engine.py (the Pine script is a *visual* of this logic — no drift
between chart and code).

ORIGIN: this is a corrected port of an operator-submitted Pine v6 script
("CVD Regime Fast -> Call/Put Desk", submitted 2026-07-30). SEVEN real bugs
were found in that script during the port, one of them severe enough that the
script could only form an opinion in a short burst after each higher-timeframe
close, on a lookback it was never configured for, with an inert conviction filter
and no position state.

BACKTEST VERDICT for the CORRECTED strategy — read
docs/CVD_REGIME_OPTIMIZATION_2026-07-30.md (which SUPERSEDES the verdict in
docs/CVD_REGIME_BACKTEST_2026-07-30.md, whose conclusion came from only 8
sessions). On 109 sessions x 8 symbols of real 5-min bars the shipped defaults are
net positive (PF 1.090, +67.5% summed, 2222 trades) BUT: a 1000-config search
produced zero configurations that survived out-of-sample (0 of 15), the edge
decays monotonically Apr->Jul (PF 1.360 -> 0.916), and it averages just +0.030%
of the underlying's move per trade — thinner than the bid/ask spread on the
0.30-0.40 delta contracts this is meant to trade. DO NOT ARM LIVE. Fixing the
bugs made the script correct; it did not make it profitable, and nothing here
should be read as claiming otherwise.

The bugs are listed here rather than silently corrected. Each claim below was measured, not assumed — the numbers
come from tests/test_cvd_regime_engine_smoke.py, which reproduces the original
formulas alongside the fixed ones.

  BUG 1 (CRITICAL — the HTF filter was quantized to hourly closes AND measured
         on the wrong lookback).
    The submitted script did:
        htfCvdS  = request.security(syminfo.tickerid, htfTF, cvdS)
        htfSlope = htfCvdS - htfCvdS[slopeLen]
    `htfCvdS[slopeLen]` indexes the CHART's bar array, not the HTF bar array.
    request.security() with lookahead_off returns the last *closed* HTF value
    and holds it flat across every chart bar inside the forming HTF bar. On a
    5-minute chart with a 60-minute HTF that is 12 identical chart bars, so
    `htfCvdS - htfCvdS[3]` is exactly 0.0 on 9 of every 12 bars — measured at
    73.7% of bars on real SPY data. On those bars htfBull and htfBear are BOTH
    false, and since alignedBull/alignedBear AND the `useEarly` path all require
    one of them, no signal of any kind could fire there.
    The net effect is NOT signal starvation, and measurement corrected that
    assumption: it is signal QUANTIZATION. Every signal the script could produce
    was confined to the 26.4% of bars where an HTF bucket boundary happened to
    fall inside the 3-bar window — i.e. it could only form an opinion in a short
    burst after each hourly close — and on those bars it was reading a
    1-HTF-BAR difference, never the intended slope_len. Measured on the same real
    bars, the original actually emitted MORE signals than this engine does (217
    vs 102 across 5 symbols) because BUG 2 and BUG 5 left it with no conviction
    gate and no position state. Both the timing and the lookback were wrong; the
    volume of signals was not the problem.
    FIX: the slope is measured in HTF space, over slope_len completed HTF
    buckets, as intended.

  BUG 2 (the conviction filter did nothing at any usable setting).
    Scoring gave a flat +-14 (flow) +-10 (price) +-10 (HTF) off a base of 50,
    and alignedBull requires all three to agree. So an aligned-bull bar always
    scored >= 84 and an aligned-bear bar always scored <= 16. The gates were
    `callSignal = alignedBull and score >= minConviction` and
    `putSignal  = alignedBear and score <= 100 - minConviction`, so for any
    minConviction between 17 and 83 (the default is 55) the score test was
    *always* satisfied whenever alignment held. `minConviction` was a no-op
    input. FIX: the flow/HTF/price contributions are now continuous
    (magnitude-scaled, not flat +-N), so a weakly-aligned bar scores near 50
    and the threshold actually binds.

  BUG 3 (strength was dimensionally wrong, so it was systematically small).
    `strength = math.abs(cvdSlope) / ta.stdev(cvdS, 30)` divides a 3-bar CHANGE
    in CVD by the standard deviation of the CVD LEVEL. With a daily reset the
    level's stdev is dominated by the session's cumulative drift, so the ratio
    is systematically depressed: measured median 0.326 on the test series,
    reaching the `math.min(strength * 7.0, 14.0)` cap on only 1.5% of bars. The
    strength term therefore contributed ~2 points of a possible 14 almost all
    the time — not literally zero, but close enough to dead weight that it could
    not differentiate a violent flow impulse from a drifting one, which is the
    entire reason the term exists. FIX: the slope is normalized by the rolling
    stdev of the SLOPE (same units); measured median rises to 0.948.

  BUG 4 (the smoothed CVD was discontinuous across every session boundary).
    `cvd` was reset daily but `cvdS = ta.ema(cvd, smoothLen)` was NOT — the EMA
    carried the prior session's ending CVD level into the new session, so the
    first ~smoothLen bars of every day showed a large artificial slope caused
    purely by the reset, in whichever direction yesterday closed. FIX: the EMA
    state is re-seeded on reset, AND no signal is allowed until slope_len bars
    into the session (before that, `cvdS - cvdS[slope_len]` still straddles the
    boundary).

  BUG 5 (exit signals were not position-aware and were not edge-gated).
    `exitLong = putSignal or (flowBear and callSignal[1])` was plotted with
    plotshape on every bar the condition held (an X-cross on every bar of a
    downtrend) and fired whether or not a long was ever open. FIX: a real
    one-position-at-a-time state machine; exits are edge events that can only
    occur while a position is actually open.

  BUG 6 (signals were evaluated on the live, unclosed bar -> repaint).
    No barstate.isconfirmed gate anywhere, so shapes and alertcondition() could
    fire mid-bar and then vanish. Every other v6 script in indicators/ confirms
    on close. FIX: bar-close confirmation (this engine is inherently
    close-based; the Pine port gates on barstate.isconfirmed).

  BUG 7 (no risk container at all, on a script whose stated purpose is buying
    options). The submitted script had no stop, no target, no cooldown and no
    cap on how often it could flip. FIX: ATR stop, R-multiple target, and a
    cooldown after every exit. NOTE these are modelled on the UNDERLYING's
    move — see the disclosure below.

DISCLOSURES (kept in code, not just in docs):

  * "CVD" here is a BAR-RANGE PROXY for delta, not true bid/ask delta. It is
    volume * ((close-low) - (high-close)) / (high-low), computed from ordinary
    OHLCV — the same proxy the submitted script used. Real signed delta needs
    tick/quote data that neither TradingView's standard feed nor this
    codebase's data providers supply. Same proxy class as the DLMD/OFI label
    in SML_Cycle_Intelligence_Engine_v6.pine.
  * The stop/target model here is a DIRECTIONAL %-move on the underlying, the
    same convention as breakout_engine.py / druck_engine.py / mm_intel_engine.py.
    It does NOT model option premium, leverage, theta or spread. A profitable
    directional result is NECESSARY BUT NOT SUFFICIENT for a profitable
    delta-options result.

Live-execution signal mapping (compute_series()'s "live_signal") deliberately
matches the house convention already used by breakout_engine.py and
mm_intel_scanner.py:
    ENTER_LONG        -> "BUY"
    ENTER_SHORT       -> "SELL"
    exit of a LONG    -> "SELL"   (closes the long; matches
                                   iam_executor._close_equity_position)
    exit of a SHORT   -> None     (iam_executor has no "close an existing put"
                                   mechanism; inventing one here would add an
                                   un-backtested action)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import math
import os

# Contribution weights. They sum to 50 so a fully-aligned, maximum-strength bar
# reaches exactly 100 and its mirror reaches exactly 0.
W_FLOW = 20.0
W_HTF = 18.0
W_PRICE = 12.0
DIVERGENCE_PENALTY = 16.0


@dataclass
class CvdParams:
    reset_period: str = "day"      # "none" | "day" | "week" | "month"
    smooth_len: int = 5
    slope_len: int = 3
    htf_minutes: int = 60          # higher timeframe for the flow confirmation
    ema_len: int = 13              # price filter
    stdev_len: int = 30            # normalization window for slope strength
    atr_len: int = 14
    min_conviction: float = 55.0
    use_early: bool = True
    early_slack: float = 8.0
    stop_atr: float = 1.5          # initial stop distance, in ATRs
    target_r: float = 2.0          # target as a multiple of the stop distance
    cooldown_bars: int = 3         # bars to stand down after any exit
    exit_on_flip: bool = True      # close when the flow regime flips against us

    @classmethod
    def from_env(cls) -> "CvdParams":
        return cls(
            reset_period=os.environ.get("CVD_RESET_PERIOD", "day").lower(),
            smooth_len=int(os.environ.get("CVD_SMOOTH_LEN", "5")),
            slope_len=int(os.environ.get("CVD_SLOPE_LEN", "3")),
            htf_minutes=int(os.environ.get("CVD_HTF_MINUTES", "60")),
            ema_len=int(os.environ.get("CVD_EMA_LEN", "13")),
            stdev_len=int(os.environ.get("CVD_STDEV_LEN", "30")),
            atr_len=int(os.environ.get("CVD_ATR_LEN", "14")),
            min_conviction=float(os.environ.get("CVD_MIN_CONVICTION", "55")),
            use_early=os.environ.get("CVD_USE_EARLY", "true").lower() == "true",
            early_slack=float(os.environ.get("CVD_EARLY_SLACK", "8")),
            stop_atr=float(os.environ.get("CVD_STOP_ATR", "1.5")),
            target_r=float(os.environ.get("CVD_TARGET_R", "2.0")),
            cooldown_bars=int(os.environ.get("CVD_COOLDOWN_BARS", "3")),
            exit_on_flip=os.environ.get("CVD_EXIT_ON_FLIP", "true").lower() == "true",
        )


# ─────────────────────────────────────────────────────────────────────────────
# bar helpers — tolerant of every bar dict shape used across this codebase
# ─────────────────────────────────────────────────────────────────────────────
def _bar_val(bar: dict, *keys, default=0.0) -> float:
    for k in keys:
        v = bar.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _bar_dt(bar: dict, idx: int) -> Optional[datetime]:
    raw = (bar.get("date") or bar.get("begins_at") or bar.get("timestamp")
           or bar.get("t") or bar.get("time"))
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        # seconds or milliseconds since epoch
        secs = float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    s = str(raw).strip().replace("Z", "+00:00")
    for parse in (datetime.fromisoformat,):
        try:
            dt = parse(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return None


def _reset_key(dt: Optional[datetime], period: str) -> Optional[str]:
    """Bucket label whose change marks a CVD reset. None => never reset."""
    if dt is None or period in ("none", ""):
        return None
    if period == "day":
        return dt.strftime("%Y-%m-%d")
    if period == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]}"
    if period == "month":
        return dt.strftime("%Y-%m")
    return None


def _htf_key(dt: Optional[datetime], htf_minutes: int) -> Optional[str]:
    """Bucket label for the higher timeframe. Timestamp-floored, so it is
    correct on any chart timeframe (this is the BUG 1 fix)."""
    if dt is None or htf_minutes <= 0:
        return None
    epoch_min = int(dt.timestamp() // 60)
    return str(epoch_min // htf_minutes)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _stdev(window: list) -> float:
    n = len(window)
    if n < 2:
        return 0.0
    mean = sum(window) / n
    var = sum((v - mean) ** 2 for v in window) / (n - 1)
    return math.sqrt(var) if var > 0 else 0.0


def _htf_same_session_slope(htf_closed: list, slope_len: int) -> Optional[float]:
    """Slope of the completed-HTF-bucket series, measured only between buckets
    belonging to the SAME reset session. Prefers the full slope_len lag and
    walks the lag down to 1 when the session is young. None => no same-session
    comparison is available yet."""
    if len(htf_closed) < 2:
        return None
    latest_key, latest_val = htf_closed[-1]
    for lag in range(slope_len, 0, -1):
        if len(htf_closed) > lag and htf_closed[-1 - lag][0] == latest_key:
            return latest_val - htf_closed[-1 - lag][1]
    return None


def bar_delta(high: float, low: float, close: float, volume: float) -> float:
    """Bar-range delta PROXY — see the module docstring's disclosure. Identical
    to the submitted Pine script's formula."""
    rng = high - low
    if rng <= 0:
        return 0.0
    return volume * ((close - low) - (high - close)) / rng


# ─────────────────────────────────────────────────────────────────────────────
# core
# ─────────────────────────────────────────────────────────────────────────────
def compute_series(bars: list, p: CvdParams = None) -> dict:
    """Full walk-forward evaluation. Causal: bar i uses only bars 0..i, and the
    HTF confirmation uses only *completed* HTF buckets (the non-repainting
    equivalent of request.security(..., expr[1], lookahead_on) in Pine).

    Returns per-bar arrays plus the terminal position state.
    """
    p = p or CvdParams.from_env()
    n = len(bars)
    out_keys = ("cvd", "cvd_smooth", "cvd_slope", "flow_n", "htf_n", "price_n",
                "score", "regime", "atr", "event", "live_signal", "state_dir",
                "bias")
    out = {k: [None] * n for k in out_keys}
    trades: list = []
    if n == 0:
        return {**out, "trades": trades, "in_pos": False, "direction": None,
                "entry_price": None, "stop_price": None, "target_price": None}

    # rolling state
    cvd = 0.0
    ema_cvd: Optional[float] = None
    ema_px: Optional[float] = None
    atr: Optional[float] = None
    prev_close: Optional[float] = None
    prev_reset_key: Optional[str] = None
    bars_since_reset = 0

    smooth_hist: list = []      # cvdS history (for the chart-TF slope)
    slope_hist: list = []       # cvd_slope history (for stdev normalization)
    # (reset_key, smoothed CVD) at the close of each COMPLETED HTF bucket. The
    # reset_key is carried so an HTF slope is never measured ACROSS a CVD reset
    # (see the same-session rule below).
    htf_closed: list = []
    htf_slope_hist: list = []
    cur_htf_key: Optional[str] = None
    cur_htf_last_smooth: Optional[float] = None
    cur_htf_reset_key: Optional[str] = None

    # position state
    in_pos = False
    direction: Optional[str] = None       # "long" | "short"
    entry_price: Optional[float] = None
    entry_idx: Optional[int] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    cooldown = 0

    k_ema_cvd = 2.0 / (p.smooth_len + 1.0)
    k_ema_px = 2.0 / (p.ema_len + 1.0)

    for i, bar in enumerate(bars):
        high = _bar_val(bar, "high", "h", "high_price")
        low = _bar_val(bar, "low", "l", "low_price")
        close = _bar_val(bar, "close", "c", "close_price")
        volume = _bar_val(bar, "volume", "v")
        dt = _bar_dt(bar, i)

        # ── CVD with reset ────────────────────────────────────────────────
        rkey = _reset_key(dt, p.reset_period)
        do_reset = rkey is not None and prev_reset_key is not None and rkey != prev_reset_key
        prev_reset_key = rkey if rkey is not None else prev_reset_key

        d = bar_delta(high, low, close, volume)
        if do_reset:
            cvd = d
            # BUG 4 FIX: re-seed the smoothing state so the new session does not
            # inherit the prior session's CVD level.
            ema_cvd = d
            smooth_hist = []
            slope_hist = []
            bars_since_reset = 1
        else:
            cvd = cvd + d
            ema_cvd = d if ema_cvd is None else ema_cvd + k_ema_cvd * (cvd - ema_cvd)
            bars_since_reset += 1
        if ema_cvd is None:
            ema_cvd = cvd
        cvd_s = ema_cvd
        smooth_hist.append(cvd_s)

        # ── chart-timeframe flow slope ────────────────────────────────────
        cvd_slope = 0.0
        if len(smooth_hist) > p.slope_len:
            cvd_slope = cvd_s - smooth_hist[-1 - p.slope_len]
        slope_hist.append(cvd_slope)
        sd_slope = _stdev(slope_hist[-p.stdev_len:])
        flow_n = _clamp(cvd_slope / sd_slope, -1.0, 1.0) if sd_slope > 0 else 0.0

        # ── HTF flow slope, computed IN HTF SPACE (BUG 1 fix) ─────────────
        # Only *completed* HTF buckets are ever read, so this is causal and
        # non-repainting by construction. Computed natively from timestamps
        # rather than via request.security() — that call was the source of
        # BUG 1, and doing it natively also guarantees chart/code parity.
        hkey = _htf_key(dt, p.htf_minutes)
        if hkey is not None:
            if cur_htf_key is None:
                cur_htf_key = hkey
            elif hkey != cur_htf_key:
                # the previous HTF bucket just CLOSED — only now is it usable.
                if cur_htf_last_smooth is not None:
                    htf_closed.append((cur_htf_reset_key, cur_htf_last_smooth))
                    s = _htf_same_session_slope(htf_closed, p.slope_len)
                    if s is not None:
                        htf_slope_hist.append(s)
                cur_htf_key = hkey
            cur_htf_last_smooth = cvd_s
            cur_htf_reset_key = rkey

        # Same-session rule: an HTF slope measured across a CVD reset compares
        # post-reset CVD against pre-reset CVD, which is meaningless. Rather
        # than blank the HTF read for the first slope_len HTF bars of every
        # session (with a 60m HTF that would be the first ~3 hours — most of
        # the tradeable day), fall back to the longest lag available INSIDE the
        # current session, minimum 1. If no prior same-session bucket has
        # closed yet, there is no HTF confirmation and no aligned signal.
        htf_slope = 0.0
        have_htf = False
        if htf_closed and htf_closed[-1][0] == rkey:
            s = _htf_same_session_slope(htf_closed, p.slope_len)
            if s is not None:
                htf_slope, have_htf = s, True
        sd_htf = _stdev(htf_slope_hist[-p.stdev_len:])
        htf_n = (_clamp(htf_slope / sd_htf, -1.0, 1.0)
                 if (have_htf and sd_htf > 0) else 0.0)

        # ── price filter + ATR ────────────────────────────────────────────
        ema_px = close if ema_px is None else ema_px + k_ema_px * (close - ema_px)
        tr = (high - low) if prev_close is None else max(
            high - low, abs(high - prev_close), abs(low - prev_close))
        atr = tr if atr is None else atr + (tr - atr) / p.atr_len
        prev_close = close
        price_n = _clamp((close - ema_px) / atr, -1.0, 1.0) if atr and atr > 0 else 0.0

        # ── regime + conviction (BUG 2 + BUG 3 fix) ───────────────────────
        aligned_bull = flow_n > 0 and price_n > 0 and htf_n > 0
        aligned_bear = flow_n < 0 and price_n < 0 and htf_n < 0
        divergence = (flow_n > 0 and price_n < 0) or (flow_n < 0 and price_n > 0)

        score = 50.0 + W_FLOW * flow_n + W_HTF * htf_n + W_PRICE * price_n
        if divergence:
            score -= DIVERGENCE_PENALTY
        score = _clamp(score, 0.0, 100.0)

        regime = ("ALIGNED BULL" if aligned_bull else
                  "ALIGNED BEAR" if aligned_bear else
                  "DIVERGENCE" if divergence else "NEUTRAL")

        # BUG 4 FIX (second half): the chart-TF slope straddles the session
        # boundary for its first slope_len bars, and the HTF confirmation needs
        # slope_len+1 completed buckets. No signal before both are honest.
        warm = (bars_since_reset > p.slope_len
                and have_htf
                and len(slope_hist) > p.slope_len)

        put_thresh = 100.0 - p.min_conviction
        call_ok = warm and aligned_bull and score >= p.min_conviction
        put_ok = warm and aligned_bear and score <= put_thresh
        early_call = (warm and p.use_early and not call_ok and flow_n > 0
                      and htf_n > 0 and score >= p.min_conviction - p.early_slack)
        early_put = (warm and p.use_early and not put_ok and flow_n < 0
                     and htf_n < 0 and score <= put_thresh + p.early_slack)

        bias = ("CALL" if call_ok else "PUT" if put_ok else
                "EARLY CALL" if early_call else "EARLY PUT" if early_put else "WAIT")

        want_long = call_ok or early_call
        want_short = put_ok or early_put

        out["cvd"][i] = cvd
        out["cvd_smooth"][i] = cvd_s
        out["cvd_slope"][i] = cvd_slope
        out["flow_n"][i] = round(flow_n, 4)
        out["htf_n"][i] = round(htf_n, 4)
        out["price_n"][i] = round(price_n, 4)
        out["score"][i] = round(score, 2)
        out["regime"][i] = regime
        out["atr"][i] = atr
        out["bias"][i] = bias

        # ── position state machine (BUG 5 + BUG 7 fix) ────────────────────
        if in_pos:
            hit_stop = (close <= stop_price) if direction == "long" else (close >= stop_price)
            hit_target = (close >= target_price) if direction == "long" else (close <= target_price)
            flipped = p.exit_on_flip and (
                (direction == "long" and want_short) or
                (direction == "short" and want_long))

            event = None
            if hit_stop:
                event = "EXIT_STOP"
            elif hit_target:
                event = "EXIT_TARGET"
            elif flipped:
                event = "EXIT_FLIP"

            if event:
                pnl = ((close - entry_price) / entry_price if direction == "long"
                       else (entry_price - close) / entry_price)
                trades.append({
                    "direction": direction, "entry_idx": entry_idx, "exit_idx": i,
                    "entry_price": entry_price, "exit_price": close,
                    "stop_price": stop_price, "target_price": target_price,
                    "pnl_pct": round(pnl * 100, 4), "exit_reason": event,
                    "bars_held": i - entry_idx,
                })
                out["event"][i] = event
                # exit of a LONG closes it; exit of a SHORT emits nothing.
                if direction == "long":
                    out["live_signal"][i] = "SELL"
                in_pos = False
                direction = None
                entry_price = entry_idx = stop_price = target_price = None
                cooldown = p.cooldown_bars
                continue
            out["state_dir"][i] = direction
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        if want_long and atr and atr > 0:
            in_pos, direction, entry_price, entry_idx = True, "long", close, i
            stop_price = close - p.stop_atr * atr
            target_price = close + p.stop_atr * atr * p.target_r
            out["event"][i] = "ENTER_LONG"
            out["live_signal"][i] = "BUY"
            out["state_dir"][i] = "long"
        elif want_short and atr and atr > 0:
            in_pos, direction, entry_price, entry_idx = True, "short", close, i
            stop_price = close + p.stop_atr * atr
            target_price = close - p.stop_atr * atr * p.target_r
            out["event"][i] = "ENTER_SHORT"
            out["live_signal"][i] = "SELL"
            out["state_dir"][i] = "short"

    return {**out, "trades": trades, "in_pos": in_pos, "direction": direction,
            "entry_price": entry_price, "stop_price": stop_price,
            "target_price": target_price}


def analyze(symbol: str, bars: list, p: CvdParams = None) -> dict:
    """On-demand analysis of the LATEST bar — same convention as
    orb_engine.analyze() / druck_engine.analyze() / breakout_engine.analyze().
    Real bars only; never fabricates a reading when data is short."""
    p = p or CvdParams.from_env()
    # need enough bars for the ATR/stdev windows AND for slope_len+1 completed
    # HTF buckets to exist at all.
    min_bars = max(p.stdev_len, p.atr_len, p.ema_len) + p.slope_len + 1
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    if out["score"][last] is None:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars), "min_bars": min_bars}

    return {
        "symbol": symbol.upper(),
        "status": "success",
        "price": _bar_val(bars[-1], "close", "c", "close_price"),
        "regime": out["regime"][last],
        "conviction": out["score"][last],
        "bias": out["bias"][last],
        "components": {
            "flow_n": out["flow_n"][last],
            "htf_n": out["htf_n"][last],
            "price_n": out["price_n"][last],
        },
        "cvd": out["cvd"][last],
        "cvd_smooth": out["cvd_smooth"][last],
        "atr": out["atr"][last],
        "event": out["event"][last],
        "signal": out["live_signal"][last],
        "position": {
            "in_position": out["in_pos"],
            "direction": out["direction"],
            "entry_price": out["entry_price"],
            "stop_price": out["stop_price"],
            "target_price": out["target_price"],
        },
        "params": {
            "reset_period": p.reset_period, "smooth_len": p.smooth_len,
            "slope_len": p.slope_len, "htf_minutes": p.htf_minutes,
            "ema_len": p.ema_len, "min_conviction": p.min_conviction,
            "stop_atr": p.stop_atr, "target_r": p.target_r,
            "cooldown_bars": p.cooldown_bars,
        },
        "disclosure": (
            "CVD is a bar-range proxy computed from OHLCV, not true bid/ask "
            "delta. Stop/target model the underlying's directional move only — "
            "option premium, leverage, theta and spread are NOT modelled."
        ),
    }
