import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request, Response, HTTPException

from .neynar import verify_webhook_signature
from .parser import parse_command, CommandType, MIN_TIP, MAX_TIP
from .registry import (
    init_db, register_wallet, get_wallet_by_fid, get_wallet_by_username,
    get_fid_by_username, record_tip, get_tip_stats,
    get_weekly_leaderboard, get_all_time_leaderboard,
)
from .xrpl_client import (
    check_trust_line, get_rlusd_balance, two_leg_tip, sweep_fees_to_treasury,
    BOT_ADDRESS, BOOST_FEE,
)
from . import caster, bureau

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("tipmaster")

_START_TIME = time.time()
_processed_casts: set[str] = set()
_MAX_DEDUP_CACHE = 2000


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("TipMaster ready")
    yield


app = FastAPI(title="TipMaster", version="2.0.0", lifespan=lifespan)


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
        await register_wallet(sender_fid, sender_username, cmd.wallet_address)
        await caster.reply_to_cast(cast_hash, caster.register_success_text(sender_username, cmd.wallet_address))

    elif cmd.type == CommandType.BALANCE:
        wallet = await get_wallet_by_fid(sender_fid)
        if not wallet:
            await caster.reply_to_cast(cast_hash, caster.balance_no_wallet_text(sender_username))
            return
        balance = await get_rlusd_balance(wallet)
        await caster.reply_to_cast(cast_hash, caster.balance_text(sender_username, wallet, str(balance)))

    elif cmd.type == CommandType.TIP:
        await _handle_tip(cmd, sender_fid, sender_username, cast_hash)


async def _handle_tip(cmd, sender_fid: int, sender_username: str, cast_hash: str) -> None:
    sender_wallet = await get_wallet_by_fid(sender_fid)
    if not sender_wallet:
        await caster.reply_to_cast(cast_hash, caster.tip_no_sender_wallet_text(sender_username))
        return

    recipient_wallet = await get_wallet_by_username(cmd.target_username)
    if not recipient_wallet:
        await caster.reply_to_cast(cast_hash, caster.tip_no_recipient_wallet_text(cmd.target_username))
        return

    if not await check_trust_line(recipient_wallet):
        await caster.reply_to_cast(cast_hash, caster.tip_no_trust_line_text(cmd.target_username))
        return

    amount = Decimal(str(cmd.amount))
    boost = cmd.boost
    total_needed = amount + (BOOST_FEE if boost else Decimal("0"))

    sender_balance = await get_rlusd_balance(sender_wallet)
    if sender_balance < total_needed:
        boost_note = f" (+ {BOOST_FEE} RLUSD boost fee)" if boost else ""
        await caster.reply_to_cast(
            cast_hash,
            f"@{sender_username} Insufficient balance. "
            f"Need {total_needed} RLUSD{boost_note}, have {sender_balance}.",
        )
        return

    ok, tx_hash, err, fee = await two_leg_tip(
        sender_wallet=sender_wallet,
        recipient_wallet=recipient_wallet,
        gross_amount=amount,
        cast_hash=cast_hash,
        boost=boost,
    )

    if ok:
        recipient_fid = await get_fid_by_username(cmd.target_username)
        await record_tip(
            sender_fid=sender_fid,
            sender_user=sender_username,
            recipient_user=cmd.target_username,
            amount=float(amount),
            fee=float(fee),
            boost=boost,
            tx_hash=tx_hash,
            cast_hash=cast_hash,
            recipient_fid=recipient_fid,
        )

        await caster.reply_to_cast(
            cast_hash,
            caster.tip_success_text(
                f"@{sender_username}", f"@{cmd.target_username}",
                float(amount), tx_hash, boost=boost, fee=float(fee),
            ),
        )

        # Fire-and-forget: Credit Bureau push + treasury sweep
        asyncio.create_task(_post_tip_side_effects(sender_wallet, float(amount), sender_fid))

    else:
        log.error("Tip failed: %s", err)
        await caster.reply_to_cast(cast_hash, caster.tip_failed_text(err))


async def _post_tip_side_effects(sender_wallet: str, amount: float, sender_fid: int) -> None:
    """Non-critical background tasks after a successful tip."""
    try:
        stats = await get_tip_stats(sender_fid)
        await bureau.push_tip_activity(sender_wallet, amount, stats["sent_count"])
    except Exception as exc:
        log.debug("Bureau push error: %s", exc)
    try:
        await sweep_fees_to_treasury()
    except Exception as exc:
        log.debug("Sweep error: %s", exc)
