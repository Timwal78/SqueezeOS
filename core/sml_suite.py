import numpy as np
import pandas as pd
from typing import Dict, List, Optional

class SMLSuite:
    """
    Python implementation of SML Apex and Leviathan institutional logic.
    """
    
    @staticmethod
    def calculate_apex_score(df: pd.DataFrame, 
                           ema_fast: pd.Series, 
                           ema_slow: pd.Series, 
                           rsi: pd.Series, 
                           macd_hist: pd.Series, 
                           vol_avg: pd.Series) -> Dict:
        """
        Apex Breakout Engine v2 Score (0-7)
        1. Trend Alignment
        2. Momentum (RSI/MACD)
        3. Volume Spike
        4. MTF Bias (Mocked as 1 for now)
        5. ATR Expansion
        6. Body Confirmation
        7. Extension Check
        """
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        score = 0
        # 1. Trend
        if last_row['close'] > ema_fast.iloc[-1] and ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            score += 1
        # 2. Momentum
        if rsi.iloc[-1] > 50 and macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]:
            score += 1
        # 3. Volume
        if last_row['volume'] > (vol_avg.iloc[-1] * 1.35):
            score += 1
        # 4. MTF Bias (Assumed positive for now)
        score += 1
        # 5. ATR Expansion
        atr = (df['high'] - df['low']).rolling(14).mean()
        if (last_row['high'] - last_row['low']) > atr.iloc[-1]:
            score += 1
        # 6. Body Confirmation
        body = abs(last_row['close'] - last_row['open'])
        range_bar = max(last_row['high'] - last_row['low'], 0.01)
        if (body / range_bar) * 100 >= 25:
            score += 1
        # 7. Extension Check
        dist = abs(last_row['close'] - ema_fast.iloc[-1]) / atr.iloc[-1]
        if dist <= 3.0:
            score += 1
            
        return {
            "apex_score": score, 
            "regime": "IGNITION" if score >= 4 else "DORMANT",
            "signals": {
                "buy": score >= 5 and last_row['close'] > prev_row['high'],
                "sell": score >= 5 and last_row['close'] < prev_row['low']
            }
        }

    @staticmethod
    def calculate_leviathan_metrics(df: pd.DataFrame, 
                                  vol_avg: pd.Series) -> Dict:
        """
        Leviathan Liquidity Matrix v2 Metrics
        - Phantom Delta (CVD)
        - Institutional Volume
        - Matrix State
        """
        last_row = df.iloc[-1]
        
        # Buy/Sell Pressure (Leviathan Math)
        bar_range = max(last_row['high'] - last_row['low'], 0.01)
        buy_p = last_row['volume'] * ((last_row['close'] - last_row['low']) + (last_row['high'] - last_row['open'])) / (2 * bar_range)
        buy_p = max(0.0, min(last_row['volume'], buy_p))
        sell_p = last_row['volume'] - buy_p
        delta = buy_p - sell_p
        
        is_inst_vol = last_row['volume'] > (vol_avg.iloc[-1] * 1.5)
        
        # Conviction Score (Simplified)
        conviction = 0
        if is_inst_vol: conviction += 40
        if abs(delta) > vol_avg.iloc[-1] * 0.5: conviction += 20
        # htf bias etc (mocked)
        conviction += 15 
        
        return {
            "phantom_delta": delta,
            "inst_vol_spike": is_inst_vol,
            "conviction_score": conviction,
            "matrix_state": "TRAPPING" if conviction >= 60 else "HUNTING"
        }

    @staticmethod
    def calculate_war_room_beast_score(df: pd.DataFrame, 
                                     indicators: Dict) -> Dict:
        """
        SML War Room Beast v2.0 Composite Score (0-100)
        - Engine 1: Trend & Structure
        - Engine 2: Momentum & Acceleration
        - Engine 3: Volume & Participation
        - Engine 4: MTF Alignment
        - Engine 5: Price Action & Traps
        """
        last_row = df.iloc[-1]
        
        # Engine 1: Trend & Structure (Max ~20)
        ts_bull = 0.0
        ts_bear = 0.0
        # simplified logic
        if indicators['ema_fast'] > indicators['ema_slow']: ts_bull += 6.0
        else: ts_bear += 6.0
        if last_row['close'] > indicators['ema_base']: ts_bull += 6.0
        else: ts_bear += 6.0
        # structure (HH/HL) - placeholder
        ts_bull += 8.0 if indicators.get('is_hh', False) else 0.0
        
        # Engine 2: Momentum (Max ~20)
        ma_bull = 0.0
        ma_bear = 0.0
        if indicators['rsi'] > 55: ma_bull += 10.0
        elif indicators['rsi'] < 45: ma_bear += 10.0
        if indicators.get('accel', 0) > 0: ma_bull += 10.0
        else: ma_bear += 10.0
        
        # Engine 3: Volume (Max ~20)
        vp_bull = 0.0
        vp_bear = 0.0
        if indicators['rvol'] > 1.1:
            if last_row['close'] > last_row['open']: vp_bull += 20.0
            else: vp_bear += 20.0
            
        # Engine 4: MTF (Max ~20) - placeholder
        mt_bull = 15.0 # assume strong mtf for now
        mt_bear = 0.0
        
        # Engine 5: Price Action (Max ~20)
        pa_bull = 0.0
        pa_bear = 0.0
        if indicators.get('is_trap', False) == "BEAR_TRAP": pa_bull += 20.0
        if indicators.get('is_trap', False) == "BULL_TRAP": pa_bear += 20.0
        
        bull_score = min(100, ts_bull + ma_bull + vp_bull + mt_bull + pa_bull)
        bear_score = min(100, ts_bear + ma_bear + vp_bear + mt_bear + pa_bear)
        edge = bull_score - bear_score
        
        return {
            "bull_score": bull_score,
            "bear_score": bear_score,
            "edge": edge,
            "bias": "STRONG LONG" if edge > 18 else "STRONG SHORT" if edge < -18 else "NEUTRAL",
            "grade": "A+" if abs(edge) > 25 else "B" if abs(edge) > 10 else "C"
        }
