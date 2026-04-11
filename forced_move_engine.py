"""
SML Forced Move Engine™ v3.0 - SQUEEZE OS Trading Platform
Translates PineScript indicator into Python module for detecting forced market moves.

The engine tracks a 4-layer lifecycle:
1. PRESSURE: Market compression and institutional positioning
2. TRIGGER: Catalysts that initiate the move
3. ACCELERATION: Post-break momentum and dealer reactions
4. COMMITMENT: Validation that the move will follow through

Author: SQUEEZE OS
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field
from collections import defaultdict

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class Bar:
    """OHLCV bar data structure."""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int

    @classmethod
    def from_dict(cls, data: dict) -> "Bar":
        """Convert dict to Bar instance."""
        return cls(
            date=data.get("date", ""),
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            volume=int(data.get("volume", 0))
        )


class ForcedMoveEngine:
    """
    Detects forced market moves through 4-layer lifecycle analysis.

    Maintains per-symbol state for cooldowns, trigger states, and directional tracking.
    """

    def __init__(self):
        """Initialize engine with default parameters matching PineScript v3.0."""
        # Technical parameters
        self.atr_len = 20
        self.vol_len = 20
        self.bb_len = 20
        self.bb_mult = 2.0
        self.pivot_len = 10
        self.trap_lookback = 50

        # Pressure thresholds
        self.calm_max = 30
        self.loaded_min = 66

        # Trigger thresholds
        self.vol_spike_thresh = 2.0
        self.vuvd_stdev = 1.5
        self.iv_accel_thresh = 1.2
        self.cooldown_bars = 5

        # Acceleration thresholds
        self.accel_weak_max = 30
        self.accel_violent_min = 66
        self.dead_bars = 3

        # Commitment thresholds
        self.trap_fake = 20.0
        self.trap_fragile = 40.0
        self.trap_forced = 60.0

        # Per-symbol state machines
        self._cooldown_count = defaultdict(int)      # Cooldown counter
        self._trigger_state = defaultdict(str)        # IDLE, ARMED, TRIGGERING, FALSE, COOLDOWN
        self._bars_since_trig = defaultdict(int)      # Bars since trigger activated
        self._same_dir_bars = defaultdict(int)        # Consecutive same-direction bars
        self._walls_above = defaultdict(list)         # Historical resistance levels
        self._walls_below = defaultdict(list)         # Historical support levels
        self._last_trigger_bar = defaultdict(int)     # Bar index of last trigger
        self._trigger_direction = defaultdict(str)    # Direction of trigger: BULL, BEAR

    def analyze(self, symbol: str, bars: list, vix: float = 20.0) -> Optional[Dict]:
        """
        Analyze symbol for forced move signals across 4 layers.

        Args:
            symbol: Trading pair symbol (e.g., "SPY", "BTC/USD")
            bars: List of OHLCV dicts [{date, open, high, low, close, volume}, ...]
            vix: Current VIX (volatility index) for threshold adaptation

        Returns:
            Dict with pressure, trigger, acceleration, commitment scores and action signal.
            None if insufficient data or error occurs.
        """
        # Validation
        if not bars or len(bars) < max(self.bb_len, self.trap_lookback, 30):
            logger.warning(
                f"{symbol}: Insufficient bars (need {max(self.bb_len, self.trap_lookback, 30)}, "
                f"got {len(bars)})"
            )
            return None

        try:
            # Convert to Bar objects if needed
            if isinstance(bars[0], dict):
                bars = [Bar.from_dict(b) for b in bars]

            # Extract OHLCV arrays for numpy operations
            opens = np.array([b.open for b in bars], dtype=np.float64)
            highs = np.array([b.high for b in bars], dtype=np.float64)
            lows = np.array([b.low for b in bars], dtype=np.float64)
            closes = np.array([b.close for b in bars], dtype=np.float64)
            volumes = np.array([b.volume for b in bars], dtype=np.float64)

            # Calculate technical indicators
            atr = self._calculate_atr(highs, lows, closes)
            bb_upper, bb_lower, bb_width = self._calculate_bollinger_bands(closes)
            vol_sma = self._sma(volumes, self.vol_len)
            roc = self._rate_of_change(closes, 3)

            # Calculate volume profile
            up_vol, dn_vol = self._calculate_direction_volume(opens, closes, volumes)
            vol_delta = up_vol - dn_vol

            # Detect walls (pivot highs/lows)
            walls_above, walls_below = self._find_walls(highs, lows, closes)
            self._walls_above[symbol] = walls_above
            self._walls_below[symbol] = walls_below

            # Update VIX-adjusted thresholds
            vix_adjust = self._get_vix_adjustment(vix)
            adjusted_calm = self.calm_max + vix_adjust
            adjusted_loaded = self.loaded_min + vix_adjust

            # LAYER 1: PRESSURE SCORE
            pressure_result = self._calculate_pressure(
                closes, highs, lows, volumes, vol_delta, bb_width, atr,
                adjusted_calm, adjusted_loaded
            )

            # LAYER 2: TRIGGER DETECTOR
            trigger_result = self._calculate_trigger(
                symbol, closes, volumes, vol_sma, vol_delta, atr,
                pressure_result["state"], roc, up_vol, dn_vol
            )

            # LAYER 3: ACCELERATION MODEL
            acceleration_result = self._calculate_acceleration(
                symbol, closes, volumes, vol_sma, atr, roc, vol_delta,
                self._bars_since_trig[symbol]
            )

            # LAYER 4: COMMITMENT
            commitment_result = self._calculate_commitment(
                symbol, closes, volumes, vol_delta, atr,
                self._bars_since_trig[symbol], walls_above, walls_below,
                trigger_result["state"]
            )

            # Determine composite action
            action, size_pct, direction = self._determine_action(
                pressure_result, trigger_result, acceleration_result,
                commitment_result, symbol
            )

            # Increment state counters
            self._bars_since_trig[symbol] += 1
            self._cooldown_count[symbol] = max(0, self._cooldown_count[symbol] - 1)

            return {
                "symbol": symbol,
                "pressure": {
                    "score": pressure_result["score"],
                    "state": pressure_result["state"],
                    "components": pressure_result["components"]
                },
                "trigger": {
                    "score": trigger_result["score"],
                    "state": trigger_result["state"],
                    "inputs_active": trigger_result["inputs_active"],
                    "components": trigger_result["components"]
                },
                "acceleration": {
                    "score": acceleration_result["score"],
                    "state": acceleration_result["state"],
                    "dead_setup": acceleration_result["dead_setup"],
                    "components": acceleration_result["components"]
                },
                "commitment": {
                    "score": commitment_result["score"],
                    "state": commitment_result["state"],
                    "trapped_pct": commitment_result["trapped_pct"],
                    "components": commitment_result["components"]
                },
                "action": action,
                "size_pct": size_pct,
                "direction": direction,
                "vix": vix
            }

        except Exception as e:
            logger.error(f"{symbol}: Analysis error - {str(e)}")
            return None

    # ==================== LAYER 1: PRESSURE ====================

    def _calculate_pressure(self, closes, highs, lows, volumes, vol_delta, bb_width,
                           atr, calm_max, loaded_min) -> Dict:
        """
        Calculate PRESSURE SCORE (0-100).

        Combines 4 components:
        1. Wall Proximity (25%): Distance to nearest pivot high/low
        2. GEX Proximity (25%): Volume delta accumulation
        3. OI Concentration (25%): Volume in tight price zone
        4. Compression (25%): Bollinger Band width percentile
        """
        current_price = closes[-1]
        current_atr = atr[-1]

        # 1. WALL PROXIMITY (25%)
        walls_above = self._find_pivot_highs(highs, lows, self.pivot_len)
        walls_below = self._find_pivot_lows(highs, lows, self.pivot_len)

        wall_dist_above = float('inf')
        wall_dist_below = float('inf')

        if walls_above:
            nearest_above = min([w for w in walls_above if w > current_price],
                               default=None)
            if nearest_above:
                wall_dist_above = (nearest_above - current_price) / (current_atr * 3)

        if walls_below:
            nearest_below = max([w for w in walls_below if w < current_price],
                               default=None)
            if nearest_below:
                wall_dist_below = (current_price - nearest_below) / (current_atr * 3)

        min_wall_dist = min(wall_dist_above, wall_dist_below)
        wall_proximity = max(0, min(100, (1 - min(min_wall_dist, 1.0)) * 100))

        # 2. GEX PROXIMITY PROXY (25%)
        vol_delta_10 = np.sum(vol_delta[-10:])
        vol_delta_range = np.ptp(np.convolve(vol_delta, np.ones(10)/10, mode='valid')[-90:])
        gex_score = 0.0
        if vol_delta_range > 0:
            gex_score = min(100, abs(vol_delta_10) / vol_delta_range * 100)

        # 3. OI CONCENTRATION PROXY (25%)
        zone_volume = 0
        total_volume = np.sum(volumes[-self.trap_lookback:])
        for i in range(-self.trap_lookback, 0):
            if abs(closes[i] - current_price) <= current_atr * 0.5:
                zone_volume += volumes[i]

        oi_ratio = (zone_volume / total_volume * 300) if total_volume > 0 else 0
        oi_concentration = min(100, oi_ratio)

        # 4. COMPRESSION (25%)
        bb_width_percentiles = []
        for i in range(-100, 0):
            if i >= -len(bb_width):
                bb_width_percentiles.append(bb_width[i])

        compression = 0.0
        if bb_width_percentiles:
            current_bb_width = bb_width[-1]
            percentile = np.mean(np.array(bb_width_percentiles) < current_bb_width) * 100
            compression = 100 - percentile  # Inverted: tight = high score

        # COMPOSITE PRESSURE SCORE (equal 25% weights)
        pressure_score = (wall_proximity + gex_score + oi_concentration + compression) / 4
        pressure_score = np.clip(pressure_score, 0, 100)

        # STATE DETERMINATION
        if pressure_score < calm_max:
            state = "CALM"
        elif pressure_score >= loaded_min:
            state = "LOADED"
        else:
            state = "BUILD"

        return {
            "score": float(pressure_score),
            "state": state,
            "components": {
                "wall_proximity": float(wall_proximity),
                "gex_proxy": float(gex_score),
                "oi_concentration": float(oi_concentration),
                "compression": float(compression)
            }
        }

    # ==================== LAYER 2: TRIGGER ====================

    def _calculate_trigger(self, symbol: str, closes, volumes, vol_sma, vol_delta, atr,
                          pressure_state, roc, up_vol, dn_vol) -> Dict:
        """
        Calculate TRIGGER DETECTOR (0-100) with state machine.

        State machine: IDLE → ARMED → TRIGGERING → COOLDOWN

        Detects:
        1. Vol Spike: volume > 2.0 * SMA
        2. VUVD Shift: directional volume change
        3. IV Accel: ATR(5) / ATR(20) > 1.2
        4. Micro Break: price crosses wall
        """
        current_vol = volumes[-1]
        current_atr = atr[-1]
        current_atr_short = np.mean(atr[-5:])
        current_atr_long = np.mean(atr[-20:])

        # Check individual trigger inputs
        vol_spike_score = min(100, max(0, (current_vol / (vol_sma[-1] + 1e-9) - 1) * 50))

        # VUVD Shift
        vuvd_current = (up_vol[-1] - dn_vol[-1]) / (up_vol[-1] + dn_vol[-1] + 1e-9)
        vuvd_3bars_ago = (up_vol[-4] - dn_vol[-4]) / (up_vol[-4] + dn_vol[-4] + 1e-9)
        vuvd_delta = abs(vuvd_current - vuvd_3bars_ago)
        vuvd_stdev = np.std([
            (up_vol[i] - dn_vol[i]) / (up_vol[i] + dn_vol[i] + 1e-9)
            for i in range(-20, 0)
        ])
        vuvd_score = min(100, (vuvd_delta / (self.vuvd_stdev * stdev + 1e-9)) * 50)

        # IV Acceleration
        iv_ratio = current_atr_short / (current_atr_long + 1e-9)
        iv_accel_score = min(100, max(0, (iv_ratio - 1) / (self.iv_accel_thresh - 1) * 100))

        # Micro Break (price crosses wall)
        walls_above = self._walls_above.get(symbol, [])
        walls_below = self._walls_below.get(symbol, [])
        micro_break_score = 0.0

        if walls_above:
            for wall in walls_above[-3:]:
                if closes[-2] < wall and closes[-1] >= wall:
                    micro_break_score = 75.0
                    break

        if walls_below:
            for wall in walls_below[-3:]:
                if closes[-2] > wall and closes[-1] <= wall:
                    micro_break_score = 75.0
                    break

        # Count active inputs
        inputs_active = sum([
            vol_spike_score > 50,
            vuvd_score > 50,
            iv_accel_score > 50,
            micro_break_score > 50
        ])

        # STATE MACHINE
        current_state = self._trigger_state[symbol]
        cooldown = self._cooldown_count[symbol]

        if cooldown > 0:
            current_state = "COOLDOWN"
        elif current_state == "IDLE" or current_state == "":
            # IDLE → ARMED: Pressure BUILD + 2 inputs
            if pressure_state in ["BUILD", "LOADED"] and inputs_active >= 2:
                current_state = "ARMED"
            else:
                current_state = "IDLE"

        elif current_state == "ARMED":
            # ARMED → TRIGGERING: Pressure LOADED + 3 inputs
            if pressure_state == "LOADED" and inputs_active >= 3:
                current_state = "TRIGGERING"
                self._bars_since_trig[symbol] = 0
                self._last_trigger_bar[symbol] = 0
                # Determine trigger direction
                if closes[-1] > closes[-2]:
                    self._trigger_direction[symbol] = "BULL"
                else:
                    self._trigger_direction[symbol] = "BEAR"
            # ARMED → FALSE: 2 inputs but no LOADED pressure
            elif inputs_active < 2:
                current_state = "FALSE"

        elif current_state == "TRIGGERING":
            # Stay in TRIGGERING until cooldown
            if pressure_state == "CALM":
                current_state = "FALSE"

        elif current_state == "FALSE":
            # FALSE → COOLDOWN after 2 bars
            if self._bars_since_trig[symbol] > 2:
                self._cooldown_count[symbol] = self.cooldown_bars
                current_state = "COOLDOWN"

        self._trigger_state[symbol] = current_state

        # TRIGGER SCORE
        trigger_score = (vol_spike_score + vuvd_score + iv_accel_score + micro_break_score) / 4
        trigger_score = np.clip(trigger_score, 0, 100)

        return {
            "score": float(trigger_score),
            "state": current_state,
            "inputs_active": inputs_active,
            "components": {
                "vol_spike": float(vol_spike_score),
                "vuvd_shift": float(vuvd_score),
                "iv_accel": float(iv_accel_score),
                "micro_break": float(micro_break_score)
            }
        }

    # ==================== LAYER 3: ACCELERATION ====================

    def _calculate_acceleration(self, symbol: str, closes, volumes, vol_sma, atr, roc,
                               vol_delta, bars_since_trig) -> Dict:
        """
        Calculate ACCELERATION MODEL (0-100).

        Components:
        1. Post-Break Momentum (30%): |ROC(3)| normalized
        2. Dealer Reaction (25%): Volume delta vs moving average
        3. Continuation (25%): Same-direction bars ratio
        4. Gamma Feedback (20%): ROC acceleration
        """
        current_atr = atr[-1]
        current_price = closes[-1]

        # 1. POST-BREAK MOMENTUM (30%)
        momentum = abs(roc[-1]) / (current_atr / current_price + 1e-9)
        momentum_score = min(100, momentum * 50)

        # 2. DEALER REACTION (25%)
        vol_delta_recent = vol_delta[-1]
        vol_delta_sma = np.mean(vol_delta[-10:])
        vol_delta_stdev = np.std(vol_delta[-20:])
        dealer_reaction = abs(vol_delta_recent - vol_delta_sma) / (vol_delta_stdev + 1e-9) * 33
        dealer_score = min(100, dealer_reaction)

        # 3. CONTINUATION (25%)
        same_dir_bars = 0
        if bars_since_trig > 0 and bars_since_trig < len(closes):
            trigger_idx = len(closes) - bars_since_trig
            trigger_direction = self._trigger_direction[symbol]

            for i in range(trigger_idx, len(closes) - 1):
                if trigger_direction == "BULL" and closes[i+1] > closes[i]:
                    same_dir_bars += 1
                elif trigger_direction == "BEAR" and closes[i+1] < closes[i]:
                    same_dir_bars += 1

            continuation_ratio = same_dir_bars / max(1, bars_since_trig)
        else:
            continuation_ratio = 0.0

        continuation_score = continuation_ratio * 100

        # 4. GAMMA FEEDBACK (20%)
        roc_of_roc = 0.0
        if len(roc) >= 2:
            roc_of_roc = abs(roc[-1] - roc[-2]) / (abs(roc[-2]) + 1e-9)
        gamma_score = min(100, roc_of_roc * 50)

        # ACCELERATION SCORE
        accel_score = (
            momentum_score * 0.30 +
            dealer_score * 0.25 +
            continuation_score * 0.25 +
            gamma_score * 0.20
        )
        accel_score = np.clip(accel_score, 0, 100)

        # STATE DETERMINATION
        if accel_score < self.accel_weak_max:
            state = "WEAK"
        elif accel_score >= self.accel_violent_min:
            state = "VIOLENT"
        else:
            state = "CLEAN"

        # DEAD SETUP CHECK: WEAK for 3+ bars after trigger
        dead_setup = (state == "WEAK" and bars_since_trig >= self.dead_bars)

        return {
            "score": float(accel_score),
            "state": state,
            "dead_setup": dead_setup,
            "components": {
                "post_break_momentum": float(momentum_score),
                "dealer_reaction": float(dealer_score),
                "continuation": float(continuation_score),
                "gamma_feedback": float(gamma_score)
            }
        }

    # ==================== LAYER 4: COMMITMENT ====================

    def _calculate_commitment(self, symbol: str, closes, volumes, vol_delta, atr,
                             bars_since_trig, walls_above, walls_below,
                             trigger_state) -> Dict:
        """
        Calculate COMMITMENT (0-100).

        Components:
        1. Trapped Volume (30%): Volume on wrong side / total
        2. Past-Strike Distance (20%): ATR units past wall
        3. Follow-Through Volume (20%): Avg volume since trigger
        4. Accel Delta (15%): Momentum still increasing
        5. Opposing Liquidity (15%): Wall strength ratio
        """
        current_price = closes[-1]
        current_atr = atr[-1]
        current_vol = volumes[-1]
        normal_vol = np.mean(volumes[-50:])

        # 1. TRAPPED VOLUME (30%)
        if bars_since_trig > 0 and trigger_state == "TRIGGERING":
            trigger_idx = len(closes) - bars_since_trig
            trigger_direction = self._trigger_direction[symbol]

            trapped_vol = 0
            total_vol = 0

            for i in range(trigger_idx, len(closes)):
                total_vol += volumes[i]
                if trigger_direction == "BULL" and closes[i] < closes[trigger_idx]:
                    trapped_vol += volumes[i]
                elif trigger_direction == "BEAR" and closes[i] > closes[trigger_idx]:
                    trapped_vol += volumes[i]

            trapped_pct = (trapped_vol / total_vol * 100) if total_vol > 0 else 0.0
        else:
            trapped_pct = 0.0

        trapped_score = min(100, max(0, (100 - trapped_pct) / 100 * 100))

        # 2. PAST-STRIKE DISTANCE (20%)
        past_distance = 0.0
        if trigger_state == "TRIGGERING":
            trigger_direction = self._trigger_direction[symbol]

            if trigger_direction == "BULL" and walls_above:
                strike_wall = min(walls_above)
                if current_price > strike_wall:
                    past_distance = (current_price - strike_wall) / current_atr
            elif trigger_direction == "BEAR" and walls_below:
                strike_wall = max(walls_below)
                if current_price < strike_wall:
                    past_distance = (strike_wall - current_price) / current_atr

        past_distance_score = min(100, past_distance * 20)

        # 3. FOLLOW-THROUGH VOLUME (20%)
        if bars_since_trig > 0:
            follow_vol = np.mean(volumes[-bars_since_trig:])
        else:
            follow_vol = current_vol

        vol_ratio = follow_vol / (normal_vol + 1e-9)
        follow_vol_score = min(100, vol_ratio * 50)

        # 4. ACCEL DELTA (15%)
        accel_delta = 0.0
        if len(atr) >= 10 and bars_since_trig > 3:
            recent_atr_accel = (np.mean(atr[-3:]) / np.mean(atr[-6:-3])) - 1
            accel_delta = max(0, recent_atr_accel * 100)

        accel_delta_score = min(100, accel_delta)

        # 5. OPPOSING LIQUIDITY (15%)
        opposing_score = 50.0  # Default middle ground
        if walls_above and walls_below:
            above_strength = len([w for w in walls_above if w > current_price])
            below_strength = len([w for w in walls_below if w < current_price])
            if trigger_direction == "BULL":
                opposing_score = (1 - above_strength / (above_strength + below_strength + 1e-9)) * 100
            else:
                opposing_score = (1 - below_strength / (above_strength + below_strength + 1e-9)) * 100

        # COMMITMENT SCORE
        commitment_score = (
            trapped_score * 0.30 +
            past_distance_score * 0.20 +
            follow_vol_score * 0.20 +
            accel_delta_score * 0.15 +
            opposing_score * 0.15
        )
        commitment_score = np.clip(commitment_score, 0, 100)

        # STATE DETERMINATION
        if trapped_pct > self.trap_fake:
            state = "FAKE"
        elif commitment_score < self.trap_fragile:
            state = "FRAGILE"
        elif commitment_score >= self.trap_forced:
            state = "FORCED"
        else:
            state = "COMMITTED"

        return {
            "score": float(commitment_score),
            "state": state,
            "trapped_pct": float(trapped_pct),
            "components": {
                "trapped_volume": float(trapped_score),
                "past_distance": float(past_distance_score),
                "follow_through_vol": float(follow_vol_score),
                "accel_delta": float(accel_delta_score),
                "opposing_liquidity": float(opposing_score)
            }
        }

    # ==================== ACTION DETERMINATION ====================

    def _determine_action(self, pressure, trigger, acceleration, commitment,
                         symbol: str) -> tuple:
        """
        Determine composite action and position size based on all 4 layers.

        Returns: (action_str, size_pct, direction)
        """
        pressure_score = pressure["score"]
        trigger_score = trigger["score"]
        trigger_state = trigger["state"]
        accel_score = acceleration["score"]
        accel_state = acceleration["state"]
        commit_score = commitment["score"]
        commit_state = commitment["state"]
        dead_setup = acceleration["dead_setup"]

        # Count strong layers (score >= 66)
        strong_layers = sum([
            pressure_score >= 66,
            trigger_score >= 66,
            accel_score >= 66,
            commit_score >= 66
        ])

        direction = self._trigger_direction.get(symbol, "FLAT")

        # PRIMARY CONDITIONS
        if trigger_state == "COOLDOWN":
            return "WAIT", 0, "FLAT"

        if dead_setup:
            return "EXIT — DEAD SETUP", 0, "FLAT"

        if trigger_state not in ["TRIGGERING", "ARMED"]:
            if pressure["state"] == "LOADED" and trigger_score >= 50:
                return "ENTER SMALL", 25, direction
            elif pressure["state"] in ["BUILD", "LOADED"]:
                return "WATCH — PREPARE", 0, direction
            else:
                return "MONITOR", 0, "FLAT"

        # TRIGGER-ACTIVE CONDITIONS
        if commit_state == "FAKE" or (dead_setup and accel_state == "WEAK"):
            return "EXIT IMMEDIATELY", 0, "FLAT"

        # Strong commitment states
        if commit_state == "FORCED" and strong_layers >= 3:
            return "FULL SIZE — THE MOVE", 100, direction

        if commit_state == "COMMITTED" and strong_layers >= 3:
            return "ADD POSITION", 75, direction

        if commit_state == "COMMITTED" and strong_layers >= 2:
            return "HOLD — TIGHT STOP", 50, direction

        if commit_state == "FRAGILE" and strong_layers >= 2:
            return "HOLD — TIGHT STOP", 50, direction

        if trigger_state == "TRIGGERING" and accel_state == "VIOLENT":
            return "ADD POSITION", 75, direction

        if trigger_state == "TRIGGERING" and accel_state == "CLEAN":
            return "HOLD — TIGHT STOP", 50, direction

        if trigger_state == "ARMED" and pressure["state"] == "LOADED":
            return "ENTER SMALL", 25, direction

        # FALLBACK
        if pressure["state"] == "LOADED":
            return "WATCH — PREPARE", 0, direction

        return "MONITOR", 0, "FLAT"

    # ==================== TECHNICAL INDICATORS ====================

    def _calculate_atr(self, highs, lows, closes, period: int = 20) -> np.ndarray:
        """Calculate Average True Range."""
        tr = np.maximum(
            highs - lows,
            np.maximum(
                np.abs(highs - np.roll(closes, 1)),
                np.abs(lows - np.roll(closes, 1))
            )
        )
        tr[0] = highs[0] - lows[0]

        atr = np.zeros_like(tr)
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    def _calculate_bollinger_bands(self, closes, period: int = 20,
                                   std_dev: float = 2.0) -> tuple:
        """Calculate Bollinger Bands."""
        sma = self._sma(closes, period)
        std = np.zeros_like(closes)

        for i in range(period - 1, len(closes)):
            std[i] = np.std(closes[i - period + 1:i + 1])

        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        width = upper - lower

        return upper, lower, width

    def _sma(self, data, period: int) -> np.ndarray:
        """Calculate Simple Moving Average."""
        result = np.zeros_like(data)
        for i in range(len(data)):
            if i < period - 1:
                result[i] = np.mean(data[:i + 1])
            else:
                result[i] = np.mean(data[i - period + 1:i + 1])
        return result

    def _rate_of_change(self, closes, period: int = 3) -> np.ndarray:
        """Calculate Rate of Change (ROC)."""
        roc = np.zeros_like(closes)
        for i in range(period, len(closes)):
            roc[i] = (closes[i] - closes[i - period]) / closes[i - period]
        return roc

    def _calculate_direction_volume(self, opens, closes, volumes) -> tuple:
        """Calculate up and down volume."""
        up_vol = np.zeros_like(volumes)
        dn_vol = np.zeros_like(volumes)

        for i in range(len(closes)):
            if closes[i] >= opens[i]:
                up_vol[i] = volumes[i]
            else:
                dn_vol[i] = volumes[i]

        return up_vol, dn_vol

    def _find_walls(self, highs, lows, closes) -> tuple:
        """Detect resistance (walls above) and support (walls below)."""
        walls_above = self._find_pivot_highs(highs, lows, self.pivot_len)
        walls_below = self._find_pivot_lows(highs, lows, self.pivot_len)
        return walls_above, walls_below

    def _find_pivot_highs(self, highs, lows, lookback: int = 10) -> List[float]:
        """Find local highs (resistance levels)."""
        pivots = []
        for i in range(lookback, len(highs) - lookback):
            if highs[i] == np.max(highs[i - lookback:i + lookback + 1]):
                pivots.append(float(highs[i]))
        return pivots

    def _find_pivot_lows(self, highs, lows, lookback: int = 10) -> List[float]:
        """Find local lows (support levels)."""
        pivots = []
        for i in range(lookback, len(lows) - lookback):
            if lows[i] == np.min(lows[i - lookback:i + lookback + 1]):
                pivots.append(float(lows[i]))
        return pivots

    def _get_vix_adjustment(self, vix: float) -> float:
        """Adjust thresholds based on VIX level."""
        if vix < 15:
            return 10  # Easier to trigger in low volatility
        elif vix > 30:
            return -10  # Harder to trigger in high volatility
        else:
            return 0  # Normal thresholds


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Initialize engine
    engine = ForcedMoveEngine()

    # Example bar data
    example_bars = [
        {
            "date": "2026-03-20",
            "open": 100.0,
            "high": 102.5,
            "low": 99.5,
            "close": 101.0,
            "volume": 1000000
        },
        {
            "date": "2026-03-21",
            "open": 101.0,
            "high": 103.0,
            "low": 100.5,
            "close": 102.5,
            "volume": 1200000
        },
        # ... more bars
    ]

    # Analyze
    result = engine.analyze("SPY", example_bars, vix=20.0)
    if result:
        print(f"Action: {result['action']}")
        print(f"Direction: {result['direction']}")
        print(f"Size: {result['size_pct']}%")
