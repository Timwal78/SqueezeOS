"""
SQUEEZE OS v4.3 — Institutional GEX & Flow Fusion Engine
═══════════════════════════════════════════════════════════
Directional volatility extraction via dealer mechanics, gamma exposure
profiling, and institutional flow analysis.

ACCURACY UPGRADES (v4.3):
  - Dynamic expected_move from GEX magnitude + IV surface
  - Zero Gamma Line (ZGL) detection — the fulcrum price
  - Put Wall / Call Wall identification with magnitude ranking
  - DTE-weighted urgency scoring
  - Gamma Flip detection (long→short transition)
  - Pin risk detection near max OI strikes at expiry
  - Improved time-weighting formula (exponential decay)
"""
import asyncio
import logging
import time
import math
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import deque
from schwab_api import schwab_api
from data_providers import PolygonProvider

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class FlowSignal:
    ticker: str
    timestamp: datetime
    signal_type: str   # gamma_squeeze_setup, gamma_support_bounce, gamma_flip, pin_risk
    strike: float
    gex_at_strike: float
    spot_price: float
    urgency_score: float   # 0-100
    expected_move: float   # Dynamic % estimate
    confidence: str        # high, medium, low


@dataclass
class GEXProfile:
    """Full gamma exposure profile for a ticker."""
    ticker: str
    spot_price: float
    total_gex: float
    profile_shape: str           # long_gamma, short_gamma
    by_strike: Dict[float, float] = field(default_factory=dict)

    # Key levels
    max_gamma_strike: float = 0   # Call wall (highest positive GEX)
    min_gamma_strike: float = 0   # Put wall (most negative GEX)
    zero_gamma_line: float = 0    # Price where GEX flips sign
    max_oi_strike: float = 0      # Highest total OI (pin magnet)

    # Walls
    call_wall: float = 0          # Strongest call-side GEX concentration
    put_wall: float = 0           # Strongest put-side GEX concentration

    # Derived metrics
    gamma_notional: float = 0     # $ of delta hedging per 1% move
    expected_move: float = 0      # Dynamic expected move %
    iv_surface_avg: float = 0     # Average IV across ATM strikes

    timestamp: float = 0


# ═══════════════════════════════════════════════════════════════
# MATH UTILITIES
# ═══════════════════════════════════════════════════════════════

