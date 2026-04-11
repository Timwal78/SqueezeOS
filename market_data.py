import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import logging
import os
import time
import threading
from functools import lru_cache

class MarketDataService:
    def __init__(self):
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        if not self.alpha_vantage_key:
            logging.getLogger(__name__).warning("ALPHA_VANTAGE_API_KEY not set — Alpha Vantage data will be unavailable")
        self.cache = {}
        self.cache_duration = 20  # RELAXED: 20 seconds (was 60s) for live streaming
        self.request_lock = threading.Lock()
        self.last_request_times = {}
        self.min_request_interval = 0.1  # RELAXED: 0.1 seconds (was 2s) between requests per symbol
        
    def get_current_timestamp(self):
        """Get current timestamp in EDT format"""
        edt = timezone(timedelta(hours=-4))  # EDT is UTC-4
        return datetime.now(edt).strftime("%Y-%m-%d %I:%M:%S %p EDT")
    
    def get_price_data(self, symbol):
        """Get basic price data for a symbol with caching and rate limiting"""
        # Check cache first
        cache_key = f"price_{symbol}"
        if self._is_cached_and_fresh(cache_key):
            return self.cache[cache_key]['data']
        
        # Rate limiting
        if not self._can_make_request(symbol):
            logging.warning(f"Rate limit hit for {symbol}, returning cached data if available")
            if cache_key in self.cache:
                return self.cache[cache_key]['data']
            return None
        
        try:
            with self.request_lock:
                self.last_request_times[symbol] = time.time()
            
            # Handle crypto symbols
            if symbol.endswith('-USD') or symbol in ['BTC', 'ETH', 'DOGE', 'SHIB']:
                result = self._get_crypto_price(symbol)
            else:
                # Handle stock/ETF symbols with minimal data fetch
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1d", interval="1d")  # Reduced data fetch
                
                if hist.empty:
                    return None
                    
                current_price = hist['Close'].iloc[-1]
                
                # Get basic info without triggering full info fetch
                try:
                    info = ticker.info
                    market_cap = info.get("marketCap")
                except Exception as e:
                    logging.getLogger(__name__).debug(f"[MARKET] Failed to fetch info for {symbol}: {e}")
                    market_cap = None
                
                result = {
                    "symbol": symbol,
                    "price": round(float(current_price), 2),
                    "currency": "USD",
                    "market_cap": market_cap,
                    "volume": int(hist['Volume'].iloc[-1]) if not hist['Volume'].empty else 0,
                    "change_24h": self._calculate_24h_change(hist),
                    "last_updated": self.get_current_timestamp()
                }
            
            # Cache the result
            if result:
                self.cache[cache_key] = {
                    'data': result,
                    'timestamp': time.time()
                }
            
            return result
            
        except Exception as e:
            logging.error(f"Error fetching price data for {symbol}: {e}")
            # Return cached data if available
            if cache_key in self.cache:
                return self.cache[cache_key]['data']
            return None
    
    def get_detailed_data(self, symbol):
        """Get detailed market data including technical indicators"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="30d")
            
            if hist.empty:
                return None
            
            # Calculate technical indicators
            close_prices = hist['Close']
            sma_20 = close_prices.rolling(window=20).mean().iloc[-1]
            sma_50 = close_prices.rolling(window=min(50, len(hist))).mean().iloc[-1]
            
            # Calculate RSI
            rsi = self._calculate_rsi(hist['Close'])
            
            # Calculate volume indicators
            volume_series = hist['Volume']
            avg_volume = volume_series.rolling(window=20).mean().iloc[-1]
            volume_ratio = volume_series.iloc[-1] / avg_volume if avg_volume > 0 else 1
            
            return {
                "symbol": symbol,
                "price": round(float(hist['Close'].iloc[-1]), 2),
                "volume": int(hist['Volume'].iloc[-1]),
                "sma_20": round(float(sma_20), 2) if not pd.isna(sma_20) else None,
                "sma_50": round(float(sma_50), 2) if not pd.isna(sma_50) else None,
                "rsi": round(float(rsi), 2) if not pd.isna(rsi) else None,
                "volume_ratio": round(float(volume_ratio), 2),
                "change_24h": self._calculate_24h_change(hist),
                "high_52w": round(float(hist['High'].max()), 2),
                "low_52w": round(float(hist['Low'].min()), 2),
                "last_updated": self.get_current_timestamp()
            }
            
        except Exception as e:
            logging.error(f"Error fetching detailed data for {symbol}: {e}")
            return None
    
    def _get_crypto_price(self, symbol):
        """Get cryptocurrency price from CoinGecko"""
        try:
            # Map common crypto symbols
            crypto_map = {
                'BTC-USD': 'bitcoin',
                'BTC': 'bitcoin',
                'ETH-USD': 'ethereum',
                'ETH': 'ethereum',
                'DOGE-USD': 'dogecoin',
                'DOGE': 'dogecoin',
                'SHIB-USD': 'shiba-inu',
                'SHIB': 'shiba-inu'
            }
            
            coin_id = crypto_map.get(symbol, symbol.lower().replace('-usd', ''))
            
            url = f"{self.coingecko_base_url}/simple/price"
            params = {
                'ids': coin_id,
                'vs_currencies': 'usd',
                'include_24hr_change': 'true',
                'include_market_cap': 'true',
                'include_24hr_vol': 'true'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if coin_id in data:
                coin_data = data[coin_id]
                return {
                    "symbol": symbol,
                    "price": coin_data.get('usd', 0),
                    "currency": "USD",
                    "market_cap": coin_data.get('usd_market_cap'),
                    "volume": coin_data.get('usd_24h_vol', 0),
                    "change_24h": coin_data.get('usd_24h_change', 0),
                    "last_updated": self.get_current_timestamp()
                }
            
            return None
            
        except Exception as e:
            logging.error(f"Error fetching crypto price for {symbol}: {e}")
            return None
    
    def _calculate_24h_change(self, hist):
        """Calculate 24h price change percentage"""
        try:
            if len(hist) < 2:
                return 0
            current_price = hist['Close'].iloc[-1]
            prev_price = hist['Close'].iloc[-2]
            return round(((current_price - prev_price) / prev_price) * 100, 2)
        except Exception as e:
            logging.getLogger(__name__).warning(f"[MARKET] 24h change calculation failed: {e}")
            return 0
    
    def _calculate_rsi(self, prices, period=14):
        """Calculate Relative Strength Index"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1]
        except Exception as e:
            logging.getLogger(__name__).warning(f"[MARKET] RSI calculation failed: {e}")
            return None  # Return None instead of fake neutral RSI
    
    def _is_cached_and_fresh(self, cache_key):
        """Check if data is cached and still fresh"""
        if cache_key not in self.cache:
            return False
        return (time.time() - self.cache[cache_key]['timestamp']) < self.cache_duration
    
    def _can_make_request(self, symbol):
        """Check if we can make a request for this symbol (rate limiting)"""
        if symbol not in self.last_request_times:
            return True
        return (time.time() - self.last_request_times[symbol]) >= self.min_request_interval
    
    def get_market_status(self):
        """Get current market status and hours information"""
        est = timezone(timedelta(hours=-5))  # EST is UTC-5
        edt = timezone(timedelta(hours=-4))  # EDT is UTC-4 (during daylight saving)
        
        # Use EDT for now (March-November), EST for December-February
        current_month = datetime.now().month
        if 3 <= current_month <= 11:  # Daylight saving months
            market_tz = edt
            tz_name = "EDT"
        else:
            market_tz = est
            tz_name = "EST"
        
        now = datetime.now(market_tz)
        current_time = now.time()
        weekday = now.weekday()  # Monday=0, Sunday=6
        
        # Market is closed on weekends
        if weekday >= 5:  # Saturday or Sunday
            return {
                "status": "CLOSED",
                "message": "Weekend - Markets Closed",
                "next_session": "Pre-Market opens Monday 4:00 AM",
                "session_type": "weekend",
                "is_extended_hours": False,
                "timestamp": now.strftime("%Y-%m-%d %I:%M:%S %p") + f" {tz_name}"
            }
        
        # Define market hours (EST/EDT)
        pre_market_start = datetime.strptime("04:00", "%H:%M").time()
        market_open = datetime.strptime("09:30", "%H:%M").time()
        market_close = datetime.strptime("16:00", "%H:%M").time()
        after_hours_end = datetime.strptime("20:00", "%H:%M").time()
        
        # Determine current market session
        if current_time < pre_market_start:
            # Before 4:00 AM - Market closed
            status = "CLOSED"
            message = "Market Closed - Pre-Market Opens at 4:00 AM"
            next_session = "Pre-Market opens at 4:00 AM"
            session_type = "closed"
            is_extended = False
        elif current_time < market_open:
            # 4:00 AM - 9:30 AM - Pre-Market
            status = "PRE-MARKET"
            message = "🌅 Pre-Market Trading Active"
            next_session = "Market opens at 9:30 AM"
            session_type = "pre_market"
            is_extended = True
        elif current_time < market_close:
            # 9:30 AM - 4:00 PM - Regular Market Hours
            status = "MARKET OPEN"
            message = "📈 Regular Market Hours"
            next_session = "Market closes at 4:00 PM"
            session_type = "regular"
            is_extended = False
        elif current_time < after_hours_end:
            # 4:00 PM - 8:00 PM - After Hours
            status = "AFTER-HOURS"
            message = "🌆 After-Hours Trading Active"
            next_session = "Market opens tomorrow at 9:30 AM"
            session_type = "after_hours"
            is_extended = True
        else:
            # After 8:00 PM - Market closed
            status = "CLOSED"
            message = "Market Closed - Pre-Market Opens Tomorrow at 4:00 AM"
            next_session = "Pre-Market opens tomorrow at 4:00 AM"
            session_type = "closed"
            is_extended = False
        
        return {
            "status": status,
            "message": message,
            "next_session": next_session,
            "session_type": session_type,
            "is_extended_hours": is_extended,
            "current_time": current_time.strftime("%I:%M %p"),
            "timezone": tz_name,
            "timestamp": now.strftime("%Y-%m-%d %I:%M:%S %p") + f" {tz_name}",
            "weekday": now.strftime("%A")
        }
    
    def is_after_hours(self):
        """Check if current time is after-hours (pre-market or after-hours)"""
        market_status = self.get_market_status()
        return market_status["is_extended_hours"]
    
    def get_extended_hours_data(self, symbol):
        """Get extended hours price data for after-hours scanning"""
        try:
            ticker = yf.Ticker(symbol)
            # Get more granular data for extended hours analysis
            hist = ticker.history(period="5d", interval="1h")
            
            if hist.empty:
                return None
            
            # Get regular market close price for gap analysis
            regular_hours_data = ticker.history(period="2d", interval="1d")
            if regular_hours_data.empty:
                return None
                
            prev_close = regular_hours_data['Close'].iloc[-2] if len(regular_hours_data) >= 2 else regular_hours_data['Close'].iloc[-1]
            current_price = hist['Close'].iloc[-1]
            
            # Calculate gap percentage
            gap_percent = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            # Calculate extended hours volume (approximate)
            recent_volume = hist['Volume'].tail(6).sum()  # Last 6 hours of trading
            avg_volume = hist['Volume'].mean() * 6
            
            return {
                "symbol": symbol,
                "current_price": round(float(current_price), 2),
                "prev_close": round(float(prev_close), 2),
                "gap_percent": round(gap_percent, 2),
                "gap_direction": "UP" if gap_percent > 0 else "DOWN" if gap_percent < 0 else "FLAT",
                "extended_volume": int(recent_volume) if recent_volume > 0 else 0,
                "volume_ratio": round(recent_volume / avg_volume, 2) if avg_volume > 0 else 1,
                "last_updated": self.get_current_timestamp(),
                "market_status": self.get_market_status()
            }
            
        except Exception as e:
            logging.error(f"Error fetching extended hours data for {symbol}: {e}")
            return None
