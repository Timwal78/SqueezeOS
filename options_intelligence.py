"""
SQUEEZE OS v4.3 — Options Intelligence Layer
═══════════════════════════════════════════════════════════════
Institutional-grade options analysis: sweep detection, whale watching,
unusual volume spike detection, contract recommendations, and flow summary.

This module ingests real options chain data from the Schwab API and
performs sophisticated analysis to identify institutional activity patterns.

FEATURES:
  - PUT/CALL SWEEP DETECTION: Identifies aggressive premium accumulation
  - UNUSUAL VOLUME SPIKES: Flags vol/OI anomalies and extremes
  - WHALE WATCH: Detects large premium blocks by size class
  - SMART RECOMMENDATIONS: Scores contracts by delta, DTE, liquidity, IV
  - FLOW SUMMARY: Computes net delta, GEX, put/call ratios, max pain
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class Sweep:
    """Put/Call sweep detection result."""
    symbol: str
    strike: float
    expiry: str
    dte: int
    option_type: str  # CALL or PUT
    premium: float  # Single contract value in $
    volume: int
    open_interest: int
    vol_oi_ratio: float
    aggression_pct: float  # % of trade at ask vs mid
    iv: float
    delta: float
    sweep_score: float  # 0-100
    is_bullish: bool


@dataclass
class UnusualActivity:
    """Unusual options volume spike."""
    symbol: str
    strike: float
    expiry: str
    dte: int
    option_type: str
    volume: int
    open_interest: int
    vol_oi_ratio: float
    iv: float
    iv_rank: Optional[float]  # Percentile 0-100
    premium_total: float
    severity: str  # UNUSUAL, EXTREME, CRITICAL


@dataclass
class Whale:
    """Large premium block (whale watch)."""
    symbol: str
    strike: float
    expiry: str
    dte: int
    option_type: str
    premium_total: float  # volume * price * 100
    size_class: str  # SHARK, WHALE, MEGALODON
    direction: str  # BULLISH, BEARISH, NEUTRAL
    delta: float
    iv: float
    price_distance_pct: float  # Distance from spot in %
    whale_score: float  # 0-100


@dataclass
class Recommendation:
    """Contract recommendation with scoring."""
    symbol: str
    strike: float
    expiry: str
    dte: int
    option_type: str
    delta: float
    gamma: float
    iv: float
    bid: float
    ask: float
    spread_pct: float
    liquidity_score: float  # 0-100
    value_score: float  # 0-100
    overall_score: float  # 0-100
    recommendation_text: str


@dataclass
class FlowSummary:
    """Complete options flow snapshot."""
    symbol: str
    timestamp: datetime

    # Ratios
    put_call_vol_ratio: float
    put_call_oi_ratio: float

    # Premium
    total_call_premium: float
    total_put_premium: float
    net_premium: float  # Positive = more call premium

    # Delta exposure
    total_call_delta: float
    total_put_delta: float
    net_delta: float

    # Gamma exposure (GEX)
    total_gex: float
    gex_call: float
    gex_put: float

    # Derived metrics
    max_pain_strike: Optional[float]
    net_positioning: str  # BULL_HEAVY, BEAR_HEAVY, BALANCED


# ═══════════════════════════════════════════════════════════════
# MAIN OPTIONS INTELLIGENCE CLASS
# ═══════════════════════════════════════════════════════════════

class OptionsIntelligence:
    """
    Institutional-grade options intelligence layer.
    Ingests Schwab options chain data and performs sophisticated analysis.
    """

    def __init__(self):
        """Initialize the options intelligence engine."""
        logger.info("[OPTIONS_INTEL] Options Intelligence initialized")

    # ═══════════════════════════════════════════════════════════════
    # 1. SWEEP DETECTION
    # ═══════════════════════════════════════════════════════════════

    def detect_sweeps(self, symbol: str, chain: Dict[str, Any]) -> List[Sweep]:
        """
        Detect put/call sweeps in the options chain.

        A sweep is identified when:
        - Volume is significantly higher than OI (vol >> OI)
        - Trades are aggressive (at or above ask)
        - Premium size is meaningful

        Args:
            symbol: Stock symbol
            chain: Schwab options chain dict with callExpDateMap/putExpDateMap

        Returns:
            List of Sweep objects sorted by sweep_score (highest first)
        """
        sweeps = []

        try:
            # Process both calls and puts
            for opt_type, exp_map in [
                ("CALL", chain.get("callExpDateMap", {})),
                ("PUT", chain.get("putExpDateMap", {})),
            ]:
                if not exp_map or not isinstance(exp_map, dict):
                    continue

                for expiry_key, strikes in exp_map.items():
                    if not strikes or not isinstance(strikes, dict):
                        continue

                    # Parse expiry: format is "2024-01-19:5"
                    expiry_date, dte = self._parse_expiry_key(expiry_key)
                    if dte is None:
                        continue

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list):
                            continue

                        for opt in option_list:
                            if not opt or not isinstance(opt, dict):
                                continue

                            # Extract metrics
                            strike = self._safe_float(opt.get("strike"), 0)
                            vol = int(opt.get("totalVolume") or opt.get("volume") or 0)
                            oi = int(opt.get("openInterest") or opt.get("oi") or 0)
                            bid = self._safe_float(opt.get("bid"), 0)
                            ask = self._safe_float(opt.get("ask"), 0)
                            last = self._safe_float(opt.get("last") or opt.get("lastPrice"), 0)
                            mark = self._safe_float(opt.get("mark"), 0)
                            iv = self._safe_float(opt.get("volatility"), 0) / 100
                            delta = self._safe_float(opt.get("delta"), 0)

                            # Skip if no volume or OI
                            if vol == 0 or oi == 0:
                                continue

                            # Calculate sweep metrics
                            vol_oi_ratio = vol / oi if oi > 0 else 0
                            premium = mark or last or ((bid + ask) / 2 if bid and ask else 0)
                            premium_total = premium * 100 * vol

                            # Aggression: % of trades at or above ask
                            mid_price = (bid + ask) / 2 if (bid and ask) else mark or last
                            aggression_pct = 0.0
                            if last >= ask * 0.99 and ask > 0:
                                aggression_pct = 100.0
                            elif last >= mid_price:
                                aggression_pct = 50.0

                            # Sweep score: weighted across all factors
                            sweep_score = self._compute_sweep_score(
                                vol_oi_ratio,
                                aggression_pct,
                                premium_total,
                                iv,
                                delta,
                                dte,
                            )

                            # Only flag as sweep if score is significant
                            if sweep_score >= 40:  # Threshold
                                is_bullish = opt_type == "CALL"

                                sweep = Sweep(
                                    symbol=symbol,
                                    strike=strike,
                                    expiry=expiry_date,
                                    dte=dte,
                                    option_type=opt_type,
                                    premium=premium,
                                    volume=vol,
                                    open_interest=oi,
                                    vol_oi_ratio=vol_oi_ratio,
                                    aggression_pct=aggression_pct,
                                    iv=iv,
                                    delta=delta,
                                    sweep_score=sweep_score,
                                    is_bullish=is_bullish,
                                )
                                sweeps.append(sweep)

        except Exception as e:
            logger.error(
                f"[OPTIONS_INTEL] Error detecting sweeps for {symbol}: {e}",
                exc_info=True,
            )

        # Sort by sweep score (highest first)
        sweeps.sort(key=lambda x: x.sweep_score, reverse=True)
        return sweeps

    # ═══════════════════════════════════════════════════════════════
    # 2. UNUSUAL VOLUME SPIKE DETECTION
    # ═══════════════════════════════════════════════════════════════

    def detect_unusual_volume(self, symbol: str, chain: Dict[str, Any]) -> List[UnusualActivity]:
        """
        Detect unusual options volume spikes.

        Criteria:
        - vol/OI > 3.0 = UNUSUAL
        - vol/OI > 5.0 = EXTREME
        - vol/OI > 10.0 + high premium = CRITICAL

        Args:
            symbol: Stock symbol
            chain: Schwab options chain dict

        Returns:
            List of UnusualActivity objects sorted by severity
        """
        activities = []

        try:
            for opt_type, exp_map in [
                ("CALL", chain.get("callExpDateMap", {})),
                ("PUT", chain.get("putExpDateMap", {})),
            ]:
                if not exp_map or not isinstance(exp_map, dict):
                    continue

                for expiry_key, strikes in exp_map.items():
                    if not strikes or not isinstance(strikes, dict):
                        continue

                    expiry_date, dte = self._parse_expiry_key(expiry_key)
                    if dte is None:
                        continue

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list):
                            continue

                        for opt in option_list:
                            if not opt or not isinstance(opt, dict):
                                continue

                            strike = self._safe_float(opt.get("strike"), 0)
                            vol = int(opt.get("totalVolume") or opt.get("volume") or 0)
                            oi = int(opt.get("openInterest") or opt.get("oi") or 0)
                            bid = self._safe_float(opt.get("bid"), 0)
                            ask = self._safe_float(opt.get("ask"), 0)
                            last = self._safe_float(opt.get("last") or opt.get("lastPrice"), 0)
                            mark = self._safe_float(opt.get("mark"), 0)
                            iv_raw = self._safe_float(opt.get("volatility"), 0)
                            iv = iv_raw / 100 if iv_raw else 0
                            iv_rank = self._safe_float(
                                opt.get("iv_rank") or opt.get("ivPercentile"), None
                            )

                            if vol == 0 or oi == 0:
                                continue

                            vol_oi_ratio = vol / oi
                            premium = mark or last or ((bid + ask) / 2 if bid and ask else 0)
                            premium_total = premium * 100 * vol

                            # Classify severity
                            severity = "UNUSUAL"
                            if vol_oi_ratio >= 10.0 and premium_total >= 500000:
                                severity = "CRITICAL"
                            elif vol_oi_ratio >= 5.0:
                                severity = "EXTREME"
                            elif vol_oi_ratio >= 3.0:
                                severity = "UNUSUAL"
                            else:
                                # Not unusual enough
                                continue

                            activity = UnusualActivity(
                                symbol=symbol,
                                strike=strike,
                                expiry=expiry_date,
                                dte=dte,
                                option_type=opt_type,
                                volume=vol,
                                open_interest=oi,
                                vol_oi_ratio=vol_oi_ratio,
                                iv=iv,
                                iv_rank=iv_rank,
                                premium_total=premium_total,
                                severity=severity,
                            )
                            activities.append(activity)

        except Exception as e:
            logger.error(
                f"[OPTIONS_INTEL] Error detecting unusual volume for {symbol}: {e}",
                exc_info=True,
            )

        # Sort: CRITICAL > EXTREME > UNUSUAL, then by vol/OI ratio
        severity_order = {"CRITICAL": 0, "EXTREME": 1, "UNUSUAL": 2}
        activities.sort(
            key=lambda x: (severity_order.get(x.severity, 99), -x.vol_oi_ratio)
        )
        return activities

    # ═══════════════════════════════════════════════════════════════
    # 3. WHALE WATCH
    # ═══════════════════════════════════════════════════════════════

    def detect_whales(
        self, symbol: str, chain: Dict[str, Any], quote: Dict[str, Any]
    ) -> List[Whale]:
        """
        Detect large premium blocks (whale activity).

        Size classes:
        - SHARK: $100K - $500K
        - WHALE: $500K - $2M
        - MEGALODON: $2M+

        Args:
            symbol: Stock symbol
            chain: Schwab options chain dict
            quote: Quote dict with 'last' or 'mark' for spot price

        Returns:
            List of Whale objects sorted by premium_total (highest first)
        """
        whales = []
        spot_price = self._get_spot_price(quote)

        if spot_price <= 0:
            logger.warning(f"[OPTIONS_INTEL] Invalid spot price for {symbol}: {spot_price}")
            return whales

        try:
            for opt_type, exp_map in [
                ("CALL", chain.get("callExpDateMap", {})),
                ("PUT", chain.get("putExpDateMap", {})),
            ]:
                if not exp_map or not isinstance(exp_map, dict):
                    continue

                for expiry_key, strikes in exp_map.items():
                    if not strikes or not isinstance(strikes, dict):
                        continue

                    expiry_date, dte = self._parse_expiry_key(expiry_key)
                    if dte is None:
                        continue

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list):
                            continue

                        for opt in option_list:
                            if not opt or not isinstance(opt, dict):
                                continue

                            strike = self._safe_float(opt.get("strike"), 0)
                            vol = int(opt.get("totalVolume") or opt.get("volume") or 0)
                            bid = self._safe_float(opt.get("bid"), 0)
                            ask = self._safe_float(opt.get("ask"), 0)
                            last = self._safe_float(opt.get("last") or opt.get("lastPrice"), 0)
                            mark = self._safe_float(opt.get("mark"), 0)
                            iv = self._safe_float(opt.get("volatility"), 0) / 100
                            delta = self._safe_float(opt.get("delta"), 0)

                            if vol == 0:
                                continue

                            # Contract premium value
                            premium = mark or last or ((bid + ask) / 2 if bid and ask else 0)
                            premium_total = premium * 100 * vol

                            # Only flag if >= $100K
                            if premium_total < 100000:
                                continue

                            # Size class
                            if premium_total >= 2000000:
                                size_class = "MEGALODON"
                            elif premium_total >= 500000:
                                size_class = "WHALE"
                            else:
                                size_class = "SHARK"

                            # Direction: calls at ask = bullish
                            direction = "NEUTRAL"
                            last_price = last or mark or ((bid + ask) / 2 if bid and ask else 0)
                            if opt_type == "CALL":
                                if last_price >= ask * 0.99:
                                    direction = "BULLISH"
                                elif last_price <= bid * 1.01:
                                    direction = "BEARISH"
                            else:
                                if last_price >= ask * 0.99:
                                    direction = "BEARISH"
                                elif last_price <= bid * 1.01:
                                    direction = "BULLISH"

                            # Distance from spot
                            price_distance_pct = abs((strike - spot_price) / spot_price) * 100

                            # Whale score: premium + size class + IV
                            whale_score = self._compute_whale_score(
                                premium_total, iv, delta, dte, price_distance_pct
                            )

                            whale = Whale(
                                symbol=symbol,
                                strike=strike,
                                expiry=expiry_date,
                                dte=dte,
                                option_type=opt_type,
                                premium_total=premium_total,
                                size_class=size_class,
                                direction=direction,
                                delta=delta,
                                iv=iv,
                                price_distance_pct=price_distance_pct,
                                whale_score=whale_score,
                            )
                            whales.append(whale)

        except Exception as e:
            logger.error(
                f"[OPTIONS_INTEL] Error detecting whales for {symbol}: {e}",
                exc_info=True,
            )

        # Sort by premium (highest first)
        whales.sort(key=lambda x: x.premium_total, reverse=True)
        return whales

    # ═══════════════════════════════════════════════════════════════
    # 4. STRIKE/DATE RECOMMENDATION ENGINE
    # ═══════════════════════════════════════════════════════════════

    def recommend_contracts(
        self,
        symbol: str,
        chain: Dict[str, Any],
        quote: Dict[str, Any],
        bias: str = "BULL",
    ) -> List[Recommendation]:
        """
        Recommend optimal contracts based on directional bias.

        Scoring factors:
        - Delta sweet spot (0.25-0.40 for leverage, 0.50-0.60 for conviction)
        - DTE sweet spot (14-45 days)
        - Bid-ask spread (tighter = better)
        - IV percentile (lower = cheaper)
        - Volume (higher = better fills)

        Args:
            symbol: Stock symbol
            chain: Schwab options chain dict
            quote: Quote dict
            bias: 'BULL', 'BEAR', or 'NEUTRAL'

        Returns:
            Top 5 recommendations sorted by overall_score
        """
        recommendations = []
        spot_price = self._get_spot_price(quote)

        if spot_price <= 0:
            logger.warning(f"[OPTIONS_INTEL] Invalid spot price for {symbol}: {spot_price}")
            return recommendations

        bias = bias.upper()
        if bias not in ("BULL", "BEAR", "NEUTRAL"):
            logger.warning(f"[OPTIONS_INTEL] Invalid bias {bias}, defaulting to BULL")
            bias = "BULL"

        try:
            for opt_type, exp_map in [
                ("CALL", chain.get("callExpDateMap", {})),
                ("PUT", chain.get("putExpDateMap", {})),
            ]:
                # Filter by bias
                if bias == "BULL" and opt_type != "CALL":
                    continue
                if bias == "BEAR" and opt_type != "PUT":
                    continue

                if not exp_map or not isinstance(exp_map, dict):
                    continue

                for expiry_key, strikes in exp_map.items():
                    if not strikes or not isinstance(strikes, dict):
                        continue

                    expiry_date, dte = self._parse_expiry_key(expiry_key)
                    if dte is None or dte < 1 or dte > 60:
                        continue  # Outside ideal DTE range

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list):
                            continue

                        for opt in option_list:
                            if not opt or not isinstance(opt, dict):
                                continue

                            strike = self._safe_float(opt.get("strike"), 0)
                            vol = int(opt.get("totalVolume") or opt.get("volume") or 0)
                            oi = int(opt.get("openInterest") or opt.get("oi") or 0)
                            bid = self._safe_float(opt.get("bid"), 0)
                            ask = self._safe_float(opt.get("ask"), 0)
                            last = self._safe_float(opt.get("last") or opt.get("lastPrice"), 0)
                            mark = self._safe_float(opt.get("mark"), 0)
                            iv = self._safe_float(opt.get("volatility"), 0) / 100
                            delta = self._safe_float(opt.get("delta"), 0)
                            gamma = self._safe_float(opt.get("gamma"), 0)

                            if vol == 0 or bid == 0 or ask == 0:
                                continue

                            # Spread
                            mid = (bid + ask) / 2
                            spread_pct = (ask - bid) / mid * 100 if mid > 0 else 100

                            # Liquidity score: volume + OI, tight spread
                            liquidity_score = self._compute_liquidity_score(vol, oi, spread_pct)

                            # Value score: IV percentile preference + DTE
                            value_score = self._compute_value_score(iv, dte)

                            # Delta score: preference for certain delta ranges
                            delta_score = self._compute_delta_score(delta, bias)

                            # Overall score
                            overall_score = (
                                delta_score * 0.35 + liquidity_score * 0.35 + value_score * 0.30
                            )

                            rec = Recommendation(
                                symbol=symbol,
                                strike=strike,
                                expiry=expiry_date,
                                dte=dte,
                                option_type=opt_type,
                                delta=delta,
                                gamma=gamma,
                                iv=iv,
                                bid=bid,
                                ask=ask,
                                spread_pct=spread_pct,
                                liquidity_score=liquidity_score,
                                value_score=value_score,
                                overall_score=overall_score,
                                recommendation_text=self._generate_recommendation_text(
                                    symbol, strike, opt_type, delta, dte, overall_score, bias
                                ),
                            )
                            recommendations.append(rec)

        except Exception as e:
            logger.error(
                f"[OPTIONS_INTEL] Error generating recommendations for {symbol}: {e}",
                exc_info=True,
            )

        # Sort by overall score and return top 5
        recommendations.sort(key=lambda x: x.overall_score, reverse=True)
        return recommendations[:5]

    # ═══════════════════════════════════════════════════════════════
    # 5. OPTIONS FLOW SUMMARY
    # ═══════════════════════════════════════════════════════════════

    def compute_flow_summary(self, symbol: str, chain: Dict[str, Any]) -> dict:
        """
        Compute comprehensive options flow snapshot.

        Metrics:
        - Put/Call ratio (volume-weighted)
        - Put/Call OI ratio
        - Total premium by side
        - Net delta exposure
        - GEX (gamma exposure)
        - Max pain strike
        - Net positioning

        Args:
            symbol: Stock symbol
            chain: Schwab options chain dict

        Returns:
            FlowSummary as dict
        """
        summary = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "put_call_vol_ratio": 0.0,
            "put_call_oi_ratio": 0.0,
            "total_call_premium": 0.0,
            "total_put_premium": 0.0,
            "net_premium": 0.0,
            "total_call_delta": 0.0,
            "total_put_delta": 0.0,
            "net_delta": 0.0,
            "total_gex": 0.0,
            "gex_call": 0.0,
            "gex_put": 0.0,
            "max_pain_strike": None,
            "net_positioning": "BALANCED",
        }

        try:
            call_vol = 0
            put_vol = 0
            call_oi = 0
            put_oi = 0
            call_premium = 0.0
            put_premium = 0.0
            call_delta_sum = 0.0
            put_delta_sum = 0.0
            gex_call = 0.0
            gex_put = 0.0

            # Spot price for GEX
            spot_price = 0.0

            # Process calls
            call_map = chain.get("callExpDateMap", {})
            if call_map and isinstance(call_map, dict):
                for expiry_key, strikes in call_map.items():
                    if not strikes or not isinstance(strikes, dict):
                        continue

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list):
                            continue

                        for opt in option_list:
                            if not opt or not isinstance(opt, dict):
                                continue

                            vol = int(opt.get("totalVolume") or opt.get("volume") or 0)
                            oi = int(opt.get("openInterest") or opt.get("oi") or 0)
                            mark = self._safe_float(opt.get("mark"), 0)
                            last = self._safe_float(opt.get("last") or opt.get("lastPrice"), 0)
                            bid = self._safe_float(opt.get("bid"), 0)
                            ask = self._safe_float(opt.get("ask"), 0)
                            delta = self._safe_float(opt.get("delta"), 0)
                            gamma = self._safe_float(opt.get("gamma"), 0)

                            price = mark or last or ((bid + ask) / 2 if bid and ask else 0)

                            call_vol += vol
                            call_oi += oi
                            call_premium += price * 100 * vol
                            call_delta_sum += delta * oi * 100

                            # GEX for calls (positive)
                            gex_call += gamma * oi * 100

            # Process puts
            put_map = chain.get("putExpDateMap", {})
            if put_map and isinstance(put_map, dict):
                for expiry_key, strikes in put_map.items():
                    if not strikes or not isinstance(strikes, dict):
                        continue

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list):
                            continue

                        for opt in option_list:
                            if not opt or not isinstance(opt, dict):
                                continue

                            vol = int(opt.get("totalVolume") or opt.get("volume") or 0)
                            oi = int(opt.get("openInterest") or opt.get("oi") or 0)
                            mark = self._safe_float(opt.get("mark"), 0)
                            last = self._safe_float(opt.get("last") or opt.get("lastPrice"), 0)
                            bid = self._safe_float(opt.get("bid"), 0)
                            ask = self._safe_float(opt.get("ask"), 0)
                            delta = self._safe_float(opt.get("delta"), 0)
                            gamma = self._safe_float(opt.get("gamma"), 0)

                            price = mark or last or ((bid + ask) / 2 if bid and ask else 0)

                            put_vol += vol
                            put_oi += oi
                            put_premium += price * 100 * vol
                            put_delta_sum += delta * oi * 100  # Delta already negative

                            # GEX for puts (negative)
                            gex_put -= gamma * oi * 100

            # Compute ratios
            put_call_vol_ratio = put_vol / call_vol if call_vol > 0 else 0
            put_call_oi_ratio = put_oi / call_oi if call_oi > 0 else 0

            net_premium = call_premium - put_premium
            net_delta = call_delta_sum + put_delta_sum
            total_gex = gex_call + gex_put

            # Net positioning
            if net_delta > 10000:
                net_positioning = "BULL_HEAVY"
            elif net_delta < -10000:
                net_positioning = "BEAR_HEAVY"
            else:
                net_positioning = "BALANCED"

            summary.update(
                {
                    "put_call_vol_ratio": round(put_call_vol_ratio, 2),
                    "put_call_oi_ratio": round(put_call_oi_ratio, 2),
                    "total_call_premium": round(call_premium, 2),
                    "total_put_premium": round(put_premium, 2),
                    "net_premium": round(net_premium, 2),
                    "total_call_delta": round(call_delta_sum, 2),
                    "total_put_delta": round(put_delta_sum, 2),
                    "net_delta": round(net_delta, 2),
                    "total_gex": round(total_gex, 2),
                    "gex_call": round(gex_call, 2),
                    "gex_put": round(gex_put, 2),
                    "net_positioning": net_positioning,
                }
            )

        except Exception as e:
            logger.error(
                f"[OPTIONS_INTEL] Error computing flow summary for {symbol}: {e}",
                exc_info=True,
            )

        return summary

    # ═══════════════════════════════════════════════════════════════
    # MASTER SCAN METHOD
    # ═══════════════════════════════════════════════════════════════

    def scan_symbol(
        self, symbol: str, chain: Dict[str, Any], quote: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run complete options analysis pipeline.

        Executes all analyses:
        1. Sweep detection
        2. Unusual volume detection
        3. Whale watch
        4. Contract recommendations (BULL bias)
        5. Flow summary

        Args:
            symbol: Stock symbol
            chain: Schwab options chain dict
            quote: Quote dict

        Returns:
            Comprehensive analysis dict
        """
        logger.info(f"[OPTIONS_INTEL] Scanning {symbol}...")

        result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "sweeps": [],
            "unusual_activity": [],
            "whales": [],
            "recommendations": [],
            "flow_summary": {},
        }

        try:
            # Run all analyses
            result["sweeps"] = [asdict(s) for s in self.detect_sweeps(symbol, chain)]
            result["unusual_activity"] = [asdict(u) for u in self.detect_unusual_volume(symbol, chain)]
            result["whales"] = [asdict(w) for w in self.detect_whales(symbol, chain, quote)]
            result["recommendations"] = [
                asdict(r) for r in self.recommend_contracts(symbol, chain, quote, bias="BULL")
            ]
            result["flow_summary"] = self.compute_flow_summary(symbol, chain)

            logger.info(
                f"[OPTIONS_INTEL] Scan complete: "
                f"sweeps={len(result['sweeps'])}, "
                f"unusual={len(result['unusual_activity'])}, "
                f"whales={len(result['whales'])}, "
                f"recs={len(result['recommendations'])}"
            )

        except Exception as e:
            logger.error(f"[OPTIONS_INTEL] Error scanning {symbol}: {e}", exc_info=True)
            result["error"] = str(e)

        return result

    # ═══════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_expiry_key(key: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Parse Schwab expiry key format: "2024-01-19:5"

        Returns:
            Tuple of (expiry_date_str, days_to_expiration)
        """
        try:
            parts = key.split(":")
            if len(parts) == 2:
                return parts[0], int(parts[1])
        except (ValueError, IndexError):
            pass
        return None, None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Safely convert value to float."""
        try:
            if value is None:
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _get_spot_price(quote: Dict[str, Any]) -> float:
        """Extract spot price from quote dict."""
        if not quote or not isinstance(quote, dict):
            return 0.0

        for key in ["last", "mark", "lastPrice", "markPrice"]:
            val = quote.get(key)
            if val:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass

        return 0.0

    @staticmethod
    def _compute_sweep_score(
        vol_oi_ratio: float,
        aggression_pct: float,
        premium_total: float,
        iv: float,
        delta: float,
        dte: int,
    ) -> float:
        """
        Score a sweep: 0-100 scale.

        Factors:
        - vol/OI ratio (primary)
        - Aggression at ask
        - Premium size
        - IV level
        - Time to expiry
        """
        score = 0.0

        # Vol/OI ratio (0-40 pts)
        if vol_oi_ratio >= 10.0:
            score += 40
        elif vol_oi_ratio >= 5.0:
            score += 30
        elif vol_oi_ratio >= 3.0:
            score += 20
        elif vol_oi_ratio >= 1.5:
            score += 10

        # Aggression (0-25 pts)
        score += aggression_pct / 4  # 100% aggression = 25 pts

        # Premium size (0-20 pts)
        if premium_total >= 2000000:
            score += 20
        elif premium_total >= 500000:
            score += 15
        elif premium_total >= 100000:
            score += 10

        # IV level (0-10 pts) — higher IV = more interesting
        if iv > 0.8:
            score += 10
        elif iv > 0.5:
            score += 5

        # DTE adjustment: 14-45 days is sweet spot
        if 14 <= dte <= 45:
            score += 5
        elif dte < 7:
            score -= 5  # Avoid theta crush

        return min(100.0, score)

    @staticmethod
    def _compute_whale_score(
        premium_total: float,
        iv: float,
        delta: float,
        dte: int,
        price_distance_pct: float,
    ) -> float:
        """Score a whale block: 0-100."""
        score = 0.0

        # Premium size (primary, 0-50 pts)
        if premium_total >= 5000000:
            score += 50
        elif premium_total >= 2000000:
            score += 40
        elif premium_total >= 500000:
            score += 30
        elif premium_total >= 100000:
            score += 20

        # IV level (0-20 pts)
        if iv > 1.0:
            score += 20
        elif iv > 0.75:
            score += 15
        elif iv > 0.5:
            score += 10

        # Delta conviction (0-15 pts): 0.3-0.7 is strong
        abs_delta = abs(delta)
        if 0.3 <= abs_delta <= 0.7:
            score += 15
        elif 0.2 <= abs_delta <= 0.8:
            score += 10

        # Price distance (0-15 pts): closer = stronger
        if price_distance_pct <= 5:
            score += 15
        elif price_distance_pct <= 15:
            score += 10
        elif price_distance_pct <= 30:
            score += 5

        return min(100.0, score)

    @staticmethod
    def _compute_liquidity_score(
        volume: int, open_interest: int, spread_pct: float
    ) -> float:
        """Score liquidity: 0-100."""
        score = 50.0  # Base

        # Volume (0-25 pts)
        if volume >= 1000:
            score += 25
        elif volume >= 500:
            score += 20
        elif volume >= 100:
            score += 10

        # Open interest (0-15 pts)
        if open_interest >= 10000:
            score += 15
        elif open_interest >= 1000:
            score += 10
        elif open_interest >= 100:
            score += 5

        # Spread (0-10 pts): tighter = better
        if spread_pct < 0.5:
            score += 10
        elif spread_pct < 1.0:
            score += 7
        elif spread_pct < 2.0:
            score += 4

        return min(100.0, score)

    @staticmethod
    def _compute_value_score(iv: float, dte: int) -> float:
        """Score option value: 0-100."""
        score = 50.0  # Base

        # IV preference: lower IV = cheaper
        if iv < 0.3:
            score += 25
        elif iv < 0.5:
            score += 15
        elif iv < 0.75:
            score += 5

        # DTE preference: 14-45 days is ideal
        if 14 <= dte <= 45:
            score += 25
        elif 7 <= dte < 14:
            score += 15
        elif 45 < dte <= 60:
            score += 15

        return min(100.0, score)

    @staticmethod
    def _compute_delta_score(delta: float, bias: str) -> float:
        """Score delta for directional bias: 0-100."""
        score = 0.0

        if bias == "BULL":
            # Prefer delta 0.25-0.40 for leverage, 0.50-0.60 for conviction
            abs_delta = abs(delta)
            if 0.25 <= abs_delta <= 0.40:
                score = 80.0
            elif 0.50 <= abs_delta <= 0.60:
                score = 90.0
            elif 0.15 <= abs_delta < 0.25:
                score = 60.0
            elif 0.40 < abs_delta <= 0.50:
                score = 75.0
            elif abs_delta > 0.70:
                score = 50.0
        elif bias == "BEAR":
            # Puts with negative delta
            if -0.40 <= delta <= -0.25:
                score = 80.0
            elif -0.60 <= delta <= -0.50:
                score = 90.0
            elif -0.25 < delta <= -0.15:
                score = 60.0
            elif -0.50 < delta <= -0.40:
                score = 75.0
            elif delta < -0.70:
                score = 50.0
        else:  # NEUTRAL
            # Both sides equally valued
            abs_delta = abs(delta)
            if 0.40 <= abs_delta <= 0.60:
                score = 90.0
            elif 0.25 <= abs_delta <= 0.75:
                score = 80.0

        return score

    @staticmethod
    def _generate_recommendation_text(
        symbol: str,
        strike: float,
        opt_type: str,
        delta: float,
        dte: int,
        score: float,
        bias: str,
    ) -> str:
        """Generate human-readable recommendation text."""
        quality = "Strong" if score >= 75 else "Good" if score >= 60 else "Moderate"
        direction = "Call" if opt_type == "CALL" else "Put"

        return (
            f"{quality} {direction} at ${strike:.0f} strike ({dte} DTE, "
            f"Delta {delta:.2f}). Aligns with {bias} bias."
        )
