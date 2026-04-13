"""
SQUEEZE OS v5.0 — Multi-Provider Data Layer
Auto-discovers tickers. Scans the entire market. Strictly Real-Time Data.

DISCOVERY (find tickers automatically):
  - Alpaca Screener: most-active + top movers (free, fast)
  - Polygon Grouped Daily: ALL US stocks OHLCV in one call (free)

QUOTES (get real-time data for discovered tickers):
  1. Schwab (if authenticated)
  2. Alpaca snapshots (batch, fast)
  3. Polygon prev-day bars (5/min, slow)
  4. Alpha Vantage (25/day, last resort)
"""
import os
import sys
import time
import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================
# BULLETPROOF .env loader
# ============================================================
def load_env_file():
    loaded = 0
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
        os.path.join(os.getcwd(), '.env'),
    ]
    for env_path in paths:
        if os.path.exists(env_path):
            logger.info(f"[ENV] Reading: {env_path}")
            with open(env_path, 'r') as f:
                for ln, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    if val:
                        os.environ[key] = val
                        masked = val[:4] + '...' + val[-4:] if len(val) > 10 else '****'
                        logger.info(f"[ENV] {key} = {masked}")
                        loaded += 1
            break
    logger.info(f"[ENV] Loaded {loaded} keys")

load_env_file()


