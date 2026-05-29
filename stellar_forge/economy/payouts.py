"""
payouts.py — idempotent RLUSD payout of accrued referral rebates (step 2).

The ledger records what the protocol OWES. This module is how that debt is
actually settled on the XRP Ledger, safely:

  - Each payout records a `paid_through` cursor = the max ledger.id it covers.
    The next payout only sums ledger entries with id > paid_through, so a
    crash or retry can NEVER double-pay. This is the core safety property.
  - A new payout for an account is refused while a prior one is PENDING or
    SUBMITTED (no concurrent in-flight payouts for the same account).
  - The on-chain submitter is injected. The real one (XRPLSubmitter) builds a
    genuine xrpl-py RLUSD Payment and submits it; tests inject a recording
    double. There is NO fake tx-hash generation on the real path — a payout is
    only CONFIRMED when the submitter returns a real validated hash.

Run live only with a funded protocol wallet seed in the environment; default
is dry-run, which records intent but submits nothing and never marks CONFIRMED.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from .store import Store, to_rlusd


class Submitter(Protocol):
    def submit(self, dest_wallet: str, amount_drops: int) -> str:
        """Send the payment; return a validated tx hash. Raise on failure."""
        ...


class DryRunSubmitter:
    """Records intent, submits nothing. Used when no wallet is configured.
    Raises so the runner leaves the payout PENDING rather than faking success."""
    def submit(self, dest_wallet: str, amount_drops: int) -> str:
        raise RuntimeError(
            "DRY_RUN: no protocol wallet configured; payout left PENDING. "
            "Set AGENT_XRPL_SEED + RLUSD_ISSUER and use XRPLSubmitter to send."
        )


class XRPLSubmitter:
    """Real RLUSD (IOU) payment via xrpl-py. Imported lazily so the economy
    layer has no hard xrpl dependency until you actually pay out."""

    def __init__(self, seed: Optional[str] = None, issuer: Optional[str] = None,
                 currency_hex: Optional[str] = None,
                 rpc_url: str = "https://xrplcluster.com") -> None:
        self.seed = seed or os.environ.get("AGENT_XRPL_SEED", "")
        self.issuer = issuer or os.environ.get("RLUSD_ISSUER", "")
        # RLUSD uses a 160-bit hex currency code (>3 chars can't be ISO).
        self.currency = currency_hex or os.environ.get(
            "RLUSD_CURRENCY_HEX", "524C555344000000000000000000000000000000")
        self.rpc_url = rpc_url
        if not self.seed or not self.issuer:
            raise ValueError("XRPLSubmitter requires AGENT_XRPL_SEED and RLUSD_ISSUER")

    def submit(self, dest_wallet: str, amount_drops: int) -> str:
        from xrpl.clients import JsonRpcClient
        from xrpl.wallet import Wallet
        from xrpl.models.transactions import Payment
        from xrpl.models.amounts import IssuedCurrencyAmount
        from xrpl.transaction import submit_and_wait

        client = JsonRpcClient(self.rpc_url)
        wallet = Wallet.from_seed(self.seed)
        amount = IssuedCurrencyAmount(
            currency=self.currency, issuer=self.issuer,
            value=str(to_rlusd(amount_drops)),
        )
        tx = Payment(account=wallet.classic_address, destination=dest_wallet, amount=amount)
        resp = submit_and_wait(tx, client, wallet)
        result = resp.result
        if result.get("validated") and result.get("meta", {}).get(
                "TransactionResult") == "tesSUCCESS":
            return result["hash"]
        raise RuntimeError(f"payout not validated: {result.get('meta')}")


@dataclass
class PayoutResult:
    account: str
    amount_rlusd: float
    state: str
    tx_hash: Optional[str] = None
    reason: Optional[str] = None


class PayoutRunner:
    def __init__(self, store: Store, submitter: Optional[Submitter] = None,
                 eligibility=None, min_payout_drops: int = 10_000) -> None:
        self.store = store
        self.submitter = submitter or DryRunSubmitter()
        self.eligibility = eligibility       # optional EarnEligibility (step 3)
        self.min_payout_drops = min_payout_drops

    def _paid_through(self, account: str) -> int:
        rows = self.store._all(
            "SELECT paid_through FROM payouts WHERE account=? AND state='CONFIRMED' "
            "ORDER BY paid_through DESC LIMIT 1", (account,))
        return int(rows[0]["paid_through"]) if rows else 0

    def _has_inflight(self, account: str) -> bool:
        rows = self.store._all(
            "SELECT 1 AS x FROM payouts WHERE account=? AND state IN ('PENDING','SUBMITTED') "
            "LIMIT 1", (account,))
        return bool(rows)

    def pay(self, account: str, dest_wallet: str) -> PayoutResult:
        # Sybil gate: only withdrawable accounts get paid (step 3).
        if self.eligibility is not None:
            ok, reason = self.eligibility.is_withdrawable(account)
            if not ok:
                return PayoutResult(account, 0.0, "INELIGIBLE", reason=reason)

        if self._has_inflight(account):
            return PayoutResult(account, 0.0, "SKIPPED", reason="payout already in flight")

        paid_through = self._paid_through(account)
        owed, new_cursor = self.store.unpaid_balance(account, paid_through)
        if owed < self.min_payout_drops:
            return PayoutResult(account, to_rlusd(owed), "SKIPPED",
                                reason=f"below min payout ({self.min_payout_drops} drops)")

        # Record a PENDING payout BEFORE submitting (so a crash mid-submit is
        # recoverable and we never lose the cursor).
        now = time.time()
        with self.store._tx() as cur:
            cur.execute(self.store._q(
                "INSERT INTO payouts(account, amount_drops, paid_through, state, "
                "created_at, updated_at) VALUES(?,?,?,'PENDING',?,?)"),
                (account, owed, new_cursor, now, now))

        try:
            tx_hash = self.submitter.submit(dest_wallet, owed)
        except Exception as e:
            with self.store._tx() as cur:
                cur.execute(self.store._q(
                    "UPDATE payouts SET state='FAILED', updated_at=? "
                    "WHERE account=? AND state='PENDING' AND paid_through=?"),
                    (time.time(), account, new_cursor))
            return PayoutResult(account, to_rlusd(owed), "FAILED", reason=str(e))

        with self.store._tx() as cur:
            cur.execute(self.store._q(
                "UPDATE payouts SET state='CONFIRMED', tx_hash=?, updated_at=? "
                "WHERE account=? AND state='PENDING' AND paid_through=?"),
                (tx_hash, time.time(), account, new_cursor))
        return PayoutResult(account, to_rlusd(owed), "CONFIRMED", tx_hash=tx_hash)
