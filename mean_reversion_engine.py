import yfinance as yf
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

# Standard SqueezeOS Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MEAN_REVERSION_ENGINE")

class MeanReversionEngine:
    """
    SQUEEZE OS Multi-Ticker Mean Reversion Scanner v2.0
    Finds oversold/overbought reversals in a broad universe of stocks.
    Prioritizes budget-friendly tickers (<$50 default).
    """

    def __init__(self, bb_period=20, bb_std=2.0, rsi_period=14, max_price=100.0):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.max_price = max_price

    def fetch_batch_data(self, symbols, days=100):
        """Fetch historical data for a list of symbols efficiently."""
        if not symbols: return {}
        logger.info(f"Batch fetching {len(symbols)} symbols...")
        # yf.download is faster for batches
        try:
            # yfinance threads=True causes deadlocks on Windows and hangs the Flask server.
            data = yf.download(symbols, period=f"{days}d", group_by='ticker', progress=False, threads=False)
            return data
        except Exception as e:
            logger.error(f"Batch fetch error: {e}")
            return {}

    def calculate_indicators(self, df):
        """Calculate Bollinger Bands, RSI, Z-Score, and Advanced Filters."""
        # Ensure we have enough data (200d for long-term trend)
        if len(df) < 20: return None
        
        # 1. Bollinger Bands (20, 2)
        df['SMA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA20'] + (self.bb_std * df['STD20'])
        df['BB_Lower'] = df['SMA20'] - (self.bb_std * df['STD20'])

        # 2. RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))

        # 3. Z-Score (Distance from Mean)
        df['Z_Score'] = (df['Close'] - df['SMA20']) / (df['STD20'] + 1e-9)
        
        # 4. Long-Term Trend (200 SMA)
        if len(df) >= 200:
            df['SMA200'] = df['Close'].rolling(window=200).mean()
        else:
            df['SMA200'] = df['Close'].rolling(window=len(df)).mean()

        # 5. Relative Volume (RVOL)
        df['Vol_SMA20'] = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / (df['Vol_SMA20'] + 1e-9)

        # 6. Green Bar Confirmation (Close > Open)
        df['is_green'] = df['Close'] > df['Open']
        
        return df

    def scan_universe(self, symbols, show_all=False):
        """Scan a list of symbols and yield prioritized opportunities with Edge Boosters."""
        # Multi-ticker fetch (requesting more days to ensure SMA200 stability)
        batch_df = self.fetch_batch_data(symbols, days=250)
        
        for sym in symbols:
            try:
                if len(symbols) > 1:
                    df = batch_df[sym].copy() if sym in batch_df.columns.levels[0] else None
                else:
                    df = batch_df.copy()
                
                if df is None or df.dropna(subset=['Close']).empty: continue
                
                df = self.calculate_indicators(df)
                if df is None: continue
                
                last = df.iloc[-1]
                price = float(last['Close'])
                
                # Budget Filter
                if price > self.max_price: continue
                
                rsi = float(last['RSI'])
                z_score = float(last['Z_Score'])
                rvol = float(last['RRV'] if 'RRV' in last else last['RVOL'])
                sma200 = float(last['SMA200'])
                is_green = bool(last['is_green'])
                
                # --- Edge Boosters ---
                is_above_sma200 = price > sma200  # Pullback in an uptrend (High Probability)
                is_below_sma200 = price < sma200  # Death spiral (Lower Probability)
                high_vol = rvol > 1.5           # Capitulation spike (Exhaustion confirmed)
                
                # Signal logic
                is_oversold = (price < last['BB_Lower']) and (rsi < 30)
                is_overbought = (price > last['BB_Upper']) and (rsi > 70)
                
                # Potential/Near-miss logic
                is_near_oversold = (z_score < -1.5) or (rsi < 35)
                is_near_overbought = (z_score > 1.5) or (rsi > 65)
                
                if not (is_oversold or is_overbought or is_near_oversold or is_near_overbought or show_all): continue
                
                # Confidence Calculation (Weighted 0-100)
                base_conf = ((35 - rsi) / 35 * 50 + 50) if (is_oversold or is_near_oversold) else ((rsi - 65) / 35 * 50 + 50) if (is_overbought or is_near_overbought) else 0
                z_conf = min(abs(z_score) / 3.0 * 100, 100) if abs(z_score) > 1.0 else 0
                
                # Boosters
                boost = 0
                if is_above_sma200 and (is_oversold or is_near_oversold): boost += 15 # Buy with trend
                if high_vol: boost += 10 # Confidence in exhaustion
                if is_green: boost += 5   # Buyers are stepping in
                
                confidence = round(min(0.5 * base_conf + 0.5 * z_conf + boost, 100), 2)
                
                flags = []
                if is_above_sma200: flags.append("TREND+")
                if high_vol: flags.append("VOL!")
                if is_green: flags.append("BUYER+")
                
                yield {
                    "symbol": sym,
                    "price": float(round(price, 2)),
                    "rsi": float(round(rsi, 2)),
                    "z_score": float(round(z_score, 2)),
                    "rvol": float(round(rvol, 2)),
                    "status": "OVERSOLD" if is_oversold else "NEAR OVERSOLD" if is_near_oversold else "OVERBOUGHT" if is_overbought else "NEAR OVERBOUGHT" if is_near_overbought else "NEUTRAL",
                    "triggered": bool(is_oversold or is_overbought),
                    "confidence": float(confidence),
                    "flags": " ".join(flags),
                    "action": "PUT CREDIT SPREAD" if (is_oversold or is_near_oversold) else "CALL CREDIT SPREAD" if (is_overbought or is_near_overbought) else "WAIT"
                }
            except Exception as e:
                logger.debug(f"Error scanning {sym}: {e}")
                

    def print_scanner_report(self, opportunities):
        """Display a rich summary of the top findings."""
        print("\n" + "═"*85)
        print(" SQUEEZE OS: MEAN REVERSION WATCHLIST ".center(85))
        print(f" (Filtered: Price < ${self.max_price}) ".center(85))
        print("═"*85)
        
        if not opportunities:
            print("  NO OPPORTUNITIES DETECTED CURRENTLY.  ".center(85))
            print("═"*85 + "\n")
            return

        print(f"{'SYMBOL':<10} | {'PRICE':<8} | {'RSI':<6} | {'Z':<5} | {'RVOL':<5} | {'STATUS':<15} | {'FLAGS':<10} | {'ACTION'}")
        print("-" * 85)
        
        for o in opportunities[:15]:
            color = "\033[92m" if "OVERSOLD" in o['status'] else "\033[91m" if "OVERBOUGHT" in o['status'] else ""
            bold = "\033[1m" if o['triggered'] else ""
            reset = "\033[0m"
            print(f"{bold}{o['symbol']:<10}{reset} | ${o['price']:<7} | {o['rsi']:<6} | {o['z_score']:<5} | {o['rvol']:<5} | {color}{o['status']:<15}{reset} | {o['flags']:<10} | {o['action']}")
            
        print("═"*85 + "\n")

if __name__ == "__main__":
    # Test on a diverse list of mid-range liquid stocks
    engine = MeanReversionEngine(max_price=100.0)
    test_universe = ["AMD", "NIO", "PLTR", "SOFI", "PFE", "F", "BAC", "T", "VALE", "AAL"]
    opps = engine.scan_universe(test_universe)
    engine.print_scanner_report(opps)
