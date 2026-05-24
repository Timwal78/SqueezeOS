import os
import logging
import httpx

log = logging.getLogger("tipmaster.bureau")

PROOF402_BASE = os.getenv("PROOF402_BASE_URL", "https://four02proof.onrender.com")


async def push_tip_activity(wallet: str, amount: float, tip_count: int) -> bool:
    """
    Notify 402Proof Agent Credit Bureau that this wallet performed a tip.
    Increases the wallet's bureau score — tipping activity = positive signal.
    Fire-and-forget; caller should not await the result for critical paths.
    """
    if not wallet:
        return False
    try:
        payload = {
            "wallet": wallet,
            "event": "TIP_SENT",
            "amount_rlusd": str(amount),
            "tip_count": tip_count,
            "source": "tipmaster",
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{PROOF402_BASE}/v1/bureau/activity",
                json=payload,
            )
            if resp.status_code in (200, 201, 204):
                log.debug("Bureau activity posted for %s", wallet[:8])
                return True
            log.debug("Bureau activity non-2xx %s for %s", resp.status_code, wallet[:8])
            return False
    except Exception as exc:
        log.debug("Bureau push failed (non-critical): %s", exc)
        return False
