import os
import json
import base64
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
from threading import Lock, RLock
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

class SchwabAPI:
    """
    Schwab Individual Trader API Client
    Handles OAuth2 flow and market data requests.
    """
    def __init__(self, client_id=None, client_secret=None, redirect_uri=None):
        self.client_id = client_id or os.environ.get('SCHWAB_CLIENT_ID', 'cOb3GLiEmhfxGyfWUSDvaqqYayNUTVuCexRlzRbSumWvz5I6')
        self.client_secret = client_secret or os.environ.get('SCHWAB_CLIENT_SECRET', 'Uyn7D7MRvYE2TQ88jHNLLiC79p9RH3qB73OJaAEw1A3ElDm5QtgBwSR5Ei1uNX6I')
        self.redirect_uri = redirect_uri or os.environ.get('SCHWAB_REDIRECT_URI', 'https://127.0.0.1:8182/callback')
        
        self.base_url = "https://api.schwabapi.com"
        self.token_file = os.path.join(os.path.dirname(__file__), 'schwab_tokens.json')
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = 0
        self._auth_lock = RLock()
        
        self._load_tokens()

    @property
    def authenticated(self):
        """Check if we have a valid (or refreshable) session."""
        return self._ensure_authenticated()

    def _load_tokens(self):
        """Load tokens from local file if they exist"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    tokens = json.load(f)
                    self.access_token = tokens.get('access_token')
                    self.refresh_token = tokens.get('refresh_token')
                    self.token_expires_at = tokens.get('expires_at', 0)
            except Exception as e:
                logger.error(f"Error loading tokens: {e}")

    def _save_tokens(self, token_data):
        """Save tokens to local file — IRONCLAD safety check"""
        new_at = token_data.get('access_token')
        new_rt = token_data.get('refresh_token')
        
        with self._auth_lock:
            # NEVER save if the source is an error object or missing critical keys
            if not new_at or not new_rt or 'error' in token_data:
                logger.error(f"🛑 REJECTED: Attempted to save invalid token data: {token_data}")
                return False
    
            self.access_token = new_at
            self.refresh_token = new_rt
            expires_in = token_data.get('expires_in', 1800)
            self.token_expires_at = time.time() + expires_in
            
            tokens = {
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'expires_at': self.token_expires_at,
                'updated_at': datetime.now().isoformat()
            }
            
            try:
                tmp_path = self.token_file + '.tmp'
                with open(tmp_path, 'w') as f:
                    json.dump(tokens, f, indent=4)
                os.replace(tmp_path, self.token_file)
                logger.info("📡 Institutional Session Cached Securely")
                return True
            except Exception as e:
                logger.error(f"Error saving tokens: {e}")
                return False

    def get_auth_url(self):
        """Generate the authorization URL for the user to visit"""
        from urllib.parse import quote
        encoded_uri = quote(self.redirect_uri, safe='')
        auth_url = f"{self.base_url}/v1/oauth/authorize?response_type=code&client_id={self.client_id}&redirect_uri={encoded_uri}"
        logger.info(f"🔑 Auth URL generated | client_id: {self.client_id[:6]}... | redirect: {self.redirect_uri}")
        return auth_url

    def exchange_code(self, code):
        """Exchange auth code for access and refresh tokens"""
        from urllib.parse import unquote
        
        # CRITICAL: URL-decode the auth code — Schwab encodes special chars
        # (e.g. %40 for @, %2B for +) in the callback URL
        if code:
            code = unquote(code)
        
        url = f"{self.base_url}/v1/oauth/token"
        
        auth_str = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri
        }
        
        logger.info(f"📡 Exchanging code | redirect_uri: {self.redirect_uri} | code_len: {len(code) if code else 0}")
        
        try:
            response = requests.post(url, headers=headers, data=data, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.error(f"🛑 Token exchange network error: {e}")
            return {"status": "error", "message": f"Network error: {str(e)}"}
        
        if response.status_code == 200:
            token_data = response.json()
            self._save_tokens(token_data)
            logger.info("✅ Schwab OAuth: Token exchange successful")
            return {"status": "success"}
        else:
            err_msg = response.text
            try:
                err_data = response.json()
                err_msg = err_data.get('error_description') or err_data.get('error') or err_msg
            except Exception:
                pass
            logger.error(f"🛑 Token exchange failed [{response.status_code}]: {err_msg}")
            return {"status": "error", "message": err_msg}

    def refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        with self._auth_lock:
            # Double check if another thread already refreshed the token while we waited for the lock
            if self.access_token and time.time() < self.token_expires_at - 60:
                logger.info("🔄 Token already refreshed by another thread")
                return True

            if not self.refresh_token:
                logger.warning("🛑 Cannot refresh: no refresh_token available")
                return False
        
        if not self.client_id or not self.client_secret:
            logger.error("🛑 Cannot refresh: client_id or client_secret missing")
            return False
            
        url = f"{self.base_url}/v1/oauth/token"
        
        auth_str = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }
        
        try:
            response = requests.post(url, headers=headers, data=data, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.error(f"🛑 Token refresh network error: {e}")
            return False
        
        if response.status_code == 200:
            token_data = response.json()
            # Schwab may or may not rotate the refresh_token
            if 'refresh_token' not in token_data:
                token_data['refresh_token'] = self.refresh_token
            self._save_tokens(token_data)
            logger.info("🔄 Schwab token refreshed successfully")
            return True
        elif response.status_code == 401:
            # Refresh token expired — user needs to re-authenticate
            logger.error("🛑 Refresh token EXPIRED — full re-auth required")
            self.access_token = None
            self.token_expires_at = 0
            return False
        else:
            logger.error(f"🛑 Token refresh failed [{response.status_code}]: {response.text}")
            return False

    def _ensure_authenticated(self):
        """Check if access token is valid, refresh if needed"""
        if not self.access_token:
            return False
            
        if time.time() > self.token_expires_at - 60: # 1 minute buffer
            return self.refresh_access_token()
            
        return True

    def get_quotes(self, symbols: List[str], progress_cb=None) -> Dict:
        """Fetch real-time quotes for a list of symbols (Batched 50 at a time)"""
        if not self._ensure_authenticated():
            return {"error": "Not authenticated"}
            
        if not symbols: return {}

        results = {}
        batch_size = 500  # Schwab API documentation recommends max 500 symbols per request — already optimal
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        
        for i in range(0, len(symbols), batch_size):
            batch_num = (i // batch_size) + 1
            batch = symbols[i:i + batch_size]
            if progress_cb:
                progress_cb(f"Schwab Batch: {batch_num}/{total_batches} assets processing...")
            
            symbols_str = ",".join(batch)
            url = f"{self.base_url}/marketdata/v1/quotes?symbols={symbols_str}&fields=quote,fundamental,reference"
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200:
                    batch_data = response.json()
                    results.update(batch_data)
                else:
                    logger.error(f"Error fetching batch: {response.status_code}")
            except Exception as e:
                logger.error(f"Schwab batch exception: {e}")
                
        return results

    def get_option_chains(self, symbol: str, strategy: str = "SINGLE",
                          contract_type: str = "ALL") -> Dict:
        """
        Fetch real-time option chains with Greeks from Schwab.
        Schwab requires: symbol, contractType, fromDate, toDate at minimum.
        """
        if not self._ensure_authenticated():
            return {"error": "Not authenticated"}

        # Date range: today → 90 days out (Schwab rejects missing dates)
        today     = datetime.now().strftime("%Y-%m-%d")
        far_date  = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")

        params = {
            "symbol":       symbol,
            "contractType": contract_type,   # ALL | CALL | PUT
            "strategy":     strategy,
            "fromDate":     today,
            "toDate":       far_date,
            "includeQuotes":"TRUE",
            "range":        "ALL",           # Wide open (all strikes)
        }

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept":        "application/json",
        }

        try:
            response = requests.get(
                f"{self.base_url}/marketdata/v1/chains",
                headers=headers,
                params=params,
                timeout=15,
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error fetching option chains: {response.text}")
                return {"error": response.text}
        except Exception as e:
            logger.error(f"Option chain request exception for {symbol}: {e}")
            return {"error": str(e)}

    def get_price_history(self, symbol: str, period_type: str = "day", period: int = 1, 
                          frequency_type: str = "minute", frequency: int = 1) -> Dict:
        """Fetch price history for a symbol"""
        if not self._ensure_authenticated():
            return {"error": "Not authenticated"}
            
        url = f"{self.base_url}/marketdata/v1/pricehistory?symbol={symbol}&periodType={period_type}&period={period}&frequencyType={frequency_type}&frequency={frequency}"
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error fetching price history: {response.text}")
                return {"error": response.text}
        except Exception as e:
            logger.error(f"Price history exception: {e}")
            return {"error": str(e)}

    # --- ORDER EXECUTION (LIVE) ---

    def get_account_numbers(self) -> List[Dict]:
        """Retrieve account hash values required for order placement."""
        if not self._ensure_authenticated():
            return []
            
        url = f"{self.base_url}/trader/v1/accounts/accountNumbers"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error fetching account numbers: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Account numbers retrieval error: {e}")
            return []

    def get_balances(self) -> List[Dict]:
        """Fetch all account balances and positions."""
        if not self._ensure_authenticated():
            return []
            
        url = f"{self.base_url}/trader/v1/accounts?fields=positions"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error fetching account balances: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Balances retrieval error: {e}")
            return []

    def place_order(self, account_hash: str, order_payload: Dict) -> Dict:
        """Place an order in a specific Schwab account."""
        if not self._ensure_authenticated():
            return {"status": "error", "message": "Not authenticated"}
            
        url = f"{self.base_url}/trader/v1/accounts/{account_hash}/orders"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        try:
            response = requests.post(url, headers=headers, json=order_payload, timeout=15)
            # Schwab returns 201 Created on success, with the order ID in the Location header
            if response.status_code == 201:
                order_id = response.headers.get('Location', '').split('/')[-1]
                logger.info(f"✅ Schwab Order Placed: {order_id}")
                return {"status": "success", "order_id": order_id}
            else:
                try:
                    err_msg = response.json().get('message', response.text)
                except:
                    err_msg = response.text
                logger.error(f"🛑 Schwab Order Failed [{response.status_code}]: {err_msg}")
                return {"status": "error", "message": err_msg, "code": response.status_code}
        except Exception as e:
            logger.error(f"Schwab order exception: {e}")
            return {"status": "error", "message": str(e)}

# Global instance for easy access
schwab_api = SchwabAPI()
