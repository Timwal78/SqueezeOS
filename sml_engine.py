import os
import numpy as np
import pandas as pd
import math
import logging
import time
from enum import IntEnum, Enum
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SMLRegime(IntEnum):
    STEALTH = 0
    CONFLICT = 1
    EXECUTION = 2
    COLLAPSE = 3

class SMLLifecycle(Enum):
    DORMANT = "Dormant"
    EARLY = "Early"
    BUILDING = "Building"
    TRIGGERED = "Triggered"
    ACTIVE = "Active"
    EXTENDED = "Extended"
    EXHAUSTING = "Exhausting"
    INVALID = "Invalid"

class SMLEngine:
    """
    SML Fractal Cascade™ — Engine v2 (Python Port)
    Institutional implementation of multi-layer trend, risk, and regime intelligence.
    """

    def __init__(self, settings=None):
        self.settings = settings or {
            "norm_len": int(os.getenv("SML_NORM_LEN", "55")),
            "fast_len": int(os.getenv("SML_FAST_LEN", "5")),
            "slow_len": int(os.getenv("SML_SLOW_LEN", "21")),
            "roc_len": int(os.getenv("SML_ROC_LEN", "5")),
            "vol_len": int(os.getenv("SML_VOL_LEN", "20")),
            "hurst_len": int(os.getenv("SML_HURST_LEN", "100")),
            "bb_len": int(os.getenv("SML_BB_LEN", "20")),
            "bb_mult": float(os.getenv("SML_BB_MULT", "2.0")),
            "atr_len": int(os.getenv("SML_ATR_LEN", "14")),
            "swing_len": int(os.getenv("SML_SWING_LEN", "10")),
            "precursor_bias": float(os.getenv("SML_PRECURSOR_BIAS", "1.15")),
            "squeeze_bias": float(os.getenv("SML_SQUEEZE_BIAS", "1.15")),
            "mode_profile": os.getenv("SML_MODE_PROFILE", "Early") 
        }

    # ═══════════════════════════════════════════════════════════
    # CORE HELPERS
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def f_safe_div(a, b):
        """Safe division for scalars and series."""
        if isinstance(b, (pd.Series, np.ndarray)):
            return (a / b).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return a / b if b != 0 and not np.isnan(b) else 0.0

    @staticmethod
    def f_clamp(x, lo, hi):
        return max(lo, min(hi, float(x)))

    @staticmethod
    def f_classify(c2h, c2l, c2c, c1h, c1l):
        """Implements SML Fractal Acceptance logic."""
        accept_above = c2c > c1h
        accept_below = c2c < c1l
        if accept_above and not accept_below:
            return 1
        if accept_below and not accept_above:
            return -1
        return 0

    @staticmethod
    def f_sweep_state(c2h, c2l, c1h, c1l):
        """Implements SML Sweep detection."""
        if c2h > c1h and c2l >= c1l:
            return 1 # REJECT HI
        if c2l < c1l and c2h <= c1h:
            return 2 # REJECT LO
        if c2h > c1h and c2l < c1l:
            return 3 # CHOP
        return 0

    @staticmethod
    def f_state_str(direction, sweep):
        if direction == 1: return "ACCEPT UP"
        if direction == -1: return "ACCEPT DN"
        if sweep == 1: return "REJECT HI"
        if sweep == 2: return "REJECT LO"
        if sweep == 3: return "CHOP"
        return "INSIDE"

    @staticmethod
    def f_meaning_str(direction, sweep):
        if direction == 1: return "Price broke above and held — bullish"
        if direction == -1: return "Price broke below and held — bearish"
        if sweep == 1: return "Poked above then fell back — rejected breakout"
        if sweep == 2: return "Dipped below then bounced — rejected breakdown"
        if sweep == 3: return "Hit both sides — indecision, stay out"
        return "No clear move yet"

    @staticmethod
    def f_z(series, length):
        """Rolling Z-Score calculation."""
        if len(series) < 2: return 0.0
        l = min(len(series), int(length))
        window = series[-l:]
        mean, std = np.mean(window), np.std(window)
        return (series[-1] - mean) / (std + 1e-9)

    @staticmethod
    def f_norm100(x, divisor):
        """Normalization to 0-100 range similar to Pine Script f_norm100."""
        clamped = max(-1.0, min(1.0, float(x) / float(divisor)))
        return 50.0 + 50.0 * clamped

    def f_trend_score(self, close_series):
        """EMA-diff + ROC z-score fusion."""
        slow_len = int(self.settings.get('slow_len', 21))
        fast_len = int(self.settings.get('fast_len', 5))
        norm_len = int(self.settings.get('norm_len', 55))
        roc_len = int(self.settings.get('roc_len', 5))

        if len(close_series) < slow_len: return 0.0
        
        # Calculate EMAs
        ema_f = close_series.ewm(span=fast_len, adjust=False).mean()
        ema_s = close_series.ewm(span=slow_len, adjust=False).mean()
        diff = ema_f - ema_s
        
        tz = float(self.f_z(diff.values, norm_len))
        
        # ROC Calculation
        roc = close_series.pct_change(roc_len)
        rz = float(self.f_z(roc.dropna().values, norm_len))
        
        return 0.65 * tz + 0.35 * rz

    def f_rs_score(self, num_series, den_series):
        """Relative Strength Score (Rolling Z-score of Ratio's ROC)."""
        roc_len = int(self.settings.get('roc_len', 5))
        norm_len = int(self.settings.get('norm_len', 55))

        if len(num_series) < 5 or len(den_series) < 5: return 0.0
        ratio = num_series / den_series
        rr = ratio.pct_change(roc_len)
        return float(self.f_z(rr.dropna().values, norm_len))

    def f_vol_score(self, vol_series):
        """Volume Score (Rolling Z-score of Volume Ratio)."""
        vol_len = int(self.settings.get('vol_len', 20))
        norm_len = int(self.settings.get('norm_len', 55))

        if len(vol_series) < vol_len: return 0.0
        v_sma = vol_series.rolling(window=vol_len).mean()
        vr = vol_series / (v_sma + 1e-9)
        return float(self.f_z(vr.values, norm_len))

    def f_smi(self, close_series, high_series, low_series, len_smi=13, smooth1=2, smooth2=2):
        """Standard SMI (Stochastic Momentum Index) for Precursor momentum."""
        if len(close_series) < len_smi + smooth1 + smooth2:
            return 0.0
        
        center = (high_series.rolling(len_smi).max() + low_series.rolling(len_smi).min()) / 2.0
        diff = close_series - center
        
        diff_smooth = diff.ewm(span=smooth1, adjust=False).mean().ewm(span=smooth2, adjust=False).mean()
        
        rng = high_series.rolling(len_smi).max() - low_series.rolling(len_smi).min()
        rng_smooth = rng.ewm(span=smooth1, adjust=False).mean().ewm(span=smooth2, adjust=False).mean() / 2.0
        
        smi = 100.0 * self.f_safe_div(diff_smooth, rng_smooth)
        return float(smi.iloc[-1])

    def f_hurst(self, close_series):
        """Hurst Exponent (Rescaled Range R/S)."""
        hurst_len = int(self.settings.get('hurst_len', 100))
        if len(close_series) < 50: return 0.5
        
        l = min(len(close_series), hurst_len)
        window = close_series.iloc[-l:]
        
        log_ret = np.log(window / window.shift(1)).dropna()
        if len(log_ret) < 20: return 0.5
        
        mean_ret = float(log_ret.mean())
        dev = log_ret - mean_ret
        cum_dev = dev.cumsum()
        r = float(cum_dev.max() - cum_dev.min())
        s = float(log_ret.std())
        
        rs = r / (s + 1e-9)
        # Using a fixed log/log ratio for the Hurst exponent estimation
        hurst_val = np.log(rs) / np.log(l)
        return float(self.f_clamp(hurst_val, 0.0, 1.0))

    def f_round(self, val: float, digits: int) -> float:
        """Linter-friendly manual rounding helper."""
        try:
            factor = 10.0 ** int(digits)
            return float(math.floor(float(val) * factor + 0.5) / factor)
        except (ValueError, TypeError, ZeroDivisionError):
            return 0.0

    # ═══════════════════════════════════════════════════════════
    # FRACTAL CASCADE™ MULTI-TIMEFRAME ALIGNMENT
    # ═══════════════════════════════════════════════════════════

    def _resample_to_timeframes(self, bars: list) -> dict:
        """
        Resample daily OHLCV bars into 8 timeframes.
        bars: list of dicts with keys {date, open, high, low, close, volume}
        Returns: dict mapping timeframe labels to resampled OHLCV lists
        """
        if not bars or len(bars) == 0:
            return {}

        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(bars)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        else:
            df['date'] = pd.date_range(end=datetime.now(), periods=len(df), freq='D')

        df.set_index('date', inplace=True)

        resampled = {}

        # 1D: each bar as-is
        resampled['1D'] = bars

        # 2D: group every 2 bars
        if len(df) >= 2:
            grouped_2d = df.resample('2D').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['2D'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_2d.iterrows()
            ]

        # 4D: group every 4 bars
        if len(df) >= 4:
            grouped_4d = df.resample('4D').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['4D'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_4d.iterrows()
            ]

        # 1W: group by calendar week
        if len(df) >= 5:
            grouped_1w = df.resample('W').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['1W'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_1w.iterrows()
            ]

        # 2W: group every 2 calendar weeks
        if len(df) >= 10:
            grouped_2w = df.resample('2W').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['2W'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_2w.iterrows()
            ]

        # 1M: group by calendar month
        if len(df) >= 20:
            grouped_1m = df.resample('M').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['1M'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_1m.iterrows()
            ]

        # 3M: group by calendar quarter
        if len(df) >= 60:
            grouped_3m = df.resample('Q').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['3M'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_3m.iterrows()
            ]

        # 6M: group by half-year (Jan-Jun, Jul-Dec)
        if len(df) >= 120:
            grouped_6m = df.resample('6M').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            resampled['6M'] = [
                {
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                }
                for idx, row in grouped_6m.iterrows()
            ]

        return resampled

    def compute_fractal_cascade(self, symbol: str, history: dict) -> dict:
        """
        Compute SML Fractal Cascade™ multi-timeframe alignment logic.

        Args:
            symbol: trading symbol (e.g., "AAPL")
            history: dict with daily OHLCV bars as list of dicts
                     Keys: {date, open, high, low, close, volume}

        Returns:
            dict with:
                - per-timeframe classification (direction, sweep, state)
                - weighted alignment score
                - cascade bias and meaning
                - bull/bear/avoid counts
        """
        if symbol not in history or (isinstance(history[symbol], pd.DataFrame) and history[symbol].empty) or (isinstance(history[symbol], list) and len(history[symbol]) == 0):
            logger.warning(f"[Cascade] No history for {symbol}")
            return {}

        bars = history[symbol]
        if isinstance(bars, pd.DataFrame):
            bars = bars.reset_index().to_dict('records')

        # Ensure minimum data
        if len(bars) < 2:
            return {}

        # Resample into 8 timeframes
        tf_data = self._resample_to_timeframes(bars)

        # Timeframe weights (Pine v2 Cascade)
        weights = {
            '6M': 0.15,
            '3M': 0.14,
            '1M': 0.13,
            '2W': 0.12,
            '1W': 0.12,
            '4D': 0.11,
            '2D': 0.11,
            '1D': 0.12
        }

        # Result structure
        result = {
            'symbol': symbol,
            'timeframes': {},
            'bull_count': 0,
            'bear_count': 0,
            'avoid_count': 0,
            'active_tfs': 0,
            'alignment_score': 0.0,
            'cascade_bias': 'NEUTRAL',
            'cascade_meaning': 'Timeframes are mixed — no clear direction. WAIT.'
        }

        active_weight = 0.0
        raw_alignment = 0.0

        # Process each timeframe
        for tf in ['6M', '3M', '1M', '2W', '1W', '4D', '2D', '1D']:
            if tf not in tf_data or len(tf_data[tf]) < 2:
                continue

            bars_tf = tf_data[tf]
            c1 = bars_tf[-2]  # Previous candle
            c2 = bars_tf[-1]  # Current candle

            # Extract OHLC
            c1_h, c1_l = float(c1['high']), float(c1['low'])
            c2_h, c2_l, c2c = float(c2['high']), float(c2['low']), float(c2['close'])

            # Classify direction
            direction = self.f_classify(c2_h, c2_l, c2c, c1_h, c1_l)

            # Detect sweep state
            sweep = self.f_sweep_state(c2_h, c2_l, c1_h, c1_l)

            # State classification
            state = self.f_state_str(direction, sweep)
            meaning = self.f_meaning_str(direction, sweep)

            # Record per-timeframe result
            result['timeframes'][tf] = {
                'direction': direction,
                'sweep': sweep,
                'state': state,
                'meaning': meaning,
                'c1_high': c1_h,
                'c1_low': c1_l,
                'c2_close': c2c,
                'c2_high': c2_h,
                'c2_low': c2_l
            }

            # Accumulate weighted alignment
            w = weights[tf]
            active_weight += w
            raw_alignment += w * direction

            # Count directional bias
            if direction > 0:
                result['bull_count'] += 1
            elif direction < 0:
                result['bear_count'] += 1
            else:
                result['avoid_count'] += 1

            result['active_tfs'] += 1

        # Compute weighted alignment score
        if active_weight > 0:
            result['alignment_score'] = (raw_alignment / active_weight) * 100.0
        else:
            result['alignment_score'] = 0.0

        # Determine cascade bias and meaning
        align = result['alignment_score']
        if align > 50.0:
            result['cascade_bias'] = 'STRONG BULL'
            result['cascade_meaning'] = 'Almost all timeframes agree price is going UP. Strong buy conditions.'
        elif align > 25.0:
            result['cascade_bias'] = 'BULL'
            result['cascade_meaning'] = 'Most timeframes favor upside. Look for long entries on dips.'
        elif align > 10.0:
            result['cascade_bias'] = 'LEAN BULL'
            result['cascade_meaning'] = 'Slight bullish lean but not convincing yet.'
        elif align < -50.0:
            result['cascade_bias'] = 'STRONG BEAR'
            result['cascade_meaning'] = 'Almost all timeframes agree price is going DOWN. Avoid longs.'
        elif align < -25.0:
            result['cascade_bias'] = 'BEAR'
            result['cascade_meaning'] = 'Most timeframes favor downside. Avoid buying.'
        elif align < -10.0:
            result['cascade_bias'] = 'LEAN BEAR'
            result['cascade_meaning'] = 'Slight bearish lean. Not a great time to buy.'
        else:
            result['cascade_bias'] = 'NEUTRAL'
            result['cascade_meaning'] = 'Timeframes are mixed — no clear direction. WAIT.'

        return result

    def compute_all(self, target_symbol: str, market_history: dict, mtf_data: dict = None, net_pressure_history: list = None, use_cascade: bool = True):
        """
        Main calculation entry point. Overhauled for Ignition War Room v2.
        mtf_data: Optional dict mapping TF labels (e.g. '1W') to classification results.
        use_cascade: If True, compute Fractal Cascade and integrate into alignment scoring.
        """
        # 1. Dependency Checks
        required = ["SPY", "VIX", "TLT", "DXY", "QQQ", "IWM", "IJR", "XRT", target_symbol]
        for s in required:
            if s not in market_history or market_history[s].empty:
                logger.warning(f"[SML] Missing history for {s}")
                return None

        # Compute Fractal Cascade if enabled and no pre-computed mtf_data
        if use_cascade and not mtf_data:
            cascade_result = self.compute_fractal_cascade(target_symbol, market_history)
            if cascade_result and 'timeframes' in cascade_result:
                # Convert cascade result to mtf_data format for compatibility
                mtf_data = {}
                for tf, tf_result in cascade_result['timeframes'].items():
                    mtf_data[tf] = {'classify': tf_result['direction']}

        # Helpers
        def get_c(sym): return market_history[sym]['close']
        def get_v(sym): return market_history[sym]['volume']
        def get_h(sym): return market_history[sym]['high']
        def get_l(sym): return market_history[sym]['low']

        # 2. Score Components
        tlt_s = self.f_trend_score(get_c("TLT"))
        dxy_s = self.f_trend_score(get_c("DXY"))
        vix_s = self.f_trend_score(get_c("VIX"))
        macro_score = 0.40 * tlt_s - 0.30 * dxy_s - 0.30 * vix_s

        spy_s = self.f_trend_score(get_c("SPY"))
        qqq_s = self.f_trend_score(get_c("QQQ"))
        iwm_s = self.f_trend_score(get_c("IWM"))
        ijr_s = self.f_trend_score(get_c("IJR"))
        risk_score = 0.20 * spy_s + 0.15 * qqq_s + 0.35 * iwm_s + 0.30 * ijr_s

        xrt_s = self.f_trend_score(get_c("XRT"))
        xrt_rs_spy = self.f_rs_score(get_c("XRT"), get_c("SPY"))
        basket_score = 0.50 * xrt_s + 0.25 * iwm_s + 0.15 * ijr_s + 0.10 * xrt_rs_spy

        target_c = get_c(target_symbol)
        target_v = get_v(target_symbol)
        target_trend = self.f_trend_score(target_c)
        target_rs_spy = self.f_rs_score(target_c, get_c("SPY"))
        target_rs_xrt = self.f_rs_score(target_c, get_c("XRT"))
        target_vol_s = self.f_vol_score(target_v)
        target_score = 0.40 * target_trend + 0.25 * target_rs_spy + 0.15 * target_rs_xrt + 0.20 * target_vol_s

        # ═══════════════════════════════════════════════════════════
        # SQUEEZE & PRECURSOR ENGINE (v2)
        # ═══════════════════════════════════════════════════════════
        
        # 1. BB/KC Calculation (Institutional Carter Squeeze)
        bb_len = int(self.settings.get('bb_len', 20))
        bb_mult = float(self.settings.get('bb_mult', 2.0))
        atr_len = int(self.settings.get('atr_len', 14))
        
        bb_basis = target_c.rolling(window=bb_len).mean()
        bb_dev = target_c.rolling(window=bb_len).std()
        bb_upper = bb_basis + bb_mult * bb_dev
        bb_lower = bb_basis - bb_mult * bb_dev
        
        # Keltner (Using EMA and ATR)
        kc_basis = target_c.ewm(span=bb_len, adjust=False).mean()
        # ATR Calculation
        tr = pd.concat([
            get_h(target_symbol) - get_l(target_symbol),
            abs(get_h(target_symbol) - target_c.shift(1)),
            abs(get_l(target_symbol) - target_c.shift(1))
        ], axis=1).max(axis=1)
        target_atr = tr.rolling(window=atr_len).mean()
        
        kc_width = target_atr * 1.5
        kc_upper = kc_basis + kc_width
        kc_lower = kc_basis - kc_width
        
        # Squeeze Detection: BB inside KC
        is_squeezing = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        squeeze_val = float(is_squeezing.iloc[-1])
        
        # Compression Score (Z-score of BB width normalized)
        bb_w = (bb_upper - bb_lower) / (bb_basis + 1e-9)
        bb_w_s = self.f_z(bb_w.values, int(self.settings['norm_len']))
        compression_score = -bb_w_s # Tightness = positive score
        
        # 2. Precursor Momentum (SMI)
        smi_val = self.f_smi(target_c, get_h(target_symbol), get_l(target_symbol))
        
        # 3. Final Precursor Scoring
        # A true precursor happens when we are in a squeeze AND momentum is building
        precursor_score = self.f_clamp((compression_score * 20.0) + (abs(smi_val) * 0.5), 0.0, 100.0)
        if not is_squeezing.iloc[-1]:
            precursor_score *= 0.5 # Penalty for no squeeze
            
        squeeze_score = self.f_clamp(precursor_score * 1.15 if is_squeezing.iloc[-1] else 0.0, 0.0, 100.0)
        early_window_score = self.f_clamp(30.0 + (compression_score * 10.0), 0.0, 100.0)
        
        target_ema = target_c.ewm(span=int(self.settings['slow_len']), adjust=False).mean()
        target_stretch_raw = self.f_safe_div(target_c - target_ema, target_ema)
        target_stretch = self.f_z(target_stretch_raw.values, int(self.settings['norm_len']))
        
        reflex_score = 0.35 * target_vol_s + 0.30 * (-bb_w_s) + 0.20 * target_rs_spy + 0.15 * target_trend

        # ═══════════════════════════════════════════════════════════
        # REGIME LOGIC (v2)
        # ═══════════════════════════════════════════════════════════

        hurst_val = self.f_hurst(target_c)
        hurst_trending = hurst_val > 0.58
        hurst_noise = 0.42 <= hurst_val <= 0.58
        hurst_reverting = hurst_val < 0.42
        hurst_confirms = hurst_trending or hurst_val > 0.45 

        squeeze_setup = compression_score > 0.70 and target_rs_spy > 0.00 and basket_score > -0.20 and target_stretch < 1.00
        deleveraging = vix_s > 0.80 and risk_score < -0.40 and basket_score < -0.30
        
        recent_low = float(target_c.iloc[-int(self.settings['swing_len']):].min())

        # HTF Score component for chains (v2 Cascade Map)
        # This must be computed BEFORE regime detection which uses it
        htf_alignment = 0.0
        bull_count = 0
        bear_count = 0
        avoid_count = 0
        active_tfs = 0
        cascade_bias = "NEUTRAL"
        cascade_meaning = "Timeframes are mixed — no clear direction. WAIT."

        if mtf_data:
            # Pine v2 Weighted Cascade
            weights = {'6M': 0.15, '3M': 0.14, '1M': 0.13, '2W': 0.12, '1W': 0.12, '4D': 0.11, '2D': 0.11, '1D': 0.12}
            active_weight = 0.0
            raw_alignment = 0.0

            for tf, result in mtf_data.items():
                if tf in weights:
                    w = weights[tf]
                    active_weight += w
                    d = result.get('classify', 0)
                    raw_alignment += w * d

                    if d > 0: bull_count += 1
                    elif d < 0: bear_count += 1
                    else: avoid_count += 1
                    active_tfs += 1

            htf_alignment = (raw_alignment / active_weight * 100.0) if active_weight > 0 else 0.0

            # Cascade Bias
            if htf_alignment > 50.0: cascade_bias = "STRONG BULL"
            elif htf_alignment > 25.0: cascade_bias = "BULL"
            elif htf_alignment > 10.0: cascade_bias = "LEAN BULL"
            elif htf_alignment < -50.0: cascade_bias = "STRONG BEAR"
            elif htf_alignment < -25.0: cascade_bias = "BEAR"
            elif htf_alignment < -10.0: cascade_bias = "LEAN BEAR"

            # Cascade Meaning (Top Verdict)
            if htf_alignment > 50.0: cascade_meaning = "Almost all timeframes agree price is going UP. Strong buy conditions."
            elif htf_alignment > 25.0: cascade_meaning = "Most timeframes favor upside. Look for long entries on dips."
            elif htf_alignment > 10.0: cascade_meaning = "Slight bullish lean but not convincing yet."
            elif htf_alignment < -50.0: cascade_meaning = "Almost all timeframes agree price is going DOWN. Avoid longs."
            elif htf_alignment < -25.0: cascade_meaning = "Most timeframes favor downside. Avoid buying."
            elif htf_alignment < -10.0: cascade_meaning = "Slight bearish lean. Not a great time to buy."

        # Map to old variable for internal logic
        mtf_align = htf_alignment

        abs_align = abs(mtf_align)
        regime = SMLRegime.CONFLICT
        regime_conf = 40.0

        if abs_align < 15.0 and not hurst_trending:
            regime = SMLRegime.STEALTH
            regime_conf = (15.0 - abs_align) / 15.0 * 60.0 + (40.0 if hurst_reverting else 20.0)
        elif abs_align >= 15.0 and abs_align < 40.0 and hurst_noise:
            # CONFLICT is already default, just setting conf
            regime_conf = self.f_clamp(abs_align / 40.0 * 100.0, 20.0, 80.0)
        elif abs_align >= 40.0 and hurst_trending:
            regime = SMLRegime.EXECUTION
            regime_conf = self.f_clamp(abs_align / 100.0 * 80.0 + 20.0, 40.0, 100.0)
        elif abs_align >= 30.0 and not hurst_trending:
            # Simple approximation of crossing zero logic without full history
            regime = SMLRegime.COLLAPSE
            regime_conf = 60.0

        if squeeze_setup and regime < SMLRegime.EXECUTION:
            regime = SMLRegime.CONFLICT # Squeeze setup often happens in Conflict
            regime_conf = max(regime_conf, 65.0)
        if deleveraging:
            regime = SMLRegime.COLLAPSE
            regime_conf = max(regime_conf, 75.0)

        # Compute HTF score from already-calculated mtf_align
        htf_score = mtf_align / 50.0

        # Dynamic Chain Weights based on Regime
        w_macro, w_risk, w_basket, w_target, w_reflex, w_htf = 0.18, 0.18, 0.20, 0.24, 0.10, 0.10
        if regime == SMLRegime.EXECUTION:
            w_macro, w_risk, w_basket, w_target, w_reflex, w_htf = 0.12, 0.14, 0.18, 0.28, 0.13, 0.15
        elif regime == SMLRegime.COLLAPSE:
            w_macro, w_risk, w_basket, w_target, w_reflex, w_htf = 0.25, 0.24, 0.20, 0.15, 0.08, 0.08

        w_sum = w_macro + w_risk + w_basket + w_target + w_reflex + w_htf
        
        def f_pos01(x): return self.f_clamp(x / 2.0, 0.0, 1.0)
        def f_neg01(x): return self.f_clamp((-x) / 2.0, 0.0, 1.0)

        bull_chain = 100.0 * (
            (w_macro * f_pos01(macro_score)) + (w_risk * f_pos01(risk_score)) + 
            (w_basket * f_pos01(basket_score)) + (w_target * f_pos01(target_score)) + 
            (w_reflex * f_pos01(reflex_score)) + (w_htf * f_pos01(htf_score))
        ) / w_sum
        bear_chain = 100.0 * (
            (w_macro * f_neg01(macro_score)) + (w_risk * f_neg01(risk_score)) + 
            (w_basket * f_neg01(basket_score)) + (w_target * f_neg01(target_score)) + 
            (w_reflex * f_neg01(reflex_score)) + (w_htf * f_neg01(htf_score))
        ) / w_sum
        net_pressure = bull_chain - bear_chain

        dep_bull_agree = (1 if macro_score > 0 else 0) + (1 if risk_score > 0 else 0) + (1 if basket_score > 0 else 0) + (1 if target_score > 0 else 0) + (1 if reflex_score > 0 else 0)
        dep_bear_agree = (1 if macro_score < 0 else 0) + (1 if risk_score < 0 else 0) + (1 if basket_score < -0 else 0) + (1 if target_score < 0 else 0) + (1 if reflex_score < 0 else 0)
        
        dep_alignment = float(dep_bull_agree if net_pressure >= 0 else dep_bear_agree) / 5.0
        htf_align_norm = self.f_clamp(abs_align / 100.0, 0.0, 1.0)
        separation = self.f_clamp(abs(net_pressure) / 60.0, 0.0, 1.0)
        confirmation = self.f_clamp(abs(target_score) / 1.5, 0.0, 1.0)
        
        # Pine v2 confidence: 30% dep, 25% htf, 20% sep, 15% conf, 10% regime
        confidence = 100.0 * (0.30 * dep_alignment + 0.25 * htf_align_norm + 0.20 * separation + 0.15 * confirmation + 0.10 * (regime_conf / 100.0))
        if regime == SMLRegime.EXECUTION and hurst_trending:
            confidence += 10.0 # Hurst Bonus
            
        confidence = self.f_clamp(confidence, 0.0, 100.0)

        # ═══════════════════════════════════════════════════════════
        # LIFECYCLE & DECISION (v2)
        # ═══════════════════════════════════════════════════════════

        # Lifecycle Logic Logic (Pine v2)
        net_slope = 0.0
        if net_pressure_history and len(net_pressure_history) >= 4:
            net_slope = net_pressure - net_pressure_history[-4]

        early_state      = 8.0 < net_pressure <= 15.0 and confidence >= 40.0
        building_state   = net_pressure > 15.0 and net_slope > 0.0 and target_rs_spy > 0.0
        triggered_state  = net_pressure > 22.0 and target_c.iloc[-1] > target_ema.iloc[-1] and target_vol_s > -0.25 and target_rs_spy > 0.0
        active_state     = net_pressure > 30.0 and target_c.iloc[-1] > target_ema.iloc[-1] and target_vol_s > 0.0 and target_trend > 0.0
        extended_state   = active_state and target_stretch > 1.00
        exhausting_state = net_pressure > 25.0 and target_stretch > 1.20 and net_slope < 0.0
        invalid_state    = net_pressure < 0.0 and target_c.iloc[-1] < target_ema.iloc[-1]

        lifecycle = SMLLifecycle.DORMANT
        if invalid_state: lifecycle = SMLLifecycle.INVALID
        elif exhausting_state: lifecycle = SMLLifecycle.EXHAUSTING
        elif extended_state: lifecycle = SMLLifecycle.EXTENDED
        elif active_state: lifecycle = SMLLifecycle.ACTIVE
        elif triggered_state: lifecycle = SMLLifecycle.TRIGGERED
        elif building_state: lifecycle = SMLLifecycle.BUILDING
        elif early_state: lifecycle = SMLLifecycle.EARLY

        # Decisions (Pine v2)
        # buyNow = triggeredState and confidence >= 55.0 and targetStretch < 1.10 and macroScore > -0.60 and basketScore > 0.0 and htfBullOK and regimeOK
        htf_bull_ok = mtf_align > 0.0 # and bullTFs >= 3 (need to implement TFs)
        regime_ok = regime == SMLRegime.CONFLICT or regime == SMLRegime.EXECUTION
        
        buy_now = triggered_state and confidence >= 55.0 and target_stretch < 1.10 and macro_score > -0.60 and basket_score > 0.0 and htf_bull_ok and regime_ok
        buy_confirm = not buy_now and building_state and confidence >= 45.0 and compression_score > -0.50 and target_c.iloc[-1] > target_ema.iloc[-1] and mtf_align > -10.0
        trim = net_pressure > 25.0 and exhausting_state
        sell_exit = net_pressure < -18.0 and target_c.iloc[-1] < target_ema.iloc[-1] and confidence >= 50.0  # and htfBearOK
        
        decision = "WAIT"
        if buy_now: decision = "BUY NOW"
        elif buy_confirm: decision = "BUY CONFIRM"
        elif trim: decision = "TRIM / TP"
        elif sell_exit: decision = "SELL / EXIT"
        elif net_pressure > 10.0 and target_c.iloc[-1] > target_ema.iloc[-1]: decision = "HOLD"

        # Levels
        target_atr_series = (target_c.rolling(2).max() - target_c.rolling(2).min())
        target_atr_val = float(target_atr_series.ewm(span=int(self.settings['atr_len']), adjust=False).mean().iloc[-1])
        
        last_close = float(target_c.iloc[-1])
        target_ema_val = float(target_ema.iloc[-1])
        
        long_inv = float(min(target_ema_val - target_atr_val * 0.75, recent_low))
        short_inv = float(max(target_ema_val + target_atr_val * 0.75, float(target_c.iloc[-int(self.settings['swing_len']):].max())))
        
        # Optionally include detailed Fractal Cascade data
        cascade_data = {}
        if use_cascade and mtf_data:
            cascade_detail = self.compute_fractal_cascade(target_symbol, market_history)
            if cascade_detail:
                cascade_data = {
                    'cascade_timeframes': cascade_detail.get('timeframes', {}),
                    'cascade_alignment_score': self.f_round(cascade_detail.get('alignment_score', 0.0), 2),
                    'cascade_bull_count': cascade_detail.get('bull_count', 0),
                    'cascade_bear_count': cascade_detail.get('bear_count', 0),
                    'cascade_avoid_count': cascade_detail.get('avoid_count', 0),
                    'cascade_active_tfs': cascade_detail.get('active_tfs', 0)
                }

        result = {
            "symbol": str(target_symbol),
            "regime": regime,
            "regime_text": regime.name,
            "regime_confidence": self.f_round(regime_conf, 1),
            "confidence": self.f_round(confidence, 1),
            "net_pressure": self.f_round(net_pressure, 2),
            "bull_chain": self.f_round(bull_chain, 1),
            "bear_chain": self.f_round(bear_chain, 1),
            "macro_score": self.f_round(macro_score, 2),
            "risk_score": self.f_round(risk_score, 2),
            "basket_score": self.f_round(basket_score, 2),
            "target_score": self.f_round(target_score, 2),
            "reflex_score": self.f_round(reflex_score, 2),
            "compression_score": self.f_round(compression_score, 2),
            "target_stretch": self.f_round(target_stretch, 2),
            "precursor_score": self.f_round(precursor_score, 1),
            "squeeze_score": self.f_round(squeeze_score, 1),
            "early_window_score": self.f_round(early_window_score, 1),
            "smi_val": self.f_round(smi_val, 2),
            "is_squeezing": bool(squeeze_val),
            "hurst_val": self.f_round(hurst_val, 2),
            "hurst_confirms": bool(hurst_confirms),
            "recent_low": recent_low,
            "lifecycle": lifecycle,
            "lifecycle_text": lifecycle.value,
            "decision": str(decision),
            "levels": {
                "invalidation": self.f_round(short_inv if decision == "SELL / EXIT" else long_inv, 3),
                "tp1": self.f_round(last_close + (target_atr_val * 1.5 if decision != "SELL / EXIT" else -target_atr_val * 1.5), 3),
                "tp2": self.f_round(last_close + (target_atr_val * 3.0 if decision != "SELL / EXIT" else -target_atr_val * 3.0), 3)
            },
            "timestamp": float(time.time()),
            "htf_alignment": self.f_round(htf_alignment, 2),
            "bull_count": bull_count,
            "bear_count": bear_count,
            "avoid_count": avoid_count,
            "cascade_bias": cascade_bias,
            "cascade_meaning": cascade_meaning
        }

        # Merge cascade data if available
        result.update(cascade_data)

        return result
