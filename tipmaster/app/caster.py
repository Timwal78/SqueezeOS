import os
import httpx
from typing import Optional

NEYNAR_API_KEY = os.getenv("NEYNAR_API_KEY", "")
NEYNAR_BOT_SIGNER_UUID = os.getenv("NEYNAR_BOT_SIGNER_UUID", "")
NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"

XRPL_EXPLORER_BASE = "https://livenet.xrpl.org/transactions"


def tx_url(tx_hash: str) -> str:
    return f"{XRPL_EXPLORER_BASE}/{tx_hash}"


async def reply_to_cast(parent_hash: str, text: str, channel_id: Optional[str] = None) -> bool:
    if not NEYNAR_API_KEY or not NEYNAR_BOT_SIGNER_UUID:
        raise RuntimeError("NEYNAR_API_KEY or NEYNAR_BOT_SIGNER_UUID is not set")
    payload: dict = {
        "signer_uuid": NEYNAR_BOT_SIGNER_UUID,
        "text": text,
        "parent": parent_hash,
    }
    if channel_id:
        payload["channel_id"] = channel_id
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            NEYNAR_CAST_URL,
            json=payload,
            headers={"x-api-key": NEYNAR_API_KEY, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return True


def tip_success_text(
    sender: str,
    recipient: str,
    amount: float,
    tx_hash: str,
    boost: bool = False,
    fee: float = 0.0,
) -> str:
    if boost:
        badge = "💎🚀✨ BOOSTED TIP"
        emoji = "🌟"
    else:
        badge = "✅ Tip sent"
        emoji = "💸"

    fee_line = f"  Platform fee: {fee:.4f} RLUSD\n" if fee > 0 else ""
    return (
        f"{badge}\n"
        f"{emoji} {sender} → {recipient}: {amount} RLUSD\n"
        f"{fee_line}"
        f"🔗 {tx_url(tx_hash)}"
    )


def leaderboard_text(entries: list, period: str = "this week") -> str:
    if not entries:
        return f"No tips recorded {period} yet. Be the first! `@tipmaster 1 @someone`"
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 10
    lines = [f"🏆 Top Tippers — {period}"]
    for entry in entries[:10]:
        medal = medals[entry["rank"] - 1]
        lines.append(
            f"{medal} @{entry['username']} — {entry['volume']:.2f} RLUSD "
            f"({entry['tip_count']} tips)"
        )
    lines.append("\nTip more to climb the board! `@tipmaster 1 @someone`")
    return "\n".join(lines)


def tip_no_sender_wallet_text(sender: str) -> str:
    return (
        f"@{sender} You don't have a wallet registered.\n"
        "Link yours: `@tipmaster register rXXXX...`"
    )


def tip_no_recipient_wallet_text(recipient: str) -> str:
    return (
        f"@{recipient} hasn't registered an XRPL wallet yet.\n"
        "They need: `@tipmaster register rXXXX...`"
    )


def tip_no_trust_line_text(recipient: str) -> str:
    return (
        f"@{recipient}'s wallet needs an RLUSD trust line.\n"
        "Set TrustSet to issuer rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De (currency: RLUSD)."
    )


def tip_failed_text(error: str) -> str:
    return f"❌ Tip failed: {error}"


def register_success_text(username: str, wallet: str) -> str:
    return (
        f"✅ @{username} wallet registered!\n"
        f"Address: {wallet[:8]}...{wallet[-4:]}\n"
        "You can now send and receive RLUSD tips."
    )


def balance_text(username: str, wallet: str, balance: str) -> str:
    return f"💰 @{username}\nWallet: {wallet[:8]}...{wallet[-4:]}\nBalance: {balance} RLUSD"


def balance_no_wallet_text(username: str) -> str:
    return (
        f"@{username} no wallet registered.\n"
        "Link yours: `@tipmaster register rXXXX...`"
    )


def stats_text(username: str, stats: dict) -> str:
    return (
        f"📊 @{username} stats\n"
        f"Sent: {stats['sent_count']} tips ({stats['sent_volume']:.4f} RLUSD)\n"
        f"Received: {stats['received_count']} tips ({stats['received_volume']:.4f} RLUSD)"
    )


def help_text() -> str:
    from .xrpl_client import BOT_ADDRESS
    bot_addr = BOT_ADDRESS if BOT_ADDRESS else "bot wallet"
    return (
        "TipMaster — RLUSD tips on Farcaster ⚡\\n\\n"
        "Commands:\\n"
        "  @tipmaster register rXXX   — link your XRPL wallet\\n"
        f"  Deposit RLUSD to {bot_addr} to fund your balance!\\n"
        "  @tipmaster balance         — check your tipping balance\\n"
        "  @tipmaster 5 @user         — tip 5 RLUSD\\n"
        "  @tipmaster boost 5 @user   — boosted tip (💎 badge + 0.05 RLUSD fee)\\n"
        "  @tipmaster stats           — your tip history\\n"
        "  @tipmaster leaderboard     — top tippers this week\\n"
        "  @tipmaster help            — this message\\n\\n"
        "Min: 0.10 RLUSD · Max: 100 RLUSD · 1% platform fee\\n"
        "Powered by XRPL + 402Proof"
    )


def unknown_command_text() -> str:
    return "I didn't understand that. Try `@tipmaster help` for commands."
