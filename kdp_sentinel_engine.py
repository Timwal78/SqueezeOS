import logging
import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any

logger = logging.getLogger("KDP-Sentinel")

class KdpSentinelEngine:
    """
    Expert-Precision Institutional Sentinel for KDP.
    Focuses on institutional accumulation, OI/Volume anomalies, and 
    high-conviction positioning.
    """

    def __init__(self, data_manager):
        self.dm = data_manager
        self.symbol = "KDP"
        self.min_score_alert = 75
        self.ideal_delta = (0.25, 0.55)
        self.ideal_dte = (7, 60) # KDP is slower, need more time

    def score_contract(self, opt: dict, spot: float) -> dict:
        """
        Expert scoring for KDP contracts.
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

        # 1. Delta Sweet Spot (0-30 pts)
        if self.ideal_delta[0] <= abs_delta <= self.ideal_delta[1]:
            score += 30
            notes.append("delta sweet spot")
        elif 0.15 <= abs_delta <= 0.70:
            score += 15

        # 2. Institutional OI/Vol Ratio (0-25 pts)
        # High OI with rising volume = active institutional engagement
        if oi > 1000:
            if vol > 0 and (vol / oi) > 0.1:
                score += 25
                notes.append("high institutional turnover")
            elif oi > 5000:
                score += 15
                notes.append("deep institutional liquidity")

        # 3. DTE Positioning (0-20 pts)
        if self.ideal_dte[0] <= dte <= self.ideal_dte[1]:
            score += 20
            notes.append("optimal institutional window")
        elif dte > 60:
            score += 10 # LEAPS accumulation

        # 4. Liquidity/Spread (0-15 pts)
        if spread_pct < 0.05:
            score += 15
            notes.append("tight institutional spread")
        elif spread_pct < 0.15:
            score += 8

        # 5. IV Relative Value (0-10 pts)
        # KDP usually has low IV, spikes are significant
        if iv > 0 and iv < 0.25:
            score += 10
            notes.append("low-risk premium entry")

        return {
            "type": opt_type,
            "strike": strike,
            "mid": round(mid, 2),
            "score": min(100, score),
            "delta": round(delta, 2),
            "iv": round(iv, 2),
            "dte": dte,
            "oi": oi,
            "vol": vol,
            "oi_vol_ratio": round(oi / vol, 1) if vol > 0 else 0,
            "spread_pct": round(spread_pct * 100, 2),
            "notes": notes
        }

    def run_scan(self, chain: dict, quote: dict) -> dict:
        """
        Runs the KDP institutional scan on provided chain data.
        """
        spot = float(quote.get('lastPrice', quote.get('last', 0)))
        if spot <= 0:
            return {"error": "Invalid spot price"}

        scored = []
        
        for exp_map in [chain.get('callExpDateMap', {}), chain.get('putExpDateMap', {})]:
            for date_key in exp_map:
                for strike_key in exp_map[date_key]:
                    opts = exp_map[date_key][strike_key]
                    for opt in opts:
                        s = self.score_contract(opt, spot)
                        if s and s['score'] > 30:
                            scored.append(s)

        scored.sort(key=lambda x: -x['score'])
        
        return {
            "symbol": self.symbol,
            "spot": spot,
            "timestamp": datetime.now().isoformat(),
            "top_contracts": scored[:15],
            "bias": "BULLISH" if sum(1 for x in scored[:5] if x['type'] == 'CALL') > 2 else "BEARISH"
        }
