"""L402 protocol parser — no payment logic, just header parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class L402Challenge:
    invoice: str
    macaroon: str
    payment_hash: str | None
    amount_sats: int | None
    expires_at: int | None

    @classmethod
    def from_response(cls, headers: dict, body: dict | None = None) -> "L402Challenge":
        www_auth = headers.get("www-authenticate", "")
        invoice = _extract_quoted(www_auth, "invoice") or ""
        macaroon = _extract_quoted(www_auth, "macaroon") or ""

        amount_sats = None
        payment_hash = None
        expires_at = None

        if body:
            amount_sats = body.get("amount_sats")
            payment_hash = body.get("payment_hash")
            expires_at = body.get("expires_at")

        return cls(
            invoice=invoice,
            macaroon=macaroon,
            payment_hash=payment_hash,
            amount_sats=amount_sats,
            expires_at=expires_at,
        )

    def is_valid(self) -> bool:
        return bool(self.invoice) and bool(self.macaroon)


def build_auth_header(preimage_hex: str, macaroon_b64: str) -> str:
    return f"L402 {preimage_hex}:{macaroon_b64}"


def _extract_quoted(header: str, key: str) -> str | None:
    pattern = rf'{key}="([^"]*)"'
    match = re.search(pattern, header)
    return match.group(1) if match else None
