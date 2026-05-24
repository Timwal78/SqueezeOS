import os
import time
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request, Response, HTTPException

from .neynar import verify_webhook_signature
from .parser import parse_command, CommandType
from .registry import init_db, register_wallet, get_wallet_by_fid, get_wallet_by_username
from .xrpl_client import check_trust_line, get_rlusd_balance, send_rlusd, BOT_ADDRESS
from . import caster

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("tipmaster")

_START_TIME = time.time()
_processed_casts: set[str] = set()
_MAX_DEDUP_CACHE = 2000


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("TipMaster ready — DB initialised")
    yield


app = FastAPI(title="TipMaster", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    return {
        "service": "tipmaster",
        "uptime_seconds": int(time.time() - _START_TIME),
        "bot_address": BOT_ADDRESS or "not configured",
        "dedup_cache_size": len(_processed_casts),
    }


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

    event_type = payload.get("type", "")
    if event_type != "cast.created":
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
    is_mention = any(p.get("fid") == bot_fid for p in mentioned_profiles)
    if not is_mention:
        return Response(status_code=204)

    log.info("Processing cast %s from @%s (FID %d): %s", cast_hash[:12], sender_username, sender_fid, cast_text[:80])

    cmd = parse_command(cast_text)

    try:
        await _handle_command(cmd, sender_fid, sender_username, cast_hash, cast_data)
    except Exception as exc:
        log.exception("Unhandled error processing cast %s: %s", cast_hash[:12], exc)
        try:
            await caster.reply_to_cast(cast_hash, caster.tip_failed_text(str(exc)))
        except Exception:
            pass

    return Response(status_code=200)


async def _handle_command(
    cmd,
    sender_fid: int,
    sender_username: str,
    cast_hash: str,
    cast_data: dict,
) -> None:
    if cmd.type == CommandType.HELP or cmd.type == CommandType.UNKNOWN:
        if cmd.type == CommandType.UNKNOWN and cmd.amount is not None:
            amount = cmd.amount
            from .parser import MIN_TIP, MAX_TIP
            if amount < MIN_TIP or amount > MAX_TIP:
                await caster.reply_to_cast(
                    cast_hash,
                    f"Tip amount must be between {MIN_TIP} and {MAX_TIP} RLUSD.",
                )
                return
            await caster.reply_to_cast(cast_hash, caster.unknown_command_text())
            return
        text = caster.help_text() if cmd.type == CommandType.HELP else caster.unknown_command_text()
        await caster.reply_to_cast(cast_hash, text)
        return

    if cmd.type == CommandType.REGISTER:
        wallet = cmd.wallet_address
        await register_wallet(sender_fid, sender_username, wallet)
        log.info("Registered FID %d (@%s) → %s", sender_fid, sender_username, wallet)
        await caster.reply_to_cast(cast_hash, caster.register_success_text(sender_username, wallet))
        return

    if cmd.type == CommandType.BALANCE:
        wallet = await get_wallet_by_fid(sender_fid)
        if not wallet:
            await caster.reply_to_cast(cast_hash, caster.balance_no_wallet_text(sender_username))
            return
        balance = await get_rlusd_balance(wallet)
        await caster.reply_to_cast(
            cast_hash,
            caster.balance_text(sender_username, wallet, str(balance)),
        )
        return

    if cmd.type == CommandType.TIP:
        await _handle_tip(cmd, sender_fid, sender_username, cast_hash, cast_data)
        return


async def _handle_tip(cmd, sender_fid: int, sender_username: str, cast_hash: str, cast_data: dict) -> None:
    sender_wallet = await get_wallet_by_fid(sender_fid)
    if not sender_wallet:
        await caster.reply_to_cast(cast_hash, caster.tip_no_sender_wallet_text(sender_username))
        return

    target_username = cmd.target_username
    recipient_wallet = await get_wallet_by_username(target_username)

    if not recipient_wallet:
        await caster.reply_to_cast(cast_hash, caster.tip_no_recipient_wallet_text(target_username))
        return

    has_trust_line = await check_trust_line(recipient_wallet)
    if not has_trust_line:
        await caster.reply_to_cast(cast_hash, caster.tip_no_trust_line_text(target_username))
        return

    amount = Decimal(str(cmd.amount))

    sender_balance = await get_rlusd_balance(sender_wallet)
    if sender_balance < amount:
        await caster.reply_to_cast(
            cast_hash,
            f"@{sender_username} Insufficient RLUSD balance. You have {sender_balance} RLUSD.",
        )
        return

    log.info(
        "Tip: @%s → @%s, amount %s RLUSD, cast %s",
        sender_username, target_username, amount, cast_hash[:12],
    )

    ok, tx_hash = await send_rlusd(
        destination=recipient_wallet,
        amount=amount,
        memo=f"TipMaster:{cast_hash[:16]}",
    )

    if ok:
        log.info("Tip succeeded, tx_hash=%s", tx_hash)
        await caster.reply_to_cast(
            cast_hash,
            caster.tip_success_text(
                f"@{sender_username}",
                f"@{target_username}",
                float(amount),
                tx_hash,
            ),
        )
    else:
        log.error("Tip failed: %s", tx_hash)
        await caster.reply_to_cast(cast_hash, caster.tip_failed_text(tx_hash))
