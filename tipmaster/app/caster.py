import os
import httpx
from typing import Optional

NEYNAR_API_KEY = os.getenv("NEYNAR_API_KEY", "")
NEYNAR_BOT_SIGNER_UUID = os.getenv("NEYNAR_BOT_SIGNER_UUID", "")
NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"

XRPL_EXPLORER_BASE = "https://livenet.xrpl.org/transactions"


def tx_url(tx_hash: str) -> str:
    return f"{XRPL_EXPLORER_BASE}/{tx_hash}"


async def reply_to_cast(
    parent_hash: str,
    text: str,
    channel_id: Optional[str] = None,
) -> bool:
    if not NEYNAR_API_KEY or not NEYNAR_BOT_SIGNER_UUID:
        raise RuntimeError("NEYNAR_API_KEY or NEYNAR_BOT_SIGNER_UUID is not set")

    payload: dict = {
        "signer_uuid": NEYNAR_BOT_SIGNER_UUID,
        "text": text,
        "parent": parent_hash,
    }
    if channel_id:
        payload["channel_id"] = channel_id

    headers = {
        "api_key": NEYNAR_API_KEY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(NEYNAR_CAST_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return True


def tip_success_text(
    sender: str,
    recipient: str,
    amount: float,
    tx_hash: str,
) -> str:
    return (
        f"✅ {sender} tipped {amount} RLUSD to {recipient}\n"
        f"🔗 {tx_url(tx_hash)}"
    )


def tip_no_sender_wallet_text(sender: str) -> str:
    return (
        f"@{sender} You don't have a wallet registered. "
        "Use `@tipmaster register rXXXX...` to link your XRPL wallet."
    )


def tip_no_recipient_wallet_text(recipient: str) -> str:
    return (
        f"@{recipient} hasn't registered a wallet yet. "
        "They need to reply with `@tipmaster register rXXXX...` before receiving tips."
    )


def tip_no_trust_line_text(recipient: str) -> str:
    return (
        f"@{recipient}'s wallet doesn't have a trust line for RLUSD. "
        "They need to set a trust line to rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De "
        "with currency RLUSD before receiving tips."
    )


def tip_failed_text(error: str) -> str:
    return f"❌ Tip failed: {error}"


def register_success_text(username: str, wallet: str) -> str:
    return f"✅ @{username} registered wallet {wallet[:8]}...{wallet[-4:]}"


def balance_text(username: str, wallet: str, balance: str) -> str:
    return f"💰 @{username} — {wallet[:8]}...{wallet[-4:]}: {balance} RLUSD"


def balance_no_wallet_text(username: str) -> str:
    return (
        f"@{username} You don't have a wallet registered. "
        "Use `@tipmaster register rXXXX...` to link your XRPL wallet."
    )


def help_text() -> str:
    return (
        "TipMaster — RLUSD tips on Farcaster\n\n"
        "Commands:\n"
        "  @tipmaster 5 @user — tip 5 RLUSD\n"
        "  @tipmaster tip 5 @user — same\n"
        "  @tipmaster register rXXXX... — link your XRPL wallet\n"
        "  @tipmaster balance — check your RLUSD balance\n"
        "  @tipmaster help — show this message\n\n"
        f"Min: 0.10 RLUSD · Max: 100 RLUSD"
    )


def unknown_command_text() -> str:
    return (
        "I didn't understand that. Try `@tipmaster help` for a list of commands."
    )
