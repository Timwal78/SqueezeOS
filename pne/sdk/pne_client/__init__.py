"""
pne-client — Python SDK for the PNE Sovereign Intent Auction.

Handles the full L402/x402 payment cycle automatically.

Quick start:

    from pne_client import PNEClient

    async with PNEClient(
        base_url="https://n-exchequer.io",
        max_tip=5000,
        strategy="optimal",
    ) as client:
        resp = await client.get("/v1/market-data", params={"symbol": "IWM"})
        print(resp.json())
        print("Auction rank:", client._get_rank(resp))
"""
from .client import PNEClient
from .auction import AggressiveBidder, ConservativeBidder, OptimalBidder, Strategy
from .exceptions import (
    BudgetExhausted,
    L402Error,
    MaxRetriesExceeded,
    MerkleVerificationError,
    PaymentError,
    PNEError,
    UpstreamError,
)
from .payment import XRPLAdapter, USDCAdapter, LightningAdapter, DevAdapter

__all__ = [
    "PNEClient",
    "AggressiveBidder",
    "ConservativeBidder",
    "OptimalBidder",
    "Strategy",
    "PNEError",
    "BudgetExhausted",
    "L402Error",
    "MaxRetriesExceeded",
    "MerkleVerificationError",
    "PaymentError",
    "UpstreamError",
    "XRPLAdapter",
    "USDCAdapter",
    "LightningAdapter",
    "DevAdapter",
]

__version__ = "1.0.0"
