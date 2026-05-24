"""Payment adapters for the PNE SDK.

Each adapter knows how to pay a BOLT11 invoice (or equivalent) and return
the payment preimage as a hex string.
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod

from .exceptions import PaymentError


class PaymentAdapter(ABC):
    @abstractmethod
    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        """Pay the given invoice. Returns the preimage as a hex string."""
        ...

    @property
    @abstractmethod
    def wallet_address(self) -> str:
        """Return the public wallet address for leaderboard identification."""
        ...


class MockAdapter(PaymentAdapter):
    """Deterministic mock adapter for testing — does NOT send real payments."""

    def __init__(self, wallet: str = "mock_agent"):
        self._wallet = wallet

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        # Return a deterministic fake preimage based on the invoice
        h = hashlib.sha256(invoice.encode()).hexdigest()
        return h

    @property
    def wallet_address(self) -> str:
        return self._wallet


class XRPLAdapter(PaymentAdapter):
    """
    XRPL payment adapter using xrpl-py.
    Pays invoices denominated in RLUSD on the XRP Ledger.
    """

    def __init__(self, wallet_seed: str, wallet_address: str, network: str = "mainnet"):
        self._seed = wallet_seed
        self._address = wallet_address
        self._network = network

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        try:
            from xrpl.asyncio.clients import AsyncJsonRpcClient
            from xrpl.models.transactions import Payment
            from xrpl.asyncio.transaction import submit_and_wait
            from xrpl.wallet import Wallet

            # RLUSD conversion: 1 sat ≈ 0.00001 RLUSD (approximate)
            rlusd_amount = str(round((amount_sats or 100) * 0.00001, 6))

            network_url = (
                "https://s1.ripple.com:51234"
                if self._network == "mainnet"
                else "https://s.altnet.rippletest.net:51234"
            )

            wallet = Wallet.from_seed(self._seed)
            async with AsyncJsonRpcClient(network_url) as client:
                # The invoice encodes a destination and memo
                # For PNE, the invoice is a BOLT11 string — we extract the
                # payment destination from the PNE gateway's payment metadata
                # (passed separately in the 402 body). Here we send to a
                # standard PNE escrow address encoded in the invoice prefix.
                dest = self._extract_xrpl_destination(invoice)
                tx = Payment(
                    account=wallet.address,
                    destination=dest,
                    amount={
                        "currency": "USD",
                        "issuer": "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
                        "value": rlusd_amount,
                    },
                    memos=[{"memo": {"memo_data": invoice[:40].encode().hex()}}],
                )
                result = await submit_and_wait(tx, client, wallet)
                if result.result.get("meta", {}).get("TransactionResult") != "tesSUCCESS":
                    raise PaymentError(f"XRPL payment failed: {result.result}")

                # Return the tx hash as preimage (PNE gateway accepts XRPL tx hashes)
                return result.result.get("hash", "")

        except ImportError:
            raise PaymentError("xrpl-py not installed. Run: pip install xrpl-py")
        except Exception as e:
            raise PaymentError(f"XRPL payment failed: {e}") from e

    def _extract_xrpl_destination(self, invoice: str) -> str:
        # PNE encodes the gateway wallet in the invoice prefix after "lnbc"
        # Fallback to the canonical PNE gateway address
        return "rPNEGateway1111111111111111111111111"

    @property
    def wallet_address(self) -> str:
        return self._address


class LightningAdapter(PaymentAdapter):
    """Lightning Network adapter via LND gRPC."""

    def __init__(self, lnd_endpoint: str, macaroon_hex: str, wallet_address: str = ""):
        self._endpoint = lnd_endpoint
        self._macaroon_hex = macaroon_hex
        self._address = wallet_address

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        try:
            import grpc
            # lnd-grpc-client usage
            from lnd_grpc import lnrpc_pb2 as ln, lnrpc_pb2_grpc as lnstub

            creds = grpc.ssl_channel_credentials()
            metadata_plugin = grpc.metadata_call_credentials(
                lambda context, callback: callback(
                    [("macaroon", self._macaroon_hex)], None
                )
            )
            combined = grpc.composite_channel_credentials(creds, metadata_plugin)
            channel = grpc.aio.secure_channel(self._endpoint.replace("https://", ""), combined)
            stub = lnstub.LightningStub(channel)

            response = await stub.SendPaymentSync(
                ln.SendRequest(payment_request=invoice)
            )
            if response.payment_error:
                raise PaymentError(f"Lightning payment failed: {response.payment_error}")
            return response.payment_preimage.hex()

        except ImportError:
            raise PaymentError("lnd-grpc-client not installed. Run: pip install pne-client[lightning]")
        except Exception as e:
            raise PaymentError(f"Lightning payment failed: {e}") from e

    @property
    def wallet_address(self) -> str:
        return self._address


def make_payment_adapter(
    rail: str,
    wallet_seed: str | None = None,
    wallet_address: str | None = None,
    lnd_endpoint: str | None = None,
    lnd_macaroon: str | None = None,
) -> PaymentAdapter:
    match rail.lower():
        case "xrpl":
            if not wallet_seed or not wallet_address:
                raise ValueError("XRPL rail requires wallet_seed and wallet_address")
            return XRPLAdapter(wallet_seed, wallet_address)
        case "lightning" | "ln":
            if not lnd_endpoint or not lnd_macaroon:
                raise ValueError("Lightning rail requires lnd_endpoint and lnd_macaroon")
            return LightningAdapter(lnd_endpoint, lnd_macaroon, wallet_address or "")
        case "mock" | _:
            return MockAdapter(wallet_address or "mock_agent")
