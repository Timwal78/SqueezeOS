"""
SML Market Maker Intelligence™ v4 — Python Execution Engine Port
═══════════════════════════════════════════════════════════════════════════════
Direct Python translation of SML Market Maker Intelligence™ v4 (PineScript v6)

Computes:
  • Kalman-Filtered Inventory Estimation (separate Q and R noise parameters)
  • Rolling 75-bar Inventory Z-score (inv_z)
  • Institutional Flow Quality Filter (Absorption vs Conviction Flow)
  • HJB Optimal Control (Riccati Steady-State Solution for Hedge Rate)
  • Gamma Pressure Synthesis (Dynamic Strike Grid & Dealer Gamma Proxy)
  • Critical Signals (Long/Short Forced Hedge Signals)
  • Invalidation Tracking (ATR-based Stop/Invalidation Level)

Author: ScriptMasterLabs™ / SqueezeOS Pro
"""

import math
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("MM-V4")


class KalmanInventoryFilter:
    """
    Kalman-Filtered Inventory Estimation with separate process noise (Q)
    and measurement noise (R).
    """

    def __init__(
        self,
        lam: float = 0.15,
        q_process: float = 0.5,
        r_measurement: float = 1.0,
        inv_lookback: int = 75,
    ):
        self.lam = lam
        self.q_process = q_process
        self.r_measurement = r_measurement
        self.inv_lookback = inv_lookback

        self.inventory_estimate = 0.0
        self.inventory_variance = 1.0
        self.history: List[float] = []

    def update(self, open_p: float, high_p: float, low_p: float, close_p: float, volume: float) -> Tuple[float, float]:
        range_val = (high_p - low_p) + 0.001
        if close_p > open_p:
            buy_flow = volume * (close_p - open_p) / range_val
            sell_flow = 0.0
        elif close_p < open_p:
            buy_flow = 0.0
            sell_flow = volume * (open_p - close_p) / range_val
        else:
            buy_flow = 0.0
            sell_flow = 0.0

        net_flow = buy_flow - sell_flow
        mm_position = -net_flow

        # Kalman step
        pred_inv = self.inventory_estimate * (1.0 - self.lam)
        pred_var = self.inventory_variance + (self.q_process ** 2)
        kalman_gain = pred_var / (pred_var + (self.r_measurement ** 2))

        self.inventory_estimate = pred_inv + kalman_gain * (mm_position - pred_inv)
        self.inventory_variance = (1.0 - kalman_gain) * pred_var

        self.history.append(self.inventory_estimate)
        if len(self.history) > 500:
            self.history.pop(0)

        # Compute rolling Z-score over inv_lookback
        if len(self.history) >= self.inv_lookback:
            window = self.history[-self.inv_lookback:]
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            std = math.sqrt(var)
            inv_z = (self.inventory_estimate - mean) / std if std > 0 else 0.0
        else:
            inv_z = 0.0

        return self.inventory_estimate, inv_z


