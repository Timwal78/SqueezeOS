"""
SQUEEZE OS v5.1 — THE BEASTMODE EDITION
Auto-discovers tickers. Scans the entire market. Zero fake data.

DISCOVERY (find tickers automatically):
  - Alpaca Screener: most-active + top movers (free, fast)
  - Polygon Grouped Daily: ALL US stocks OHLCV in one call (free)

QUOTES (get real-time data for discovered tickers):
  1. Tradier (Institutional - Primary)
  2. Alpaca snapshots (batch, fast)
  3. Polygon prev-day bars (5/min, slow)
  4. Alpha Vantage (25/day, last resort)
"""
import os
import sys
import time
import logging
import requests
import numpy as np
import base64
import json
import httpx
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import sigkick

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
        self.min_interval = 0.35
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

    def get_most_actives(self, top: int = 100) -> List[dict]:
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
                params={'top': top},
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
        batch_size = 50
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


# ============================================================
# POLYGON PROVIDER — discovery + per-symbol quotes
# ============================================================
class PolygonProvider:
    def __init__(self):
        self.api_key = os.environ.get('POLYGON_API_KEY', '')
        self.base = 'https://api.polygon.io'
        self.last_call = 0
        self.min_interval = 13.0
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
            # SqueezeOS Fix: Try today first, then fall back.
            now = datetime.now()
            # If it's before 4 AM EST (market data reset), use yesterday
            if now.hour < 4: 
                now -= timedelta(days=1)
            
            # Find the most recent weekday
            while now.weekday() >= 5: # Sat=5, Sun=6
                now -= timedelta(days=1)
            date_str = now.strftime('%Y-%m-%d')
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
                    time.sleep(30)
            except Exception as e:
                logger.warning(f"[POLYGON] {sym}: {e}")
        return results

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


