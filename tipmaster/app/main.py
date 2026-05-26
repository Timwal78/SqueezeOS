import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request, Response, HTTPException, Header
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .neynar import verify_webhook_signature
from .parser import parse_command, CommandType, MIN_TIP, MAX_TIP
from .registry import (
    init_db, register_wallet, get_wallet_by_fid, get_wallet_by_username,
    get_fid_by_username, record_tip, get_tip_stats,
    get_weekly_leaderboard, get_all_time_leaderboard,
    get_destination_tag, is_setup_fee_paid, mark_setup_fee_paid
)
from .xrpl_client import (
    check_trust_line, get_rlusd_balance, check_setup_fee_paid,
    generate_p2p_payment_link, generate_setup_fee_link, BOT_ADDRESS, TREASURY_ADDRESS
)
from . import caster, bureau

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("tipmaster")

_START_TIME = time.time()
_processed_casts: set[str] = set()
_MAX_DEDUP_CACHE = 2000

# Safety flag — the custody rebuild has landed. Tipping is enabled by default.
_TIPS_ENABLED = os.getenv("TIPMASTER_TIPS_ENABLED", "true").lower() == "true"


import random

scheduler = AsyncIOScheduler()

MARKETING_COPIES = [
    "🚀 The Web3 Phonebook is live!\n\nStop asking for wallet addresses. Link your Farcaster to your XRPL wallet securely with ZERO custody. Tip anyone directly P2P!\n\nTo register, cast: `@tipmaster register <address>`\n\n/xrpl /builders #RLUSD",
    "💸 Want to tip your favorite Farcaster creators but hate middle-men fees?\n\nTipMaster routes tips directly to your XRPL wallet using RLUSD. Zero custody, instant settlement.\n\nCast `@tipmaster register <address>` to begin!\n\n/xrpl /base #Web3",
    "🤖 Attention AI Agent Builders:\n\nTipMaster's Developer API is live. Your AI agents can now resolve Farcaster usernames directly to XRPL wallets for autonomous P2P tipping!\n\nDocs: `/api/resolve/{username}`\n\n/ai /xrpl #AgentEconomy",
    "🏆 Want to climb the tipping leaderboard?\n\nWe are the official non-custodial Web3 Phonebook on Farcaster. Link your wallet and start tipping creators instantly in RLUSD!\n\nCast `@tipmaster register <address>` to start.\n\n/xrpl /crypto"
]

async def scheduled_weekly_broadcast():
    try:
        entries = await get_weekly_leaderboard(10)
        text = caster.leaderboard_text(entries, "this week")
        await caster.publish_cast(text)
        log.info("Successfully published weekly leaderboard auto-post.")
    except Exception as e:
        log.error(f"Failed to publish weekly leaderboard auto-post: {e}")

# Schedule the broadcast every Friday at 17:00 UTC (noon Eastern)
scheduler.add_job(scheduled_weekly_broadcast, 'cron', day_of_week='fri', hour=17, minute=0)

async def scheduled_marketing_broadcast():
    try:
        text = random.choice(MARKETING_COPIES)
        await caster.publish_cast(text)
        log.info("Successfully published scheduled marketing auto-post.")
    except Exception as e:
        log.error(f"Failed to publish marketing auto-post: {e}")

