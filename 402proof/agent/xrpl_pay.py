"""
XRPL payment executor for 402Proof agents.
Handles XRP and RLUSD IOU payments with memo binding.
"""

import time
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet
from xrpl.models.transactions import Payment, Memo, MemoField, TrustSet
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import submit_and_wait
from xrpl.utils import xrp_to_drops
from xrpl.models.requests import AccountInfo

XRPL_RPC   = "https://xrplcluster.com"
RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"

def get_client() -> JsonRpcClient:
    return JsonRpcClient(XRPL_RPC)

def wallet_from_seed(seed: str) -> Wallet:
    return Wallet.from_seed(seed)

def new_testnet_wallet() -> Wallet:
    """Generate a funded testnet wallet (for dev/testing only)."""
    from xrpl.clients import JsonRpcClient as J
    tc = J("https://s.altnet.rippletest.net:51234")
    return generate_faucet_wallet(tc, debug=False)

def get_balance_xrp(wallet: Wallet) -> float:
    client = get_client()
    try:
        resp = client.request(AccountInfo(account=wallet.classic_address, ledger_index="validated"))
        drops = int(resp.result["account_data"]["Balance"])
        return drops / 1_000_000
    except Exception:
        return 0.0

def pay_xrp(wallet: Wallet, destination: str, amount_xrp: float, memo_hex: str) -> str:
    """Send XRP payment with memo. Returns tx hash."""
    client = get_client()
    memo = Memo(memo_data=MemoField(memo_hex))
    tx = Payment(
        account=wallet.classic_address,
        destination=destination,
        amount=xrp_to_drops(amount_xrp),
        memos=[memo],
    )
    resp = submit_and_wait(tx, client, wallet)
    if resp.result.get("meta", {}).get("TransactionResult") != "tesSUCCESS":
        raise RuntimeError(f"XRP payment failed: {resp.result.get('meta', {}).get('TransactionResult')}")
    return resp.result["hash"]

def ensure_rlusd_trustline(wallet: Wallet) -> None:
    """Create RLUSD trust line if not already set."""
    client = get_client()
    tx = TrustSet(
        account=wallet.classic_address,
        limit_amount=IssuedCurrencyAmount(
            currency="USD",
            issuer=RLUSD_ISSUER,
            value="1000000",
        ),
    )
    resp = submit_and_wait(tx, client, wallet)
    result = resp.result.get("meta", {}).get("TransactionResult", "")
    if result not in ("tesSUCCESS", "tecNO_CHANGE"):
        raise RuntimeError(f"Trust line failed: {result}")

def pay_rlusd(wallet: Wallet, destination: str, amount: str, memo_hex: str) -> str:
    """Send RLUSD IOU payment with memo. Returns tx hash."""
    client = get_client()
    memo = Memo(memo_data=MemoField(memo_hex))
    tx = Payment(
        account=wallet.classic_address,
        destination=destination,
        amount=IssuedCurrencyAmount(
            currency="USD",
            issuer=RLUSD_ISSUER,
            value=amount,
        ),
        memos=[memo],
    )
    resp = submit_and_wait(tx, client, wallet)
    if resp.result.get("meta", {}).get("TransactionResult") != "tesSUCCESS":
        raise RuntimeError(f"RLUSD payment failed: {resp.result.get('meta', {}).get('TransactionResult')}")
    return resp.result["hash"]

def pay_invoice(wallet: Wallet, invoice: dict) -> str:
    """
    Auto-dispatch: pay XRP or RLUSD based on invoice asset.
    Returns XRPL tx hash.
    """
    asset  = invoice["asset"].upper()
    pay_to = invoice["pay_to"]
    amount = invoice["amount"]
    memo   = invoice["memo_hex"]

    if asset == "XRP":
        return pay_xrp(wallet, pay_to, float(amount), memo)
    elif asset == "RLUSD":
        ensure_rlusd_trustline(wallet)
        return pay_rlusd(wallet, pay_to, amount, memo)
    else:
        raise ValueError(f"Unknown asset: {asset}")