# ============================================================
# ALPHA VANTAGE — last resort quotes
# ============================================================
class AlphaVantageProvider:
    def __init__(self):
        self.api_key = os.environ.get('ALPHA_VANTAGE_API_KEY', '')
        self.base = 'https://www.alphavantage.co/query'
        self.last_call = 0
        self.min_interval = 13.0
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
# SCHWAB PROVIDER — OAuth + Real Quotes (Institutional Grade)
# ============================================================
class SchwabProvider:
    def __init__(self):
        self.client_id = os.environ.get("SCHWAB_CLIENT_ID", "")
        self.secret = os.environ.get("SCHWAB_SECRET", "")
        self.refresh_token = os.environ.get("SCHWAB_REFRESH_TOKEN", "")
        self.base_url = "https://api.schwabapi.com"
        
        # Token cache
        self.token = ""
        self.token_expiry = datetime.now()
        
        if self.available:
            logger.info(f"[SCHWAB] Ready ({self.client_id[:6]}...)")
        else:
            logger.warning("[SCHWAB] Not configured (Check SCHWAB_CLIENT_ID/SECRET/REFRESH_TOKEN)")

    @property
    def available(self):
        return bool(self.client_id and self.secret and self.refresh_token)

    async def _refresh_token(self) -> str:
        """Refresh Schwab access token using refresh token flow."""
        if not self.available:
            return ""
        
        # Check cache (refresh 5 mins early)
        if self.token and datetime.now() < (self.token_expiry - timedelta(minutes=5)):
            return self.token
        
        try:
            credentials = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/v1/oauth/token",
                    headers={
                        "Authorization": f"Basic {credentials}",
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token
                    },
                    timeout=10
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    self.token = data.get("access_token", "")
                    expires_in = data.get("expires_in", 1800)
                    self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                    logger.info(f"[SCHWAB] Token refreshed (expires in {expires_in//60}m)")
                    return self.token
                else:
                    logger.error(f"[SCHWAB] Token refresh failed: {resp.status_code} {resp.text}")
                    return ""
        except Exception as e:
            logger.error(f"[SCHWAB] OAuth error: {e}")
            return ""

    async def get_quote_async(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Schwab via async call."""
        token = await self._refresh_token()
        if not token:
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/marketdata/v1/quotes/{symbol}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"fields": "quote,reference,regular"},
                    timeout=5
                )
                
                if resp.status_code == 200:
                    data = resp.json().get(symbol, {})
                    quote = data.get("quote", {})
                    ref = data.get("reference", {})
                    
                    return {
                        "symbol": symbol,
                        "price": round(float(quote.get("lastPrice", 0)), 4),
                        "change": round(float(quote.get("netChange", 0)), 4),
                        "changePct": round(float(quote.get("netPercentChange", 0)), 2),
                        "volume": int(quote.get("totalVolume", 0)),
                        "open": round(float(quote.get("openPrice", 0)), 4),
                        "high": round(float(quote.get("highPrice", 0)), 4),
                        "low": round(float(quote.get("lowPrice", 0)), 4),
                        "prevClose": round(float(quote.get("closePrice", 0)), 4),
                        # Greek proxies if available
                        "implied_volatility": ref.get("impliedVolatility", 0),
                        "put_call_ratio": ref.get("putCallRatio", 0),
                        "source": "schwab"
                    }
        except Exception as e:
            logger.debug(f"[SCHWAB] Quote error for {symbol}: {e}")
        return None

    def get_quotes_batch(self, symbols: List[str]) -> Dict[str, dict]:
        """Synchronous wrapper for batch quotes (Schwab API is mostly single-ticker or small batch)."""
        if not self.available:
            return {}
        
        results = {}
        try:
            # Running async loop in thread for sync compat
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def run_batch():
                tasks = [self.get_quote_async(s) for s in symbols]
                return await asyncio.gather(*tasks)
            
            batch_results = loop.run_until_complete(run_batch())
            loop.close()
            
            for r in batch_results:
                if r:
                    results[r['symbol']] = r
        except Exception as e:
            logger.error(f"[SCHWAB] Batch quote error: {e}")
            
        return results


# ============================================================
# TRADIER WRAPPER
# ============================================================
class TradierProvider:
    def __init__(self, api_instance):
        self.api = api_instance

    @property
    def available(self):
        return bool(self.api and self.api.token)

    def get_quotes_batch(self, symbols: List[str], progress_cb=None) -> Dict[str, dict]:
        if not self.available: return {}
        try:
            raw = self.api.get_quotes(symbols)
            if 'error' in raw: return {}
            
            results = {}
            for sym, q in raw.items():
                # Tradier field mapping
                price = q.get('last', 0) or q.get('mark', 0) or q.get('bid', 0)
                avg_vol = float(q.get('average_volume') or 1)
                vol = float(q.get('volume') or 0)
                
                results[sym] = {
                    'symbol': sym,
                    'price': round(float(price), 4),
                    'change': round(float(q.get('change', 0)), 4),
                    'changePct': round(float(q.get('change_percentage', 0)), 2),
                    'volume': int(vol), 
                    'avgVolume': int(avg_vol),
                    'volRatio': round(vol / avg_vol, 2) if avg_vol > 0 else 1.0,
                    'bid': round(float(q.get('bid') or 0), 4),
                    'ask': round(float(q.get('ask') or 0), 4),
                    'open': round(float(q.get('open') or 0), 4),
                    'high': round(float(q.get('high') or 0), 4),
                    'low': round(float(q.get('low') or 0), 4),
                    'description': q.get('description', ''),
                    'source': 'tradier',
                }
            return results
        except Exception as e:
            logger.error(f"[TRADIER] Provider Error: {e}")
            return {}


# ============================================================
# UNIFIED DATA MANAGER
# ============================================================
class DataManager:
    """Auto-discovers tickers + fetches real quotes. Never fakes data."""

    def __init__(self):
        logger.info("[DATA] Initializing...")
        from tradier_api import tradier_api
        self.tradier = TradierProvider(tradier_api)
        self.alpaca = AlpacaProvider()
        self.polygon = PolygonProvider()
        self.alphav = AlphaVantageProvider()
        self.schwab = SchwabProvider()
        logger.info("[DATA] Ready")

    def provider_status(self) -> dict:
        return {
            'tradier': self.tradier.available,
            'schwab': self.schwab.available,
            'alpaca': self.alpaca.available,
            'polygon': self.polygon.available,
            'alphavantage': self.alphav.available,
        }

    # --- AUTO-DISCOVERY ---

    def discover_universe(self, progress_cb=None, limit=600) -> Dict[str, dict]:
        universe = {}
        
        def is_junk(sym):
            if not sym: return True
            sym = sym.upper()
            if any(x in sym for x in ['.', '-', ' ', '/']): return True
            if sym.endswith('W') or sym.endswith('WS') or sym.endswith('U'): return True
            if len(sym) > 5: return True  # Skip long symbols (typically warrants/units)
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
            logger.info(f"[DISCOVERY] Alpaca: {len(universe)} movers")

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
                    if poly_added >= limit:
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
        # TIER 3: TRADIER MOVERS — If available, use primary source
        # ════════════════════════════════════════════════════════════
        if self.tradier.available:
            # Tradier doesn't have a direct 'movers' endpoint for whole indices in the same way,
            # but we can skip this or use Polygon's scan which is already superior.
            pass

        # ════════════════════════════════════════════════════════════
        # TIER 4: INSTITUTIONAL FAVORITES ONLY (No Hardcoding)
        WATCHLIST = os.environ.get('SQUEEZE_FAVORITES', 'AMC,GME').split(',')
        
        watchlist_added = 0
        for sym in WATCHLIST:
            if sym not in universe:
                universe[sym] = {'symbol': sym, 'discovery': 'watchlist'}
                watchlist_added += 1

        if progress_cb: progress_cb(f'Discovered {len(universe)} tickers')
        logger.info(f"[DISCOVERY] Total universe: {len(universe)} tickers (watchlist backfill: {watchlist_added})")
        return universe

    # --- QUOTES ---

    def get_quotes(self, symbols: List[str], progress_cb=None, fast_only=False) -> Dict[str, dict]:
        """Fetch real quotes for given symbols via best provider."""
        if not symbols: return {}
        results = {}
        remaining = list(symbols)

        # 1. Schwab (Priority Fallback / High Quality Greeks)
        if self.schwab.available and remaining:
            # Schwab is better for quality, but slower for massive batches.
            # We use it for small priority batches.
            data = self.schwab.get_quotes_batch(remaining[:20]) 
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 2. Tradier (High Speed Batch)
        if self.tradier.available and remaining:
            data = self.tradier.get_quotes_batch(remaining, progress_cb=progress_cb)
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 2. Alpaca (High Speed Batch)
        if self.alpaca.available and remaining:
            data = self.alpaca.get_snapshots(remaining)
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 3. Polygon (Institutional Preference / Fallback)
        if not fast_only and self.polygon.available and remaining:
            # Only do this for small batches (e.g. Grimoire), NOT for scanner (remaining > 50)
            if len(remaining) <= 10:
                data = self.polygon.get_quotes_batch(remaining)
                results.update(data)
                remaining = [s for s in remaining if s not in results]

        return results

    # --- HISTORY ---

    def get_history(self, symbol: str, days: int = 30) -> List[dict]:
        """Fetch historical bars for a symbol."""
        # Try Alpaca first (it's faster for bars)
        if self.alpaca.available:
            try:
                end = datetime.now()
                start = end - timedelta(days=days)
                r = requests.get(
                    f"{self.alpaca.data_base}/v2/stocks/{symbol}/bars",
                    headers=self.alpaca._headers(),
                    params={
                        'timeframe': '1Day',
                        'start': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'end': end.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'limit': 100,
                        'adjustment': 'all',
                        'feed': 'iex'
                    },
                    timeout=15
                )
                if r.status_code == 200:
                    bars = r.json().get('bars', [])
                    # Translate to standard format
                    return [
                        {'c': b['c'], 'h': b['h'], 'l': b['l'], 'o': b['o'], 'v': b['v'], 't': b['t']}
                        for b in bars
                    ]
            except Exception as e:
                logger.debug(f"[ALPACA] History error for {symbol}: {e}")

        # Fallback to Polygon
        if self.polygon.available:
            try:
                end = datetime.now()
                start = end - timedelta(days=days)
                url = f"{self.polygon.base}/v2/aggs/ticker/{symbol}/range/1/day/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
                r = requests.get(url, params={'adjusted': 'true', 'apiKey': self.polygon.api_key}, timeout=15)
                if r.status_code == 200:
                    results = r.json().get('results', [])
                    return [
                        {'c': b['c'], 'h': b['h'], 'l': b['l'], 'o': b['o'], 'v': b['v'], 't': b['t']}
                        for b in results
                    ]
            except Exception as e:
                logger.debug(f"[POLYGON] History error for {symbol}: {e}")

        return []

    # --- SIG-KICK INTELLIGENCE ---

    def get_sigkick_analysis(self, sym: str, timeframes: List[str] = ['day']) -> Dict:
        """Institutional Grade Multi-Timeframe Path Signature Analysis."""
        if not self.polygon.available:
            return {"score": 0, "regime": "POLYGON REQUIRED"}
        
        signatures = {}
        try:
            for tf in timeframes:
                # Map shorthand to polygon timespans
                multiplier = 1
                timespan = 'day'
                if tf == '1h': timespan = 'hour'
                elif tf == '4h': 
                    multiplier = 4
                    timespan = 'hour'
                elif tf == '15m':
                    multiplier = 15
                    timespan = 'minute'
                
                end_date = datetime.now()
                start_date = end_date - timedelta(days=60 if timespan == 'day' else 14)
                
                r = requests.get(
                    f"{self.polygon.base}/v2/aggs/ticker/{sym}/range/{multiplier}/{timespan}/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}",
                    params={'adjusted': 'true', 'limit': 100, 'apiKey': self.polygon.api_key},
                    timeout=15
                )
                
                if r.status_code == 200:
                    data = r.json()
                    results = data.get('results', [])
                    if results:
                        prices = [ b.get('c') for b in results ]
                        volumes = [ b.get('v') for b in results ]
                        highs = [ b.get('h') for b in results ]
                        lows = [ b.get('l') for b in results ]
                        tr = [ max(h-l, abs(h-prices[idx]), abs(l-prices[idx])) 
                              for idx, (h,l) in enumerate(zip(highs[1:], lows[1:])) ]
                        atr = sum(tr[-14:]) / 14 if len(tr) >= 14 else (sum(tr)/len(tr) if tr else 0.5)
                        
                        # Institutional Pinned Anchor (v1.1)
                        anchor = sigkick.calculate_pinned_price(prices, volumes)
                        signatures[tf] = sigkick.calculate_sigkick(prices, volumes, atr, anchor_price=anchor)

            if not signatures: return {"score": 0, "regime": "NO DATA"}
            
            # Combine MTF
            alignment = sigkick.calculate_mtf_alignment(signatures)
            primary = signatures.get('day', list(signatures.values())[0])
            
            return {
                "score": alignment['sync_score'] if alignment['sync_score'] > 0 else primary['score'],
                "regime": primary['regime'],
                "alignment": alignment,
                "timeframes": signatures
            }
            
        except Exception as e:
            logger.error(f"[SIGKICK] Error analyzing {sym}: {e}")
            
        return {"score": 0, "regime": "ANALYSIS FAILED"}

    def get_etf_basket_correlation(self, sym: str, etf: str = 'XRT') -> Dict:
        """Detect Divergence between Asset and ETF Creation/Redemption Basket."""
        if not self.polygon.available:
            return {"score": 0, "regime": "POLYGON REQUIRED"}
            
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=60)
            
            # Fetch for both
            data_sym = requests.get(f"{self.polygon.base}/v2/aggs/ticker/{sym}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}", params={'apiKey': self.polygon.api_key}).json().get('results', [])
            data_etf = requests.get(f"{self.polygon.base}/v2/aggs/ticker/{etf}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}", params={'apiKey': self.polygon.api_key}).json().get('results', [])
            
            if not data_sym or not data_etf: return {"status": "INSUFFICIENT DATA", "score": 0}
            
            prices_sym = [ b['c'] for b in data_sym ]
            prices_etf = [ b['c'] for b in data_etf ]
            
            # Standardize lengths
            ml = min(len(prices_sym), len(prices_etf))
            ps = prices_sym[-ml:]
            pe = prices_etf[-ml:]
            
            # Correlation
            corr = np.corrcoef(ps, pe)[0,1]
            
            # Signature Divergence (using simpler entropy delta)
            sig_s = sigkick.calculate_sigkick(ps, [1]*ml, 1) # Dummy volume/atr for quick comparison
            sig_e = sigkick.calculate_sigkick(pe, [1]*ml, 1)
            
            div_score = abs(sig_s['score'] - sig_e['score'])
            
            status = "STABLE"
            if corr < 0.5 and div_score > 30: status = "ACTIVE BASKET DIVERGENCE"
            elif corr < 0.7: status = "WEAKENING CORRELATION"
            
            return {
                "status": status,
                "correlation": round(corr, 4),
                "divergence_score": int(div_score),
                "sym": sym,
                "etf": etf
            }
        except Exception as e:
            logger.error(f"[SIGKICK] ETF Error: {e}")
            return {"status": "ERROR", "score": 0}
