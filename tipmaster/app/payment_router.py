import os
import httpx
import logging
from decimal import Decimal
from typing import Tuple

log = logging.getLogger("tipmaster.payment_router")

GHOST_LAYER_URL = os.getenv("GHOST_LAYER_URL", "https://ghost-layer.onrender.com")

async def execute_withdrawal(recipient_wallet: str, amount: Decimal, currency: str, chain: str) -> Tuple[bool, str, str]:
    """
    Executes a withdrawal to the user's wallet via the GhostLayer API (or xrpl_client for RLUSD).
    Returns (success, tx_hash, error_msg).
    """
    if currency == "RLUSD" and chain == "XRPL":
        # For MVP, we can still use the local xrpl_client for RLUSD if desired, or route to GhostLayer.
        # Since ghost-layer handles both, let's route to GhostLayer as requested.
        pass

    try:
        payload = {
            "destination": recipient_wallet,
            "amount": float(amount),
            "currency": currency,
            "chain": chain
        }
        # In a real system, add auth headers here
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GHOST_LAYER_URL}/api/v1/withdraw",
                json=payload,
                timeout=30.0
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return True, data.get("tx_hash", "ghost_tx_pending"), ""
            else:
                return False, "", f"GhostLayer API error: {resp.text}"
                
    except Exception as e:
        log.exception("Error calling GhostLayer API")
        return False, "", str(e)
