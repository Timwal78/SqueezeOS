"""
SQUEEZE OS v5.0 — Multi-Provider Data Layer
Auto-discovers tickers. Scans the entire market. Strictly Real-Time Data.

DISCOVERY (find tickers automatically):
  - Alpaca Screener: most-active + top movers (free, fast)
  - Polygon Grouped Daily: ALL US stocks OHLCV in one call (free)

QUOTES (get real-time data for discovered tickers):
  1. Tradier (production-tier brokerage feed; sandbox is 15-min delayed)
  2. Alpaca snapshots (free IEX quotes, batch)
  3. Polygon prev-day bars (free 5/min tier)
  4. Alpha Vantage (free 25/day, last-resort fallback)
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
        # Environment-only — see options_service.py for the rotation note.
        self.api_key = os.environ.get('ALPACA_API_KEY', '')
        self.api_secret = os.environ.get('ALPACA_API_SECRET', '')
        # Respect ALPACA_PAPER flag for data and API endpoints
        is_paper = os.environ.get('ALPACA_PAPER', 'false').lower() == 'true'
        if is_paper:
            self.data_base = 'https://data.alpaca.markets' # Data is often the same, but let's be explicit if needed
            self.api_base = 'https://paper-api.alpaca.markets'
        else:
            self.data_base = 'https://data.alpaca.markets'
            self.api_base = 'https://api.alpaca.markets'
        
        self.last_call = 0
        self.min_interval = 0.1  # RELAXED: 100ms (was 350ms) — Alpaca allows high frequency
        self.last_error = None
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
            url = f"{self.api_base}/v2/account"
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
            url = f"{self.api_base}/v2/orders"
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

    def get_news(self, limit: int = 10) -> List[Dict]:
        """Fetch latest breaking market news."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            url = f"{self.data_base}/v1beta1/news"
            r = requests.get(url, headers=self._headers(), params={'limit': limit}, timeout=15)
            if r.status_code == 200:
                return r.json().get('news', [])
        except Exception as e:
            logger.error(f"[ALPACA] News error: {e}")
        return []

    def get_option_contracts(self, symbol: str, max_dte: int = 10) -> List[dict]:
        """Fetch option contracts for a symbol."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            start = datetime.now().strftime('%Y-%m-%d')
            end = (datetime.now() + timedelta(days=max_dte)).strftime('%Y-%m-%d')
            params = {
                'underlying_symbols': symbol,
                'status': 'active',
                'expiration_date_gte': start,
                'expiration_date_lte': end,
                'limit': 10000
            }
            r = requests.get(f"{self.api_base}/v2/options/contracts", headers=self._headers(), params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                return data.get('option_contracts', data.get('contracts', []))
            else:
                logger.warning(f"[ALPACA] Option contracts {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"[ALPACA] Option contracts error: {e}")
        return []

    def get_option_snapshots(self, symbols: List[str]) -> Dict[str, dict]:
        """Fetch option snapshots for a list of symbols."""
        if not self.available or not symbols:
            return {}
        results = {}
        batch_size = 100
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            self._rate_limit()
            try:
                params = {'symbols': ','.join(batch), 'feed': 'opra'}
                r = requests.get(f"{self.data_base}/v1beta1/options/snapshots", headers=self._headers(), params=params, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    # Standardize format: Alpaca snapshots can be a dict or {snapshots: {...}}
                    snaps = data.get('snapshots', data if isinstance(data, dict) else {})
                    results.update(snaps)
                    self.last_error = None
                elif r.status_code == 403:
                    if "OPRA agreement" in r.text:
                        self.last_error = "OPRA_UNSIGNED"
                    else:
                        self.last_error = "AUTH_ERROR"
                    logger.warning(f"[ALPACA] Option snap {r.status_code}: {r.text[:200]}")
                else:
                    self.last_error = f"HTTP_{r.status_code}"
                    logger.warning(f"[ALPACA] Option snap {r.status_code}: {r.text[:200]}")
            except Exception as e:
                self.last_error = "EXCEPTION"
                logger.error(f"[ALPACA] Option snap error: {e}")
        return results

    def get_historical_bars(self, symbol: str, timeframe: str = '1Day', limit: int = 40) -> List[dict]:
        """Fetch historical stock bars."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=limit + 10)).strftime('%Y-%m-%d')
            params = {
                'timeframe': timeframe,
                'start': start,
                'end': end,
                'limit': limit,
                'feed': 'iex',
                'sort': 'desc'
            }
            r = requests.get(f"{self.data_base}/v2/stocks/{symbol}/bars", headers=self._headers(), params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                bars = data.get('bars', [])
                # Return in chronological order
                return sorted(bars, key=lambda x: x.get('t', ''))
            else:
                logger.warning(f"[ALPACA] Stock bars {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"[ALPACA] Stock bars error: {e}")
        return []


# ============================================================
# POLYGON PROVIDER — discovery + per-symbol quotes
# ============================================================
# Resilient libsml import — works regardless of PYTHONPATH / working directory.
# libsml lives at: scratch/libsml/ (parent of SqueezeOS directory)
import sys as _sys
_libsml_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _libsml_root not in _sys.path:
    _sys.path.insert(0, _libsml_root)
try:
    from libsml.rate_guard import PolygonRateGuard
except ImportError as _e:
    logger.warning(f"[POLYGON] libsml.rate_guard not found ({_e}). Using no-op rate guard.")
    class PolygonRateGuard:
        @staticmethod
        def wait(): pass
        @staticmethod
        def emergency_backoff(): import time; time.sleep(60)

class PolygonProvider:
    def __init__(self):
        self.api_key = os.environ.get('POLYGON_API_KEY', '')
        self.base = 'https://api.polygon.io'
        if self.available:
            logger.info(f"[POLYGON] Ready ({self.api_key[:6]}...)")
        else:
            logger.warning("[POLYGON] Not configured")

    @property
    def available(self):
        return bool(self.api_key)

    def _rate_limit(self):
        PolygonRateGuard.wait()

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
                    # RATE LIMIT HIT: Use the standardized institutional backoff
                    PolygonRateGuard.emergency_backoff()
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
# TRADIER PROVIDER — live execution + options quotes
# ============================================================
class TradierProvider:
    def __init__(self):
        # Determine mode: TRADIER_LIVE=true OR TRADIER_ENV=production (matches tradier_api.py)
        self.live_mode = (
            os.environ.get('TRADIER_LIVE', 'false').lower() == 'true'
            or os.environ.get('TRADIER_ENV', 'sandbox').lower() == 'production'
        )
        if self.live_mode:
            self.api_key = (
                os.environ.get('TRADIER_PRODUCTION_API_KEY') or
                os.environ.get('TRADIER_API_KEY', '')
            )
            self.account_id = os.environ.get('TRADIER_PRODUCTION_ACCOUNT', '')
            self.base_url = 'https://api.tradier.com/v1'
        else:
            self.api_key = (
                os.environ.get('TRADIER_SANDBOX_API_KEY') or
                os.environ.get('TRADIER_API_KEY', '')
            )
            self.account_id = os.environ.get('TRADIER_SANDBOX_ACCOUNT', '')
            self.base_url = 'https://sandbox.tradier.com/v1'

        self.last_call = 0
        self.min_interval = 0.5
        if self.available:
            logger.info(f"[TRADIER] Ready ({'LIVE' if self.live_mode else 'SANDBOX'} | {self.api_key[:6]}...)")
        else:
            logger.warning("[TRADIER] Not configured")

    @property
    def available(self):
        return bool(self.api_key)  # account_id only needed for trading orders, not market data

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json'
        }

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()

    def get_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        if not self.available or not symbols:
            return {}
        self._rate_limit()
        try:
            url = f"{self.base_url}/markets/quotes"
            params = {'symbols': ','.join(symbols)}
            r = requests.get(url, headers=self._headers(), params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                quotes = data.get('quotes', {}).get('quote', [])
                if isinstance(quotes, dict): quotes = [quotes]
                
                results = {}
                for q in quotes:
                    sym = q.get('symbol')
                    if sym:
                        vol = int(q.get('volume', 0) or 0)
                        avg_vol = int(q.get('average_volume', 0) or 0)
                        vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 0
                        results[sym] = {
                            'symbol': sym,
                            'price': round(float(q.get('last', 0) or 0), 4),
                            'change': round(float(q.get('change', 0) or 0), 4),
                            'changePct': round(float(q.get('change_percentage', '0').replace('%','') if isinstance(q.get('change_percentage'), str) else q.get('change_percentage', 0) or 0), 2),
                            'volume': vol,
                            'avgVolume': avg_vol,
                            'volRatio': vol_ratio,
                            'open': round(float(q.get('open', 0) or 0), 4),
                            'high': round(float(q.get('high', 0) or 0), 4),
                            'low': round(float(q.get('low', 0) or 0), 4),
                            'bid': round(float(q.get('bid', 0) or 0), 4),
                            'ask': round(float(q.get('ask', 0) or 0), 4),
                            'prevClose': round(float(q.get('prevclose', 0) or 0), 4),
                            'week52High': round(float(q.get('week_52_high', 0) or 0), 4),
                            'week52Low': round(float(q.get('week_52_low', 0) or 0), 4),
                            'source': 'tradier',
                        }
                return results
        except Exception as e:
            logger.error(f"[TRADIER] Quotes error: {e}")
        return {}

    def place_order(self, symbol: str, qty: int, side: str, order_type: str = 'market') -> Dict:
        if not self.available:
            return {"status": "error", "message": "Tradier not configured"}
        self._rate_limit()
        try:
            url = f"{self.base_url}/accounts/{self.account_id}/orders"
            payload = {
                'class': 'equity',
                'symbol': symbol,
                'side': side.lower(),
                'quantity': qty,
                'type': order_type,
                'duration': 'day'
            }
            r = requests.post(url, headers=self._headers(), data=payload, timeout=15)
            if r.status_code == 200:
                order = r.json().get('order', {})
                logger.info(f"✅ Tradier Order Placed: {order.get('id')}")
                return {"status": "success", "order_id": order.get('id')}
            else:
                err = r.text
                logger.error(f"🛑 Tradier Order Failed [{r.status_code}]: {err}")
                return {"status": "error", "message": err}
        except Exception as e:
            logger.error(f"[TRADIER] Order error: {e}")
            return {"status": "error", "message": str(e)}
    def get_option_expirations(self, symbol: str) -> list:
        """Fetch available option expiration dates for symbol."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            url = f"{self.base_url}/markets/options/expirations"
            params = {'symbol': symbol, 'includeAllRoots': 'true', 'strikes': 'false'}
            r = requests.get(url, headers=self._headers(), params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                exps = data.get('expirations', {}) or {}
                dates = exps.get('date', []) or []
                if isinstance(dates, str): dates = [dates]
                return dates
        except Exception as e:
            logger.error(f"[TRADIER] Expirations error {symbol}: {e}")
        return []

    def get_option_chains(self, symbol: str) -> dict:
        """Fetch option chain for symbol via Tradier options API (0DTE to 14 days)."""
        if not self.available:
            return None
        from datetime import datetime, timedelta
        try:
            # Get expirations first
            exps = self.get_option_expirations(symbol)
            if not exps:
                return None

            now = datetime.now()
            max_exp = now + timedelta(days=14)
            # Filter to 0-14 day expirations
            valid_exps = []
            for d in exps:
                try:
                    dt = datetime.strptime(d, '%Y-%m-%d')
                    if dt.date() >= now.date() and dt <= max_exp:
                        valid_exps.append(d)
                except:
                    continue
            if not valid_exps:
                return None

            # Fetch chain for nearest expiration (minimize API calls)
            # Get up to 3 expirations to cover 0DTE + weekly
            all_options = []
            for exp_date in valid_exps[:3]:
                self._rate_limit()
                url = f"{self.base_url}/markets/options/chains"
                params = {'symbol': symbol, 'expiration': exp_date, 'greeks': 'true'}
                r = requests.get(url, headers=self._headers(), params=params, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    options = data.get('options', {}) or {}
                    chain = options.get('option', []) or []
                    if isinstance(chain, dict): chain = [chain]
                    all_options.extend(chain)

            if all_options:
                return {'symbol': symbol, 'options': all_options, 'source': 'tradier'}
            return None
        except Exception as e:
            logger.error(f"[TRADIER] Option chain error {symbol}: {e}")
            return None

    def get_price_history(self, symbol: str, period_type: str = 'month', period: int = 1) -> dict:
        """Fetch OHLCV history via Tradier timesales."""
        if not self.available:
            return {}
        self._rate_limit()
        try:
            url = f"{self.base_url}/markets/history"
            params = {'symbol': symbol, 'interval': 'daily'}
            r = requests.get(url, headers=self._headers(), params=params, timeout=12)
            if r.status_code == 200:
                hist = r.json().get('history', {}) or {}
                days = hist.get('day', []) or []
                if isinstance(days, dict): days = [days]
                candles = [{'datetime': d.get('date'), 'open': d.get('open', 0),
                            'high': d.get('high', 0), 'low': d.get('low', 0),
                            'close': d.get('close', 0), 'volume': d.get('volume', 0)} for d in days]
                return {'candles': candles, 'symbol': symbol}
            return {}
        except Exception as e:
            logger.error(f"[TRADIER] History error {symbol}: {e}")
            return {}


# ============================================================
# UNIFIED DATA MANAGER
# ============================================================
class DataManager:
    """Auto-discovers tickers + fetches real quotes. Never fakes data."""

    def __init__(self, schwab_state=None):
        # `schwab_state` kept in the signature for back-compat with old callers.
        # The Schwab provider was deprecated in favor of Tradier; this slot now
        # always resolves to None and the downstream `if self.schwab` guards are
        # dead branches that the next refactor will remove.
        logger.info("[DATA] Initializing...")
        self.schwab = None
        self.alpaca = AlpacaProvider()
        self.polygon = PolygonProvider()
        self.alphav = AlphaVantageProvider()
        self.tradier = TradierProvider()
        logger.info("[DATA] Ready")

    def provider_status(self) -> dict:
        return {
            'tradier': self.tradier.available,
            'alpaca': self.alpaca.available,
            'polygon': self.polygon.available,
            'alphavantage': self.alphav.available,
        }

    # --- AUTO-DISCOVERY ---

    def discover_universe(self, progress_cb=None, limit=10000) -> Dict[str, dict]:
        universe = {}
        
        def is_junk(sym):
            if not sym: return True
            sym = sym.upper()
            if any(x in sym for x in ['.', '-', ' ', '/']): return True
            if sym.endswith('W') or sym.endswith('WS') or sym.endswith('U'): return True
            return False

        # ════════════════════════════════════════════════════════════
        # TIER 1: TRADIER QUOTES — Primary execution-grade source
        # ════════════════════════════════════════════════════════════
        # Tradier doesn’t have a movers endpoint, so seed with a curated
        # watchlist of high-liquidity names for baseline discovery.
        _TRADIER_SEED = ['SPY','QQQ','IWM','AAPL','TSLA','NVDA','AMZN','MSFT',
                         'META','GOOGL','AMD','PLTR','SOFI','MARA','RIOT','COIN',
                         'GME','AMC','SNDL','BBBY','NIO','LCID','RIVN','SPCE']
        if self.tradier.available:
            if progress_cb: progress_cb('Discovering: Tradier seed universe...')
            quotes = self.tradier.get_quotes(_TRADIER_SEED)
            for sym, q in quotes.items():
                if sym and not is_junk(sym):
                    universe[sym] = {**q, 'symbol': sym, 'discovery': 'tradier_seed'}
            logger.info(f"[DISCOVERY] Tradier seed: {len(universe)} tickers")

        # ════════════════════════════════════════════════════════════
        # TIER 2: ALPACA MOVERS — Supplemental gainers/losers
        # ════════════════════════════════════════════════════════════
        if self.alpaca.available:
            if progress_cb: progress_cb('Discovering: Alpaca movers...')
            movers = self.alpaca.get_movers(top=50)
            for item in movers.get('gainers', []):
                sym = item.get('symbol', '')
                if sym and not is_junk(sym):
                    chg = item.get('percent_change', 0)
                    if abs(chg) >= 1.0:
                        universe.setdefault(sym, {'symbol': sym, 'discovery': 'alpaca_gainer', 'changePct': chg})
            for item in movers.get('losers', []):
                sym = item.get('symbol', '')
                if sym and not is_junk(sym):
                    chg = item.get('percent_change', 0)
                    if abs(chg) >= 1.0:
                        universe.setdefault(sym, {'symbol': sym, 'discovery': 'alpaca_loser', 'changePct': chg})
            actives = self.alpaca.get_most_actives(top=100)
            for item in actives:
                sym = item.get('symbol', '')
                if sym and not is_junk(sym) and sym not in universe:
                    universe[sym] = {'symbol': sym, 'discovery': 'alpaca_active', 'volume': item.get('volume', 0)}
            logger.info(f"[DISCOVERY] Alpaca: {len(universe)} total after movers")

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
                    
                    # MANIFESTO: WIDE OPEN FETCH — 10k vol minimum, $50 SWEET SPOT CAP
                    if vol >= 10000 and 0.01 <= price <= 50.0 and abs(chg_pct) >= 0.05:
                        if sym not in universe:
                            universe[sym] = bar
                            universe[sym]['discovery'] = 'polygon_scan'
                            universe[sym]['changePct'] = chg_pct
                            poly_added += 1
                logger.info(f"[DISCOVERY] Polygon: {poly_added} tickers added")

        if progress_cb: progress_cb(f'Discovered {len(universe)} tickers')
        logger.info(f"[DISCOVERY] Total universe: {len(universe)} tickers")
        return universe

    # --- QUOTES ---

    def get_quotes(self, symbols: List[str], progress_cb=None, fast_only=False) -> Dict[str, dict]:
        """Fetch real quotes for given symbols via best provider."""
        if not symbols: return {}
        results = {}
        remaining = list(symbols)

        # 1. Tradier (PRIMARY — Execution-grade, live data)
        if self.tradier.available and remaining:
            data = self.tradier.get_quotes(remaining)
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 2. Alpaca (BACKUP — High speed batch)
        if self.alpaca.available and remaining:
            data = self.alpaca.get_snapshots(remaining)
            results.update(data)
            remaining = [s for s in remaining if s not in results]

        # 4. Polygon (SLOW - Skip if fast_only is requested)
        if not fast_only and self.polygon.available and remaining:
            # Only do this for small batches (e.g. Grimoire), NOT for scanner (remaining > 50)
            if len(remaining) <= 10:
                data = self.polygon.get_quotes_batch(remaining)
                results.update(data)
                remaining = [s for s in remaining if s not in results]

        return results
    def get_historical_bars(self, symbol: str, timeframe: str = '1Day', limit: int = 40) -> List[dict]:
        return self.alpaca.get_historical_bars(symbol, timeframe, limit)

    def get_bars(self, symbol: str, timeframe: str = '1D', limit: int = 60) -> List[dict]:
        """Fetch historical bars primarily using Polygon, fallback to Alpaca."""
        try:
            if self.polygon.available:
                # Map timeframe to Polygon formats (e.g. 1D -> 1, day)
                multiplier = 1
                timespan = 'day'
                days_back = limit * 2 # pad for weekends
                if timeframe.upper() == '1D':
                    timespan = 'day'
                    days_back = limit * 2
                elif timeframe.upper() == '1MIN' or timeframe.upper() == '1M':
                    timespan = 'minute'
                    days_back = max(2, int(limit / 390)) + 1
                elif timeframe.upper() == '5MIN' or timeframe.upper() == '5M':
                    multiplier = 5
                    timespan = 'minute'
                    days_back = max(2, int(limit / 78)) + 1
                    
                bars = self.polygon.get_aggregates(symbol, multiplier=multiplier, timespan=timespan, limit=limit, days_back=days_back)
                if bars:
                    # Polygon returns them descending usually (from our code), but lets make sure it's consistent if the app expects ascending
                    # DataManager usually returns chronological order (ascending) for AI processing
                    bars = sorted(bars, key=lambda x: x.get('timestamp', 0))
                    return bars
        except Exception as e:
            logger.error(f"[DATA] Polygon get_bars error: {e}")
            
        # Fallback to Alpaca
        alpaca_tf = '1Day'
        if timeframe.upper() in ['1MIN', '1M']: alpaca_tf = '1Min'
        elif timeframe.upper() in ['5MIN', '5M']: alpaca_tf = '5Min'
        return self.alpaca.get_historical_bars(symbol, alpaca_tf, limit)

    def get_option_contracts(self, symbol: str, max_dte: int = 10) -> List[dict]:
        return self.alpaca.get_option_contracts(symbol, max_dte)

    def get_option_snapshots(self, symbols: List[str]) -> Dict[str, dict]:
        return self.alpaca.get_option_snapshots(symbols)
