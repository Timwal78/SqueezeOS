"""PNEClient — the main SDK entry point.

Handles the full L402 authentication cycle automatically:
  1. Make request → receive 402 → pay invoice → retry with auth
  2. Check auction rank → if above target, increase Grace Tip and retry
  3. Never exceeds max_tip budget
  4. Fires callbacks for observability (never blocks the hot path)
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

from .auction import BiddingStrategy, make_strategy
from .audit import AuditClient
from .exceptions import (
    BudgetExhausted,
    L402Error,
    MaxRetriesExceeded,
    PaymentError,
    UpstreamError,
)
from .l402 import L402Challenge, build_auth_header
from .payment import PaymentAdapter, make_payment_adapter

log = logging.getLogger("pne_client")

DEFAULT_BASE_URL = "https://n-exchequer.io"


class PNEClient:
    """
    Autonomous x402/L402 client for the PNE Sovereign Intent Auction.

    All 402 payment cycles are handled automatically. The client will:
    - Pay the invoice using the configured payment rail
    - Include X-Grace-Tip for auction priority
    - Retry with increasing tips if the target rank is not achieved
    - Never exceed max_tip budget
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        wallet_seed: str | None = None,
        wallet_address: str | None = None,
        max_tip: int = 5000,
        tip_step: int = 500,
        target_rank: int = 1,
        max_retries: int = 3,
        strategy: str = "optimal",
        payment_rail: str = "mock",
        lnd_endpoint: str | None = None,
        lnd_macaroon: str | None = None,
        timeout: float = 30.0,
        on_payment: Callable[[str, int], None] | None = None,
        on_auction_rank: Callable[[int], None] | None = None,
        on_budget_exhausted: Callable[[], None] | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._max_tip = max_tip
        self._tip_step = tip_step
        self._target_rank = target_rank
        self._max_retries = max_retries
        self._timeout = timeout

        self._strategy: BiddingStrategy = make_strategy(strategy)

        self._payment_adapter: PaymentAdapter = make_payment_adapter(
            rail=payment_rail,
            wallet_seed=wallet_seed,
            wallet_address=wallet_address,
            lnd_endpoint=lnd_endpoint,
            lnd_macaroon=lnd_macaroon,
        )

        self._on_payment = on_payment
        self._on_auction_rank = on_auction_rank
        self._on_budget_exhausted = on_budget_exhausted

        self._http = httpx.AsyncClient(timeout=timeout)
        self._audit = AuditClient(self._base, self._http)

        # Cached auth token (preimage:macaroon) — reused until expired
        self._current_token: str | None = None

    @property
    def wallet_address(self) -> str:
        return self._payment_adapter.wallet_address

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._execute("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._execute("POST", path, **kwargs)

    async def _execute(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        initial_tip = self._strategy.initial_tip(self._max_tip)
        return await self._execute_with_l402(method, path, grace_tip=initial_tip, **kwargs)

    async def _execute_with_l402(
        self,
        method: str,
        path: str,
        grace_tip: int = 0,
        _attempt: int = 0,
        **kwargs: Any,
    ) -> httpx.Response:
        if _attempt >= self._max_retries:
            raise MaxRetriesExceeded(f"Exceeded {self._max_retries} retries on {path}")

        headers: dict[str, str] = dict(kwargs.pop("headers", {}))
        headers["X-Agent-Wallet"] = self.wallet_address
        headers["X-PNE-Client"] = "pne-client/1.0.0"
        if grace_tip > 0:
            headers["X-Grace-Tip"] = str(grace_tip)
        if self._current_token:
            headers["Authorization"] = f"L402 {self._current_token}"

        url = f"{self._base}{path}"
        resp = await self._http.request(method, url, headers=headers, **kwargs)

        # ── Payment required ─────────────────────────────────────────────
        if resp.status_code == 402:
            try:
                body = resp.json()
            except Exception:
                body = {}

            challenge = L402Challenge.from_response(dict(resp.headers), body)
            if not challenge.is_valid():
                raise L402Error("CHALLENGE_PARSE_FAILED", "Could not parse L402 challenge")

            log.debug("402 received: invoice=%s...", challenge.invoice[:20])

            try:
                preimage = await self._payment_adapter.pay_invoice(
                    challenge.invoice, challenge.amount_sats
                )
            except PaymentError as e:
                if self._on_budget_exhausted:
                    self._on_budget_exhausted()
                raise

            self._current_token = f"{preimage}:{challenge.macaroon}"

            if self._on_payment:
                self._on_payment(preimage, challenge.amount_sats or 0)

            return await self._execute_with_l402(
                method, path, grace_tip=grace_tip, _attempt=_attempt + 1, **kwargs
            )

        # ── Auth errors — clear token and surface ────────────────────────
        if resp.status_code == 401:
            self._current_token = None
            try:
                data = resp.json()
                code = data.get("error", "UNAUTHORIZED")
                msg = data.get("message", "")
            except Exception:
                code, msg = "UNAUTHORIZED", resp.text[:200]

            if code == "TOKEN_EXPIRED":
                # Re-request invoice on next attempt
                return await self._execute_with_l402(
                    method, path, grace_tip=grace_tip, _attempt=_attempt + 1, **kwargs
                )
            raise L402Error(code, msg)

        # ── Success — check auction rank ──────────────────────────────────
        if resp.status_code == 200:
            rank = self._get_rank(resp)
            if rank is not None:
                self._strategy.record_outcome(rank, grace_tip)
                if self._on_auction_rank:
                    self._on_auction_rank(rank)
                log.debug("Auction rank: %d (target: %d)", rank, self._target_rank)

                if rank > self._target_rank:
                    new_tip = self._strategy.increase_tip(grace_tip, rank, self._max_tip)
                    if new_tip > self._max_tip:
                        if self._on_budget_exhausted:
                            self._on_budget_exhausted()
                        raise BudgetExhausted(
                            f"Rank {rank} achieved but budget exhausted "
                            f"(max_tip={self._max_tip}, needed>{self._max_tip})"
                        )
                    if new_tip > grace_tip:
                        log.debug("Retrying with higher tip: %d → %d sats", grace_tip, new_tip)
                        return await self._execute_with_l402(
                            method, path, grace_tip=new_tip, _attempt=_attempt + 1, **kwargs
                        )

            return resp

        # ── Other errors ──────────────────────────────────────────────────
        if resp.status_code >= 500:
            raise UpstreamError(resp.status_code, resp.text)

        resp.raise_for_status()
        return resp

    def _get_rank(self, resp: httpx.Response) -> int | None:
        rank_header = resp.headers.get("x-auction-rank")
        if rank_header:
            try:
                return int(rank_header)
            except ValueError:
                pass
        return None

    def get_merkle_leaf(self, resp: httpx.Response) -> str | None:
        return resp.headers.get("x-merkle-leaf")

    async def verify_audit(self, auction_id: str) -> bool:
        return await self._audit.verify(auction_id)

    async def auction_book(self) -> dict:
        resp = await self._http.get(f"{self._base}/v1/auction/book")
        resp.raise_for_status()
        return resp.json()

    async def leaderboard(self, period: str = "24h") -> dict:
        resp = await self._http.get(
            f"{self._base}/v1/leaderboard", params={"period": period}
        )
        resp.raise_for_status()
        return resp.json()

    async def status(self) -> dict:
        resp = await self._http.get(f"{self._base}/v1/status")
        resp.raise_for_status()
        return resp.json()

    async def __aenter__(self) -> "PNEClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()
