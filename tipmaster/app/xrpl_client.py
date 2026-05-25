import os
import logging
from decimal import Decimal
from typing import Optional, Tuple

from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountLines, AccountInfo, Tx
from xrpl.models.transactions import Memo, Payment
from xrpl.wallet import Wallet

log = logging.getLogger("tipmaster.xrpl")

RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "RLUSD"
XRPL_RPC_URL = os.getenv("XRPL_RPC_URL", "https://xrplcluster.com")

BOT_SEED = os.getenv("TIPMASTER_XRPL_SEED", "")
BOT_ADDRESS = os.getenv("TIPMASTER_XRPL_ADDRESS", "")
TREASURY_ADDRESS = os.getenv("TIPMASTER_TREASURY_ADDRESS", BOT_ADDRESS)

FEE_RATE = Decimal("0.01")      # 1% on every tip
BOOST_FEE = Decimal("0.05")     # extra charge for boosted tips
SWEEP_THRESHOLD = Decimal("1")  # sweep when accumulated fees exceed 1 RLUSD


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
    for line in resp.result.get("lines", []):
        if line.get("account") == RLUSD_ISSUER and line.get("currency") == RLUSD_CURRENCY:
            return True
    return False


async def get_rlusd_balance(address: str) -> Decimal:
    client = _make_client()
    req = AccountLines(account=address)
    resp = await client.request(req)
    for line in resp.result.get("lines", []):
        if line.get("account") == RLUSD_ISSUER and line.get("currency") == RLUSD_CURRENCY:
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
            return True, response.result.get("hash", "")
        return False, f"XRPL error: {tx_result}"
    except Exception as exc:
        return False, str(exc)


async def verify_deposit_tx(tx_hash: str) -> Tuple[bool, str, Decimal, str]:
    """
    Verifies that an XRPL transaction is a successful deposit of RLUSD to the BOT_ADDRESS.
    Returns (is_valid, sender_wallet, amount, error_message).
    """
    client = _make_client()
    try:
        req = Tx(transaction=tx_hash)
        resp = await client.request(req)
        tx = resp.result
        meta = tx.get("meta", {})
        if meta.get("TransactionResult") != "tesSUCCESS":
            return False, "", Decimal("0"), "Transaction failed on ledger"
        
        if tx.get("TransactionType") != "Payment":
            return False, "", Decimal("0"), "Not a Payment transaction"
            
        if tx.get("Destination") != BOT_ADDRESS:
            return False, "", Decimal("0"), f"Destination is not BOT_ADDRESS"
            
        amount_obj = tx.get("Amount")
        if not isinstance(amount_obj, dict):
            return False, "", Decimal("0"), "Amount is not an issued currency"
            
        if amount_obj.get("currency") != RLUSD_CURRENCY or amount_obj.get("issuer") != RLUSD_ISSUER:
            return False, "", Decimal("0"), "Currency is not RLUSD"
            
        amount_val = Decimal(amount_obj.get("value", "0"))
        sender_wallet = tx.get("Account", "")
        return True, sender_wallet, amount_val, ""
    except Exception as exc:
        return False, "", Decimal("0"), str(exc)


async def execute_custodial_tip(
    recipient_wallet: str,
    gross_amount: Decimal,
    cast_hash: str,
    boost: bool = False,
) -> Tuple[bool, str, str, Decimal]:
    """
    Custodial tip execution. Bot deducts from user's internal balance, then sends `net` to recipient.
    Returns (ok, tx_hash, error_message, fee_collected).
    """
    fee = (gross_amount * FEE_RATE).quantize(Decimal("0.000001"))
    net = gross_amount - fee

    memo_base = f"TipMaster:{cast_hash[:16]}"

    ok, tx_hash = await send_rlusd(
        destination=recipient_wallet,
        amount=net,
        memo=memo_base + ":deliver",
    )
    if not ok:
        return False, "", f"Delivery leg failed: {tx_hash}", Decimal("0")

    log.info("Custodial tip settled: gross=%s fee=%s net=%s boost=%s tx=%s", gross_amount, fee, net, boost, tx_hash)
    return True, tx_hash, "", fee


async def sweep_fees_to_treasury() -> Optional[str]:
    """
    Sweep RLUSD from bot gateway wallet to cold treasury when balance exceeds threshold.
    Called in background after every tip — no-op if below threshold or treasury not set.
    """
    if not TREASURY_ADDRESS or TREASURY_ADDRESS == BOT_ADDRESS:
        return None
    try:
        balance = await get_rlusd_balance(BOT_ADDRESS)
        if balance < SWEEP_THRESHOLD:
            return None
        ok, tx_hash = await send_rlusd(
            destination=TREASURY_ADDRESS,
            amount=balance,
            memo="TipMaster:fee_sweep",
        )
        if ok:
            log.info("Fee sweep → treasury %s: %s RLUSD, tx=%s", TREASURY_ADDRESS, balance, tx_hash)
            return tx_hash
        log.warning("Fee sweep failed: %s", tx_hash)
        return None
    except Exception as exc:
        log.warning("Fee sweep exception: %s", exc)
        return None