# ============================================================
# ALPACA PROVIDER — discovery + quotes
# ============================================================
class AlpacaProvider:
    def __init__(self):
        self.api_key = os.environ.get('ALPACA_API_KEY', '')
        self.api_secret = os.environ.get('ALPACA_API_SECRET', '')
        self.data_base = 'https://data.alpaca.markets'
        self.last_call = 0
        self.min_interval = 0.1  # RELAXED: 100ms (was 350ms) — Alpaca allows high frequency
        if self.available:
            logger.info(f"[ALPACA] Ready ({self.api_key[:6]}...)")
        else:
            logger.warning("[ALPACA] Not configured")

    @property
    def available(self):
        return bool(self.api_key and self.api_secret)

    def _headers(self):
        return {'APCA-API-KEY-ID': self.api_key, 'APCA-API-SECRET-KEY': self.api_secret}

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()

    # --- DISCOVERY ---

    def get_most_actives(self, top: int = 20) -> List[dict]:
        """Top stocks by volume — auto-discovery endpoint."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            r = requests.get(
                f"{self.data_base}/v1beta1/screener/stocks/most-actives",
                headers=self._headers(),
                params={'by': 'volume', 'top': top},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                actives = data.get('most_actives', [])
                # Law 2: 100% FETCH — Using full results from the API
                logger.info(f"[ALPACA] Most actives: {len(actives)} tickers")
                return actives
            else:
                logger.warning(f"[ALPACA] Most actives {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"[ALPACA] Most actives error: {e}")
        return []

    def get_movers(self, top: int = 50) -> dict:
        """Top gainers + losers — auto-discovery endpoint."""
        if not self.available:
            return {'gainers': [], 'losers': []}
        self._rate_limit()
        try:
            r = requests.get(
                f"{self.data_base}/v1beta1/screener/stocks/movers",
                headers=self._headers(),
                params={'top': min(top, 50)},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                gainers = data.get('gainers', [])
                losers = data.get('losers', [])
                logger.info(f"[ALPACA] Movers: {len(gainers)} gainers, {len(losers)} losers")
                return {'gainers': gainers, 'losers': losers}
            else:
                logger.warning(f"[ALPACA] Movers {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"[ALPACA] Movers error: {e}")
        return {'gainers': [], 'losers': []}

    # --- QUOTES ---

    def get_snapshots(self, symbols: List[str]) -> Dict[str, dict]:
        if not self.available or not symbols:
            return {}
        results = {}
        batch_size = 100  # RELAXED: 100 (was 50) — Alpaca supports larger batches for snapshots
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            self._rate_limit()
            try:
                r = requests.get(
                    f"{self.data_base}/v2/stocks/snapshots",
                    headers=self._headers(),
                    params={'symbols': ','.join(batch), 'feed': 'iex'},
                    timeout=30,
                )
                if r.status_code == 200:
                    for sym, snap in r.json().items():
                        bar = snap.get('dailyBar', {})
                        prev = snap.get('prevDailyBar', {})
                        latest = snap.get('latestTrade', {})
                        minute = snap.get('minuteBar', {})
                        price = latest.get('p') or minute.get('c') or bar.get('c', 0)
                        prev_close = prev.get('c', 0)
                        change = round(price - prev_close, 4) if price and prev_close else 0
                        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
                        vol = bar.get('v', 0)
                        prev_vol = prev.get('v', 1)
                        results[sym] = {
                            'symbol': sym,
                            'price': round(price, 4) if price else 0,
                            'change': change,
                            'changePct': change_pct,
                            'volume': vol,
                            'avgVolume': prev_vol,
                            'volRatio': round(vol / prev_vol, 2) if prev_vol else 0,
                            'open': bar.get('o', 0),
                            'high': bar.get('h', 0),
                            'low': bar.get('l', 0),
                            'prevClose': prev_close,
                            'source': 'alpaca',
                        }
                elif r.status_code == 403:
                    logger.error("[ALPACA] 403 — bad keys")
                    return results
                else:
                    logger.warning(f"[ALPACA] Snap {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.error(f"[ALPACA] Snap error: {e}")
        return results

    def get_account(self) -> Dict:
        """Fetch account details (equity, buying power)."""
        if not self.available:
            return {}
        self._rate_limit()
        try:
            url = f"{self.data_base.replace('data', 'api')}/v2/account" # Switch from data.alpaca to api.alpaca
            r = requests.get(url, headers=self._headers(), timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.error(f"[ALPACA] Account error: {e}")
        return {}

    def place_order(self, symbol: str, qty: int, side: str, order_type: str = 'market') -> Dict:
        """Place a live order on Alpaca."""
        if not self.available:
            return {"status": "error", "message": "Not configured"}
        self._rate_limit()
        try:
            url = f"{self.data_base.replace('data', 'api')}/v2/orders"
            payload = {
                "symbol": symbol,
                "qty": qty,
                "side": side.lower(),
                "type": order_type,
                "time_in_force": "gtc"
            }
            r = requests.post(url, headers=self._headers(), json=payload, timeout=15)
            if r.status_code == 200:
                order = r.json()
                logger.info(f"✅ Alpaca Order Placed: {order['id']}")
                return {"status": "success", "order_id": order['id']}
            else:
                try:
                    err_msg = r.json().get('message', r.text)
                except:
                    err_msg = r.text
                logger.error(f"🛑 Alpaca Order Failed [{r.status_code}]: {err_msg}")
                return {"status": "error", "message": err_msg}
        except Exception as e:
            logger.error(f"[ALPACA] Order error: {e}")
            return {"status": "error", "message": str(e)}


# ============================================================
# POLYGON PROVIDER — discovery + per-symbol quotes
# ============================================================
class PolygonProvider:
    def __init__(self):
        self.api_key = os.environ.get('POLYGON_API_KEY', '')
        self.base = 'https://api.polygon.io'
        self.last_call = 0
        self.min_interval = 12.0  # RELAXED: 12s (was 13s) — Polygon FREE tier: 5 requests/min = 12s minimum
        if self.available:
            logger.info(f"[POLYGON] Ready ({self.api_key[:6]}...)")
        else:
            logger.warning("[POLYGON] Not configured")

    @property
    def available(self):
        return bool(self.api_key)

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()

    # --- DISCOVERY ---

    def get_grouped_daily(self, date_str: str = None) -> Dict[str, dict]:
        """
        ALL US stocks OHLCV in ONE call. Free tier endpoint.
        Returns {symbol: {o, h, l, c, v, ...}} for the entire market.
        """
        if not self.available:
            return {}
        if not date_str:
            # SqueezeOS Discovery: Always use YESTERDAY for full market scan
            # Polygon FREE tier doesn't allow "Today" during market hours.
            # We just need "Yesterday's" movers to find today's targets.
            now = datetime.now() - timedelta(days=1)
            
            # Find the most recent weekday
            while now.weekday() >= 5: # Sat=5, Sun=6
                now -= timedelta(days=1)
            date_str = now.strftime('%Y-%m-%d')
            logger.info(f"[POLYGON] Universal discovery using session date: {date_str}")
        self._rate_limit()
        try:
            url = f"{self.base}/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
            r = requests.get(url, params={
                'adjusted': 'true', 'apiKey': self.api_key,
            }, timeout=30)
            if r.status_code == 200:
                data = r.json()
                results = {}
                for bar in data.get('results', []):
                    sym = bar.get('T', '')
                    if sym:
                        results[sym] = {
                            'symbol': sym,
                            'price': round(bar.get('c', 0), 4),
                            'open': round(bar.get('o', 0), 4),
                            'high': round(bar.get('h', 0), 4),
                            'low': round(bar.get('l', 0), 4),
                            'volume': int(bar.get('v', 0)),
                            'vwap': round(bar.get('vw', 0), 4),
                            'trades': bar.get('n', 0),
                            'source': 'polygon_grouped',
                        }
                logger.info(f"[POLYGON] Grouped daily {date_str}: {len(results)} tickers")
                return results
            elif r.status_code == 403:
                logger.warning(f"[POLYGON] Grouped daily 403 — may need paid plan: {r.text[:200]}")
            else:
                logger.warning(f"[POLYGON] Grouped daily {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"[POLYGON] Grouped daily error: {e}")
        return {}

    # --- PER-SYMBOL QUOTES ---

    def get_quotes_batch(self, symbols: List[str], progress_cb=None) -> Dict[str, dict]:
        """Previous-day bars one at a time. Slow (5/min) but free."""
        if not self.available:
            return {}
        results = {}
        for idx, sym in enumerate(symbols):
            if progress_cb:
                progress_cb(f'Polygon: {idx+1}/{len(symbols)} ({sym})')
            self._rate_limit()
            try:
                r = requests.get(
                    f"{self.base}/v2/aggs/ticker/{sym}/prev",
                    params={'adjusted': 'true', 'apiKey': self.api_key},
                    timeout=10,
                )
                if r.status_code == 200:
                    bars = r.json().get('results', [])
                    if bars:
                        b = bars[0]
                        results[sym] = {
                            'symbol': sym,
                            'price': round(b.get('c', 0), 4),
                            'change': 0, 'changePct': 0,
                            'volume': int(b.get('v', 0)),
                            'avgVolume': 0, 'volRatio': 0,
                            'open': round(b.get('o', 0), 4),
                            'high': round(b.get('h', 0), 4),
                            'low': round(b.get('l', 0), 4),
                            'source': 'polygon',
                        }
                elif r.status_code == 429:
                    # RATE LIMIT HIT: Polygon enforces 5/min on free tier — back off and skip this symbol
                    logger.warning(f"[POLYGON] 429 rate limit hit on {sym} — skipping")
                    break  # Stop processing more symbols this cycle
            except Exception as e:
                logger.warning(f"[POLYGON] {sym}: {e}")
        return results

    def get_last_trade(self, symbol: str) -> dict:
        """Get the last trade for a symbol. Free tier supports this."""
        if not self.available:
            return {}
        self._rate_limit()
        try:
            r = requests.get(f"{self.base}/v2/last/trade/{symbol}", params={
                'apiKey': self.api_key,
            }, timeout=10)
            if r.status_code == 200:
                data = r.json().get('results', {})
                return {
                    'price': data.get('p', 0),
                    'timestamp': data.get('t', 0),
                    'size': data.get('s', 0),
                    'exchange': data.get('x', 0)
                }
        except Exception as e:
            logger.warning(f"[POLYGON] Last trade {symbol}: {e}")
        return {}

    def get_aggregates(self, symbol: str, multiplier: int = 1, timespan: str = 'minute', limit: int = 30, days_back: int = 2) -> List[dict]:
        """Get aggregate bars for a symbol."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            # End is now, start is based on days_back
            end = int(time.time() * 1000)
            start = end - (days_back * 24 * 60 * 60 * 1000)
            url = f"{self.base}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start}/{end}"
            r = requests.get(url, params={
                'apiKey': self.api_key,
                'limit': limit,
                'sort': 'desc'
            }, timeout=10)
            if r.status_code == 200:
                results = r.json().get('results', [])
                return [{
                    'open': b.get('o'), 'high': b.get('h'), 'low': b.get('l'),
                    'close': b.get('c'), 'volume': b.get('v'), 'vwap': b.get('vw'),
                    'timestamp': b.get('t')
                } for b in results]
        except Exception as e:
            logger.warning(f"[POLYGON] Aggs {symbol}: {e}")
        return []

    def search_tickers(self, query: str, limit: int = 20) -> List[dict]:
        if not self.available:
            return []
        self._rate_limit()
        try:
            r = requests.get(f"{self.base}/v3/reference/tickers", params={
                'search': query, 'active': 'true', 'limit': limit,
                'market': 'stocks', 'apiKey': self.api_key,
            }, timeout=10)
            if r.status_code == 200:
                return [{'symbol': t['ticker'], 'name': t.get('name', '')}
                        for t in r.json().get('results', [])]
        except Exception as e:
            logger.warning(f"[POLYGON] Search: {e}")
        return []

    def get_news(self, symbol: str = None, limit: int = 10) -> List[dict]:
        if not self.available:
            return []
        self._rate_limit()
        try:
            params = {'limit': limit, 'apiKey': self.api_key, 'order': 'desc', 'sort': 'published_utc'}
            if symbol:
                params['ticker'] = symbol
            r = requests.get(f"{self.base}/v2/reference/news", params=params, timeout=10)
            if r.status_code == 200:
                return r.json().get('results', [])
        except Exception as e:
            logger.warning(f"[POLYGON] News error: {e}")
        return []


