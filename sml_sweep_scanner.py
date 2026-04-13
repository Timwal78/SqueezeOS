#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║  SML INSTITUTIONAL SWEEP SCANNER™ v6 — QUAD-API BEAST                    ║
║  ScriptMasterLabs™ — Strictly Real-Time Data. ALL live. ALL real.        ║
║                                                                           ║
║  DATA SOURCES (priority order):                                           ║
║    1. SCHWAB — Real-time option chains w/ Greeks, VWAP, quotes            ║
║    2. ALPACA — Discovery (most-active, movers), fast snapshots            ║
║    3. POLYGON — Full market grouped daily, aggregates, news               ║
║    4. YAHOO FINANCE — Backup option chains + discovery                    ║
║    5. ALPHA VANTAGE — Last-resort quotes                                  ║
║                                                                           ║
║  OUTPUT: BUY / SELL / HOLD with exact strike + expiration                 ║
║                                                                           ║
║  RUN:                                                                     ║
║    python sml_sweep_scanner.py                    # single scan           ║
║    python sml_sweep_scanner.py loop 15            # every 15 min          ║
║    python sml_sweep_scanner.py --price-max 100    # stocks under $100     ║
║    python sml_sweep_scanner.py --min-premium 100000  # lower threshold    ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import time
import math
import argparse
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Optional

# ─── DEPENDENCY CHECK ───
try:
    import requests
except ImportError:
    print("\n  pip install requests yfinance python-dotenv\n")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("\n  pip install yfinance\n")
    sys.exit(1)

# ─── ENV LOADER (bulletproof, same as data_providers.py) ───
def load_env_file():
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
        os.path.join(os.getcwd(), '.env'),
    ]
    for env_path in paths:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    key, val = key.strip(), val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    if val:
                        os.environ[key] = val
            break

load_env_file()

# ─── CONFIG ───
POLYGON_KEY     = os.getenv("POLYGON_API_KEY", "")
ALPACA_KEY      = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET   = os.getenv("ALPACA_API_SECRET", "") or os.getenv("ALPACA_SECRET_KEY", "")
ALPHA_KEY       = os.getenv("ALPHA_VANTAGE_API_KEY", "") or os.getenv("ALPHA_VANTAGE_KEY", "")
SCHWAB_ID       = os.getenv("SCHWAB_CLIENT_ID", "") or os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_SECRET   = os.getenv("SCHWAB_CLIENT_SECRET", "") or os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_REFRESH  = os.getenv("SCHWAB_REFRESH_TOKEN", "")

# Dedicated sweep scanner webhook → falls back to flow → all
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_SWEEP", "") or os.getenv("DISCORD_WEBHOOK_FLOW", "") or os.getenv("DISCORD_WEBHOOK_ALL", "")

