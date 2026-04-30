"""
SQUEEZE OS v4.1 — Options Flow Service
Schwab-first real options chains → unusual activity detection.
Falls back to Alpaca options → volume-based scoring.
"""
import os
import time
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class OptionsProService:
    def __init__(self):
        self.alpaca_key = os.environ.get('ALPACA_API_KEY', 'AKV39V1APUHWMFCQ2GA0')
        self.alpaca_secret = os.environ.get('ALPACA_API_SECRET', 'edlztEfaib5gGj0hQbfoV4Ezm6vdy8FnuFfW9Mx9')
        self.last_call = 0
        self.min_interval = 0.1  # RELAXED: 100ms (was 500ms) between requests
        self._schwab_api = None
        logger.info("[OPTIONS] Service ready")

    def _get_schwab(self):
        if self._schwab_api is None:
            try:
                from schwab_api import schwab_api
                if schwab_api._ensure_authenticated():
                    self._schwab_api = schwab_api
                    logger.info("[OPTIONS] Schwab API connected")
            except Exception as e:
                logger.warning(f"[OPTIONS] Failed to load Schwab API: {e}")
        return self._schwab_api

    def _schwab_available(self):
        api = self._get_schwab()
        if not api: return False
        try:
            return api._ensure_authenticated()
        except Exception as e:
            logger.warning(f"[OPTIONS] Schwab authentication check failed: {e}")
            return False

    def get_options_chain(self, symbol):
        # Try Schwab first, then Alpaca. Accept ANY valid response even with empty alerts.
        if self._schwab_available():
            result = self._schwab_chain(symbol)
            if result and 'unusual_activity' in result:
                return result  # Valid chain — even if unusual_activity is empty list
        if self.alpaca_key:
            result = self._alpaca_chain(symbol)
            if result and 'unusual_activity' in result:
                return result
        logger.warning(f"[OPTIONS] No options data available for {symbol}")
        return {'symbol': symbol, 'unusual_activity': [], 'source': 'none'}

    def _schwab_chain(self, symbol):
        try:
            api = self._get_schwab()
            if not api: return None
            raw = api.get_option_chains(symbol)
            if not raw or 'error' in raw: return None
            underlying_price = raw.get('underlyingPrice', 0) or (raw.get('underlying') or {}).get('last', 0)
            alerts = []
            call_map = raw.get('callExpDateMap', {})
            put_map = raw.get('putExpDateMap', {})

            def process_map(option_map, opt_type):
                if not option_map or not isinstance(option_map, dict): return
                for expiry_key, strikes in option_map.items():
                    if not strikes or not isinstance(strikes, dict): continue
                    if not isinstance(expiry_key, str) or ':' not in expiry_key: continue
                    
                    expiry_date = expiry_key.split(':')[0]
                    days_to_exp = self._days_to_expiry(expiry_date)

                    for strike_str, option_list in strikes.items():
                        if not option_list or not isinstance(option_list, list): continue
                        strike = float(strike_str)
                        
                        # WIDE OPEN: 100% Fetch Policy Active
                        
                        for opt in option_list:
                            if not opt or not isinstance(opt, dict): continue
                            vol = int(opt.get('totalVolume') or opt.get('volume') or 0)
                            oi = int(opt.get('openInterest') or opt.get('oi') or 0)
                            vol_oi = vol / oi if oi > 0 else (vol / 1 if vol > 0 else 0)
                            
                            # Defensive float casting for all numeric fields
                            try:
                                bid = float(opt.get('bid') or 0)
                                ask = float(opt.get('ask') or 0)
                                last = float(opt.get('last') or opt.get('lastPrice') or 0)
                                mark = float(opt.get('mark') or 0)
                                iv_raw = opt.get('volatility') or opt.get('impliedVolatility') or 0
                                iv = float(iv_raw) / 100 if iv_raw else 0
                                delta = float(opt.get('delta') or 0)
                            except (TypeError, ValueError):
                                continue

                            strike = float(strike_str)
                            price = mark or last or ((bid + ask) / 2 if bid and ask else 0)

                            # --- INSTITUTIONAL HEAT SCORING (VOL/OI DRIVEN) ---
                            # Vol/OI is the ONLY true measure of unusual activity.
                            # Raw volume means nothing — TSLA trades millions daily.
                            # A small-cap with 500 vol and 50 OI (10x) is way more unusual
                            # than TSLA with 5000 vol and 50000 OI (0.1x).
                            score = 0
                            
                            # 1. VOL/OI RATIO — Primary signal (0-50 pts)
                            if vol_oi >= 10.0: score += 50   # Extreme: 10x OI traded in one day
                            elif vol_oi >= 5.0: score += 40  # Massive spike
                            elif vol_oi >= 3.0: score += 30  # Strong unusual
                            elif vol_oi >= 2.0: score += 20  # Clearly unusual
                            elif vol_oi >= 1.5: score += 10  # Mild interest
                            # Below 1.5x = normal activity, 0 points
                            
                            # 2. AGGRESSION — Were they buying at the ask? (0-25 pts)
                            is_at_ask = (last >= ask * 0.99) if ask > 0 else False
                            if is_at_ask and vol_oi >= 2.0:
                                score += 25  # Urgently buying + unusual ratio = real heat
                            elif is_at_ask:
                                score += 10  # Aggressive but normal volume
                            elif last <= bid * 1.01 and bid > 0:
                                score -= 15  # Selling/closing — NOT a buy signal
                            
                            # 3. PREMIUM SIZE — Skin in the game (0-15 pts)
                            premium = vol * price * 100
                            # REBALANCED: Only big points for truly massive institutional chunks
                            # Over 5M = 15pts, Over 1M = 10pts
                            if premium >= 5000000 and vol_oi >= 2.0: score += 15
                            elif premium >= 1000000 and vol_oi >= 2.0: score += 10
                            elif premium >= 100000 and vol_oi >= 3.0: score += 5
                            
                            # 4. PRICE LEVEL "SWEET SPOT" — Bonus for Small/Mid Caps (0-10 pts)
                            # TSLA/NVDA don't need help. $5 - $30 stocks are the real gems.
                            if price < 15.0: score += 10    # Prime small-cap territory
                            elif price < 50.0: score += 5   # Mid-cap / Affordable territory
                            
                            # 5. IV HEAT — High IV + unusual volume (0-10 pts)
                            if iv > 0.8 and vol_oi >= 2.0: score += 10
                            elif iv > 0.5 and vol_oi >= 3.0: score += 5
                            
                            # --- SENTIMENT & LABELING ---
                            sentiment = 'BULLISH' if opt_type == 'CALL' else 'BEARISH'
                            if not is_at_ask and last <= bid * 1.01:
                                sentiment = 'BEARISH' if opt_type == 'CALL' else 'BULLISH' # Seller-driven
                                
                            is_oi_spike = (vol_oi >= 2.0 and vol >= 100)
                            is_block = (vol >= 1000 and vol_oi >= 1.5)
                            is_sweep = (vol_oi >= 2.0 and is_at_ask and vol >= 200)

                            label = opt_type
                            if is_oi_spike and is_sweep: label = f"{opt_type} SWEEP SPIKE"
                            elif is_oi_spike: label = f"{opt_type} OI SPIKE"
                            elif is_block: label = f"{opt_type} BLOCK"
                            elif is_sweep: label = f"{opt_type} SWEEP"
                            
                            if (score >= 10 and vol_oi >= 1.5) or is_oi_spike or is_block:
                                if score >= 40:
                                    logger.info(f"🔥 [WHALE] {label} on {symbol} | Vol: {vol} | Score: {score} | Prem: ${premium:,.0f}")
                                
                                alerts.append({
                                    'symbol': symbol, 'strike': strike, 'expiry': expiry_date,
                                    'expiry_formatted': self._format_expiry(expiry_date),
                                    'days_to_expiry': days_to_exp, 'type': opt_type,
                                    'price': round(price, 2), 'volume': vol, 'open_interest': oi,
                                    'premium': round(premium, 2),
                                    'vol_oi_ratio': round(vol_oi, 2), 'implied_volatility': round(iv, 4),
                                    'delta': round(delta, 3), 'unusual_score': min(score, 100),
                                    'sentiment': sentiment, 'sweep_label': label,
                                    'source': 'schwab',
                                    'is_oi_spike': is_oi_spike, 'is_block': is_block, 'is_sweep': is_sweep,
                                    'is_aggressive': is_at_ask
                                })
            process_map(call_map, 'CALL')
            process_map(put_map, 'PUT')
            alerts.sort(key=lambda x: x['unusual_score'], reverse=True)
            return {
                'symbol': symbol, 
                'unusual_activity': alerts, 
                'source': 'schwab', 
                'underlying_price': underlying_price,
                '_raw_calls': call_map,
                '_raw_puts': put_map
            }
        except Exception as e:
            logger.error(f"[OPTIONS] Schwab chain {symbol}: {e}")
            return None

    def _alpaca_chain(self, symbol):
        try:
            r = requests.get(f"https://data.alpaca.markets/v1beta1/options/snapshots/{symbol}",
                             headers={'APCA-API-KEY-ID': self.alpaca_key, 'APCA-API-SECRET-KEY': self.alpaca_secret},
                             params={'feed': 'indicative'}, timeout=10)
            if r.status_code != 200:
                logger.error(f"[OPTIONS] Alpaca chain {symbol}: HTTP {r.status_code}")
                return None
            data = r.json()
            snapshots = data.get('snapshots', {})
            alerts = []
            for contract_sym, snap in snapshots.items():
                trade = snap.get('latestTrade', {})
                vol = trade.get('v', 0)
                # Rule 2: 100% FETCH — No arbitrary volume floors
                score = min(int(vol / 100), 25) if vol > 500 else 10
                alerts.append({
                    'symbol': symbol, 'strike': 0, 'expiry': '', 'type': 'UNKNOWN',
                    'price': trade.get('p', 0), 'volume': vol, 'unusual_score': score,
                    'sentiment': 'NEUTRAL', 'source': 'alpaca'
                })
            return {'symbol': symbol, 'unusual_activity': alerts, 'source': 'alpaca'}
        except Exception as e:
            logger.error(f"[OPTIONS] Alpaca chain {symbol}: {e}")
            return None

    def _days_to_expiry(self, expiry_str):
        try:
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
            delta = expiry_date - datetime.now()
            return max(0, delta.days)
        except Exception as e:
            logger.warning(f"[OPTIONS] Failed to parse expiry date '{expiry_str}': {e}")
            return 0

    def _format_expiry(self, expiry_str):
        try:
            dt = datetime.strptime(expiry_str, '%Y-%m-%d')
            return dt.strftime('%b %d')
        except Exception as e:
            logger.warning(f"[OPTIONS] Failed to format expiry date '{expiry_str}': {e}")
            return expiry_str

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()
