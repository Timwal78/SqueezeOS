import os
from decimal import Decimal
from typing import Optional, Tuple

from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountLines
from xrpl.models.transactions import Memo, Payment
from xrpl.wallet import Wallet

RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "RLUSD"
XRPL_RPC_URL = os.getenv("XRPL_RPC_URL", "https://xrplcluster.com")

BOT_SEED = os.getenv("TIPMASTER_XRPL_SEED", "")
BOT_ADDRESS = os.getenv("TIPMASTER_XRPL_ADDRESS", "")


def _get_bot_wallet() -> Wallet:
    if not BOT_SEED:
        raise RuntimeError("TIPMASTER_XRPL_SEED is not set")
    return Wallet.from_seed(BOT_SEED)


def _make_client() -> AsyncJsonRpcClient:
    return AsyncJsonRpcClient(XRPL_RPC_URL)


async def check_trust_line(address: str) -> bool:
    client = _make_client()
    req = AccountLines(account=address)
    resp = await client.request(req)
    lines = resp.result.get("lines", [])
    for line in lines:
        if (
            line.get("account") == RLUSD_ISSUER
            and line.get("currency") == RLUSD_CURRENCY
        ):
            return True
    return False


async def get_rlusd_balance(address: str) -> Decimal:
    client = _make_client()
    req = AccountLines(account=address)
    resp = await client.request(req)
    lines = resp.result.get("lines", [])
    for line in lines:
        if (
            line.get("account") == RLUSD_ISSUER
            and line.get("currency") == RLUSD_CURRENCY
        ):
            return Decimal(line["balance"])
    return Decimal("0")


async def send_rlusd(
    destination: str,
    amount: Decimal,
    memo: Optional[str] = None,
) -> Tuple[bool, str]:
    client = _make_client()
    try:
        wallet = _get_bot_wallet()

        payment_amount = IssuedCurrencyAmount(
            currency=RLUSD_CURRENCY,
            issuer=RLUSD_ISSUER,
            value=str(amount),
        )

        tx_kwargs: dict = {
            "account": wallet.address,
            "destination": destination,
            "amount": payment_amount,
        }

        if memo:
            memo_hex = memo.encode("utf-8").hex().upper()
            tx_kwargs["memos"] = [Memo(memo_data=memo_hex)]

        tx = Payment(**tx_kwargs)
        response = await submit_and_wait(tx, client, wallet)

        meta = response.result.get("meta", {})
        tx_result = meta.get("TransactionResult", "")

        if tx_result == "tesSUCCESS":
            tx_hash = response.result.get("hash", "")
            return True, tx_hash
        else:
            return False, f"XRPL error: {tx_result}"

    except Exception as exc:
        return False, str(exc)


async def two_leg_tip(
    sender_wallet: str,
    recipient_wallet: str,
    amount: Decimal,
    cast_hash: str,
) -> Tuple[bool, str, str]:
    memo = f"TipMaster:{cast_hash[:16]}"

    ok1, result1 = await send_rlusd(
        destination=BOT_ADDRESS,
        amount=amount,
        memo=memo + ":leg1",
    )
    if not ok1:
        return False, "", f"Leg 1 (sender→bot) failed: {result1}"

    ok2, result2 = await send_rlusd(
        destination=recipient_wallet,
        amount=amount,
        memo=memo + ":leg2",
    )
    if not ok2:
        return False, result1, f"Leg 2 (bot→recipient) failed: {result2}"

    return True, result2, ""
