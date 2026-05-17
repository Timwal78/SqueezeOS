"""
402Proof FastAPI / Flask / WSGI middleware.

FastAPI usage:
    from proof402 import Proof402
    from fastapi import FastAPI, Depends

    app = FastAPI()
    proof = Proof402(endpoint_id="...", server_url="https://402proof.onrender.com")

    @app.get("/premium")
    async def premium(verified=Depends(proof.require_payment)):
        return {"data": "premium content"}

Flask/WSGI usage:
    from proof402 import Proof402Middleware
    app.wsgi_app = Proof402Middleware(
        app.wsgi_app,
        endpoint_id="...",
        server_url="https://...",
        protected_paths=["/premium", "/api/data"],
    )
"""

import json
import urllib.request
import urllib.error
from typing import Optional, List


_VERIFY_PATH = "/v1/token/verify"
_INVOICE_PATH = "/v1/invoice"


def _post_json(url: str, body: dict, timeout: int = 10) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"402Proof server {e.code}: {e.read().decode()}")
    except Exception as e:
        raise RuntimeError(f"402Proof request failed: {e}")


class Proof402:
    """FastAPI dependency injector for 402 payment gating."""

    def __init__(self, endpoint_id: str, server_url: str):
        if not endpoint_id:
            raise ValueError("endpoint_id is required")
        self.endpoint_id = endpoint_id
        self.server_url = server_url.rstrip("/")

    def get_invoice(self) -> dict:
        return _post_json(f"{self.server_url}{_INVOICE_PATH}", {"endpoint_id": self.endpoint_id})

    def verify_token(self, token: str) -> bool:
        try:
            result = _post_json(
                f"{self.server_url}{_VERIFY_PATH}",
                {"token": token, "endpoint_id": self.endpoint_id},
            )
            return result.get("status") == "VALID"
        except Exception:
            return False

    def require_payment(self):
        """FastAPI dependency. Raises HTTP 402 if no valid payment token present."""
        from fastapi import Request, HTTPException

        async def _dep(req: Request):
            token = req.headers.get("x-payment-token")
            if token and self.verify_token(token):
                return {"verified": True, "endpoint_id": self.endpoint_id}
            try:
                inv = self.get_invoice()
            except Exception:
                raise HTTPException(status_code=503, detail="Payment service unavailable")
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Payment Required",
                    "invoice": inv,
                    "instructions": {
                        "step1": f"Send {inv['amount']} {inv['asset']} on XRPL to {inv['pay_to']}",
                        "step2": f"Include MemoData: {inv['memo_hex']} in your XRPL payment",
                        "step3": f"POST {self.server_url}/v1/verify with invoice_id, tx_hash, agent_wallet",
                        "step4": "Retry with header: X-Payment-Token: <token>",
                    },
                },
            )

        return _dep


class Proof402Middleware:
    """WSGI middleware for Flask, Django, or any WSGI application."""

    def __init__(
        self,
        app,
        endpoint_id: str,
        server_url: str,
        protected_paths: Optional[List[str]] = None,
    ):
        self.app = app
        self.proof = Proof402(endpoint_id, server_url)
        self.protected_paths = protected_paths or ["/"]

    def _is_protected(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.protected_paths)

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if not self._is_protected(path):
            return self.app(environ, start_response)

        token = environ.get("HTTP_X_PAYMENT_TOKEN")
        if token and self.proof.verify_token(token):
            return self.app(environ, start_response)

        try:
            inv = self.proof.get_invoice()
        except Exception:
            start_response("503 Service Unavailable", [("Content-Type", "application/json")])
            return [b'{"error":"Payment service unavailable"}']

        body = json.dumps({
            "error": "Payment Required",
            "invoice": inv,
            "instructions": {
                "step1": f"Send {inv['amount']} {inv['asset']} on XRPL to {inv['pay_to']}",
                "step2": f"Include MemoData: {inv['memo_hex']} in your XRPL payment",
                "step3": f"POST {self.proof.server_url}/v1/verify with invoice_id, tx_hash, agent_wallet",
                "step4": "Retry with header: X-Payment-Token: <token>",
            },
        }).encode()

        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("X-Payment-Network", "XRPL"),
            ("X-Payment-Address", inv["pay_to"]),
            ("X-Payment-Amount", inv["amount"]),
            ("X-Payment-Asset", inv["asset"]),
            ("X-Invoice-ID", inv["invoice_id"]),
            ("X-Memo-Hex", inv["memo_hex"]),
            ("X-Verify-URL", f"{self.proof.server_url}/v1/verify"),
        ]
        start_response("402 Payment Required", headers)
        return [body]
