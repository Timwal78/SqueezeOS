import hashlib
import hmac
import os
from typing import Optional

NEYNAR_WEBHOOK_SECRET = os.getenv("NEYNAR_WEBHOOK_SECRET", "")


def verify_webhook_signature(
    body: bytes,
    signature_header: Optional[str],
    secret: str = NEYNAR_WEBHOOK_SECRET,
) -> bool:
    if not secret:
        return False

    if not signature_header:
        return False

    sig = signature_header.lower()
    if sig.startswith("sha512="):
        sig = sig[len("sha512="):]

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, sig)
