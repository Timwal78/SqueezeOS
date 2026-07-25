"""
mm_intel_engine.py -- Python port of indicators/SML_Market_Maker_Intelligence_v4.pine.
Pine is a visual of this math, this module is the single source of truth --
same convention as imo_engine.py/druck_engine.py/sr_matrix_engine.py.

The Kalman inventory filter + HJB Riccati hedge-rate math here is a near-
exact match to logic already live server-side in gamma_flow_engine.py's
embedded "MM Intel v3" section (_update_mm_intel()/_update_gamma_pressure()),
which had no Pine visual companion before this build. This module is an
INDEPENDENT port of the Pine script (not a wrapper around gamma_flow_engine.py)
so it can be walk-forward backtested without touching that already-live async
engine -- same "add, don't risk existing code" pattern used for
gamma_flow_engine.detect_pin_risk().

Gamma-pressure/strike-magnet section is a disclosed round-number/volume PROXY
for dealer gamma (see the Pine script's own Section 5 comment), not a real
options-chain OI calculation -- same proxy class as SML_Gamma_Pin_v6.pine's
grid, answering a different question (ongoing inventory-hedge stress here,
near-expiry pin risk there).

ta.percentrank(source, length) in Pine ranks the current value against the
trailing `length` bars (length+1 values including current); ta.sma/ta.stdev
need `length` full bars of history before returning a real number (na
before that). Both are reproduced with that exact causal windowing here --
no lookahead.

One real bug caught and fixed during the port (documented here rather than
silently corrected, same convention as druck_engine.py's crossover fix): the
pasted script's invalidation state machine tested a freshly-entered thesis's
"resolved" exit condition using the SAME bar and the SAME sign that just
triggered entry (a long enters because inv_z < -z_critical, which already
satisfies its own "inv_z <= 0" resolve check) -- every entry self-resolved
on the same bar it opened, so the thesis could never actually persist to a
later bar. Fixed in compute_series() below by checking exits first against
state carried in from the prior bar, using the correct recovery sign. See
that function's Section 6B comment for detail.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os


@dataclass
class MMIntelParams:
    lam: float = 0.15            # Pine's "lambda" (reserved word in Python)
    q_process: float = 0.5
    r_measurement: float = 1.0
    inv_lookback: int = 75
    c_inv: float = 0.1
    kappa_impact: float = 0.5
    gamma_term: float = 1.0
    sensitivity: str = "Normal"   # Strict | Normal | Sensitive | Aggressive
    man_z_crit: float = 0.0
    man_gamma: float = 0.0
    inv_stop_mult: float = 1.0
    structural_decay: float = 0.98
    is_crypto: bool = False

    @classmethod
    def from_env(cls) -> "MMIntelParams":
        return cls(
            lam=float(os.environ.get("MM_INTEL_LAMBDA", "0.15")),
            q_process=float(os.environ.get("MM_INTEL_Q", "0.5")),
            r_measurement=float(os.environ.get("MM_INTEL_R", "1.0")),
            inv_lookback=int(os.environ.get("MM_INTEL_INV_LOOKBACK", "75")),
            c_inv=float(os.environ.get("MM_INTEL_C_INV", "0.1")),
            kappa_impact=float(os.environ.get("MM_INTEL_KAPPA", "0.5")),
            gamma_term=float(os.environ.get("MM_INTEL_GAMMA_TERM", "1.0")),
            sensitivity=os.environ.get("MM_INTEL_SENSITIVITY", "Normal"),
            inv_stop_mult=float(os.environ.get("MM_INTEL_STOP_MULT", "1.0")),
            structural_decay=float(os.environ.get("MM_INTEL_STRUCT_DECAY", "0.98")),
            is_crypto=os.environ.get("MM_INTEL_IS_CRYPTO", "false").strip().lower() == "true",
        )

    @property
    def z_critical(self) -> float:
        if self.man_z_crit > 0:
            return self.man_z_crit
        return {"Strict": 2.5, "Normal": 2.0, "Sensitive": 1.7, "Aggressive": 1.4}.get(self.sensitivity, 2.0)

    @property
    def gamma_thresh(self) -> float:
        if self.man_gamma > 0:
            return self.man_gamma
        return {"Strict": 0.8, "Normal": 0.5, "Sensitive": 0.35, "Aggressive": 0.2}.get(self.sensitivity, 0.5)

    @property
    def stress_mult(self) -> float:
        return {"Strict": 0.6, "Normal": 0.55, "Sensitive": 0.5, "Aggressive": 0.45}.get(self.sensitivity, 0.55)


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


def _sma(values: list, i: int, period: int):
    if i + 1 < period:
        return None
    window = values[i - period + 1:i + 1]
    return sum(window) / period


def _stdev(values: list, i: int, period: int):
    if i + 1 < period:
        return None
    window = values[i - period + 1:i + 1]
    m = sum(window) / period
    var = sum((x - m) ** 2 for x in window) / period
    return math.sqrt(var)


def _percentrank(values: list, i: int, length: int):
    """Pine ta.percentrank(source, length): rank of the current value against
    the trailing `length` bars, as a 0-100 percentage. Needs length+1 total
    values (current + length prior) before returning a real number."""
    if i + 1 < length + 1:
        return None
    window = values[i - length:i + 1]
    cur = window[-1]
    count_less = sum(1 for v in window[:-1] if v < cur)
    return (count_less / length) * 100.0


def _atr_series(bars: list, period: int = 14) -> list:
    """Wilder RMA-smoothed ATR, seeded with a simple average of the first
    `period` true ranges -- matches Pine's ta.atr() convention."""
    n = len(bars)
    trs = [0.0] * n
    prev_close = None
    for i, b in enumerate(bars):
        h = _bar_val(b, "high", "h")
        l = _bar_val(b, "low", "l")
        c = _bar_val(b, "close", "c")
        tr = (h - l) if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs[i] = tr
        prev_close = c
    atr = [None] * n
    rma = None
    for i in range(n):
        if i + 1 < period:
            continue
        if rma is None:
            rma = sum(trs[i - period + 1:i + 1]) / period
        else:
            rma = (rma * (period - 1) + trs[i]) / period
        atr[i] = rma
    return atr