def estimate_gamma(S, K, T, r, sigma):
    """Black-Scholes gamma approximation."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        gamma = math.exp(-0.5 * d1**2) / (S * sigma * math.sqrt(2 * math.pi * T))
        return gamma
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def option_gex(gamma, oi, spot, option_type):
    """
    GEX for one contract = Gamma × OI × Multiplier × Spot²
    Sign convention (from DEALER perspective):
      Calls: +GEX  — Dealers are short calls, short gamma → must buy as price rises
      Puts:  -GEX  — Dealers are long puts, long gamma  → must sell as price rises
    
    Note: Using Spot² (not Spot) is the correct institutional formula.
    GEX = Γ × OI × 100 × S² × 0.01
    This gives the dollar delta change per 1% move in underlying.
    """
    if gamma <= 0 or oi <= 0 or spot <= 0:
        return 0.0
    multiplier = 100
    # Dollar gamma = Γ × OI × 100 × S² × 0.01
    dollar_gex = gamma * oi * multiplier * (spot ** 2) * 0.01
    if option_type.upper() == 'CALL':
        return dollar_gex
    else:
        return -dollar_gex


def time_weight(days_to_expiry):
    """
    Exponential decay weighting — front-week options dominate GEX.
    0 DTE  → 1.0
    7 DTE  → 0.5
    30 DTE → 0.1
    60 DTE → 0.01
    """
    if days_to_expiry <= 0:
        return 1.0
    decay_factor = float(os.getenv('GEX_DTE_DECAY_FACTOR', '0.1'))
    return math.exp(-decay_factor * days_to_expiry)


def find_zero_gamma_line(gex_by_strike, spot_price):
    """
    Find the strike where net GEX crosses from negative to positive (or vice versa).
    This is the "fulcrum" — below it, dealers amplify moves; above it, they dampen.
    """
    sorted_strikes = sorted(gex_by_strike.keys())
    if len(sorted_strikes) < 2:
        return spot_price

    # Walk through strikes finding sign changes
    for i in range(len(sorted_strikes) - 1):
        s1, s2 = sorted_strikes[i], sorted_strikes[i + 1]
        v1, v2 = gex_by_strike[s1], gex_by_strike[s2]

        if v1 * v2 < 0:  # Sign change
            # Linear interpolation to find exact crossing
            ratio = abs(v1) / (abs(v1) + abs(v2))
            zgl = s1 + ratio * (s2 - s1)
            # Only return ZGL near spot (within 10%)
            if abs(zgl - spot_price) / spot_price < 0.10:
                return round(zgl, 2)

    return spot_price  # Default to spot if no crossing found


# ═══════════════════════════════════════════════════════════════
# GEX PROFILE BUILDER
# ═══════════════════════════════════════════════════════════════

def calculate_gex_profile(raw_chain, spot_price, ticker=""):
    """Build institutional-grade GEX profile from Schwab chain data."""
    gex_by_strike = {}
    oi_by_strike = {}       # Total OI per strike (for pin detection)
    iv_samples = []         # ATM IV samples for expected move
    today = datetime.now()

    call_map = raw_chain.get('callExpDateMap', {})
    put_map = raw_chain.get('putExpDateMap', {})

    def process_map(option_map, opt_type):
        for expiry_key, strikes in option_map.items():
            if ':' not in expiry_key:
                continue
            expiry_str = expiry_key.split(':')[0]
            try:
                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
                days_to_exp = (expiry_date - today).days
                if days_to_exp < 0:
                    continue
                tw = time_weight(days_to_exp)
                T = max(0.0001, days_to_exp / 365.0)
            except (ValueError, TypeError):
                continue

            for strike_str, contracts in strikes.items():
                try:
                    strike = float(strike_str)
                except (ValueError, TypeError):
                    continue

                # Focus on ATM ± 20% (wider than before for better wall detection)
                if not (spot_price * 0.80 <= strike <= spot_price * 1.20):
                    continue

                for opt in contracts:
                    if not isinstance(opt, dict):
                        continue

                    oi = int(opt.get('openInterest', 0) or 0)
                    gamma_val = float(opt.get('gamma', 0) or 0)
                    vol = int(opt.get('totalVolume', 0) or 0)

                    # Track total OI per strike for pin detection
                    oi_by_strike[strike] = oi_by_strike.get(strike, 0) + oi

                    if oi <= 0:
                        continue

                    # If gamma is missing/zero from Schwab, estimate via BS
                    if gamma_val <= 0:
                        iv_raw = float(opt.get('volatility', 0) or 0) / 100.0
                        if iv_raw > 0:
                            gamma_val = estimate_gamma(spot_price, strike, T, 0.04, iv_raw)

                    if gamma_val <= 0:
                        continue

                    # Collect ATM IV for expected move calculation
                    if abs(strike - spot_price) / spot_price < 0.05:
                        iv_raw = float(opt.get('volatility', 0) or 0) / 100.0
                        if iv_raw > 0:
                            iv_samples.append(iv_raw)

                    gex = option_gex(gamma_val, oi, spot_price, opt_type) * tw
                    gex_by_strike[strike] = gex_by_strike.get(strike, 0) + gex

    process_map(call_map, 'CALL')
    process_map(put_map, 'PUT')

    if not gex_by_strike:
        return None

    total_gex = sum(gex_by_strike.values())
    profile_shape = 'long_gamma' if total_gex > 0 else 'short_gamma'

    # Find call wall (highest positive GEX strike)
    positive_strikes = {k: v for k, v in gex_by_strike.items() if v > 0}
    negative_strikes = {k: v for k, v in gex_by_strike.items() if v < 0}

    call_wall = max(positive_strikes, key=positive_strikes.get) if positive_strikes else spot_price
    put_wall = min(negative_strikes, key=negative_strikes.get) if negative_strikes else spot_price

    # Max gamma strike (absolute value)
    max_gamma_strike = max(gex_by_strike, key=lambda k: gex_by_strike[k])
    min_gamma_strike = min(gex_by_strike, key=lambda k: gex_by_strike[k])

    # Zero Gamma Line
    zgl = find_zero_gamma_line(gex_by_strike, spot_price)

    # Max OI strike (pin magnet near expiry)
    max_oi_strike = max(oi_by_strike, key=oi_by_strike.get) if oi_by_strike else spot_price

    # Gamma Notional: total $ of delta hedging per 1% spot move
    gamma_notional = abs(total_gex)

    # Dynamic Expected Move from ATM IV surface
    avg_iv = sum(iv_samples) / len(iv_samples) if iv_samples else 0.30
    if not iv_samples:
        logger.warning(f"No ATM IV samples available for {ticker}; using default IV of 0.30")
    # 1-day expected move ≈ IV × sqrt(1/252)
    expected_move = avg_iv * math.sqrt(1 / 252.0)
    # Gamma-regime adjustment — configurable per AGENT_LAW §2 (no hidden magic numbers).
    # GEX_SHORT_GAMMA_AMP (1.3): Dealers are short gamma → they amplify moves to hedge.
    #                             1.0 = no adjustment; >1.0 = realized vol > implied vol.
    # GEX_LONG_GAMMA_DAMP (0.7): Dealers are long gamma → they dampen moves by fading.
    #                             1.0 = no adjustment; <1.0 = realized vol < implied vol.
    short_amp = float(os.getenv('GEX_SHORT_GAMMA_AMP', '1.3'))
    long_damp = float(os.getenv('GEX_LONG_GAMMA_DAMP', '0.7'))
    
    if profile_shape == 'short_gamma':
        expected_move *= short_amp  # Amplification in short gamma
    else:
        expected_move *= long_damp  # Dampening in long gamma

    profile = GEXProfile(
        ticker=ticker,
        spot_price=spot_price,
        total_gex=total_gex,
        profile_shape=profile_shape,
        by_strike=gex_by_strike,
        max_gamma_strike=max_gamma_strike,
        min_gamma_strike=min_gamma_strike,
        zero_gamma_line=zgl,
        max_oi_strike=max_oi_strike,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_notional=gamma_notional,
        expected_move=expected_move,
        iv_surface_avg=avg_iv,
        timestamp=time.time()
    )

    return profile


# ═══════════════════════════════════════════════════════════════
# GEX ENGINE
# ═══════════════════════════════════════════════════════════════

class GammaFlowEngine:
    def __init__(self, polygon: PolygonProvider, watchlist: List[str]):
        self.schwab = schwab_api
        self.polygon = polygon
        self.watchlist = watchlist

        # State
        self.gex_cache: Dict[str, GEXProfile] = {}
        self.flow_history: Dict[str, list] = {}
        self.last_alert: Dict[str, float] = {}
        self.signals: List[FlowSignal] = []

        # MM Intel v3 State
        self.inventory_tracker: Dict[str, float] = {} # Kalman-filtered $I_t$
        self.inventory_z: Dict[str, float] = {}       # Z-score of inventory
        self.inventory_history: Dict[str, deque] = {} # For z-score calculation
        self.hjb_hedge_rate: Dict[str, float] = {}    # u* (optimal control)
        
        # Kalman / HJB parameters — all configurable per AGENT_LAW §2 (no hidden magic numbers).
        # MM_KALMAN_GAIN  (0.65): Weight on latest observation vs. prior estimate.
        #                         Higher = faster to new data; lower = smoother.
        # MM_KALMAN_LAMBDA (0.15): Inventory mean-reversion decay rate per bar.
        # MM_INV_HOLD_COST (0.10): Quadratic cost coefficient for holding inventory (c in HJB).
        # MM_MARKET_IMPACT (0.50): Linear market-impact coefficient (κ in Avellaneda-Stoikov).
        self.k_gain = float(os.getenv('MM_KALMAN_GAIN', '0.65'))
        self.lambd = float(os.getenv('MM_KALMAN_LAMBDA', '0.15'))
        self.c_inv = float(os.getenv('MM_INV_HOLD_COST', '0.1'))
        self.kappa = float(os.getenv('MM_MARKET_IMPACT', '0.5'))

        # Minimum premium threshold for detecting institutional blocks ($ value).
        # Configurable via environment variable MIN_PREMIUM_THRESHOLD (default: $1M).
        # Used in extract_unusual_flow to filter high-value option trades.
        self.min_premium = float(os.getenv('MIN_PREMIUM_THRESHOLD', '1000000.0'))
        self.is_running = False

    async def run_forever(self):
        """Main loop — 60 second refresh cycle."""
        self.is_running = True
        logger.info("[GAMMA] MM Intel v3 Engine Started — Kalman + HJB + Zero Gamma")
        while self.is_running:
            for ticker in self.watchlist:
                try:
                    await self.process_ticker(ticker)
                except Exception as e:
                    logger.error(f"[GAMMA] Error {ticker}: {e}")
            await asyncio.sleep(20)  # RELAXED: 20 seconds (was 60s) for faster gamma scanning

    async def process_ticker(self, ticker: str):
        # 1. Get spot price
        spot_data = self.polygon.get_last_trade(ticker)
        spot = float(spot_data.get('price', 0))
        if spot <= 0:
            return

        # 2. Get GEX Profile
        raw_chain = self.schwab.get_option_chains(ticker)
        if not raw_chain or 'error' in raw_chain:
            return

        profile = calculate_gex_profile(raw_chain, spot, ticker)
        if not profile:
            return

        # 3. MM Intel v3 Core: Kalman + HJB
        self._update_mm_intel(ticker, raw_chain, spot)

        # 4. Check for gamma flip
        old_profile = self.gex_cache.get(ticker)
        if old_profile and old_profile.profile_shape != profile.profile_shape:
            await self._signal_gamma_flip(ticker, spot, profile, old_profile)

        self.gex_cache[ticker] = profile

        # 5. Detect unusual flow
        recent_unusual = self.extract_unusual_flow(raw_chain, spot)

        if recent_unusual:
            await self.analyze_fusion(ticker, spot, profile, recent_unusual)

        # 6. Check pin risk
        await self._check_pin_risk(ticker, spot, profile, raw_chain)

    def _update_mm_intel(self, ticker: str, raw_chain: Dict, spot: float):
        """Implement MM Intel v3 institutional logic."""
        # A) Net Flow Calculation (Proxy from Chain Vol)
        net_flow = 0.0
        call_map = raw_chain.get('callExpDateMap', {})
        put_map = raw_chain.get('putExpDateMap', {})
        
        for opt_map, sign in [(call_map, 1), (put_map, -1)]:
            if not isinstance(opt_map, dict): continue
            for exp in opt_map:
                strikes = opt_map[exp]
                if not isinstance(strikes, dict): continue
                for strk in strikes:
                    contracts = strikes[strk]
                    if not isinstance(contracts, list): continue
                    for opt in contracts:
                        if not isinstance(opt, dict): continue
                        v = float(opt.get('totalVolume', 0) or 0)
                        p = float(opt.get('lastPrice', 0) or 0)
                        # Positive flow = retail BUY calls = MM getting SHORT delta/gamma
                        net_flow += v * p * 100.0 * sign

        # B) Kalman Filter for Inventory (I_t) - Pine v3 logic
        prev_i = self.inventory_tracker.get(ticker, 0.0)
        # Prediction: pred_inv = prev_i * (1 - lambda)
        pred_i = prev_i * (1.0 - self.lambd)
        # Correction: MM absorbtion: mm_pos = -net_flow
        current_i = pred_i + self.k_gain * (-net_flow - pred_i)
        self.inventory_tracker[ticker] = current_i
        
        # C) Z-Score for Stress
        if ticker not in self.inventory_history:
            self.inventory_history[ticker] = deque(maxlen=200)
        self.inventory_history[ticker].append(current_i)
        
        hist = list(self.inventory_history[ticker])
        if len(hist) > 10:
            arr = [float(x) for x in hist]
            avg = sum(arr) / len(arr)
            std = (sum([(x - avg)**2 for x in arr]) / len(arr))**0.5
            self.inventory_z[ticker] = (current_i - avg) / (std + 1.0)
        else:
            self.inventory_z[ticker] = 0.0
            
        # D) HJB Optimal Hedge Rate (u*) - Pine v3 Riccati steady-state
        riccati_p = math.sqrt(self.c_inv * self.kappa)
        inv_z = self.inventory_z.get(ticker, 0.0)
        self.hjb_hedge_rate[ticker] = -(1.0 / self.kappa) * riccati_p * inv_z
        
        # E) Gamma Pressure & Strike Magnets (v3)
        self._update_gamma_pressure(ticker, spot, raw_chain)

    def _update_gamma_pressure(self, ticker: str, spot: float, raw_chain: Dict):
        """Institutional Gamma Pinning & Magnetic Strike Detection."""
        # 1. Strike Grid
        if spot > 200: inc = 10.0
        elif spot > 25: inc = 2.5
        elif spot > 5: inc = 1.0
        else: inc = 0.5
        
        s_below = math.floor(spot / inc) * inc
        s_above = s_below + inc
        dist_b = abs(spot - s_below)
        dist_a = abs(spot - s_above)
        nearest = s_below if dist_b < dist_a else s_above
        dist_to_strike = min(dist_b, dist_a)
        
        # ATR estimation: use institutional proxy % if real ATR unavailable.
        # Proxy multiplier moved to config (Default: 2% of spot).
        atr_proxy_mult = float(os.getenv('MM_ATR_PROXY_MULT', '0.02'))
        atr = atr_proxy_mult * spot
        logger.debug(f"[GAMMA] {ticker}: Using [ESTIMATED_PROXY] ATR = {atr:.4f} ({atr_proxy_mult*100}% of spot)")
        pin_range = max(atr * 0.5, inc * 0.55)
        near_strike = dist_to_strike < pin_range
        
        # 3. Gamma Intensity
        # Pull volume ratio from profile or chain
        profile = self.gex_cache.get(ticker)
        # Volume ratio proxy: compute from GEX intensity if available, else mark as estimated.
        vol_ratio = 1.0
        if profile:
            # Estimated volume ratio from GEX intensity magnitude
            vol_ratio = 1.0 + (abs(profile.total_gex) / 1e6)
            logger.debug(f"[GAMMA] {ticker}: Computed vol_ratio = {vol_ratio:.4f} from GEX intensity")
        else:
            logger.warning(f"[GAMMA] {ticker}: No profile available; using default vol_ratio = 1.0")
            
        gamma_intensity = vol_ratio if near_strike else 0.0
        
        # 4. Total Pressure Synthesis
        abs_inv_z = abs(self.inventory_z.get(ticker, 0.0))
        # dealer_gamma proxy from total GEX
        total_gex = profile.total_gex if profile else 0.0
        dealer_gamma = abs(total_gex) / (spot * 0.01 + 0.001)
        
        # Pine v3: totalTotalGammaPressure = dealerGamma * absInvZ * (0.5 + volRegime)
        # Vol regime derived from ATM IV surface in the GEX profile.
        # Maps IV to 0-1 scale: 0.15 IV = 0.0 (calm), 0.80+ IV = 1.0 (volatile)
        if profile and profile.iv_surface_avg > 0:
            iv_avg = profile.iv_surface_avg
            vol_regime = max(0.0, min(1.0, (iv_avg - 0.15) / 0.65))
            logger.debug(f"[GAMMA] {ticker}: vol_regime = {vol_regime:.3f} from ATM IV surface ({iv_avg:.2f})")
        else:
            vol_regime = 0.5
            logger.debug(f"[GAMMA] {ticker}: Using fallback vol_regime = 0.5 (no IV surface data)")
        total_pressure = (dealer_gamma / 1e5) * abs_inv_z * (0.5 + vol_regime)
        
        # Store for profile
        if not hasattr(self, 'gamma_pressure'): self.gamma_pressure = {}
        if not hasattr(self, 'nearest_strike'): self.nearest_strike = {}
        
        self.gamma_pressure[ticker] = total_pressure
        self.nearest_strike[ticker] = nearest

    def extract_unusual_flow(self, raw_chain, spot):
        """Scan chain for institutional blocks (Vol > OI + High Premium)."""
        unusual = []
        call_map = raw_chain.get('callExpDateMap', {})
        put_map = raw_chain.get('putExpDateMap', {})
        today = datetime.now()

        def scan(opt_map, opt_type):
            if not isinstance(opt_map, dict): return
            for exp_key, strikes in opt_map.items():
                dte = 30
                if ':' in str(exp_key):
                    try:
                        exp_str = str(exp_key).split(':')[0]
                        exp_dt = datetime.strptime(exp_str, '%Y-%m-%d')
                        dte = max(0, (exp_dt - today).days)
                    except Exception as e:
                        logger.warning(f"Failed to parse expiry date '{exp_key}': {e}; using default DTE={dte}")

                if not isinstance(strikes, dict): continue
                for strk_str, contracts in strikes.items():
                    if not isinstance(contracts, list): continue
                    for opt in contracts:
                        if not isinstance(opt, dict): continue
                        vol = int(opt.get('totalVolume', 0) or 0)
                        oi = int(opt.get('openInterest', 0) or 0)
                        if oi <= 0: oi = 1
                        last = float(opt.get('lastPrice', 0) or 0)
                        prem = vol * last * 100.0

                        if prem > self.min_premium and vol > oi:
                            unusual.append({
                                'strike': float(strk_str),
                                'type': opt_type,
                                'vol': vol,
                                'oi': oi,
                                'premium': prem,
                                'last': last,
                                'delta': float(opt.get('delta', 0) or 0),
                                'dte': dte,
                                'iv': float(opt.get('volatility', 0) or 0) / 100.0
                            })
        scan(call_map, 'CALL')
        scan(put_map, 'PUT')
        return unusual

    async def analyze_fusion(self, ticker, spot, profile, flow_list):
        """Analyze flow against GEX profile for signal generation."""
        if not flow_list: return
        top = max(flow_list, key=lambda x: x['premium'])

        dte = float(top.get('dte', 30))
        dte_mult = max(1.0, 3.0 - (dte / 10.0))
        vol_oi_score = min(50.0, (float(top['vol']) / float(top['oi'])) * 10.0)
        prem_score = min(30.0, (float(top['premium']) / 1e6) * 20.0)
        urgency = min(100.0, (vol_oi_score + prem_score) * dte_mult)

        iv = float(top.get('iv', 0.30))
        conf = 'high' if urgency >= 75 and iv > 0.5 else ('medium' if urgency >= 50 else 'low')

        if profile.profile_shape == 'short_gamma' and top['type'] == 'CALL':
            if spot > profile.zero_gamma_line:
                await self.dispatch_signal(FlowSignal(
                    ticker=ticker, timestamp=datetime.now(),
                    signal_type='gamma_squeeze_setup',
                    strike=float(top['strike']),
                    gex_at_strike=float(profile.by_strike.get(top['strike'], 0)),
                    spot_price=spot, urgency_score=urgency,
                    expected_move=float(profile.expected_move),
                    confidence=conf
                ))

        elif profile.profile_shape == 'long_gamma' and top['type'] == 'PUT':
            if abs(spot - profile.put_wall) / spot < 0.03:
                await self.dispatch_signal(FlowSignal(
                    ticker=ticker, timestamp=datetime.now(),
                    signal_type='gamma_support_bounce',
                    strike=float(profile.put_wall),
                    gex_at_strike=float(profile.by_strike.get(profile.put_wall, 0)),
                    spot_price=spot, urgency_score=urgency,
                    expected_move=float(profile.expected_move),
                    confidence=conf
                ))

    async def _signal_gamma_flip(self, ticker, spot, profile, old_profile):
        signal = FlowSignal(
            ticker=ticker, timestamp=datetime.now(),
            signal_type='gamma_flip',
            strike=float(profile.zero_gamma_line),
            gex_at_strike=0.0,
            spot_price=spot, urgency_score=80.0 if profile.profile_shape == 'short_gamma' else 60.0,
            expected_move=float(profile.expected_move),
            confidence='high' if profile.profile_shape == 'short_gamma' else 'medium'
        )
        await self.dispatch_signal(signal)

    async def _check_pin_risk(self, ticker, spot, profile, raw_chain):
        today = datetime.now()
        maps = [raw_chain.get('callExpDateMap', {}), raw_chain.get('putExpDateMap', {})]
        for m in maps:
            if not isinstance(m, dict): continue
            for exp in m:
                if ':' not in str(exp): continue
                try:
                    dt = datetime.strptime(str(exp).split(':')[0], '%Y-%m-%d')
                    if 0 <= (dt - today).days <= 2:
                        if abs(spot - profile.max_oi_strike) / spot < 0.005:
                            await self.dispatch_signal(FlowSignal(
                                ticker=ticker, timestamp=datetime.now(),
                                signal_type='pin_risk',
                                strike=float(profile.max_oi_strike),
                                gex_at_strike=float(profile.by_strike.get(profile.max_oi_strike, 0)),
                                spot_price=spot, urgency_score=90.0,
                                expected_move=0.005,
                                confidence='high'
                            ))
                        return
                except Exception as e:
                    logger.warning(f"Failed to check pin risk for expiry '{exp}': {e}")
                    continue

    async def dispatch_signal(self, signal: FlowSignal):
        now = time.time()
        k = f"{signal.ticker}_{signal.signal_type}"
        if now - self.last_alert.get(k, 0) < 300: return
        self.last_alert[k] = now
        self.signals.append(signal)
        if len(self.signals) > 200: self.signals = self.signals[-100:]
        logger.info(f"🚨 [SIGNAL] {signal.ticker} {signal.signal_type} @ ${signal.spot_price:.2f}")

    def get_latest_signals(self):
        res = []
        for s in self.signals:
            d = s.__dict__.copy()
            d['timestamp'] = d['timestamp'].isoformat() if isinstance(d['timestamp'], datetime) else d['timestamp']
            res.append(d)
        return res

    def get_ticker_profile(self, ticker):
        if ticker not in self.gex_cache: return None
        p = self.gex_cache[ticker]
        return {
            'ticker': p.ticker, 'spot_price': p.spot_price, 'total_gex': p.total_gex,
            'profile_shape': p.profile_shape, 'max_gamma_strike': p.max_gamma_strike,
            'min_gamma_strike': p.min_gamma_strike, 'zero_gamma_line': p.zero_gamma_line,
            'max_oi_strike': p.max_oi_strike, 'call_wall': p.call_wall, 'put_wall': p.put_wall,
            'gamma_notional': p.gamma_notional, 'expected_move': p.expected_move,
            'iv_surface_avg': p.iv_surface_avg, 'timestamp': p.timestamp,
            'inventory_z': self.inventory_z.get(ticker, 0.0),
            'hjb_hedge_rate': self.hjb_hedge_rate.get(ticker, 0.0),
            'gamma_pressure': getattr(self, 'gamma_pressure', {}).get(ticker, 0.0),
            'nearest_strike': getattr(self, 'nearest_strike', {}).get(ticker, 0.0),
            'by_strike': {str(k): v for k, v in p.by_strike.items()}
        }

    # ═══════════════════════════════════════════════════════════════
    # SML MARKET MAKER INTELLIGENCE v3 INTEGRATION
    # ═══════════════════════════════════════════════════════════════

    def _compute_sma(self, values: list, period: int) -> float:
        """Compute simple moving average of last N values."""
        if not values or len(values) < period:
            return sum(values) / len(values) if values else 0.0
        return sum(values[-period:]) / period

    def _compute_stdev(self, values: list, period: int) -> float:
        """Compute standard deviation of last N values."""
        if not values or len(values) < period:
            actual_vals = values
        else:
            actual_vals = values[-period:]

        if len(actual_vals) < 2:
            return 0.0

        mean = sum(actual_vals) / len(actual_vals)
        variance = sum([(x - mean)**2 for x in actual_vals]) / len(actual_vals)
        return math.sqrt(variance)

    def _compute_atr(self, bars: list, period: int = 14) -> float:
        """Compute Average True Range from OHLCV bars."""
        if len(bars) < period:
            return 0.0

        tr_values = []
        for bar in bars[-period:]:
            high = float(bar.get('high', 0))
            low = float(bar.get('low', 0))
            close_prev = float(bar.get('close', 0))

            tr = max(
                high - low,
                abs(high - close_prev) if close_prev else 0,
                abs(low - close_prev) if close_prev else 0
            )
            tr_values.append(tr)

        return sum(tr_values) / len(tr_values) if tr_values else 0.0

    def compute_mm_intelligence(self, symbol: str, bars: list) -> dict:
        """
        Compute full SML Market Maker Intelligence v3 analysis from OHLCV bars.

        Args:
            symbol: Ticker symbol
            bars: List of OHLCV bar dicts with keys: open, high, low, close, volume

        Returns:
            dict with keys:
                - inv_z: Inventory z-score
                - flow_quality: Quality of flow (0.3-0.9)
                - flow_type: 'absorption', 'conviction', 'normal', or 'weak'
                - optimal_hedge_rate: HJB optimal control u*
                - gamma_pressure: Total gamma pressure metric
                - signal: 'LONG', 'SHORT', or 'NONE'
                - signal_confidence: Confidence 0-99
                - tactical_target: Tactical price target
                - structural_target: Structural price target
                - mm_pain_level: MM discomfort level
                - strike_pin: Nearest pinning strike and distance
        """

        if not bars or len(bars) < 20:
            logger.warning(f"[MM Intel v3] Insufficient bars for {symbol}: need 20+, got {len(bars)}")
            return self._empty_mm_result()

        # Extract OHLCV data
        opens = [float(b.get('open', 0)) for b in bars]
        highs = [float(b.get('high', 0)) for b in bars]
        lows = [float(b.get('low', 0)) for b in bars]
        closes = [float(b.get('close', 0)) for b in bars]
        volumes = [float(b.get('volume', 0)) for b in bars]

        spot_price = closes[-1]
        if spot_price <= 0:
            return self._empty_mm_result()

        # ===== STEP 1: KALMAN-FILTERED INVENTORY ESTIMATION =====
        inventory_estimates = []
        inventory_variance = 0.0

        lambda_param = 0.15
        sigma_flow = 1.0

        for i, bar in enumerate(bars):
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]
            v = volumes[i]

            # Compute range and flow
            range_val = h - l + 0.001
            buy_flow = v * (c - o) / range_val if c > o else 0.0
            sell_flow = v * (o - c) / range_val if c < o else 0.0
            net_flow = buy_flow - sell_flow
            mm_position = -net_flow  # MM takes opposite side

            # Kalman prediction
            pred_inv = inventory_estimates[-1] * (1.0 - lambda_param) if inventory_estimates else 0.0
            pred_var = inventory_variance + sigma_flow**2

            # Kalman correction
            kalman_gain = pred_var / (pred_var + sigma_flow**2)
            current_inv = pred_inv + kalman_gain * (mm_position - pred_inv)
            inventory_variance = (1.0 - kalman_gain) * pred_var

            inventory_estimates.append(current_inv)

        # Compute inventory z-score
        inv_sma = self._compute_sma(inventory_estimates, 100)
        inv_stdev = self._compute_stdev(inventory_estimates, 100)
        inv_z = (inventory_estimates[-1] - inv_sma) / (inv_stdev + 0.0001)

        # ===== STEP 2: FLOW QUALITY FILTER =====
        vol_sma = self._compute_sma(volumes, 20)
        vol_stdev = self._compute_stdev(volumes, 20)
        vol_z = (volumes[-1] - vol_sma) / (vol_stdev + 0.0001)

        h_last = highs[-1]
        l_last = lows[len(lows) - 1]
        o_last = opens[-1]
        c_last = closes[-1]
        range_last = h_last - l_last + 0.001
        body_pct = abs(c_last - o_last) / range_last

        absorption = vol_z > 1.5 and body_pct < 0.3
        conviction = vol_z > 1.5 and body_pct > 0.6

        if absorption:
            flow_quality = 0.9
            flow_type = 'absorption'
        elif conviction:
            flow_quality = 0.8
            flow_type = 'conviction'
        elif vol_z > 0.5:
            flow_quality = 0.5
            flow_type = 'normal'
        else:
            flow_quality = 0.3
            flow_type = 'weak'

        # ===== STEP 3: HJB OPTIMAL CONTROL (Riccati Solution) =====
        c_inv = 0.1
        kappa = 0.5
        gamma_term = 1.0

        riccati_p = math.sqrt(c_inv * kappa)
        optimal_hedge_z = -(1.0 / kappa) * riccati_p * inv_z

        atr = self._compute_atr(bars, 14)
        if atr <= 0:
            atr = spot_price * 0.02  # Fallback to 2% of price

        optimal_hedge_rate = optimal_hedge_z * atr

        # ===== STEP 4: GAMMA EXPOSURE SYNTHESIS =====
        # Determine strike increment
        if spot_price > 200:
            strike_increment = 10.0
        elif spot_price > 25:
            strike_increment = 2.5
        elif spot_price > 5:
            strike_increment = 1.0
        else:
            strike_increment = 0.5

        # Find nearest strike
        s_below = math.floor(spot_price / strike_increment) * strike_increment
        s_above = s_below + strike_increment
        dist_below = abs(spot_price - s_below)
        dist_above = abs(spot_price - s_above)
        nearest_strike = s_below if dist_below < dist_above else s_above
        dist_to_strike = min(dist_below, dist_above)

        # Pin range and gamma intensity
        pin_range = max(atr * 0.5, strike_increment * 0.55)
        near_strike = dist_to_strike < pin_range

        vol_avg = self._compute_sma(volumes, 20)
        gamma_intensity = (volumes[-1] / (vol_avg + 0.0001)) if near_strike else 0.0

        # Dealer gamma
        atr_pct = atr / spot_price if spot_price > 0 else 0.01
        dealer_gamma = gamma_intensity / (atr_pct + 0.001)

        # Volume regime (0-1 scale)
        vol_regime = min(1.0, vol_z / 2.0) if vol_z > 0 else 0.5

        total_gamma_pressure = dealer_gamma * abs(inv_z) * (0.5 + vol_regime)

        # ===== STEP 5: SIGNAL GENERATION =====
        z_critical = 2.0
        gamma_thresh = 0.5

        critical_long = inv_z > z_critical
        critical_short = inv_z < -z_critical
        gamma_critical = total_gamma_pressure > gamma_thresh

        if critical_short and gamma_critical:
            signal = 'LONG'  # MM must buy = price goes up
        elif critical_long and gamma_critical:
            signal = 'SHORT'  # MM must sell = price goes down
        else:
            signal = 'NONE'

        control_stress = abs(optimal_hedge_z)
        signal_confidence = min(99, int(control_stress * 20 * flow_quality))

        # ===== STEP 6: DUAL PRICE TARGETS =====
        tactical_target = c_last + optimal_hedge_z * atr * 0.5

        # Structural target uses decaying imbalance accumulator
        structural_imbalance = sum([
            (inventory_estimates[i] * math.exp(-0.05 * (len(inventory_estimates) - 1 - i)))
            for i in range(len(inventory_estimates))
        ])
        structural_target = c_last + (structural_imbalance / (abs(structural_imbalance) + 0.0001)) * atr

        # ===== MM PAIN LEVEL =====
        # How uncomfortable MM is (higher = more pressure to move market)
        mm_pain_level = min(100, int(abs(inv_z) * 30 + total_gamma_pressure * 50))

        return {
            'inv_z': round(inv_z, 4),
            'flow_quality': round(flow_quality, 4),
            'flow_type': flow_type,
            'optimal_hedge_rate': round(optimal_hedge_rate, 4),
            'gamma_pressure': round(total_gamma_pressure, 4),
            'signal': signal,
            'signal_confidence': signal_confidence,
            'tactical_target': round(tactical_target, 2),
            'structural_target': round(structural_target, 2),
            'mm_pain_level': mm_pain_level,
            'strike_pin': {
                'nearest_strike': round(nearest_strike, 2),
                'distance': round(dist_to_strike, 4),
                'is_near': near_strike,
                'pin_range': round(pin_range, 4)
            }
        }

    def compute_mm_intelligence_from_quotes(self, symbol: str, quotes_history: list) -> dict:
        """
        Convenience wrapper for MM Intelligence computation from quote history.

        Converts quote objects (with bid/ask) into synthetic OHLCV bars.
        Each quote becomes a bar where open=bid, close=ask, high=max(bid,ask), low=min(bid,ask).

        Args:
            symbol: Ticker symbol
            quotes_history: List of quote dicts with keys: bid, ask, timestamp (optional), volume (optional)

        Returns:
            Same dict as compute_mm_intelligence()
        """
        if not quotes_history or len(quotes_history) < 20:
            return self._empty_mm_result()

        bars = []
        for q in quotes_history:
            bid = float(q.get('bid', 0))
            ask = float(q.get('ask', 0))
            volume = float(q.get('volume', 100))

            if bid <= 0 or ask <= 0:
                continue

            bar = {
                'open': bid,
                'close': ask,
                'high': max(bid, ask),
                'low': min(bid, ask),
                'volume': volume
            }
            bars.append(bar)

        return self.compute_mm_intelligence(symbol, bars)

    def _empty_mm_result(self) -> dict:
        """Return empty/neutral MM Intelligence result."""
        return {
            'inv_z': 0.0,
            'flow_quality': 0.3,
            'flow_type': 'weak',
            'optimal_hedge_rate': 0.0,
            'gamma_pressure': 0.0,
            'signal': 'NONE',
            'signal_confidence': 0,
            'tactical_target': 0.0,
            'structural_target': 0.0,
            'mm_pain_level': 0,
            'strike_pin': {
                'nearest_strike': 0.0,
                'distance': 0.0,
                'is_near': False,
                'pin_range': 0.0
            }
        }