# ============================================================
# ALPHA VANTAGE — last resort quotes
# ============================================================
class AlphaVantageProvider:
    def __init__(self):
        self.api_key = os.environ.get('ALPHA_VANTAGE_API_KEY', '')
        self.base = 'https://www.alphavantage.co/query'
        self.last_call = 0
        self.min_interval = 5.0  # RELAXED: 5s (was 13s) — Alpha Vantage free: 5 calls/min = 12s, but we have 25/day hard limit anyway
        self.daily_calls = 0
        self.daily_limit = 25
        self.daily_reset = time.time()
        if self.available:
            logger.info(f"[ALPHAV] Ready ({self.api_key[:6]}...)")
        else:
            logger.warning("[ALPHAV] Not configured")

    @property
    def available(self):
        if not self.api_key: return False
        if time.time() - self.daily_reset > 86400:
            self.daily_calls = 0
            self.daily_reset = time.time()
        return self.daily_calls < self.daily_limit

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()
        self.daily_calls += 1

    def get_quotes_batch(self, symbols: List[str], progress_cb=None) -> Dict[str, dict]:
        results = {}
        for idx, sym in enumerate(symbols):
            if not self.available: break
            if progress_cb: progress_cb(f'Alpha Vantage: {idx+1}/{len(symbols)} ({sym})')
            self._rate_limit()
            try:
                r = requests.get(self.base, params={
                    'function': 'GLOBAL_QUOTE', 'symbol': sym, 'apikey': self.api_key,
                }, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if 'Note' in data or 'Information' in data:
                        break
                    gq = data.get('Global Quote', {})
                    if gq and gq.get('05. price'):
                        pct = gq.get('10. change percent', '0')
                        if isinstance(pct, str): pct = pct.rstrip('%')
                        results[sym] = {
                            'symbol': sym,
                            'price': round(float(gq['05. price']), 4),
                            'change': round(float(gq.get('09. change', 0)), 4),
                            'changePct': round(float(pct), 2),
                            'volume': int(gq.get('06. volume', 0)),
                            'avgVolume': 0, 'volRatio': 0,
                            'open': round(float(gq.get('02. open', 0)), 4),
                            'high': round(float(gq.get('03. high', 0)), 4),
                            'low': round(float(gq.get('04. low', 0)), 4),
                            'source': 'alphavantage',
                        }
            except Exception as e:
                logger.warning(f"[ALPHAV] {sym}: {e}")
        return results


# ============================================================
# SCHWAB WRAPPER
# ============================================================
class SchwabProvider:
    def __init__(self, schwab_state):
        self.schwab = schwab_state

    @property
    def available(self):
        if not self.schwab: return False
        try: return self.schwab._ensure_authenticated()
        except Exception as e:
            logging.getLogger(__name__).warning(f"[SCHWAB] Auth check failed: {e}")
            return False

    def get_quotes_batch(self, symbols: List[str], progress_cb=None) -> Dict[str, dict]:
        if not self.available: return {}
        try:
            raw = self.schwab.get_quotes(symbols, progress_cb=progress_cb)
            if 'error' in raw: return {}
            
            # FINAL DIAGNOSTIC
            import json
            try:
                with open('schwab_debug.json', 'w') as f_out:
                    json.dump(raw, f_out, indent=2)
            except Exception as e:
                    logging.getLogger(__name__).warning(f"[SCHWAB] Failed to write debug JSON: {e}")

            results = {}
            for sym, data in raw.items():
                if not isinstance(data, dict): continue
                
                # Schwab v1 can return {quote:{}, fundamental:{}, reference:{}}
                q = data.get('quote') or {}
                f = data.get('fundamental') or {}
                r = data.get('reference') or {}
                
                # IRONCLAD PRICE: Aggressive prioritization
                last_price = q.get('lastPrice')
                mark = q.get('mark')
                close = q.get('closePrice')
                bid = q.get('bidPrice')
                
                # Use the first one that exists and is > 0
                price = last_price or mark or close or bid or 0
                
                # REPAIR: Plural vs Singular Average Volume
                # ETFs like IBIT often use plural 'avg10DaysVolume'
                avg_vol = float(f.get('avg10DaysVolume') or f.get('avg10DayVolume') or 
                              f.get('avg30DaysVolume') or f.get('avg30DayVolume') or 
                              f.get('averageVolume') or f.get('average10DayVolume') or 0.0)
                
                # TOTAL VOLUME
                vol = float(q.get('totalVolume') or q.get('volume') or 0.0)
                
                # PERCENT CHANGE 
                chg_pct = (q.get('netPercentChange') or q.get('markPercentChange') or 
                           q.get('netChangePercent') or q.get('percentChange', 0.0))
                
                results[sym] = {
                    'symbol': sym,
                    'price': round(float(price), 4),
                    'change': round(float(q.get('netChange') or q.get('change', 0)), 4),
                    'changePct': round(float(chg_pct), 2),
                    'volume': int(vol), 
                    'avgVolume': int(avg_vol),
                    'volRatio': round(vol / avg_vol, 2) if avg_vol > 0 else (1.0 if vol > 0 else 0.0),
                    'bid': round(float(q.get('bidPrice') or 0), 4),
                    'ask': round(float(q.get('askPrice') or 0), 4),
                    'open': round(float(q.get('openPrice') or q.get('open', 0)), 4),
                    'high': round(float(q.get('highPrice') or q.get('high', 0)), 4),
                    'low': round(float(q.get('lowPrice') or q.get('low', 0)), 4),
                    'description': r.get('description', ''),
                    'source': 'schwab',
                }
            return results
        except Exception as e:
            logger.error(f"[SCHWAB] Error: {e}")
            return {}

    def get_movers(self, index='$SPX', direction='up', change_type='percent'):
        """Get top movers from Schwab. Safe wrapper — returns [] on failure."""
        if not self.available:
            return []
        try:
            # schwab_state.get_movers() if it exists
            if hasattr(self.schwab, 'get_movers'):
                raw = self.schwab.get_movers(index=index, direction=direction, change_type=change_type)
                if raw and isinstance(raw, list):
                    results = []
                    for m in raw:
                        sym = m.get('symbol', '')
                        if sym:
                            results.append({
                                'symbol': sym,
                                'price': float(m.get('lastPrice', m.get('last', 0))),
                                'changePct': float(m.get('netPercentChange', m.get('changePct', 0))),
                                'volume': int(m.get('totalVolume', m.get('volume', 0))),
                            })
                    return results
            return []
        except Exception as e:
            logger.debug(f"[SCHWAB] Movers unavailable: {e}")
            return []


# ============================================================
# UNIFIED DATA MANAGER
# ============================================================
class DataManager:
    """Auto-discovers tickers + fetches real quotes. Never fakes data."""

    def __init__(self, schwab_state=None):
        logger.info("[DATA] Initializing...")
        self.schwab = SchwabProvider(schwab_state) if schwab_state else None
        self.alpaca = AlpacaProvider()
        self.polygon = PolygonProvider()
        self.alphav = AlphaVantageProvider()
        logger.info("[DATA] Ready")

    def provider_status(self) -> dict:
        return {
            'schwab': self.schwab.available if self.schwab else False,
            'alpaca': self.alpaca.available,
            'polygon': self.polygon.available,
            'alphavantage': self.alphav.available,
        }

    # --- AUTO-DISCOVERY ---

    def discover_universe(self, progress_cb=None, limit=2000) -> Dict[str, dict]:
        universe = {}
        
        def is_junk(sym):
            if not sym: return True
            sym = sym.upper()
            if any(x in sym for x in ['.', '-', ' ', '/']): return True
            if sym.endswith('W') or sym.endswith('WS') or sym.endswith('U'): return True
            return False

        # ════════════════════════════════════════════════════════════
        # TIER 1: ALPACA MOVERS — Top gainers/losers
        # ════════════════════════════════════════════════════════════
        if self.alpaca.available:
            if progress_cb: progress_cb('Discovering: Alpaca movers...')
            movers = self.alpaca.get_movers(top=50)
            for item in movers.get('gainers', []):
                sym = item.get('symbol', '')
                if sym and not is_junk(sym):
                    chg = item.get('percent_change', 0)
                    if abs(chg) >= 1.0:  # Lowered from 2.5% → 1.0%
                        universe[sym] = {'symbol': sym, 'discovery': 'alpaca_gainer', 'changePct': chg}
            for item in movers.get('losers', []):
                sym = item.get('symbol', '')
                if sym and not is_junk(sym):
                    chg = item.get('percent_change', 0)
                    if abs(chg) >= 1.0:
                        universe[sym] = {'symbol': sym, 'discovery': 'alpaca_loser', 'changePct': chg}
            
            # UNLEASHED: Add Most Active (High volume liquidity)
            actives = self.alpaca.get_most_actives(top=100)
            for item in actives:
                sym = item.get('symbol', '')
                if sym and not is_junk(sym) and sym not in universe:
                    universe[sym] = {'symbol': sym, 'discovery': 'alpaca_active', 'volume': item.get('volume', 0)}
            
            logger.info(f"[DISCOVERY] Alpaca: {len(universe)} movers/actives")

        # ════════════════════════════════════════════════════════════
        # TIER 2: POLYGON GROUPED DAILY — Full market scan
        # ════════════════════════════════════════════════════════════
        if self.polygon.available:
            if progress_cb: progress_cb('Discovering: Polygon full market scan...')
            grouped = self.polygon.get_grouped_daily()
            if grouped:
                def get_heat(item):
                    bar = item[1]
                    o, c = bar.get('open', 0), bar.get('price', 0)
                    chg = abs((c - o) / o) if o > 0 else 0
                    return bar.get('volume', 0) * chg

                sorted_bars = sorted(grouped.items(), key=get_heat, reverse=True)
                poly_added = 0
                for sym, bar in sorted_bars:
                    if limit > 0 and poly_added >= limit:
                        break
                    if is_junk(sym):
                        continue

                    vol = bar.get('volume', 0)
                    price = bar.get('price', 0)
                    open_p = bar.get('open', 0)
                    chg_pct = ((price - open_p) / open_p * 100) if open_p > 0 else 0
                    
                    # TRULY WIDE OPEN: 50k vol (was 100k), 0.1% move (was 0.5%)
                    if vol >= 50000 and 0.10 <= price <= 50000 and abs(chg_pct) >= 0.1:
                        if sym not in universe:
                            universe[sym] = bar
                            universe[sym]['discovery'] = 'polygon_scan'
                            universe[sym]['changePct'] = chg_pct
                            poly_added += 1
                logger.info(f"[DISCOVERY] Polygon: {poly_added} tickers added")

        # ════════════════════════════════════════════════════════════
        # TIER 3: SCHWAB MOVERS — If available, use primary source
        # ════════════════════════════════════════════════════════════
        if self.schwab and self.schwab.available:
            if progress_cb: progress_cb('Discovering: Schwab market movers...')
            try:
                for index in ['$SPX', '$DJI', '$COMPX']:
                    movers = self.schwab.get_movers(index=index, direction='up', change_type='percent')
                    if movers:
                        for m in movers:
                            sym = m.get('symbol', '')
                            if sym and not is_junk(sym) and sym not in universe:
                                universe[sym] = {
                                    'symbol': sym, 'discovery': 'schwab_mover',
                                    'changePct': m.get('changePct', 0),
                                    'price': m.get('price', 0),
                                    'volume': m.get('volume', 0),
                                }
                    movers_dn = self.schwab.get_movers(index=index, direction='down', change_type='percent')
                    if movers_dn:
                        for m in movers_dn:
                            sym = m.get('symbol', '')
                            if sym and not is_junk(sym) and sym not in universe:
                                universe[sym] = {
                                    'symbol': sym, 'discovery': 'schwab_mover',
                                    'changePct': m.get('changePct', 0),
                                    'price': m.get('price', 0),
                                    'volume': m.get('volume', 0),
                                }
                logger.info(f"[DISCOVERY] Schwab movers added, total: {len(universe)}")
            except Exception as e:
                logger.debug(f"Schwab movers unavailable: {e}")

        if progress_cb: progress_cb(f'Discovered {len(universe)} tickers')
        logger.info(f"[DISCOVERY] Total universe: {len(universe)} tickers")
        return universe

    # --- QUOTES ---

    def get_quotes(self, symbols: List[str], progress_cb=None, fast_only=False) -> Dict[str, dict]:
        """Fetch real quotes for given symbols via best provider."""
        if not symbols: return {}
        results = {}
        remaining = list(symbols)

        # 1. Schwab (High Speed Batch)
        if self.schwab and self.schwab.available and remaining:
            data = self.schwab.get_quotes_batch(remaining, progress_cb=progress_cb)
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 2. Alpaca (High Speed Batch)
        if self.alpaca.available and remaining:
            data = self.alpaca.get_snapshots(remaining)
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 3. Polygon (SLOW - Skip if fast_only is requested)
        if not fast_only and self.polygon.available and remaining:
            # Only do this for small batches (e.g. Grimoire), NOT for scanner (remaining > 50)
            if len(remaining) <= 10:
                data = self.polygon.get_quotes_batch(remaining)
                results.update(data)
                remaining = [s for s in remaining if s not in results]

        return results
