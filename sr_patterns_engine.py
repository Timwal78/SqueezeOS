import pandas as pd
import numpy as np
import logging
import yfinance as yf
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SR_PATTERNS_ENGINE")

class SRPatternsEngine:
    """
    SqueezeOS Support/Resistance Pivot Candlestick Engine
    Identifies zones based on confirming swing pivots and triggers trades
    when specific reversal candlesticks form within those bounds.
    """
    def __init__(self, bars=10, no_of_pivots=2, zone_expiry=200, proximity_pct=0.3):
        self.bars = bars
        self.no_of_pivots = no_of_pivots
        self.zone_expiry = zone_expiry
        self.proximity_pct = proximity_pct

    def fetch_batch_data(self, symbols, period="60d", interval="60m"):
        """Fetch historical data. Uses 60 days of hourly (intraday) bars for deep pivot detection."""
        if not symbols: return {}
        try:
            data = yf.download(symbols, period=period, interval=interval, group_by='ticker', progress=False, threads=False)
            return data
        except Exception as e:
            logger.error(f"Batch fetch error SRPatterns: {e}")
            return {}

    def _find_pivots(self, highs, lows, opens, closes):
        pivot_highs, pivot_lows = [], []
        n = len(highs)
        b = self.bars
        for i in range(b, n - b):
            # Check for pivot high
            is_ph, is_pl = True, True
            
            # Using basic slicing for performance instead of inner loops
            window_highs = highs[i-b:i+b+1]
            window_lows = lows[i-b:i+b+1]
            
            if np.max(window_highs) > highs[i]:
                is_ph = False
            # Check edge case where multiple bars have the same max high.
            # Usually PineScript PivotHigh requires the peak to be strictly higher than surrounding or specifically handled
            if is_ph and len([x for x in window_highs if x == highs[i]]) > 1:
                 # If it's a double top in the same window, it's weaker. But we'll accept it if it's the first.
                 pass

            if np.min(window_lows) < lows[i]:
                is_pl = False

            if is_ph:
                pivot_highs.append({
                    'idx': i,
                    'high': highs[i],
                    'upper': max(opens[i], closes[i])
                })
            if is_pl:
                pivot_lows.append({
                    'idx': i,
                    'low': lows[i],
                    'lower': min(opens[i], closes[i])
                })
        return pivot_highs, pivot_lows

    def _build_zones(self, df):
        highs = df['High'].values
        lows = df['Low'].values
        opens = df['Open'].values
        closes = df['Close'].values
        
        phs, pls = self._find_pivots(highs, lows, opens, closes)
        
        zones = []
        # Resistance
        if len(phs) >= self.no_of_pivots:
            for k in range(self.no_of_pivots - 1, len(phs)):
                valid = True
                base_h = phs[k - (self.no_of_pivots - 1)]['high']
                base_u = phs[k - (self.no_of_pivots - 1)]['upper']
                for p in range(k - (self.no_of_pivots - 2), k + 1):
                    curr = phs[p]
                    if not (curr['high'] < base_h and curr['high'] > base_u):
                        valid = False
                        break
                if valid:
                    zones.append({
                        'start_idx': phs[k]['idx'],
                        'zone_high': base_h,
                        'zone_low': base_u,
                        'type': 'RESISTANCE',
                    })
                    
        # Support
        if len(pls) >= self.no_of_pivots:
            for k in range(self.no_of_pivots - 1, len(pls)):
                valid = True
                base_l = pls[k - (self.no_of_pivots - 1)]['low']
                base_lower = pls[k - (self.no_of_pivots - 1)]['lower']
                for p in range(k - (self.no_of_pivots - 2), k + 1):
                    curr = pls[p]
                    if not (curr['low'] > base_l and curr['low'] < base_lower):
                        valid = False
                        break
                if valid:
                    zones.append({
                        'start_idx': pls[k]['idx'],
                        'zone_high': base_lower,
                        'zone_low': base_l,
                        'type': 'SUPPORT',
                    })
                    
        # Filter Active Zones
        active_zones = []
        for z in zones:
            start_idx = z['start_idx']
            broken = False
            # Check if any close after start_idx broke the zone
            for i in range(start_idx, len(closes)):
                if z['type'] == 'RESISTANCE' and closes[i] > z['zone_high']:
                    broken = True; break
                if z['type'] == 'SUPPORT' and closes[i] < z['zone_low']:
                    broken = True; break
            
            is_expired = self.zone_expiry > 0 and (len(df) - 1 - start_idx) > self.zone_expiry
            if not broken and not is_expired:
                active_zones.append(z)
                
        return active_zones

    def scan_symbol(self, sym: str, df: pd.DataFrame) -> List[Dict]:
        """Runs pattern detection on a single symbol's OHLC Dataframe."""
        if df is None or len(df) < 50: return []
        
        zones = self._build_zones(df)
        if not zones: return []
        
        c0 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2 = df.iloc[-3]
        
        def get_metrics(c):
            candle = abs(c['High'] - c['Low'])
            body = abs(c['Open'] - c['Close'])
            body_perc = (body / candle * 100) if candle != 0 else 0
            return candle, body, body_perc

        can0, bod0, perc0 = get_metrics(c0)
        can1, bod1, perc1 = get_metrics(c1)
        can2, bod2, perc2 = get_metrics(c2)
        
        EvnCan = (bod0 > can0 * 0.6) and (c0['Open'] > c0['Close']) and (bod1 < can1 * 0.3) and (bod2 > can2 * 0.6) and (c2['Open'] < c2['Close'])
        MorCan = (bod0 > can0 * 0.6) and (c0['Open'] < c0['Close']) and (bod1 < can1 * 0.3) and (bod2 > can2 * 0.6) and (c2['Open'] > c2['Close'])
        BInBar = (c0['High'] < c1['High']) and (c0['Low'] > c1['Low']) and (bod1 > can1 * 0.4) 
        BullInBar = BInBar
        
        bperc = (c1['High'] - c1['Low']) * 0.05
        bpercc = (c1['High'] - c1['Low']) * 0.60
        tbc = (c0['Low'] > c1['Low'] - bperc) and (c0['Low'] < c1['Low'] + bperc) and (c0['Close'] > c1['Low'] + bpercc) and (c1['Open'] > c1['Close']) and ((c1['Close'] - c1['Low']) < bperc) and ((c0['Open'] - c0['Low']) < bperc) and (perc0 > 60) and (perc1 > 60)
        ttc = (c0['High'] > c1['High'] - bperc) and (c0['High'] < c1['High'] + bperc) and (c0['Close'] < c1['High'] - bpercc) and (c1['Open'] < c1['Close']) and ((c1['High'] - c1['Close']) < bperc) and ((c0['High'] - c0['Open']) < bperc) and (perc0 > 60) and (perc1 > 60)
        
        EvnCanHigh = c1['High']
        BInBarHigh = c1['High'] 
        MorCanLow = c1['Low']
        BullInBarLow = c1['Low']
        TTopH = max(c0['High'], c1['High'])
        TBotL = min(c0['Low'], c1['Low'])
        
        signals = []
        for z in zones:
            buf = z['zone_high'] * (self.proximity_pct / 100.0)
            zH_adj = z['zone_high'] + buf
            zL_adj = z['zone_low'] - buf
            
            def in_zone(val): return zL_adj <= val <= zH_adj
            
            if z['type'] == 'RESISTANCE':
                stop_loss = zH_adj
                target = float(c0['Close']) - (stop_loss - float(c0['Close'])) * 2.5 # 2.5 RR
                if EvnCan and in_zone(EvnCanHigh): signals.append({'action': 'SELL', 'pattern': 'Evening Star', 'zone': z, 'stop': stop_loss, 'target': target})
                elif BInBar and in_zone(BInBarHigh): signals.append({'action': 'SELL', 'pattern': 'Inside Bar (Bearish)', 'zone': z, 'stop': stop_loss, 'target': target})
                elif ttc and in_zone(TTopH): signals.append({'action': 'SELL', 'pattern': 'Tweezer Top', 'zone': z, 'stop': stop_loss, 'target': target})

            elif z['type'] == 'SUPPORT':
                stop_loss = zL_adj
                target = float(c0['Close']) + (float(c0['Close']) - stop_loss) * 2.5 # 2.5 RR
                if MorCan and in_zone(MorCanLow): signals.append({'action': 'BUY', 'pattern': 'Morning Star', 'zone': z, 'stop': stop_loss, 'target': target})
                elif BullInBar and in_zone(BullInBarLow): signals.append({'action': 'BUY', 'pattern': 'Inside Bar (Bullish)', 'zone': z, 'stop': stop_loss, 'target': target})
                elif tbc and in_zone(TBotL): signals.append({'action': 'BUY', 'pattern': 'Tweezer Bottom', 'zone': z, 'stop': stop_loss, 'target': target})

        res = []
        seen = set()
        for s in signals:
            key = f"{s['action']}_{s['pattern']}"
            if key not in seen:
                seen.add(key)
                s['symbol'] = sym
                s['price'] = float(c0['Close'])
                res.append(s)
                
        return res

    def scan_universe(self, symbols: List[str]) -> List[Dict]:
        """Pipes a list of symbols through the logic in bulk."""
        all_signals = []
        batch_df = self.fetch_batch_data(symbols)
        if batch_df.empty: return []

        for sym in symbols:
            try:
                if len(symbols) > 1:
                    df = batch_df[sym].copy() if sym in batch_df.columns.levels[0] else None
                else:
                    df = batch_df.copy()
                    
                if df is not None and not df.dropna(subset=['Close']).empty:
                    hits = self.scan_symbol(sym, df)
                    all_signals.extend(hits)
            except Exception as e:
                logger.debug(f"[SRPatterns] Error processing {sym}: {e}")
                
        return all_signals
