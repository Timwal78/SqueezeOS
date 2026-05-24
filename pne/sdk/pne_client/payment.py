"""Payment adapters for the PNE SDK.

Each adapter knows how to pay a BOLT11 invoice (or equivalent) and return
the payment preimage as a hex string.

Payment rails:
  - xrpl      → RLUSD on XRP Ledger (native to SqueezeOS ecosystem)
  - usdc       → USDC on Base L2 (ERC-20, contract 0x833589...8f4c7C)
  - lightning  → BTC via LND gRPC
  - dev        → Local dev/sandbox (no real payments, deterministic output)
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod

from .exceptions import PaymentError

# USDC on Base mainnet — Coinbase canonical deployment
USDC_BASE_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_BASE_CHAIN_ID = 8453

# RLUSD issuer on XRPL mainnet
RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"


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


class DevAdapter(PaymentAdapter):
    """
    Local development / sandbox adapter.
    Produces deterministic output — sends NO real payments.
    Replace with XRPLAdapter or USDCAdapter before going to production.
    """

    def __init__(self, wallet: str = "dev_agent"):
        self._wallet = wallet

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        return hashlib.sha256(invoice.encode()).hexdigest()

    @property
    def wallet_address(self) -> str:
        return self._wallet


class XRPLAdapter(PaymentAdapter):
    """
    XRPL payment adapter — pays in RLUSD on the XRP Ledger.
    Native to the SqueezeOS / 402Proof ecosystem.
    Revenue lands in your XRPL wallet instantly, no intermediaries.
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

            # 1 sat ≈ 0.00001 RLUSD
            rlusd_amount = str(round((amount_sats or 100) * 0.00001, 6))

            network_url = (
                "https://s1.ripple.com:51234"
                if self._network == "mainnet"
                else "https://s.altnet.rippletest.net:51234"
            )

            wallet = Wallet.from_seed(self._seed)
            async with AsyncJsonRpcClient(network_url) as client:
                dest = self._extract_destination(invoice)
                tx = Payment(
                    account=wallet.address,
                    destination=dest,
                    amount={
                        "currency": "USD",
                        "issuer": RLUSD_ISSUER,
                        "value": rlusd_amount,
                    },
                    memos=[{"memo": {"memo_data": invoice[:40].encode().hex()}}],
                )
                result = await submit_and_wait(tx, client, wallet)
                if result.result.get("meta", {}).get("TransactionResult") != "tesSUCCESS":
                    raise PaymentError(f"XRPL payment failed: {result.result}")
                return result.result.get("hash", "")

        except ImportError:
            raise PaymentError("xrpl-py not installed. Run: pip install xrpl-py")
        except Exception as e:
            raise PaymentError(f"XRPL payment failed: {e}") from e

    def _extract_destination(self, invoice: str) -> str:
        return os.environ.get("PNE_GATEWAY_XRPL_WALLET", "rPNEGateway1111111111111111111111111")

    @property
    def wallet_address(self) -> str:
        return self._address


class USDCAdapter(PaymentAdapter):
    """
    USDC on Base L2 payment adapter (ERC-20).
    Contract: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 (Base mainnet)
    Ghost Layer bridges your USDC payment to RLUSD for the SqueezeOS ecosystem.

    Requires: pip install web3
    Set env: BASE_RPC_URL, ETH_PRIVATE_KEY, ETH_WALLET_ADDRESS
    """

    def __init__(
        self,
        private_key: str,
        wallet_address: str,
        rpc_url: str = "https://mainnet.base.org",
        gateway_usdc_address: str | None = None,
    ):
        self._private_key = private_key
        self._address = wallet_address
        self._rpc_url = rpc_url
        # Where to send USDC — PNE gateway's Base L2 wallet
        self._gateway_address = gateway_usdc_address or os.environ.get(
            "PNE_GATEWAY_BASE_WALLET", ""
        )

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        try:
            from web3 import AsyncWeb3
            from web3.middleware import async_geth_poa_middleware

            # USDC has 6 decimals. 100 sats ≈ $0.001 ≈ 1000 USDC micro-units
            usdc_amount = max(1000, (amount_sats or 100) * 10)

            w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self._rpc_url))
            await w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)

            usdc_abi = [
                {
                    "name": "transfer",
                    "type": "function",
                    "inputs": [
                        {"name": "to", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                    ],
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "nonpayable",
                }
            ]

            contract = w3.eth.contract(
                address=AsyncWeb3.to_checksum_address(USDC_BASE_CONTRACT),
                abi=usdc_abi,
            )

            account = w3.eth.account.from_key(self._private_key)
            nonce = await w3.eth.get_transaction_count(account.address)

            tx = await contract.functions.transfer(
                AsyncWeb3.to_checksum_address(self._gateway_address),
                usdc_amount,
            ).build_transaction({
                "chainId": USDC_BASE_CHAIN_ID,
                "gas": 60000,
                "maxFeePerGas": await w3.eth.gas_price,
                "maxPriorityFeePerGas": AsyncWeb3.to_wei(1, "gwei"),
                "nonce": nonce,
            })

            signed = account.sign_transaction(tx)
            tx_hash = await w3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            if receipt.status != 1:
                raise PaymentError("USDC transfer reverted on Base")

            return tx_hash.hex()

        except ImportError:
            raise PaymentError("web3 not installed. Run: pip install pne-client[base]")
        except Exception as e:
            raise PaymentError(f"USDC Base payment failed: {e}") from e

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
    eth_private_key: str | None = None,
    base_rpc_url: str | None = None,
    gateway_base_wallet: str | None = None,
) -> PaymentAdapter:
    match rail.lower():
        case "xrpl" | "rlusd":
            if not wallet_seed or not wallet_address:
                raise ValueError("XRPL rail requires wallet_seed and wallet_address")
            return XRPLAdapter(wallet_seed, wallet_address)
        case "usdc" | "base":
            key = eth_private_key or os.environ.get("ETH_PRIVATE_KEY")
            addr = wallet_address or os.environ.get("ETH_WALLET_ADDRESS")
            if not key or not addr:
                raise ValueError("USDC rail requires eth_private_key and wallet_address")
            return USDCAdapter(
                private_key=key,
                wallet_address=addr,
                rpc_url=base_rpc_url or os.environ.get("BASE_RPC_URL", "https://mainnet.base.org"),
                gateway_usdc_address=gateway_base_wallet,
            )
        case "lightning" | "ln":
            if not lnd_endpoint or not lnd_macaroon:
                raise ValueError("Lightning rail requires lnd_endpoint and lnd_macaroon")
            return LightningAdapter(lnd_endpoint, lnd_macaroon, wallet_address or "")
        case "dev" | _:
            return DevAdapter(wallet_address or "dev_agent")