# Schedule marketing twice a week (Tuesday and Thursday at 14:00 UTC / 10 AM EST)
scheduler.add_job(scheduled_marketing_broadcast, 'cron', day_of_week='tue,thu', hour=14, minute=0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()
    log.info("TipMaster ready, APScheduler started")
    yield


app = FastAPI(title="TipMaster", version="2.0.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def index():
    return RedirectResponse("https://www.scriptmasterlabs.com", status_code=301)

@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    return FileResponse("static/sitemap.xml", media_type="application/xml")

@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return FileResponse("static/robots.txt", media_type="text/plain")

@app.get("/health")
async def health():
    return {"status": "ok"}



@app.get("/api/status")
async def status():
    return {
        "service": "tipmaster",
        "version": "2.0.0",
        "uptime_seconds": int(time.time() - _START_TIME),
        "bot_address": BOT_ADDRESS or "not configured",
        "features": ["fee_collection", "tip_boost", "leaderboard", "credit_bureau", "treasury_sweep"],
    }


@app.get("/api/leaderboard")
async def leaderboard(period: str = "week", limit: int = 10):
    if limit > 25:
        limit = 25
    if period == "alltime":
        entries = await get_all_time_leaderboard(limit)
        label = "all time"
    else:
        entries = await get_weekly_leaderboard(limit)
        label = "this week"
    return {"period": label, "leaderboard": entries}


@app.get("/api/resolve/{username}")
async def api_resolve(username: str):
    # Farcaster usernames are generally lowercase
    wallet = await get_wallet_by_username(username.lower())
    if not wallet:
        raise HTTPException(status_code=404, detail="User has not registered a wallet")
    return {"username": username.lower(), "wallet_address": wallet, "chain": "XRPL"}


@app.get("/api/user/{fid}")
async def api_get_user(fid: int):
    wallet = await get_wallet_by_fid(fid)
    if not wallet:
        raise HTTPException(status_code=404, detail="User has not registered a wallet")
    is_paid = await is_setup_fee_paid(fid)
    return {
        "fid": fid,
        "wallet_address": wallet,
        "is_setup_fee_paid": is_paid
    }


class BroadcastRequest(BaseModel):
    channel_id: str | None = None
    period: str = "week"


@app.post("/api/admin/broadcast-leaderboard")
async def api_broadcast_leaderboard(req: BroadcastRequest, authorization: str = Header(None)):
    expected_secret = os.getenv("TIPMASTER_ADMIN_SECRET")
    if not expected_secret or authorization != f"Bearer {expected_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    if req.period == "alltime":
        entries = await get_all_time_leaderboard(10)
        label = "all time"
    else:
        entries = await get_weekly_leaderboard(10)
        label = "this week"
    
    text = caster.leaderboard_text(entries, label)
    success = await caster.publish_cast(text, channel_id=req.channel_id)
    
    return {"status": "success", "posted": success}


@app.post("/webhook/cast")
async def webhook_cast(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Neynar-Signature")
    if not verify_webhook_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("type") != "cast.created":
        return Response(status_code=204)

    cast_data = payload.get("data", {})
    cast_hash: str = cast_data.get("hash", "")
    if not cast_hash:
        return Response(status_code=204)

    if cast_hash in _processed_casts:
        return Response(status_code=204)
    if len(_processed_casts) > _MAX_DEDUP_CACHE:
        _processed_casts.clear()
    _processed_casts.add(cast_hash)

    author = cast_data.get("author", {})
    sender_fid: int = author.get("fid", 0)
    sender_username: str = author.get("username", "unknown")
    cast_text: str = cast_data.get("text", "")

    bot_fid = int(os.getenv("TIPMASTER_BOT_FID", "0"))
    if sender_fid == bot_fid:
        return Response(status_code=204)

    mentioned_profiles = cast_data.get("mentioned_profiles", [])
    if not any(p.get("fid") == bot_fid for p in mentioned_profiles):
        return Response(status_code=204)

    log.info("Cast %s from @%s: %s", cast_hash[:12], sender_username, cast_text[:80])
    cmd = parse_command(cast_text)

    try:
        await _handle_command(cmd, sender_fid, sender_username, cast_hash)
    except Exception as exc:
        log.exception("Error processing %s: %s", cast_hash[:12], exc)
        try:
            await caster.reply_to_cast(cast_hash, caster.tip_failed_text(str(exc)))
        except Exception:
            pass

    return Response(status_code=200)


async def _handle_command(cmd, sender_fid: int, sender_username: str, cast_hash: str) -> None:
    if cmd.type == CommandType.HELP:
        await caster.reply_to_cast(cast_hash, caster.help_text())

    elif cmd.type == CommandType.LEADERBOARD:
        entries = await get_weekly_leaderboard(10)
        await caster.reply_to_cast(cast_hash, caster.leaderboard_text(entries, "this week"))

    elif cmd.type == CommandType.STATS:
        stats = await get_tip_stats(sender_fid)
        await caster.reply_to_cast(cast_hash, caster.stats_text(sender_username, stats))

    elif cmd.type == CommandType.UNKNOWN:
        if cmd.amount is not None and (cmd.amount < MIN_TIP or cmd.amount > MAX_TIP):
            await caster.reply_to_cast(
                cast_hash, f"Tip amount must be between {MIN_TIP} and {MAX_TIP} RLUSD."
            )
        else:
            await caster.reply_to_cast(cast_hash, caster.unknown_command_text())

    elif cmd.type == CommandType.REGISTER:
        chain = getattr(cmd, "chain", None) or "XRPL"
        dest_tag = await register_wallet(sender_fid, sender_username, cmd.wallet_address, chain)
        fee_link = generate_setup_fee_link(dest_tag)
        await caster.reply_to_cast(
            cast_hash, 
            f"@{sender_username} Wallet saved! To activate P2P tipping, please pay the one-time 15 RLUSD setup fee here: {fee_link} (Then cast `@tipmaster verify`)"
        )

    elif cmd.type == CommandType.VERIFY:
        dest_tag = await get_destination_tag(sender_fid)
        if not dest_tag:
            await caster.reply_to_cast(cast_hash, f"@{sender_username} You need to register a wallet first.")
            return
        already_marked = await is_setup_fee_paid(sender_fid)
        if already_marked:
            await caster.reply_to_cast(cast_hash, f"@{sender_username} Your account is already active! 🎉")
            return
        
        paid = await check_setup_fee_paid(dest_tag)
        if paid:
            await mark_setup_fee_paid(sender_fid)
            await caster.reply_to_cast(cast_hash, f"@{sender_username} Setup fee verified! Your account is now active for unlimited P2P tipping. 🎉")
        else:
            fee_link = generate_setup_fee_link(dest_tag)
            await caster.reply_to_cast(cast_hash, f"@{sender_username} We haven't received your 15 RLUSD setup fee yet. Pay here: {fee_link}")

    elif cmd.type == CommandType.TIP:
        if not _TIPS_ENABLED:
            await caster.reply_to_cast(
                cast_hash,
                f"@{sender_username} Tipping is temporarily disabled while the "
                "deposit/custody flow is being finalized. `register`, `balance`, "
                "`stats`, and `leaderboard` commands still work.",
            )
            return
        await _handle_tip(cmd, sender_fid, sender_username, cast_hash)


async def _handle_tip(cmd, sender_fid: int, sender_username: str, cast_hash: str) -> None:
    if not await is_setup_fee_paid(sender_fid):
        dest_tag = await get_destination_tag(sender_fid)
        if dest_tag:
            fee_link = generate_setup_fee_link(dest_tag)
            msg = f"@{sender_username} You must pay the 15 RLUSD setup fee to tip. Pay here: {fee_link}"
        else:
            msg = f"@{sender_username} You must register and pay the setup fee first. Cast `@tipmaster register <address>`."
        await caster.reply_to_cast(cast_hash, msg)
        return

    recipient_wallet = await get_wallet_by_username(cmd.target_username)
    if not recipient_wallet:
        await caster.reply_to_cast(cast_hash, f"@{sender_username} @{cmd.target_username} hasn't registered a wallet yet! They need to register first.")
        return

    amount = Decimal(str(cmd.amount))
    currency = getattr(cmd, "currency", "RLUSD")

    pay_link = generate_p2p_payment_link(recipient_wallet, amount)

    await caster.reply_to_cast(
        cast_hash,
        f"@{sender_username} Ready to tip @{cmd.target_username} {amount} {currency}! Click here to sign the P2P transaction: {pay_link}"
    )

    # Record tip intent so leaderboard and stats reflect activity.
    # The Xaman link is P2P — payment goes directly on-chain. We record
    # here since there is no callback to confirm completion.
    recipient_fid = await get_fid_by_username(cmd.target_username)
    await record_tip(
        sender_fid=sender_fid,
        sender_user=sender_username,
        recipient_user=cmd.target_username,
        amount=float(amount),
        fee=0.0,
        boost=False,
        tx_hash="",
        cast_hash=cast_hash,
        recipient_fid=recipient_fid,
        currency=currency,
        is_internal=False,
    )
    asyncio.create_task(_post_tip_side_effects(sender_fid, float(amount), sender_fid))
