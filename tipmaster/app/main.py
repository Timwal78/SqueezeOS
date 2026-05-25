import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request, Response, HTTPException
from pydantic import BaseModel

from .neynar import verify_webhook_signature
from .parser import parse_command, CommandType, MIN_TIP, MAX_TIP
from .registry import (
    init_db, register_wallet, get_wallet_by_fid, get_wallet_by_username,
    get_fid_by_username, record_tip, get_tip_stats,
    get_weekly_leaderboard, get_all_time_leaderboard,
    get_internal_balance, record_deposit, get_fid_by_wallet
)
from .xrpl_client import (
    check_trust_line, get_rlusd_balance, execute_custodial_tip, sweep_fees_to_treasury,
    verify_deposit_tx, BOT_ADDRESS, BOOST_FEE,
)
from . import caster, bureau

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("tipmaster")

_START_TIME = time.time()
_processed_casts: set[str] = set()
_MAX_DEDUP_CACHE = 2000

# Safety flag — the custody rebuild has landed. Tipping is enabled by default.
_TIPS_ENABLED = os.getenv("TIPMASTER_TIPS_ENABLED", "true").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("TipMaster ready")
    yield


app = FastAPI(title="TipMaster", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


class DepositWebhookPayload(BaseModel):
    tx_hash: str

@app.post("/webhook/deposit")
async def webhook_deposit(payload: DepositWebhookPayload):
    is_valid, sender_wallet, amount, err = await verify_deposit_tx(payload.tx_hash)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid deposit: {err}")
        
    sender_fid = await get_fid_by_wallet(sender_wallet)
    if not sender_fid:
        raise HTTPException(status_code=400, detail="Wallet not registered to any FID")
        
    inserted = await record_deposit(payload.tx_hash, sender_fid, float(amount))
    if not inserted:
        return {"status": "duplicate"}
        
    return {"status": "success", "credited_fid": sender_fid, "amount": float(amount)}


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
        chain = getattr(cmd, "chain", None) or "XRPL"
        await register_wallet(sender_fid, sender_username, cmd.wallet_address, chain)
        await caster.reply_to_cast(cast_hash, f"@{sender_username} Successfully registered your {chain} wallet: {cmd.wallet_address}")

    elif cmd.type == CommandType.BALANCE:
        currency = getattr(cmd, "currency", "RLUSD")
        int_balance = await get_internal_balance(sender_fid, currency)
        await caster.reply_to_cast(
            cast_hash, 
            f"@{sender_username} Your TipMaster internal balance: {int_balance} {currency}. "
            f"(To cash out to your wallet, cast `@tipmaster withdraw <amount> {currency}`)"
        )
        
    elif cmd.type == CommandType.WITHDRAW:
        await _handle_withdraw(cmd, sender_fid, sender_username, cast_hash)

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


async def _handle_withdraw(cmd, sender_fid: int, sender_username: str, cast_hash: str) -> None:
    currency = getattr(cmd, "currency", "RLUSD")
    chain = "BASE" if currency == "USDC" else "XRPL"
    
    wallet = await get_wallet_by_fid(sender_fid, chain=chain)
    if not wallet:
        await caster.reply_to_cast(
            cast_hash, 
            f"@{sender_username} You don't have a {chain} wallet registered for {currency} withdrawals. "
            f"Cast `@tipmaster register <address>` to set one!"
        )
        return

    amount = Decimal(str(cmd.amount))
    fee = amount * Decimal("0.02")  # 2% cash out fee
    total_deduction = amount + fee
    
    internal_balance = await get_internal_balance(sender_fid, currency)
    if internal_balance < total_deduction:
        await caster.reply_to_cast(
            cast_hash,
            f"@{sender_username} Insufficient internal balance. "
            f"Need {total_deduction} {currency} (includes 2% cash out fee), have {internal_balance}."
        )
        return

    from .payment_router import execute_withdrawal
    ok, tx_hash, err = await execute_withdrawal(wallet, amount, currency, chain)
    
    if ok:
        from .registry import record_withdrawal
        await record_withdrawal(tx_hash, sender_fid, float(total_deduction), currency)
        await caster.reply_to_cast(
            cast_hash,
            f"@{sender_username} Successfully withdrew {amount} {currency} to {wallet[:8]}! "
            f"(Fee: {fee} {currency}) 💸 tx: {tx_hash}"
        )
    else:
        await caster.reply_to_cast(cast_hash, f"@{sender_username} Withdrawal failed: {err}")


async def _handle_tip(cmd, sender_fid: int, sender_username: str, cast_hash: str) -> None:
    recipient_fid = await get_fid_by_username(cmd.target_username)
    # Even if they don't have a wallet, they can receive internal tips!
    amount = Decimal(str(cmd.amount))
    fee = amount * Decimal("0.01")  # 1% tip fee
    net_amount = amount - fee
    currency = getattr(cmd, "currency", "RLUSD")
    boost = cmd.boost
    
    # Internal tips are free, but boost fees still apply
    total_needed = amount + (BOOST_FEE if boost else Decimal("0"))

    internal_balance = await get_internal_balance(sender_fid, currency)
    if internal_balance < total_needed:
        boost_note = f" (+ {BOOST_FEE} {currency} boost fee)" if boost else ""
        await caster.reply_to_cast(
            cast_hash,
            f"@{sender_username} Insufficient internal balance. "
            f"Need {total_needed} {currency}{boost_note}, have {internal_balance}."
        )
        return

    # Record internal tip
    await record_tip(
        sender_fid=sender_fid,
        sender_user=sender_username,
        recipient_user=cmd.target_username,
        amount=float(net_amount),
        fee=float(fee),
        boost=boost,
        tx_hash="internal",
        cast_hash=cast_hash,
        recipient_fid=recipient_fid,
        currency=currency,
        is_internal=True
    )

    boost_msg = "🚀 (Boosted!)" if boost else ""
    await caster.reply_to_cast(
        cast_hash,
        f"@{sender_username} instantly tipped {amount} {currency} to @{cmd.target_username}! "
        f"(They received {net_amount} after 1% fee) 🎉 {boost_msg}"
    )

    # Fire-and-forget: Credit Bureau push (uses RLUSD stats traditionally, but we pass generic amount)
    sender_wallet = await get_wallet_by_fid(sender_fid)
    if sender_wallet:
        asyncio.create_task(_post_tip_side_effects(sender_wallet, float(amount), sender_fid))


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
