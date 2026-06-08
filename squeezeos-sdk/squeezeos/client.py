import os
import time
import requests
from typing import Dict, Any, Optional

class SqueezeOSClient:
    """
    SqueezeOS Python SDK
    Supports both traditional API Keys and ECHOLOCK-402 (RLUSD) for autonomous agents.
    """
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://squeezeos-api.onrender.com"):
        self.base_url = base_url.rstrip("/")
        
        # Determine authentication method
        self.api_key = api_key or os.environ.get("SQUEEZEOS_API_KEY")
        self.wallet_seed = os.environ.get("SQUEEZEOS_AGENT_WALLET")
        
        self.session = requests.Session()

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SqueezeOS-Python-SDK/1.0.0"
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        return headers

    def _handle_l402_payment(self, response: requests.Response) -> requests.Response:
        """Handles HTTP 402 Payment Required for autonomous agents."""
        if response.status_code == 402 and self.wallet_seed:
            try:
                import xrpl
                from xrpl.wallet import Wallet
                from xrpl.clients import JsonRpcClient
                from xrpl.models.transactions import Payment
                from xrpl.transaction import submit_and_wait
            except ImportError:
                raise ImportError("Please 'pip install xrpl-py' to use ECHOLOCK-402 autonomous payments.")

            l402_data = response.json().get('l402', {})
            destination = l402_data.get('destination')
            amount_drops = l402_data.get('amount_drops')
            payment_token = l402_data.get('payment_token')

            if not all([destination, amount_drops, payment_token]):
                raise ValueError("Invalid L402 challenge from server.")

            # Submit XRPL Payment
            client = JsonRpcClient("https://s.altnet.rippletest.net:51234/")
            wallet = Wallet.from_seed(self.wallet_seed)
            
            pay_tx = Payment(
                account=wallet.classic_address,
                amount=str(amount_drops),
                destination=destination
            )
            reply = submit_and_wait(pay_tx, client, wallet)
            tx_hash = reply.result.get('hash')

            # Retry original request with proof of payment
            req = response.request
            req.headers["X-XRPL-TxHash"] = tx_hash
            req.headers["X-Payment-Token"] = payment_token
            
            time.sleep(1) # Allow ledger to settle
            return self.session.send(req)
        
        return response

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        kwargs['headers'] = self._get_headers()
        
        response = self.session.request(method, url, **kwargs)
        
        # Intercept L402 challenge if applicable
        if response.status_code == 402:
            response = self._handle_l402_payment(response)

        response.raise_for_status()
        return response.json()

    # --- Endpoints ---

    def analyze(self, ticker: str, mode: str = "matrix") -> Dict[str, Any]:
        """Run the multi-engine SqueezeOS convergence scanner on a ticker."""
        return self._request("POST", "/api/stigmergy/analyze", json={"ticker": ticker, "mode": mode})

    def options_flow(self, ticker: str) -> Dict[str, Any]:
        """Fetch institutional options flow and gamma regimes."""
        return self._request("GET", f"/api/stigmergy/options/{ticker}")

    def convergence_scan(self) -> Dict[str, Any]:
        """Triggers a full market convergence scan (Matrix)."""
        return self._request("POST", "/api/stigmergy/scan")