def _strike_increment(close: float, is_crypto: bool) -> float:
    if is_crypto:
        if close > 10000:
            return 500.0
        if close > 1000:
            return 100.0
        if close > 100:
            return 10.0
        if close > 10:
            return 1.0
        if close > 1:
            return 0.1
        return 0.01
    if close > 500:
        return 5.0
    if close > 100:
        return 1.0
    return 0.5


def compute_series(bars: list, p: MMIntelParams = None) -> dict:
    p = p or MMIntelParams.from_env()
    n = len(bars)
    closes = [_bar_val(b, "close", "c") for b in bars]
    opens = [_bar_val(b, "open", "o") for b in bars]
    highs = [_bar_val(b, "high", "h") for b in bars]
    lows = [_bar_val(b, "low", "l") for b in bars]
    volumes = [_bar_val(b, "volume", "v") for b in bars]

    # ── Section 2: Kalman-filtered inventory (stateful walk-forward) ──
    inventory_estimate = [0.0] * n
    inventory_variance = [1.0] * n
    inv_est, inv_var = 0.0, 1.0
    mm_position = [0.0] * n
    for i in range(n):
        range_val = highs[i] - lows[i] + 0.001
        buy_flow = volumes[i] * (closes[i] - opens[i]) / range_val if closes[i] > opens[i] else 0.0
        sell_flow = volumes[i] * (opens[i] - closes[i]) / range_val if closes[i] < opens[i] else 0.0
        net_flow = buy_flow - sell_flow
        mm_position[i] = -net_flow

        pred_inv = inv_est * (1.0 - p.lam)
        pred_var = inv_var + p.q_process * p.q_process
        gain = pred_var / (pred_var + p.r_measurement * p.r_measurement)
        inv_est = pred_inv + gain * (mm_position[i] - pred_inv)
        inv_var = (1.0 - gain) * pred_var
        inventory_estimate[i] = inv_est
        inventory_variance[i] = inv_var

    inv_z = [0.0] * n
    for i in range(n):
        mean = _sma(inventory_estimate, i, p.inv_lookback)
        std = _stdev(inventory_estimate, i, p.inv_lookback)
        inv_z[i] = (inventory_estimate[i] - mean) / std if (std and std > 0) else 0.0
    abs_inv_z = [abs(z) for z in inv_z]

    stress_building = [False] * n
    for i in range(n):
        prev = inv_z[i - 5] if i >= 5 else 0.0
        stress_building[i] = abs_inv_z[i] > 1.0 and abs_inv_z[i] > abs(prev)

    # ── Section 3: flow quality ──
    flow_quality = [0.3] * n
    absorption = [False] * n
    conviction_flow = [False] * n
    for i in range(n):
        vol_avg = _sma(volumes, i, 20)
        vol_std_val = _stdev(volumes, i, 20)
        vol_z = (volumes[i] - vol_avg) / vol_std_val if (vol_avg and vol_std_val and vol_std_val > 0) else 0.0
        range_val = highs[i] - lows[i] + 0.001
        body_pct = abs(closes[i] - opens[i]) / range_val if range_val > 0 else 0.0
        absorption[i] = vol_z > 1.5 and body_pct < 0.3
        conviction_flow[i] = vol_z > 1.5 and body_pct > 0.6
        flow_quality[i] = 0.9 if absorption[i] else (0.8 if conviction_flow[i] else (0.5 if vol_z > 0.5 else 0.3))

    vol_avg_series = [_sma(volumes, i, 20) for i in range(n)]

    # ── Section 4: HJB optimal control ──
    atr_val = _atr_series(bars, 14)
    riccati_p = math.sqrt(p.c_inv * p.kappa_impact)
    optimal_hedge_z = [-(1.0 / p.kappa_impact) * riccati_p * inv_z[i] for i in range(n)]
    optimal_hedge_rate = [optimal_hedge_z[i] * (atr_val[i] or 0.0) for i in range(n)]

    # ── Section 5: gamma exposure synthesis (disclosed proxy, see module docstring) ──
    atr_pct = [(atr_val[i] / closes[i]) if (atr_val[i] is not None and closes[i] > 0) else 0.001 for i in range(n)]
    vol_regime = [0.0] * n
    total_gamma_pressure = [0.0] * n
    nearest_strike = [0.0] * n
    near_strike_flags = [False] * n
    for i in range(n):
        av = atr_val[i] or 0.0
        inc = _strike_increment(closes[i], p.is_crypto)
        strike_below = math.floor(closes[i] / inc) * inc
        strike_above = strike_below + inc
        dist_below = abs(closes[i] - strike_below)
        dist_above = abs(closes[i] - strike_above)
        nearest = strike_below if dist_below < dist_above else strike_above
        dist_to_strike = min(dist_below, dist_above)
        nearest_strike[i] = nearest

        pin_range = max(av * 0.5, inc * 0.55)
        near_strike = dist_to_strike < pin_range
        near_strike_flags[i] = near_strike

        vol_ratio = (volumes[i] / vol_avg_series[i]) if (vol_avg_series[i] and vol_avg_series[i] > 0) else 1.0
        gamma_intensity = vol_ratio if near_strike else 0.0

        second_strike = strike_above if dist_below < dist_above else strike_below
        dist_second = abs(closes[i] - second_strike)
        near_second = dist_second < pin_range * 1.5
        gamma_intensity_2 = vol_ratio * 0.5 if near_second else 0.0
        combined_gamma = gamma_intensity + gamma_intensity_2

        pr = _percentrank(atr_pct, i, 50)
        vr = (pr / 100.0) if pr is not None else 0.5
        vol_regime[i] = vr
        dealer_gamma_proxy = (combined_gamma / (atr_pct[i] + 0.001)) if atr_pct[i] > 0 else 0.0
        total_gamma_pressure[i] = dealer_gamma_proxy * abs_inv_z[i] * (0.5 + vr)

    # ── Section 6: critical events + edge-triggered signals ──
    critical_long = [inv_z[i] > p.z_critical for i in range(n)]
    critical_short = [inv_z[i] < -p.z_critical for i in range(n)]
    gamma_critical = [total_gamma_pressure[i] > p.gamma_thresh for i in range(n)]
    control_stress = [abs_inv_z[i] * (1.0 + total_gamma_pressure[i]) for i in range(n)]
    control_action = [(critical_long[i] or critical_short[i]) and gamma_critical[i] for i in range(n)]

    long_signal = [False] * n
    short_signal = [False] * n
    for i in range(n):
        crit_short_lag = (critical_short[i - 1] and gamma_critical[i - 1]) if i >= 1 else False
        crit_long_lag = (critical_long[i - 1] and gamma_critical[i - 1]) if i >= 1 else False
        long_signal[i] = critical_short[i] and gamma_critical[i] and not crit_short_lag
        short_signal[i] = critical_long[i] and gamma_critical[i] and not crit_long_lag

    signal_confidence = [min(control_stress[i] * 20.0 * flow_quality[i], 99.0) for i in range(n)]
    stress_warning = [False] * n
    for i in range(n):
        stress_warning[i] = stress_building[i] and not control_action[i] and abs_inv_z[i] > p.z_critical * p.stress_mult

    # ── Section 6B: invalidation state machine (sequential, carries state) ──
    # BUG FOUND while porting, fixed here (not in the Pine script -- kept as
    # submitted/visual, this engine is the source of truth): the pasted
    # script sets active_direction/active_invalidation from long_signal/
    # short_signal, then IMMEDIATELY tests the SAME bar's inv_z for
    # "resolved" using the SAME sign that just triggered entry (a long
    # enters because inv_z < -z_critical, which already satisfies its own
    # "inv_z <= 0" resolve check). Pine's top-to-bottom same-bar execution
    # means every entry self-resolves on the very same bar it opens --
    # active_direction/active_invalidation can never actually persist to a
    # later bar in the original script. Fixed by checking exits FIRST using
    # state carried in from the PRIOR bar (against the CORRECT recovery
    # sign -- a long thesis resolves when inv_z recovers back UP to >= 0,
    # not <= 0), then processing a fresh entry for the current bar -- same
    # "entry now, resolve/stop on a later bar" convention every other engine
    # in this repo uses (see breakout_engine.py). Entry is also gated to
    # "flat only" (one position at a time), matching sr_matrix_engine.py.
    active_direction = [0] * n   # 1 long thesis, -1 short thesis, 0 none
    active_invalidation = [None] * n
    live_signal = [None] * n     # BUY / SELL / EXIT_STOP / EXIT_RESOLVED, matching iam_executor action naming
    exit_direction = [None] * n  # direction (1/-1) that was closing on an EXIT_* bar -- active_direction is
                                 # already reset to 0 by the time an exit fires, so a consumer (the scanner)
                                 # needs this to know whether a long or a short thesis just closed.
    direction, invalidation = 0, None
    for i in range(n):
        if direction == 1 and (closes[i] < invalidation or inv_z[i] >= 0):
            live_signal[i] = "EXIT_STOP" if closes[i] < invalidation else "EXIT_RESOLVED"
            exit_direction[i] = 1
            direction, invalidation = 0, None
        elif direction == -1 and (closes[i] > invalidation or inv_z[i] <= 0):
            live_signal[i] = "EXIT_STOP" if closes[i] > invalidation else "EXIT_RESOLVED"
            exit_direction[i] = -1
            direction, invalidation = 0, None

        if direction == 0 and long_signal[i]:
            invalidation = closes[i] - (atr_val[i] or 0.0) * p.inv_stop_mult
            direction = 1
            live_signal[i] = "BUY"
        elif direction == 0 and short_signal[i]:
            invalidation = closes[i] + (atr_val[i] or 0.0) * p.inv_stop_mult
            direction = -1
            live_signal[i] = "SELL"

        active_direction[i] = direction
        active_invalidation[i] = invalidation

    # ── Section 7: dual-mode price targets ──
    tactical_target = [closes[i] + optimal_hedge_z[i] * (atr_val[i] or 0.0) * 0.5 for i in range(n)]

    structural_imbalance = [0.0] * n
    struct_acc = 0.0
    for i in range(n):
        norm_flow = (mm_position[i] * -1.0 / vol_avg_series[i]) if (vol_avg_series[i] and vol_avg_series[i] > 0) else 0.0
        struct_acc = struct_acc * p.structural_decay + norm_flow
        structural_imbalance[i] = struct_acc

    structural_target = [0.0] * n
    for i in range(n):
        s_mean = _sma(structural_imbalance, i, p.inv_lookback)
        s_std = _stdev(structural_imbalance, i, p.inv_lookback)
        struct_z = (structural_imbalance[i] - s_mean) / s_std if (s_std and s_std > 0) else 0.0
        structural_target[i] = closes[i] + (-struct_z * (atr_val[i] or 0.0) * p.gamma_term)

    # ── MM pain / damage ──
    current_damage = [p.c_inv * inv_z[i] ** 2 + p.kappa_impact * optimal_hedge_z[i] ** 2 for i in range(n)]
    damage_rising = [False] * n
    for i in range(n):
        dmg_sma = _sma(current_damage, i, 10)
        damage_rising[i] = dmg_sma is not None and current_damage[i] > dmg_sma

    return {
        "inv_z": inv_z, "abs_inv_z": abs_inv_z,
        "total_gamma_pressure": total_gamma_pressure,
        "critical_long": critical_long, "critical_short": critical_short,
        "gamma_critical": gamma_critical, "control_action": control_action,
        "long_signal": long_signal, "short_signal": short_signal,
        "signal_confidence": signal_confidence, "stress_warning": stress_warning,
        "active_direction": active_direction, "active_invalidation": active_invalidation,
        "live_signal": live_signal, "exit_direction": exit_direction,
        "nearest_strike": nearest_strike, "near_strike": near_strike_flags,
        "tactical_target": tactical_target, "structural_target": structural_target,
        "damage_rising": damage_rising, "atr": atr_val,
    }


def analyze(symbol: str, bars: list, p: MMIntelParams = None) -> dict:
    """On-demand analysis of the LATEST bar -- same convention as
    orb_engine.analyze()/breakout_engine.analyze()/sr_matrix_engine.analyze()."""
    p = p or MMIntelParams.from_env()
    min_bars = max(p.inv_lookback, 75) + 5
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    return {
        "symbol": symbol.upper(), "status": "success",
        "price": _bar_val(bars[-1], "close", "c"),
        "inv_z": out["inv_z"][last],
        "gamma_pressure": out["total_gamma_pressure"][last],
        "gamma_critical": out["gamma_critical"][last],
        "control_action": out["control_action"][last],
        "signal": out["live_signal"][last],
        "confidence": out["signal_confidence"][last],
        "nearest_strike": out["nearest_strike"][last],
        "active_direction": out["active_direction"][last],
        "active_invalidation": out["active_invalidation"][last],
        "exit_direction": out["exit_direction"][last],
        "params": {"z_critical": p.z_critical, "gamma_thresh": p.gamma_thresh, "sensitivity": p.sensitivity},
    }
