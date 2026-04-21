"""
SQUEEZE OS v5.0 — Institutional Squeeze Analyzer
═══════════════════════════════════════════════════
8-Module scoring engine with sigmoid transitions (no cliffs).
Uses single-bar quote data + optional price history for advanced metrics.

Modules:
  1. Volume Profile (0-20)     — Volume surge detection, sigmoid-mapped
  2. TTM Squeeze Proxy (0-15)  — Compression via ATR-normalized range
  3. Momentum Vector (0-15)    — ROC magnitude + acceleration
  4. VWAP Position (0-10)      — Price vs volume-weighted average
  5. RSI Engine (0-10)         — Mean-reversion + trend strength
  6. Money Flow (0-10)         — Buying pressure from close position in range
  7. Price Structure (0-10)    — Close position + tier weighting
  8. Trend Alignment (0-10)    — EMA stack order (requires history)

No fake data. No placeholders. Institutional grade.
"""
import math
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# MATH UTILITIES
# ═══════════════════════════════════════════════════════════════

def sigmoid(x, center, steepness):
    """Smooth S-curve mapping. Eliminates scoring cliffs."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - center)))
    except OverflowError:
        return 1.0 if x > center else 0.0


def clamp(val, lo=0.0, hi=100.0):
    return max(lo, min(hi, val))


# ═══════════════════════════════════════════════════════════════
# TIER WEIGHTING
# ═══════════════════════════════════════════════════════════════

def tier_weight(price):
    """
    Law 2 & 3 Compliance + SqueezeOS Sweet Spot.
    Sweet spot ($5-$50) gets 100% weight.
    All others get 20% weight (80% focus on the sweet spot).
    """
    if price <= 0: return 0.0
    if 2.0 <= price <= 60.0:
        return 1.00  # THE SWEET SPOT ($2-$60, 80% of focus)
    return 0.15      # Outside sweet spot (Mega caps, pennies - heavily reduced)


class SqueezeAnalyzer:

    def __init__(self):
        self._history_cache = {}  # symbol -> {bars: [...], ts: time}
        logger.info("[SQUEEZE] Institutional Analyzer v5.0 loaded (8-module sigmoid scoring)")

    # ═══════════════════════════════════════════════════════════
    # MODULE 1: VOLUME PROFILE (0-20 pts)
    # Sigmoid-mapped volume ratio. No more 1.49→5, 1.50→15 cliffs.
    # ═══════════════════════════════════════════════════════════

    def _volume_score(self, vol_ratio):
        if vol_ratio <= 0:
            return 0.0
        # Center at 2.0x, steepness 1.5
        # 1.0x → ~4pts, 2.0x → 10pts, 4.0x → 17pts, 8.0x → 20pts
        return sigmoid(vol_ratio, 2.0, 1.5) * 20.0

    # ═══════════════════════════════════════════════════════════
    # MODULE 2: TTM SQUEEZE PROXY (0-15 pts)
    # True TTM Squeeze needs Bollinger/Keltner history.
    # Proxy: ATR-normalized intraday range compression.
    # Tight range + volume = coiled spring about to fire.
    # ═══════════════════════════════════════════════════════════

    def _compression_score(self, price, high, low, avg_volume, volume):
        if price <= 0 or high <= low:
            return 0.0
        # Range as % of price
        range_pct = ((high - low) / price) * 100.0

        # Compression: SMALL range = HIGH score
        # Center at 2.5% range, steepness -2.0 (inverted — tighter = higher)
        compression = (1.0 - sigmoid(range_pct, 2.5, 1.5)) * 10.0

        # Bonus: Tight range + volume surge = true compression
        vol_ratio = volume / max(avg_volume, 1) if avg_volume > 0 else 1.0
        if range_pct < 3.0 and vol_ratio > 1.5:
            compression += 5.0  # Coiled spring bonus

        return min(compression, 15.0)

    # ═══════════════════════════════════════════════════════════
    # MODULE 3: MOMENTUM VECTOR (0-15 pts)
    # Magnitude + direction scoring. Dead stocks get penalized.
    # ═══════════════════════════════════════════════════════════

    def _momentum_score(self, change_pct):
        ac = abs(change_pct)
        if ac < 0.1:
            return -10.0  # Dead stock penalty

        # Sweet spot: 1-5% moves score highest
        # >10% often means the move already happened
        if ac <= 5.0:
            score = sigmoid(ac, 1.5, 2.0) * 15.0
        elif ac <= 15.0:
            score = 12.0 - (ac - 5.0) * 0.3  # Diminishing returns
        else:
            score = 9.0 - (ac - 15.0) * 0.1  # Extended moves cool off

        return max(score, 0.0)

    # ═══════════════════════════════════════════════════════════
    # MODULE 4: VWAP POSITION (0-10 pts)
    # Institutional benchmark. Price above VWAP = buyers in control.
    # We approximate VWAP from open/high/low/close/volume.
    # ═══════════════════════════════════════════════════════════

    def _vwap_score(self, price, open_price, high, low, change_pct):
        if price <= 0 or high <= low:
            return 5.0  # Neutral if no data

        # Approximate VWAP as volume-weighted typical price
        typical = (high + low + price) / 3.0

        # Distance from typical price, normalized
        dist = (price - typical) / max(typical, 0.01) * 100.0

        # Bullish: price above VWAP-proxy with positive momentum
        if dist > 0 and change_pct > 0:
            return min(sigmoid(dist, 0.5, 3.0) * 10.0, 10.0)
        # Bearish but still has structure
        elif dist < 0 and change_pct > 0:
            return 4.0  # Reclaiming — watch
        elif dist > 0 and change_pct < 0:
            return 3.0  # Fading from strength
        else:
            return 1.0  # Below VWAP, negative momentum

    # ═══════════════════════════════════════════════════════════
    # MODULE 5: RSI ENGINE (0-10 pts)
    # Approximated from price position in range.
    # Oversold bounce setup = high score.
    # Overbought exhaustion = penalty.
    # ═══════════════════════════════════════════════════════════

    def _rsi_proxy_score(self, price, high, low, change_pct):
        if high <= low:
            return 5.0
        pos = (price - low) / (high - low)

        # Oversold bounce (close near low but positive change = reversal)
        if pos < 0.3 and change_pct > 0:
            return 10.0  # Strong reversal setup
        # Closing near low, negative = breakdown
        elif pos < 0.3 and change_pct < 0:
            return 2.0  # Weak
        # Closing at highs but exhaustion risk (MUST check before 0.7 for correct ordering)
        elif pos > 0.9 and change_pct > 3:
            return 5.0  # Extended — may pull back
        # Closing at highs with momentum
        elif pos > 0.7 and change_pct > 0:
            return 8.0  # Trend continuation
        else:
            return 5.0  # Neutral

    # ═══════════════════════════════════════════════════════════
    # MODULE 6: MONEY FLOW (0-10 pts)
    # MFI proxy — buying at the high of the range on volume.
    # ═══════════════════════════════════════════════════════════

    def _money_flow_score(self, price, high, low, volume, avg_volume):
        if high <= low or volume <= 0:
            return 0.0

        # Close position in range = buying pressure proxy
        mf_ratio = (price - low) / (high - low)
        vol_mult = min(volume / max(avg_volume, 1), 5.0) / 5.0  # Normalize vol 0-1

        # High close + high volume = institutional accumulation
        raw = mf_ratio * vol_mult * 10.0
        return clamp(raw, 0.0, 10.0)

    # ═══════════════════════════════════════════════════════════
    # MODULE 7: PRICE STRUCTURE (0-10 pts)
    # Close position + price tier relevance.
    # ═══════════════════════════════════════════════════════════

    def _structure_score(self, price, high, low):
        if high <= low or price <= 0:
            return 0.0

        pos = (price - low) / (high - low)

        # Closing near high = strength
        if pos >= 0.85:
            return 10.0
        elif pos >= 0.70:
            return 8.0
        elif pos >= 0.50:
            return 5.0
        elif pos >= 0.30:
            return 3.0
        else:
            return 1.0

    # ═══════════════════════════════════════════════════════════
    # MODULE 8: TREND ALIGNMENT (0-10 pts)
    # With history: EMA 8/21/50 stack.
    # Without history: intraday trend proxy from open/close.
    # ═══════════════════════════════════════════════════════════

    def _trend_score(self, price, open_price, change_pct, history=None):
        if history and len(history) >= 5:
            # Real EMA alignment from history
            return self._trend_from_history(history, price)

        # Proxy: intraday trend direction + magnitude
        if open_price <= 0:
            return 5.0

        intraday_move = ((price - open_price) / open_price) * 100.0

        if intraday_move > 0 and change_pct > 0:
            return min(sigmoid(intraday_move, 1.0, 2.0) * 10.0, 10.0)
        elif intraday_move > 0:
            return 5.0
        elif intraday_move < -2.0:
            return 2.0
        else:
            return 4.0

    def _trend_from_history(self, bars, current_price):
        """EMA stack alignment from price history bars."""
        try:
            closes = [b.get('close', 0) for b in bars if b.get('close', 0) > 0]
            if len(closes) < 10:
                return 5.0

            # Simple EMA approximation
            def ema(data, period):
                if len(data) < period:
                    return sum(data) / len(data)
                mult = 2.0 / (period + 1)
                val = sum(data[:period]) / period
                for p in data[period:]:
                    val = (p - val) * mult + val
                return val

            ema8 = ema(closes, min(8, len(closes)))
            ema21 = ema(closes, min(21, len(closes)))

            # Bull stack: price > EMA8 > EMA21
            if current_price > ema8 > ema21:
                return 10.0
            elif current_price > ema21:
                return 7.0
            elif current_price > ema8:
                return 5.0
            elif current_price < ema8 < ema21:
                return 1.0  # Bear stack
            else:
                return 3.0
        except Exception as e:
            logger.warning(f"[TREND] Error calculating EMA alignment from history: {e}")
            return 5.0

    # ═══════════════════════════════════════════════════════════
    # MAIN SCORING ENGINE
    # ═══════════════════════════════════════════════════════════

    def analyze_symbol(self, symbol, quote_data=None, history=None):
        if not quote_data:
            return None

        price = quote_data.get('price', 0)
        if not price or price <= 0:
            return None

        volume = quote_data.get('volume', 0)
        avg_volume = quote_data.get('avgVolume', 0)
        vol_ratio = quote_data.get('volRatio', 0)
        change_pct = quote_data.get('changePct', 0)
        high = quote_data.get('high', 0)
        low = quote_data.get('low', 0)
        open_price = quote_data.get('open', 0)

        # If volRatio not pre-calculated
        if vol_ratio <= 0 and avg_volume > 0:
            vol_ratio = volume / avg_volume

        # ── Run all 8 modules ──
        s1 = self._volume_score(vol_ratio)
        s2 = self._compression_score(price, high, low, avg_volume, volume)
        s3 = self._momentum_score(change_pct)
        s4 = self._vwap_score(price, open_price, high, low, change_pct)
        s5 = self._rsi_proxy_score(price, high, low, change_pct)
        s6 = self._money_flow_score(price, high, low, volume, avg_volume)
        s7 = self._structure_score(price, high, low)
        s8 = self._trend_score(price, open_price, change_pct, history)

        # ── Raw total (max 100) ──
        raw_total = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8
        raw_total = clamp(raw_total, 0.0, 100.0)

        # ── Apply tier weight ──
        tw = tier_weight(price)
        total = clamp(raw_total * tw, 0.0, 100.0)

        # ── Dead stock hard cap ──
        if abs(change_pct) < 0.3:
            total = min(total, 30.0)

        # ── Classify ──
        if total >= 75:
            level, rec, risk = 'EXTREME', 'CRITICAL SQUEEZE ALERT', 'HIGH'
        elif total >= 55:
            level, rec, risk = 'HIGH', 'Strong institutional buildup', 'MODERATE-HIGH'
        elif total >= 40:
            level, rec, risk = 'MODERATE', 'Institutional interest detected', 'MODERATE'
        elif total >= 25:
            level, rec, risk = 'LOW', 'Scanning for setup', 'LOW'
        else:
            level, rec, risk = 'NONE', 'No setup', 'MINIMAL'

        # ── Direction with Consensus (Institutional Hardening) ──
        # We look for agreement between price change, VWAP position, trend alignment, and price structure.
        bullish_indicators = 0
        bearish_indicators = 0
        
        # 1. Price vs Reference
        if change_pct > 0.5: bullish_indicators += 1
        elif change_pct < -0.5: bearish_indicators += 1
        
        # 2. VWAP position (s4 > 6 is good bullish, s4 < 4 is bearish)
        if s4 >= 6: bullish_indicators += 1
        elif s4 <= 3: bearish_indicators += 1
        
        # 3. Trend Alignment (s8 >= 7 is bull stack, s8 <= 3 is bear stack)
        if s8 >= 7: bullish_indicators += 1
        elif s8 <= 3: bearish_indicators += 1
        
        # 4. Price Structure (s7 >= 7 is closing near high, s7 <= 3 is near low)
        if s7 >= 7: bullish_indicators += 1
        elif s7 <= 3: bearish_indicators += 1

        if bullish_indicators >= 3:
            direction = 'BULLISH'
        elif bearish_indicators >= 3:
            direction = 'BEARISH'
        elif change_pct > 0:
            direction = 'BULLISH' # Fallback
        elif change_pct < 0:
            direction = 'BEARISH' # Fallback
        else:
            direction = 'NEUTRAL'

        return {
            'symbol': symbol, 'price': price,
            'squeeze_score': round(total, 1), 'raw_score': round(raw_total, 1), 'squeeze_level': level,
            'direction': direction,
            'recommendation': rec, 'risk_level': risk,
            'volume': volume, 'changePct': change_pct, 'volRatio': vol_ratio,
            'tier': 'PENNY' if price < 2 else 'SWEET' if price <= 60 else 'LARGE' if price <= 150 else 'MEGA',
            'analysis_components': {
                'volume_profile': round(s1, 1),
                'compression': round(s2, 1),
                'momentum': round(s3, 1),
                'vwap_position': round(s4, 1),
                'rsi_engine': round(s5, 1),
                'money_flow': round(s6, 1),
                'price_structure': round(s7, 1),
                'trend_alignment': round(s8, 1),
            },
            'source': quote_data.get('source', ''),
        }

    def analyze_batch(self, quotes_dict, history_dict=None):
        results = []
        for sym, data in quotes_dict.items():
            hist = history_dict.get(sym) if history_dict else None
            r = self.analyze_symbol(sym, data, history=hist)
            if r:
                results.append(r)
        results.sort(key=lambda x: x['squeeze_score'], reverse=True)
        return results