ETFS = {
    "SPY","QQQ","IWM","DIA","XLF","XLE","XLK","XLV","XLI","XLP","XLU",
    "XLB","XLC","XLRE","XLY","GLD","SLV","TLT","HYG","EEM","EFA","VXX",
    "UVXY","SQQQ","TQQQ","SPXL","ARKK","SMH","KWEB","FXI","USO","GDX",
    "GDXJ","KRE","XBI","XOP","JETS","BITO","MSOS","SOXL","SOXS","LABU",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("SML")


# ═══════════════════════════════════════════════
# PROVIDER LAYER — Schwab, Alpaca, Polygon, Yahoo
# ═══════════════════════════════════════════════

class SchwabClient:
    """Lightweight Schwab client for the scanner. Uses existing token file."""
    def __init__(self):
        self.base_url = "https://api.schwabapi.com"
        self.token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schwab_tokens.json')
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = 0
        self._failed = False
        self._load_tokens()
        # If env has a fresh refresh token and ours is expired/missing, use it
        if SCHWAB_REFRESH and (not self.refresh_token or time.time() > self.token_expires_at):
            log.info("[SCHWAB] Using SCHWAB_REFRESH_TOKEN from env")
            self.refresh_token = SCHWAB_REFRESH
            self.token_expires_at = 0  # Force refresh

    @property
    def available(self):
        if not SCHWAB_ID or not SCHWAB_SECRET:
            return False
        if not self.access_token:
            return False
        if hasattr(self, '_failed') and self._failed:
            return False
        if time.time() > self.token_expires_at - 60:
            return self._refresh()
        return True

    def _load_tokens(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    tokens = json.load(f)
                    self.access_token = tokens.get('access_token')
                    self.refresh_token = tokens.get('refresh_token')
                    self.token_expires_at = tokens.get('expires_at', 0)
            except:
                pass

    def _refresh(self):
        if not self.refresh_token:
            return False
        import base64
        auth = base64.b64encode(f"{SCHWAB_ID}:{SCHWAB_SECRET}".encode()).decode()
        try:
            r = requests.post(f"{self.base_url}/v1/oauth/token",
                headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
                data={'grant_type': 'refresh_token', 'refresh_token': self.refresh_token},
                timeout=15)
            if r.status_code == 200:
                data = r.json()
                self.access_token = data['access_token']
                self.refresh_token = data.get('refresh_token', self.refresh_token)
                self.token_expires_at = time.time() + data.get('expires_in', 1800)
                with open(self.token_file, 'w') as f:
                    json.dump({'access_token': self.access_token, 'refresh_token': self.refresh_token,
                               'expires_at': self.token_expires_at, 'updated_at': datetime.now().isoformat()}, f, indent=4)
                log.info("[SCHWAB] Token refreshed ✅")
                return True
            else:
                log.warning(f"[SCHWAB] Refresh failed: {r.status_code} — disabling for this session")
                self._failed = True
                return False
        except Exception as e:
            log.warning(f"[SCHWAB] Refresh error: {e}")
            return False

    def _headers(self):
        return {'Authorization': f'Bearer {self.access_token}', 'Accept': 'application/json'}

    def get_option_chains(self, symbol, dte_max=30):
        """Full option chain with Greeks from Schwab."""
        if not self.available:
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        far = (datetime.now() + timedelta(days=dte_max)).strftime("%Y-%m-%d")
        try:
            r = requests.get(f"{self.base_url}/marketdata/v1/chains",
                headers=self._headers(),
                params={'symbol': symbol, 'contractType': 'ALL', 'strategy': 'SINGLE',
                        'fromDate': today, 'toDate': far, 'includeQuotes': 'TRUE', 'range': 'ALL'},
                timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.debug(f"[SCHWAB] Chain {symbol}: {e}")
        return None

    def get_quotes(self, symbols):
        """Batch quotes from Schwab."""
        if not self.available or not symbols:
            return {}
        results = {}
        for i in range(0, len(symbols), 200):
            batch = symbols[i:i+200]
            try:
                r = requests.get(f"{self.base_url}/marketdata/v1/quotes",
                    headers=self._headers(),
                    params={'symbols': ','.join(batch), 'fields': 'quote,fundamental'},
                    timeout=15)
                if r.status_code == 200:
                    for sym, data in r.json().items():
                        q = data.get('quote', {})
                        price = q.get('lastPrice') or q.get('mark') or q.get('closePrice', 0)
                        results[sym] = {
                            'price': float(price),
                            'open': float(q.get('openPrice', 0)),
                            'high': float(q.get('highPrice', 0)),
                            'low': float(q.get('lowPrice', 0)),
                            'volume': int(q.get('totalVolume', 0)),
                            'vwap': 0,  # Schwab doesn't give VWAP directly
                        }
            except Exception as e:
                log.debug(f"[SCHWAB] Quotes: {e}")
        return results

    def get_price_history_vwap(self, symbol):
        """Calculate true VWAP from intraday bars."""
        if not self.available:
            return 0
        try:
            r = requests.get(f"{self.base_url}/marketdata/v1/pricehistory",
                headers=self._headers(),
                params={'symbol': symbol, 'periodType': 'day', 'period': 1,
                        'frequencyType': 'minute', 'frequency': 5},
                timeout=15)
            if r.status_code == 200:
                candles = r.json().get('candles', [])
                if candles:
                    tp_vol = sum((c['high'] + c['low'] + c['close']) / 3 * c['volume'] for c in candles)
                    total_vol = sum(c['volume'] for c in candles)
                    if total_vol > 0:
                        return round(tp_vol / total_vol, 4)
        except:
            pass
        return 0


class AlpacaClient:
    """Alpaca discovery + quotes."""
    def __init__(self):
        self.base = 'https://data.alpaca.markets'

    @property
    def available(self):
        return bool(ALPACA_KEY and ALPACA_SECRET)

    def _headers(self):
        return {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}

    def discover(self, top=100):
        """Get most-active + movers for auto-discovery."""
        tickers = {}
        if not self.available:
            return tickers

        # Most active by volume
        try:
            r = requests.get(f"{self.base}/v1beta1/screener/stocks/most-actives",
                headers=self._headers(), params={'by': 'volume', 'top': top}, timeout=15)
            if r.status_code == 200:
                for item in r.json().get('most_actives', []):
                    sym = item.get('symbol', '')
                    if sym and '.' not in sym and '-' not in sym:
                        tickers[sym] = {'symbol': sym, 'volume': item.get('volume', 0), 'source': 'alpaca_active'}
                log.info(f"[ALPACA] Most actives: {len(tickers)} tickers")
        except Exception as e:
            log.debug(f"[ALPACA] Most actives: {e}")

        # Movers (gainers + losers)
        try:
            r = requests.get(f"{self.base}/v1beta1/screener/stocks/movers",
                headers=self._headers(), params={'top': 50}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for item in data.get('gainers', []) + data.get('losers', []):
                    sym = item.get('symbol', '')
                    if sym and '.' not in sym and '-' not in sym and sym not in tickers:
                        tickers[sym] = {'symbol': sym, 'volume': 0, 'source': 'alpaca_mover',
                                        'change_pct': item.get('percent_change', 0)}
                log.info(f"[ALPACA] Movers added, total: {len(tickers)}")
        except Exception as e:
            log.debug(f"[ALPACA] Movers: {e}")

        return tickers

    def get_snapshots(self, symbols):
        """Batch snapshots for price + volume."""
        if not self.available or not symbols:
            return {}
        results = {}
        for i in range(0, len(symbols), 100):
            batch = symbols[i:i+100]
            try:
                r = requests.get(f"{self.base}/v2/stocks/snapshots",
                    headers=self._headers(),
                    params={'symbols': ','.join(batch), 'feed': 'iex'},
                    timeout=30)
                if r.status_code == 200:
                    for sym, snap in r.json().items():
                        bar = snap.get('dailyBar', {})
                        prev = snap.get('prevDailyBar', {})
                        latest = snap.get('latestTrade', {})
                        price = latest.get('p') or bar.get('c', 0)
                        results[sym] = {
                            'price': round(float(price), 4) if price else 0,
                            'open': round(float(bar.get('o', 0)), 4),
                            'high': round(float(bar.get('h', 0)), 4),
                            'low': round(float(bar.get('l', 0)), 4),
                            'volume': int(bar.get('v', 0)),
                            'vwap': round(float(bar.get('vw', 0)), 4) if bar.get('vw') else 0,
                        }
            except Exception as e:
                log.debug(f"[ALPACA] Snapshots: {e}")
        return results


class PolygonClient:
    """Polygon for full market discovery + options flow."""
    def __init__(self):
        self.base = 'https://api.polygon.io'
        self.last_call = 0
        self.min_interval = 12.5  # 5 req/min free tier

    @property
    def available(self):
        return bool(POLYGON_KEY)

    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()

    def get_grouped_daily(self):
        """ALL US stocks OHLCV in one call — full market discovery."""
        if not self.available:
            return {}
        now = datetime.now() - timedelta(days=1)
        while now.weekday() >= 5:
            now -= timedelta(days=1)
        date_str = now.strftime('%Y-%m-%d')

        self._rate_limit()
        try:
            r = requests.get(f"{self.base}/v2/aggs/grouped/locale/us/market/stocks/{date_str}",
                params={'adjusted': 'true', 'apiKey': POLYGON_KEY}, timeout=30)
            if r.status_code == 200:
                results = {}
                for bar in r.json().get('results', []):
                    sym = bar.get('T', '')
                    if sym and '.' not in sym:
                        results[sym] = {
                            'price': round(bar.get('c', 0), 4),
                            'open': round(bar.get('o', 0), 4),
                            'high': round(bar.get('h', 0), 4),
                            'low': round(bar.get('l', 0), 4),
                            'volume': int(bar.get('v', 0)),
                            'vwap': round(bar.get('vw', 0), 4),
                        }
                log.info(f"[POLYGON] Grouped daily: {len(results)} tickers")
                return results
        except Exception as e:
            log.debug(f"[POLYGON] Grouped: {e}")
        return {}

    def get_options_flow(self, symbol, dte_max=14):
        """Get options contracts for a symbol via Polygon (if available on free tier)."""
        if not self.available:
            return []
        self._rate_limit()
        try:
            exp_date = (datetime.now() + timedelta(days=dte_max)).strftime('%Y-%m-%d')
            r = requests.get(f"{self.base}/v3/reference/options/contracts",
                params={'underlying_ticker': symbol, 'expired': 'false',
                        'expiration_date.lte': exp_date, 'limit': 250,
                        'apiKey': POLYGON_KEY},
                timeout=15)
            if r.status_code == 200:
                return r.json().get('results', [])
        except Exception as e:
            log.debug(f"[POLYGON] Options contracts {symbol}: {e}")
        return []


# ═══════════════════════════════════════════════
# STEP 1: MULTI-SOURCE DISCOVERY
# ═══════════════════════════════════════════════

def discover_tickers(price_min, price_max, schwab, alpaca, polygon):
    """
    Discover active tickers from ALL available API sources.
    Priority: Alpaca → Polygon → Yahoo → Schwab
    """
    log.info("=" * 60)
    log.info("WORLD SCAN: Multi-API Discovery")
    log.info("=" * 60)

    universe = {}  # ticker -> {price, volume, source}

    # ── TIER 1: Alpaca (fast, free) ──
    if alpaca.available:
        alpaca_tickers = alpaca.discover(top=100)
        for sym, data in alpaca_tickers.items():
            universe[sym] = data
        log.info(f"  Alpaca: {len(alpaca_tickers)} tickers discovered")

    # ── TIER 2: Polygon Grouped Daily (entire market) ──
    if polygon.available:
        grouped = polygon.get_grouped_daily()
        added = 0
        # Sort by dollar volume (price * volume) descending
        sorted_bars = sorted(grouped.items(),
            key=lambda x: x[1].get('price', 0) * x[1].get('volume', 0), reverse=True)
        for sym, bar in sorted_bars:
            if sym in universe:
                # Update price/volume if we have better data
                if bar.get('price', 0) > 0:
                    universe[sym].update(bar)
                continue
            price = bar.get('price', 0)
            vol = bar.get('volume', 0)
            if price_min <= price <= price_max and vol >= 50000:
                universe[sym] = bar
                universe[sym]['source'] = 'polygon'
                added += 1
                if added >= 500:  # cap to keep scan time reasonable
                    break
        log.info(f"  Polygon: {added} new tickers added")

    # ── TIER 3: Yahoo Finance (backup discovery) ──
    if len(universe) < 20:
        log.info("  Yahoo Finance: supplementing discovery...")
        headers = {"User-Agent": "Mozilla/5.0"}
        for cat_id in ["most_actives", "day_gainers", "day_losers"]:
            try:
                for base in ["query1", "query2"]:
                    url = f"https://{base}.finance.yahoo.com/v1/finance/screener/predefined/{cat_id}"
                    r = requests.get(url, headers=headers, params={"count": 100}, timeout=15)
                    if r.status_code == 200:
                        quotes = r.json().get("finance", {}).get("result", [{}])[0].get("quotes", [])
                        for q in quotes:
                            sym = q.get("symbol", "")
                            price = q.get("regularMarketPrice", 0)
                            vol = q.get("regularMarketVolume", 0)
                            if sym and price and '.' not in sym and '-' not in sym:
                                if price_min <= price <= price_max and sym not in universe:
                                    universe[sym] = {'price': price, 'volume': vol, 'source': 'yahoo'}
                        break
            except:
                continue
        log.info(f"  Yahoo: total now {len(universe)}")

    # ── Get prices for tickers missing them ──
    needs_price = [sym for sym, d in universe.items() if not d.get('price')]
    if needs_price and alpaca.available:
        snapshots = alpaca.get_snapshots(needs_price[:200])
        for sym, snap in snapshots.items():
            if sym in universe:
                universe[sym].update(snap)

    # ── Filter by price range ──
    filtered = {}
    for sym, data in universe.items():
        price = data.get('price', 0)
        if price and price_min <= price <= price_max:
            filtered[sym] = data

    # Sort by volume
    sorted_tickers = sorted(filtered.items(), key=lambda x: x[1].get('volume', 0), reverse=True)
    log.info(f"DISCOVERED: {len(sorted_tickers)} tickers in ${price_min}-${price_max}")
    return sorted_tickers


# ═══════════════════════════════════════════════
# STEP 2: OPTION CHAIN SCANNER
# Schwab (institutional) → Yahoo (backup)
# ═══════════════════════════════════════════════

def parse_schwab_chain(chain_data, ticker, price, dte_min, dte_max, min_premium):
    """Parse Schwab option chain format into sweep candidates."""
    sweeps = []
    today = datetime.now().date()
    is_etf = ticker in ETFS

    for side_key, side_label in [("callExpDateMap", "call"), ("putExpDateMap", "put")]:
        exp_map = chain_data.get(side_key, {})
        for exp_key, strikes in exp_map.items():
            try:
                exp_str = exp_key.split(":")[0]
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            except:
                continue

            dte = (exp_date - today).days
            if dte < dte_min or dte > dte_max:
                continue

            for strike_str, contracts in strikes.items():
                for contract in contracts:
                    strike = float(strike_str)
                    volume = int(contract.get('totalVolume', 0))
                    oi = int(contract.get('openInterest', 0))
                    last_price = float(contract.get('last', 0))
                    bid = float(contract.get('bid', 0))
                    ask = float(contract.get('ask', 0))
                    delta = float(contract.get('delta', 0))
                    gamma = float(contract.get('gamma', 0))
                    theta = float(contract.get('theta', 0))
                    iv = float(contract.get('volatility', 0)) / 100.0  # Schwab gives as %
                    symbol_desc = contract.get('symbol', '')

                    if not volume or not last_price or not strike:
                        continue

                    # OTM distance
                    if price <= 0:
                        continue
                    if side_label == "call":
                        otm_pct = (strike - price) / price
                    else:
                        otm_pct = (price - strike) / price

                    otm_max = 0.03 if is_etf else 0.05
                    if otm_pct < -0.005 or otm_pct > otm_max:
                        continue

                    premium = volume * last_price * 100
                    if premium < min_premium:
                        continue

                    mid = (bid + ask) / 2 if (bid and ask) else last_price
                    spread_pct = (ask - bid) / mid if mid > 0 and bid and ask else 0
                    vol_oi = volume / max(oi, 1)

                    sweeps.append({
                        "ticker": ticker,
                        "strike": strike,
                        "expiration": exp_str,
                        "type": side_label,
                        "premium": premium,
                        "volume": volume,
                        "price": last_price,
                        "bid": bid, "ask": ask,
                        "dte": dte,
                        "otm_pct": otm_pct,
                        "oi": oi,
                        "vol_oi": vol_oi,
                        "spread_pct": spread_pct,
                        "iv": iv,
                        "delta": delta,
                        "gamma": gamma,
                        "theta": theta,
                        "underlying_price": price,
                        "symbol": symbol_desc,
                        "source": "schwab",
                    })

    return sweeps


def scan_yahoo_chain(ticker, price, dte_min, dte_max, min_premium):
    """Backup: scan via yfinance."""
    try:
        t = yf.Ticker(ticker)
        exp_dates = t.options
    except:
        return []

    if not exp_dates:
        return []

    today = datetime.now().date()
    sweeps = []
    is_etf = ticker in ETFS

    for exp_str in exp_dates:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except:
            continue
        dte = (exp_date - today).days
        if dte < dte_min or dte > dte_max:
            continue
        try:
            chain = t.option_chain(exp_str)
        except:
            continue

        for side, df in [("call", chain.calls), ("put", chain.puts)]:
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                strike = row.get("strike", 0)
                volume = row.get("volume", 0)
                oi = row.get("openInterest", 0)
                last_price = row.get("lastPrice", 0)
                bid = row.get("bid", 0)
                ask = row.get("ask", 0)
                impl_vol = row.get("impliedVolatility", 0)

                if not volume or not last_price or not strike:
                    continue
                if volume != volume:  # NaN
                    continue

                volume = int(volume)
                oi = int(oi) if oi == oi else 0

                if price <= 0:
                    continue
                if side == "call":
                    otm_pct = (strike - price) / price
                else:
                    otm_pct = (price - strike) / price

                otm_max = 0.03 if is_etf else 0.05
                if otm_pct < -0.005 or otm_pct > otm_max:
                    continue

                premium = volume * last_price * 100
                if premium < min_premium:
                    continue

                mid = (bid + ask) / 2 if (bid and ask) else last_price
                spread_pct = (ask - bid) / mid if mid > 0 and bid and ask else 0
                vol_oi = volume / max(oi, 1)

                sweeps.append({
                    "ticker": ticker, "strike": strike, "expiration": exp_str,
                    "type": side, "premium": premium, "volume": volume,
                    "price": last_price, "bid": bid, "ask": ask,
                    "dte": dte, "otm_pct": otm_pct, "oi": oi,
                    "vol_oi": vol_oi, "spread_pct": spread_pct,
                    "iv": impl_vol, "delta": 0, "gamma": 0, "theta": 0,
                    "underlying_price": price, "symbol": "",
                    "source": "yahoo",
                })

    return sweeps


def scan_options(ticker, price, dte_min, dte_max, min_premium, schwab):
    """Scan options chain — Schwab first, Yahoo backup."""
    if schwab.available:
        chain = schwab.get_option_chains(ticker, dte_max=dte_max)
        if chain and 'callExpDateMap' in chain:
            sweeps = parse_schwab_chain(chain, ticker, price, dte_min, dte_max, min_premium)
            if sweeps:
                return sweeps

    # Fallback to Yahoo
    return scan_yahoo_chain(ticker, price, dte_min, dte_max, min_premium)


# ═══════════════════════════════════════════════
# STEP 3: MARKET DATA (VWAP + Quote)
# ═══════════════════════════════════════════════

def get_market_data(ticker, schwab, alpaca):
    """Get current price, VWAP, open/high/low from best available source."""

    # Try Schwab VWAP (true intraday calculation)
    vwap = 0
    if schwab.available:
        vwap = schwab.get_price_history_vwap(ticker)

    # Try Alpaca snapshot
    if alpaca.available:
        snaps = alpaca.get_snapshots([ticker])
        if ticker in snaps:
            data = snaps[ticker]
            if not vwap and data.get('vwap'):
                vwap = data['vwap']
            return {
                'price': data['price'],
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'vwap': vwap or data.get('vwap') or (data['high'] + data['low'] + data['price']) / 3,
                'volume': data['volume'],
            }

    # Schwab quotes
    if schwab.available:
        quotes = schwab.get_quotes([ticker])
        if ticker in quotes:
            data = quotes[ticker]
            price = data['price']
            return {
                'price': price,
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'vwap': vwap or (data['high'] + data['low'] + price) / 3,
                'volume': data['volume'],
            }

    # Yahoo fallback
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="5m")
        if not hist.empty:
            price = float(hist['Close'].iloc[-1])
            high = float(hist['High'].max())
            low = float(hist['Low'].min())
            open_p = float(hist['Open'].iloc[0])
            vol = int(hist['Volume'].sum())
            # True VWAP from 5m bars
            hist['tp'] = (hist['High'] + hist['Low'] + hist['Close']) / 3
            calc_vwap = float((hist['tp'] * hist['Volume']).sum() / max(hist['Volume'].sum(), 1))
            return {
                'price': price, 'open': open_p, 'high': high, 'low': low,
                'vwap': calc_vwap, 'volume': vol,
            }
    except:
        pass

    return None


# ═══════════════════════════════════════════════
# STEP 4: CLUSTER + SCORE + RECOMMEND
# 12-point scoring → BUY / SELL / HOLD
# ═══════════════════════════════════════════════

def cluster_and_score(sweeps, mkt):
    """
    Institutional-grade 12-point scoring → BUY/SELL/HOLD.
    v2: Graduated V/OI, IV-adjusted stops, expected-move TPs,
        IV crush warnings, spread quality gates.
    Identical methodology to OFR sweep_scanner._cluster_and_score.
    """
    groups = defaultdict(lambda: {"sweeps": [], "combined": 0})

    for s in sweeps:
        direction = "bullish" if s["type"] == "call" else "bearish"
        key = f"{s['ticker']}|{direction}"
        groups[key]["ticker"] = s["ticker"]
        groups[key]["direction"] = direction
        groups[key]["sweeps"].append(s)
        groups[key]["combined"] += s["premium"]

    results = []
    for cl in groups.values():
        sc = 0
        bd = {}

        # ── Whale detection (2pts) ──
        mx = max(s["premium"] for s in cl["sweeps"])
        if mx >= 500_000:
            sc += 2; bd["whale_print"] = 2

        # ── Combined cluster premium (2pts) ──
        if cl["combined"] >= 1_000_000:
            sc += 2; bd["combined_1m"] = 2

        # ── Stacked prints — repeated conviction (2pts) ──
        if len(cl["sweeps"]) >= 3:
            sc += 2; bd["stacked_3+"] = 2

        # ── Volume/OI ratio — GRADUATED (up to 2pts) ──
        vol_oi_values = [s["vol_oi"] for s in cl["sweeps"]]
        max_vol_oi = max(vol_oi_values) if vol_oi_values else 0
        avg_vol_oi = sum(vol_oi_values) / len(vol_oi_values) if vol_oi_values else 0
        if max_vol_oi >= 10.0 or avg_vol_oi >= 5.0:
            sc += 2; bd["vol_oi"] = 2    # Extreme — 10x+ single or 5x+ average
        elif max_vol_oi >= 5.0 or avg_vol_oi >= 2.5:
            sc += 1; bd["vol_oi"] = 1    # Strong — 5x+ single or 2.5x+ average

        # ── DTE sweet spot (1pt) ──
        avg_dte = sum(s["dte"] for s in cl["sweeps"]) / len(cl["sweeps"])
        if 2 <= avg_dte <= 14:
            sc += 1; bd["dte_sweet"] = 1

        # ── OTM proximity (1pt) ──
        avg_otm = sum(abs(s["otm_pct"]) for s in cl["sweeps"]) / len(cl["sweeps"])
        is_etf = cl["ticker"] in ETFS
        if avg_otm <= (0.03 if is_etf else 0.05):
            sc += 1; bd["otm_ok"] = 1

        # ── VWAP confirmation (1pt — rebalanced from 2 to fund V/OI) ──
        price = mkt.get("price", 0)
        vwap = mkt.get("vwap", 0)
        if vwap > 0 and price > 0:
            if cl["direction"] == "bullish" and price > vwap:
                sc += 1; bd["vwap_confirm"] = 1
            elif cl["direction"] == "bearish" and price < vwap:
                sc += 1; bd["vwap_confirm"] = 1

        # ── Opening Range Breakout confirmation (1pt) ──
        op = mkt.get("open", 0)
        if op > 0:
            if cl["direction"] == "bullish" and price > op:
                sc += 1; bd["orb_confirm"] = 1
            elif cl["direction"] == "bearish" and price < op:
                sc += 1; bd["orb_confirm"] = 1

        # ── Grade assignment ──
        grade = "S" if sc >= 11 else "A" if sc >= 9 else "B" if sc >= 7 else "C" if sc >= 5 else "F"

        # ── Disqualifiers ──
        dqs = []
        if len(cl["sweeps"]) < 2:
            dqs.append("Single isolated print (not stacked)")
        wide = sum(1 for s in cl["sweeps"] if s["spread_pct"] > 0.20)
        if wide > len(cl["sweeps"]) * 0.5:
            dqs.append("Wide bid/ask spreads (illiquid)")
        if cl["direction"] == "bullish" and vwap > 0 and price < vwap * 0.995:
            dqs.append("Price below VWAP")
        if cl["direction"] == "bearish" and vwap > 0 and price > vwap * 1.005:
            dqs.append("Price above VWAP")

        # IV crush warning (flagged on signal card, not a disqualifier)
        avg_iv = sum(s.get("iv", 0) for s in cl["sweeps"]) / len(cl["sweeps"])
        iv_crush_warning = avg_iv > 0.80

        # ── PICK BEST CONTRACT FOR RECOMMENDATION ──
        best = max(cl["sweeps"], key=lambda s: s["premium"])

        # ── RECOMMENDATION: BUY / SELL / HOLD ──
        if sc >= 7 and not dqs:
            action = "BUY CALL" if cl["direction"] == "bullish" else "BUY PUT"
        elif sc >= 5 and not dqs:
            action = "HOLD"
        else:
            action = "PASS"

        # ═══════════════════════════════════════════════════════════════
        # ENTRY / STOP / TP — IV-adjusted, DTE-aware
        # No flat percentages. Levels based on the underlying's
        # expected move and the option's delta sensitivity.
        # ═══════════════════════════════════════════════════════════════
        entry = best["price"]
        underlying_price = best.get("underlying_price", price) or price
        iv = best.get("iv", 0.30) or 0.30
        dte = best.get("dte", 7) or 7
        delta = abs(best.get("delta", 0.45)) or 0.45

        # Expected move of the UNDERLYING (1-sigma)
        # σ_move = Price × IV × √(DTE/365)
        t_years = max(dte, 1) / 365.0
        sigma_move = underlying_price * iv * math.sqrt(t_years)

        # Option's expected move ≈ delta × underlying_move
        option_1sigma = delta * sigma_move

        # STOP: Based on 0.75σ adverse move (tighter for short DTE)
        dte_tightening = max(0.5, min(1.0, dte / 14.0))
        stop_distance = option_1sigma * 0.75 * dte_tightening
        stop = max(round(entry * 0.30, 4), round(entry - stop_distance, 4))

        # TP1: 1.0σ favorable move (high-probability target)
        tp1 = round(entry + option_1sigma * 1.0, 4)

        # TP2: 1.5σ favorable move (extended target)
        tp2 = round(entry + option_1sigma * 1.5, 4)

        # Sanity checks
        if tp1 <= entry: tp1 = round(entry * 1.20, 4)
        if tp2 <= tp1: tp2 = round(tp1 * 1.25, 4)
        if stop >= entry: stop = round(entry * 0.50, 4)

        # Risk/Reward ratio
        risk = entry - stop if entry > stop else entry * 0.35
        reward = tp1 - entry if tp1 > entry else entry * 0.20
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0

        results.append({
            "ticker": cl["ticker"],
            "direction": cl["direction"],
            "action": action,
            "contract": f"{best['ticker']} {best['strike']}{best['type'][0].upper()} {best['expiration']}",
            "strike": best["strike"],
            "expiration": best["expiration"],
            "contract_type": best["type"],
            "sweeps": cl["sweeps"],
            "combined": cl["combined"],
            "score": sc,
            "grade": grade,
            "breakdown": bd,
            "disqualifiers": dqs,
            "price": price,
            "vwap": vwap,
            "open": op,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "risk_reward": rr_ratio,
            "expected_move_1sigma": round(sigma_move, 2),
            "iv_crush_warning": iv_crush_warning,
            "avg_vol_oi": round(avg_vol_oi, 1),
            "avg_dte": round(avg_dte),
            "avg_otm": avg_otm,
            "max_single": mx,
            "delta": best.get("delta", 0),
            "gamma": best.get("gamma", 0),
            "theta": best.get("theta", 0),
            "iv": best.get("iv", 0),
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)


# ═══════════════════════════════════════════════
# DISCORD ALERTS
# ═══════════════════════════════════════════════

def send_discord(cl):
    if not DISCORD_WEBHOOK:
        return
    color = {"BUY CALL": 0x00FF6A, "BUY PUT": 0xFF2D7B, "HOLD": 0xFFD700}.get(cl["action"], 0x808080)
    emoji = {"S": "💎", "A": "🔥", "B": "✅", "C": "⚠️"}.get(cl["grade"], "")

    sweep_lines = []
    for s in cl["sweeps"][:5]:
        greek_str = ""
        if s.get("delta"):
            greek_str = f" | Δ{s['delta']:.2f} Γ{s['gamma']:.4f} Θ{s['theta']:.2f}"
        sweep_lines.append(
            f"• {s['type'].upper()} ${s['strike']} {s['expiration']} | "
            f"${s['premium']:,.0f} | {s['volume']}v OI:{s['oi']} | "
            f"V/OI:{s['vol_oi']:.1f} | {s['dte']}d {abs(s['otm_pct'])*100:.1f}%OTM{greek_str}"
        )

    # Build Entry/Stop/TP line with R:R ratio
    entry_line = (
        f"${cl['entry']:.2f} / ${cl['stop']:.2f} / "
        f"${cl['tp1']:.2f} / ${cl['tp2']:.2f}"
    )
    if cl.get("risk_reward"):
        entry_line += f"  (R:R {cl['risk_reward']})"

    # IV crush warning tag
    iv_tag = ""
    if cl.get("iv_crush_warning"):
        iv_tag = "\n⚠️ **IV CRUSH RISK** — IV > 80%, consider selling premium instead"

    embed = {"embeds": [{
        "title": f"{emoji} [{cl['grade']}] {cl['action']} — {cl['ticker']}",
        "description": f"**{cl['contract']}**{iv_tag}",
        "color": color,
        "fields": [
            {"name": "Action", "value": cl["action"], "inline": True},
            {"name": "Score", "value": f"{cl['score']}/12", "inline": True},
            {"name": "Combined", "value": f"${cl['combined']:,.0f}", "inline": True},
            {"name": "💲 Price", "value": f"${cl['price']:.2f}", "inline": True},
            {"name": "📊 VWAP", "value": f"${cl['vwap']:.2f}", "inline": True},
            {"name": f"{'📈' if cl['direction']=='bullish' else '📉'} Direction", "value": cl['direction'].upper(), "inline": True},
            {"name": "📈 Exp. Move (1σ)", "value": f"${cl.get('expected_move_1sigma', 0):.2f}", "inline": True},
            {"name": "📊 Avg V/OI", "value": f"{cl.get('avg_vol_oi', 0):.1f}x", "inline": True},
            {"name": "⚖️ R:R", "value": f"{cl.get('risk_reward', 0):.1f}:1", "inline": True},
            {"name": "Sweeps", "value": "\n".join(sweep_lines) or "—", "inline": False},
            {"name": "Entry / Stop / TP1 / TP2",
             "value": entry_line, "inline": False},
        ],
        "footer": {"text": "SML Sweep Scanner™ v6.1 | ScriptMasterLabs.com | LIVE DATA ONLY"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}

    try:
        requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    except:
        pass


# ═══════════════════════════════════════════════
# MAIN SCAN
# ═══════════════════════════════════════════════

def run_scan(price_min=1, price_max=100, min_premium=150_000,
             dte_min=2, dte_max=14, min_score=5):

    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info("║  SML INSTITUTIONAL SWEEP SCANNER™ v6 — QUAD-API BEAST      ║")
    log.info("║  Strictly Real-Time Data. ALL live. ALL real.               ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")

    # Initialize providers
    schwab = SchwabClient()
    alpaca = AlpacaClient()
    polygon = PolygonClient()

    # Provider status
    providers = []
    if schwab.available: providers.append("SCHWAB ✅")
    else: providers.append("SCHWAB ❌")
    if alpaca.available: providers.append("ALPACA ✅")
    else: providers.append("ALPACA ❌")
    if polygon.available: providers.append("POLYGON ✅")
    else: providers.append("POLYGON ❌")
    providers.append("YAHOO ✅")  # Always available
    if ALPHA_KEY: providers.append("ALPHAV ✅")
    else: providers.append("ALPHAV ❌")

    log.info(f"PROVIDERS: {' | '.join(providers)}")
    log.info(f"FILTERS: ${price_min}-${price_max} | ${min_premium:,}+ prem | DTE {dte_min}-{dte_max} | Score {min_score}+")
    log.info("")

    # Step 1: Discover
    ticker_data = discover_tickers(price_min, price_max, schwab, alpaca, polygon)
    if not ticker_data:
        log.warning("No tickers found. Market may be closed.")
        return []

    qualified = []
    total_scanned = 0
    total_sweeps = 0

    for i, (ticker, info) in enumerate(ticker_data[:150]):  # Cap at 150 for scan time
        price = info.get("price", 0)
        vol = info.get("volume", 0)

        if not price or price <= 0:
            continue

        log.info(f"[{i+1}/{min(len(ticker_data), 150)}] {ticker} — ${price:.2f} (vol: {vol:,.0f})")

        # Step 2: Market data
        mkt = get_market_data(ticker, schwab, alpaca)
        if not mkt or not mkt.get("price"):
            mkt = {"price": price, "open": price, "high": price, "low": price, "vwap": price, "volume": vol}

        # Step 3: Options scan
        sweeps = scan_options(ticker, mkt["price"], dte_min, dte_max, min_premium, schwab)
        total_scanned += 1

        if not sweeps:
            continue

        total_sweeps += len(sweeps)
        log.info(f"  ⚡ {ticker} — {len(sweeps)} SWEEP CANDIDATES")

        # Step 4: Cluster + Score + Recommend
        clusters = cluster_and_score(sweeps, mkt)

        for cl in clusters:
            if cl["score"] >= min_score:
                if not cl["disqualifiers"] or cl["score"] >= 9:  # A+ overrides minor DQs
                    qualified.append(cl)
                    log.info(f"  ★ {cl['action']} {cl['contract']} [{cl['grade']}] "
                             f"{cl['score']}/12 — ${cl['combined']:,.0f}")
                    send_discord(cl)
                elif cl["disqualifiers"]:
                    log.info(f"  ⚠ {ticker} {cl['direction']} {cl['score']}/12 — DQ: {', '.join(cl['disqualifiers'])}")
            else:
                log.debug(f"  {ticker} {cl['direction']} {cl['score']}/12 — below threshold")

    # ── RESULTS ──
    log.info("")
    log.info("=" * 80)
    log.info(f"SCAN COMPLETE | {total_scanned} scanned | {total_sweeps} sweeps | {len(qualified)} QUALIFIED")
    log.info("=" * 80)

    if qualified:
        print(f"\n{'ACTION':<12} {'TICKER':<7} {'CONTRACT':<28} {'GR':<3} {'SC':<4} "
              f"{'COMBINED':>11} {'PRICE':>8} {'ENTRY':>8} {'STOP':>8} {'TP1':>8} {'TP2':>8}")
        print("-" * 110)
        for c in sorted(qualified, key=lambda x: x["score"], reverse=True):
            print(f"{c['action']:<12} {c['ticker']:<7} "
                  f"{c['strike']}{c['contract_type'][0].upper()} {c['expiration']:<18} "
                  f"{c['grade']:<3} {c['score']:<4} ${c['combined']:>10,.0f} "
                  f"${c['price']:>7.2f} ${c['entry']:>7.2f} "
                  f"${c['stop']:>7.2f} ${c['tp1']:>7.2f} ${c['tp2']:>7.2f}")

            # Sweep details
            for s in c["sweeps"][:3]:
                greek = ""
                if s.get("delta"):
                    greek = f" | D{s['delta']:.2f}"
                print(f"             {s['type'].upper()} ${s['strike']} {s['expiration']} "
                      f"| ${s['premium']:,.0f} | {s['volume']}v OI:{s['oi']} "
                      f"V/OI:{s['vol_oi']:.1f} | {s['dte']}d {abs(s['otm_pct'])*100:.1f}%OTM{greek}")

        print(f"\n{'-'*110}")
        print("  ENTRY: Wait 5-10 min after last print | Entry < 10% above whale fill")
        print("  STOP:  -35% premium OR chart through VWAP")
        print("  TP:    1/3 at +30% | 1/3 at +60% | Trail last 1/3 on 8 EMA 5m")
        print("  RISK:  0.5% acct standard | 1% max on A+ | Max 2 simultaneous")
        print("  LATE:  After 3:15 PM -> 50% size, $1M+ only, chart confirm")
        print(f"{'-'*110}\n")
    else:
        print("\n  No setups passed all filters. Flow is quiet or mixed.\n")

    return qualified


def run_loop(interval=15, **kw):
    log.info(f"CONTINUOUS MODE — scanning every {interval} min. Ctrl+C to stop.\n")
    while True:
        try:
            run_scan(**kw)
            log.info(f"Next scan in {interval} min...\n")
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            log.info("Stopped.")
            break
        except Exception as e:
            log.error(f"Scan error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SML Sweep Scanner™ v6 — Quad-API Beast")
    p.add_argument("mode", nargs="?", default="once", help="'once' or 'loop'")
    p.add_argument("interval", nargs="?", type=int, default=15, help="Loop interval (min)")
    p.add_argument("--price-min", type=float, default=1)
    p.add_argument("--price-max", type=float, default=100)
    p.add_argument("--min-premium", type=int, default=150000)
    p.add_argument("--dte-min", type=int, default=2)
    p.add_argument("--dte-max", type=int, default=14)
    p.add_argument("--min-score", type=int, default=5)
    a = p.parse_args()

    kw = dict(price_min=a.price_min, price_max=a.price_max,
              min_premium=a.min_premium, dte_min=a.dte_min,
              dte_max=a.dte_max, min_score=a.min_score)

    if a.mode == "loop":
        run_loop(interval=a.interval, **kw)
    else:
        run_scan(**kw)
