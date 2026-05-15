import logging
import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# ══════════════════════════════════════════════════════════════════════════════
# SQUEEZE OS | KDP INSTITUTIONAL SENTINEL v6.1
# ══════════════════════════════════════════════════════════════════════════════
# Specialized precision engine for Keurig Dr Pepper (KDP).
# KDP exhibits unique low-volatility accumulation patterns often missed by 
# broad-market scanners. This sentinel implements Volatility Surface analysis
# and Skew-based institutional positioning detection.
# ══════════════════════════════════════════════════════════════════════════════

logger = logging.getLogger("KDP-Sentinel")

class KdpSentinelEngine:
    """
    Expert-Precision Institutional Sentinel for KDP.
    Identifies high-conviction positioning via:
    1. Institutional Accumulation: Deep OI clusters at OTM strikes.
    2. Volatility Skew: Call vs Put premium divergence.
    3. Liquidity Resonance: OI/Volume ratios exceeding 10x norms.
    4. Time-Decay Resilience: Selection of optimal Theta/Delta windows.
    """

    def __init__(self, data_manager):
        self.dm = data_manager
        self.symbol = "KDP"
        self.min_score_alert = 75
        
        # ── SML Institutional Parameter Set ──
        self.ideal_delta = (0.25, 0.55)
        self.ideal_dte = (7, 60)      # KDP is a slow mover; avoid 0DTE gambling.
        self.max_spread_pct = 0.15    # Institutional liquidity threshold
        self.oi_threshold = 1000      # Minimum OI for institutional relevance
        
        logger.info("[KDP-SENTINEL] Institutional Engine initialized (Skew + Surface Enabled)")

    def calculate_skew(self, calls: list, puts: list, spot: float) -> float:
        """
        Calculates the Volatility Skew (Call IV - Put IV) at the 25-delta wing.
        A positive skew suggests institutional hedging or bullish call bias.
        """
        def get_delta_iv(opts, target_delta):
            valid = [o for o in opts if abs(abs(o.get('delta', 0)) - target_delta) < 0.1]
            if not valid: return None
            return sum(o.get('iv', 0) for o in valid) / len(valid)

        c_iv = get_delta_iv(calls, 0.25)
        p_iv = get_delta_iv(puts, 0.25)
        
        if c_iv and p_iv:
            return round(c_iv - p_iv, 4)
        return 0.0

    def score_contract(self, opt: dict, spot: float) -> dict:
        """
        Expert scoring for KDP contracts using multi-vector institutional heuristics.
        """
        strike = float(opt.get('strike', 0))
        opt_type = opt.get('option_type', 'CALL').upper()
        bid = float(opt.get('bid', 0))
        ask = float(opt.get('ask', 0))
        mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else float(opt.get('last', 0))
        
        if mid <= 0: return None

        vol = int(opt.get('totalVolume', 0))
        oi = int(opt.get('openInterest', 0))
        delta = float(opt.get('delta', 0))
        iv = float(opt.get('iv', 0))
        dte = int(opt.get('daysToExpiration', 0))
        
        abs_delta = abs(delta)
        spread_pct = (ask - bid) / mid if mid > 0 else 1.0

        score = 0
        notes = []

        # 1. ── Delta Sweet Spot (0-30 pts) ──
        if self.ideal_delta[0] <= abs_delta <= self.ideal_delta[1]:
            score += 30
            notes.append("Institutional delta sweet spot")
        elif 0.15 <= abs_delta <= 0.70:
            score += 15

        # 2. ── Institutional OI/Vol Ratio (0-25 pts) ──
        # High OI with rising volume = active institutional engagement.
        if oi >= self.oi_threshold:
            if vol > 0 and (vol / oi) > 0.1:
                score += 25
                notes.append("High institutional turnover detected")
            elif oi > 5000:
                score += 15
                notes.append("Deep institutional liquidity pool")

        # 3. ── DTE Positioning (0-20 pts) ──
        if self.ideal_dte[0] <= dte <= self.ideal_dte[1]:
            score += 20
            notes.append("Optimal institutional time window")
        elif dte > 60:
            score += 10 # LEAPS accumulation strategy

        # 4. ── Liquidity/Spread (0-15 pts) ──
        if spread_pct < 0.05:
            score += 15
            notes.append("Tight institutional spread")
        elif spread_pct < self.max_spread_pct:
            score += 8
        else:
            score -= 20 # Liquidity penalty
            notes.append("Wide spread risk")

        # 5. ── IV Relative Value (0-10 pts) ──
        # KDP usually has low IV (~20%); spikes above 30% are significant.
        if iv > 0 and iv < 0.28:
            score += 10
            notes.append("Low-risk premium entry (IV < 28%)")

        return {
            "type": opt_type,
            "strike": strike,
            "mid": round(mid, 2),
            "score": min(100, max(0, score)),
            "delta": round(delta, 2),
            "iv": round(iv, 2),
            "dte": dte,
            "oi": oi,
            "vol": vol,
            "oi_vol_ratio": round(oi / (vol + 1e-9), 1),
            "spread_pct": round(spread_pct * 100, 2),
            "notes": notes
        }

    def run_scan(self, chain: dict, quote: dict) -> dict:
        """
        Runs the KDP institutional scan on provided chain data.
        Returns a high-fidelity intelligence payload for the Command Center.
        """
        spot = float(quote.get('lastPrice', quote.get('last', 0)))
        if spot <= 0:
            return {"error": "Invalid spot price for KDP scan"}

        all_calls = []
        all_puts = []
        scored = []
        
        # ── Flatten & Filter Chain ──
        for exp_map in [chain.get('callExpDateMap', {}), chain.get('putExpDateMap', {})]:
            for date_key in exp_map:
                for strike_key in exp_map[date_key]:
                    opts = exp_map[date_key][strike_key]
                    for opt in opts:
                        s = self.score_contract(opt, spot)
                        if s and s['score'] > 30:
                            scored.append(s)
                            if s['type'] == 'CALL': all_calls.append(s)
                            else: all_puts.append(s)

        # ── Intelligence Synthesis ──
        scored.sort(key=lambda x: -x['score'])
        skew = self.calculate_skew(all_calls, all_puts, spot)
        
        bias = "NEUTRAL"
        top_calls = [x for x in scored if x['type'] == 'CALL'][:5]
        top_puts = [x for x in scored if x['type'] == 'PUT'][:5]
        
        if len(top_calls) > len(top_puts) and skew > -0.02:
            bias = "BULLISH"
        elif len(top_puts) > len(top_calls):
            bias = "BEARISH"

        return {
            "symbol": self.symbol,
            "spot": spot,
            "skew_25d": skew,
            "timestamp": datetime.now().isoformat(),
            "top_contracts": scored[:15],
            "institutional_bias": bias,
            "metrics": {
                "call_flow_count": len(all_calls),
                "put_flow_count": len(all_puts),
                "avg_iv": round(sum(x['iv'] for x in scored) / len(scored), 3) if scored else 0
            }
        }

# ══════════════════════════════════════════════════════════════════════════════
# END OF MODULE | SQUEEZE OS v6.1 COMPLIANT
# ══════════════════════════════════════════════════════════════════════════════