class MMv4Engine:
    """
    SML Market Maker Intelligence v4 Engine.
    """

    def __init__(
        self,
        lam: float = 0.15,
        q_process: float = 0.5,
        r_measurement: float = 1.0,
        inv_lookback: int = 75,
        c_inv: float = 0.1,
        kappa_impact: float = 0.5,
        gamma_term: float = 1.0,
        sensitivity: str = "Normal",
        inv_stop_mult: float = 1.0,
    ):
        self.lam = lam
        self.q_process = q_process
        self.r_measurement = r_measurement
        self.inv_lookback = inv_lookback
        self.c_inv = c_inv
        self.kappa_impact = kappa_impact
        self.gamma_term = gamma_term
        self.sensitivity = sensitivity
        self.inv_stop_mult = inv_stop_mult

        # Thresholds based on sensitivity
        if sensitivity == "Strict":
            self.z_critical = 2.5
            self.gamma_thresh = 0.8
        elif sensitivity == "Normal":
            self.z_critical = 2.0
            self.gamma_thresh = 0.5
        elif sensitivity == "Sensitive":
            self.z_critical = 1.7
            self.gamma_thresh = 0.35
        else:  # Aggressive
            self.z_critical = 1.4
            self.gamma_thresh = 0.2

    def analyze(self, symbol: str, bars: List[Dict], is_crypto: bool = False) -> Dict:
        if not bars or len(bars) < 20:
            return {"error": "INSUFFICIENT_BARS", "symbol": symbol}

        opens = [float(b.get("open") or b.get("o") or 0) for b in bars]
        highs = [float(b.get("high") or b.get("h") or 0) for b in bars]
        lows = [float(b.get("low") or b.get("l") or 0) for b in bars]
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars]
        volumes = [float(b.get("volume") or b.get("v") or 0) for b in bars]

        # 1. Kalman Inventory
        kalman = KalmanInventoryFilter(
            lam=self.lam,
            q_process=self.q_process,
            r_measurement=self.r_measurement,
            inv_lookback=self.inv_lookback,
        )

        inv_z_list = []
        inv_est = 0.0
        inv_z = 0.0

        for o, h, l, c, v in zip(opens, highs, lows, closes, volumes):
            inv_est, inv_z = kalman.update(o, h, l, c, v)
            inv_z_list.append(inv_z)

        abs_inv_z = abs(inv_z)

        # 2. Flow Quality Filter (last 20 bars)
        vol_20 = volumes[-20:]
        vol_avg = sum(vol_20) / len(vol_20)
        vol_var = sum((x - vol_avg) ** 2 for x in vol_20) / len(vol_20)
        vol_std = math.sqrt(vol_var)
        curr_vol = volumes[-1]
        vol_z = (curr_vol - vol_avg) / vol_std if (vol_avg > 0 and vol_std > 0) else 0.0

        curr_range = (highs[-1] - lows[-1]) + 0.001
        body_pct = abs(closes[-1] - opens[-1]) / curr_range

        absorption = (vol_z > 1.5) and (body_pct < 0.3)
        conviction_flow = (vol_z > 1.5) and (body_pct > 0.6)

        if absorption:
            flow_quality = 0.9
        elif conviction_flow:
            flow_quality = 0.8
        elif vol_z > 0.5:
            flow_quality = 0.5
        else:
            flow_quality = 0.3

        # 3. HJB Optimal Control (Riccati Solution)
        riccati_p = math.sqrt(self.c_inv * self.kappa_impact)
        optimal_hedge_z = -(1.0 / self.kappa_impact) * riccati_p * inv_z

        # ATR 14
        tr_list = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
        atr_14 = sum(tr_list[-14:]) / 14 if len(tr_list) >= 14 else curr_range

        optimal_hedge_rate = optimal_hedge_z * atr_14

        # 4. Gamma Pressure Synthesis
        last_close = closes[-1]
        if is_crypto:
            if last_close > 10000: strike_increment = 500.0
            elif last_close > 1000: strike_increment = 100.0
            elif last_close > 100: strike_increment = 10.0
            elif last_close > 10: strike_increment = 1.0
            elif last_close > 1: strike_increment = 0.1
            else: strike_increment = 0.01
        else:
            if last_close > 500: strike_increment = 5.0
            elif last_close > 100: strike_increment = 1.0
            elif last_close > 25: strike_increment = 0.5
            else: strike_increment = 0.5

        strike_below = math.floor(last_close / strike_increment) * strike_increment
        strike_above = strike_below + strike_increment
        dist_below = abs(last_close - strike_below)
        dist_above = abs(last_close - strike_above)
        nearest_strike = strike_below if dist_below < dist_above else strike_above
        dist_to_strike = min(dist_below, dist_above)

        atr_pin = atr_14 * 0.5
        min_pin = strike_increment * 0.55
        pin_range = max(atr_pin, min_pin)
        near_strike = dist_to_strike < pin_range

        vol_ratio = curr_vol / vol_avg if vol_avg > 0 else 1.0
        gamma_intensity = vol_ratio if near_strike else 0.0

        second_strike = strike_above if dist_below < dist_above else strike_below
        dist_second = abs(last_close - second_strike)
        near_second = dist_second < (pin_range * 1.5)
        gamma_intensity_2 = (vol_ratio * 0.5) if near_second else 0.0

        combined_gamma = gamma_intensity + gamma_intensity_2

        atr_pct = (atr_14 / last_close) if last_close > 0 else 0.001
        # Percentile rank of atr_pct in last 50 bars
        atr_pct_hist = [(tr / c) if c > 0 else 0.001 for tr, c in zip(tr_list[-50:], closes[-50:])]
        below_count = sum(1 for x in atr_pct_hist if x <= atr_pct)
        vol_regime = (below_count / len(atr_pct_hist)) if atr_pct_hist else 0.5

        dealer_gamma_proxy = combined_gamma / (atr_pct + 0.001)
        total_gamma_pressure = dealer_gamma_proxy * abs_inv_z * (0.5 + vol_regime)

        # 5. Critical Events & Signals
        critical_long = inv_z > self.z_critical
        critical_short = inv_z < -self.z_critical
        gamma_critical = total_gamma_pressure > self.gamma_thresh
        control_stress = abs_inv_z * (1.0 + total_gamma_pressure)
        control_action = (critical_long or critical_short) and gamma_critical

        # Check 1-bar lag for signals
        inv_z_prev = inv_z_list[-2] if len(inv_z_list) >= 2 else 0.0
        crit_short_prev = inv_z_prev < -self.z_critical
        crit_long_prev = inv_z_prev > self.z_critical

        long_signal = critical_short and gamma_critical and not (crit_short_prev and gamma_critical)
        short_signal = critical_long and gamma_critical and not (crit_long_prev and gamma_critical)

        raw_conf = control_stress * 20.0
        signal_confidence = min(raw_conf * flow_quality, 99.0)

        # Invalidation level calculation
        if long_signal:
            invalidation_level = last_close - atr_14 * self.inv_stop_mult
            signal_direction = "BUY"
        elif short_signal:
            invalidation_level = last_close + atr_14 * self.inv_stop_mult
            signal_direction = "SELL"
        else:
            invalidation_level = None
            signal_direction = "HOLD"

        return {
            "symbol": symbol,
            "version": "MM_v4",
            "inventory_estimate": round(inv_est, 4),
            "inv_z": round(inv_z, 3),
            "abs_inv_z": round(abs_inv_z, 3),
            "flow_quality": round(flow_quality, 2),
            "absorption": absorption,
            "conviction_flow": conviction_flow,
            "optimal_hedge_z": round(optimal_hedge_z, 3),
            "optimal_hedge_rate": round(optimal_hedge_rate, 4),
            "total_gamma_pressure": round(total_gamma_pressure, 3),
            "gamma_critical": gamma_critical,
            "nearest_strike": nearest_strike,
            "near_strike": near_strike,
            "critical_long": critical_long,
            "critical_short": critical_short,
            "control_action": control_action,
            "long_signal": long_signal,
            "short_signal": short_signal,
            "signal_direction": signal_direction,
            "signal_confidence": round(signal_confidence, 1),
            "invalidation_level": round(invalidation_level, 2) if invalidation_level else None,
            "atr_14": round(atr_14, 2),
            "price": last_close,
        }
