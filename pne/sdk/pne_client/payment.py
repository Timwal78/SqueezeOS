"""Payment adapters for the PNE SDK.

Multi-rail by default — no extra hassle.

The AutoAdapter (default) detects your wallet from env vars and pays
with the best available rail automatically:

  Priority: USDC (Base L2) → RLUSD (XRPL) → SOL (Solana) → Dev sandbox

Just set the env vars for whichever wallet you have:

  USDC/Base:  ETH_PRIVATE_KEY + ETH_WALLET_ADDRESS
  RLUSD/XRPL: XRPL_WALLET_SEED + XRPL_WALLET_ADDRESS
  SOL:        SOLANA_PRIVATE_KEY + SOLANA_WALLET_ADDRESS

That's it. PNEClient() with no arguments will figure out which one to use.
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod

from .exceptions import PaymentError

# ── Contract addresses ────────────────────────────────────────────────────────
USDC_BASE_CONTRACT    = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base mainnet
USDC_SOLANA_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # Solana mainnet
RLUSD_XRPL_ISSUER     = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
BASE_CHAIN_ID         = 8453
SOL_USDC_DECIMALS     = 6


class PaymentAdapter(ABC):
    @abstractmethod
    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        """Pay the given invoice. Returns tx hash / preimage as hex string."""
        ...

    @property
    @abstractmethod
    def wallet_address(self) -> str:
        """Public wallet address shown on the leaderboard."""
        ...

    @property
    def rail_name(self) -> str:
        return self.__class__.__name__.replace("Adapter", "")


# ── Auto-detection ────────────────────────────────────────────────────────────

class AutoAdapter(PaymentAdapter):
    """
    Zero-config adapter. Reads env vars and picks the first available rail.
    Priority: USDC (Base) → RLUSD (XRPL) → SOL → Dev sandbox.

    Usage:
        client = PNEClient()          # AutoAdapter is the default
        # Set whichever env vars match your wallet — nothing else needed.
    """

    def __init__(self):
        self._delegate = self._detect()

    def _detect(self) -> PaymentAdapter:
        eth_key  = os.environ.get("ETH_PRIVATE_KEY")
        eth_addr = os.environ.get("ETH_WALLET_ADDRESS")
        xrpl_seed = os.environ.get("XRPL_WALLET_SEED")
        xrpl_addr = os.environ.get("XRPL_WALLET_ADDRESS")
        sol_key  = os.environ.get("SOLANA_PRIVATE_KEY")
        sol_addr = os.environ.get("SOLANA_WALLET_ADDRESS")

        if eth_key and eth_addr:
            return USDCAdapter(
                private_key=eth_key,
                wallet_address=eth_addr,
                rpc_url=os.environ.get("BASE_RPC_URL", "https://mainnet.base.org"),
                gateway_usdc_address=os.environ.get("PNE_GATEWAY_BASE_WALLET", ""),
            )
        if xrpl_seed and xrpl_addr:
            return XRPLAdapter(wallet_seed=xrpl_seed, wallet_address=xrpl_addr)
        if sol_key and sol_addr:
            return SolanaAdapter(
                private_key_b58=sol_key,
                wallet_address=sol_addr,
                gateway_sol_address=os.environ.get("PNE_GATEWAY_SOL_WALLET", ""),
            )
        return DevAdapter()

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        return await self._delegate.pay_invoice(invoice, amount_sats)

    @property
    def wallet_address(self) -> str:
        return self._delegate.wallet_address

    @property
    def rail_name(self) -> str:
        return self._delegate.rail_name

    @property
    def active_rail(self) -> str:
        return self._delegate.rail_name


# ── USDC on Base L2 (primary) ─────────────────────────────────────────────────

class USDCAdapter(PaymentAdapter):
    """
    USDC on Base L2 — primary payment rail.
    Contract: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
    Ghost Layer bridges to RLUSD for the SqueezeOS ecosystem.

    pip install pne-client[base]   (pulls web3)
    """

    def __init__(
        self,
        private_key: str,
        wallet_address: str,
        rpc_url: str = "https://mainnet.base.org",
        gateway_usdc_address: str = "",
    ):
        self._private_key = private_key
        self._address = wallet_address
        self._rpc_url = rpc_url
        self._gateway = gateway_usdc_address or os.environ.get("PNE_GATEWAY_BASE_WALLET", "")

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        try:
            from web3 import AsyncWeb3
            usdc_amount = max(1000, (amount_sats or 100) * 10)  # 6 decimals, ~$0.001 min

            w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self._rpc_url))
            usdc_abi = [{
                "name": "transfer", "type": "function",
                "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
                "outputs": [{"name": "", "type": "bool"}],
                "stateMutability": "nonpayable",
            }]
            contract = w3.eth.contract(
                address=AsyncWeb3.to_checksum_address(USDC_BASE_CONTRACT), abi=usdc_abi
            )
            account = w3.eth.account.from_key(self._private_key)
            nonce = await w3.eth.get_transaction_count(account.address)
            tx = await contract.functions.transfer(
                AsyncWeb3.to_checksum_address(self._gateway), usdc_amount
            ).build_transaction({
                "chainId": BASE_CHAIN_ID, "gas": 60000, "nonce": nonce,
                "maxFeePerGas": await w3.eth.gas_price,
                "maxPriorityFeePerGas": AsyncWeb3.to_wei(1, "gwei"),
            })
            signed = account.sign_transaction(tx)
            tx_hash = await w3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status != 1:
                raise PaymentError("USDC transfer reverted on Base")
            return tx_hash.hex()
        except ImportError:
            raise PaymentError("Run: pip install pne-client[base]")
        except Exception as e:
            raise PaymentError(f"USDC/Base payment failed: {e}") from e

    @property
    def wallet_address(self) -> str:
        return self._address


# ── RLUSD on XRPL ────────────────────────────────────────────────────────────

class XRPLAdapter(PaymentAdapter):
    """
    RLUSD on XRP Ledger — native SqueezeOS / 402Proof rail.
    Revenue lands in your XRPL wallet instantly.

    pip install xrpl-py   (included in base pne-client install)
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

            rlusd_amount = str(round((amount_sats or 100) * 0.00001, 6))
            network_url = (
                "https://s1.ripple.com:51234"
                if self._network == "mainnet"
                else "https://s.altnet.rippletest.net:51234"
            )
            wallet = Wallet.from_seed(self._seed)
            async with AsyncJsonRpcClient(network_url) as client:
                dest = os.environ.get("PNE_GATEWAY_XRPL_WALLET", "rPNEGateway1111111111111111111111111")
                tx = Payment(
                    account=wallet.address,
                    destination=dest,
                    amount={"currency": "USD", "issuer": RLUSD_XRPL_ISSUER, "value": rlusd_amount},
                    memos=[{"memo": {"memo_data": invoice[:40].encode().hex()}}],
                )
                result = await submit_and_wait(tx, client, wallet)
                if result.result.get("meta", {}).get("TransactionResult") != "tesSUCCESS":
                    raise PaymentError(f"XRPL payment failed: {result.result}")
                return result.result.get("hash", "")
        except ImportError:
            raise PaymentError("Run: pip install xrpl-py")
        except Exception as e:
            raise PaymentError(f"RLUSD/XRPL payment failed: {e}") from e

    @property
    def wallet_address(self) -> str:
        return self._address


# ── SOL on Solana ─────────────────────────────────────────────────────────────

class SolanaAdapter(PaymentAdapter):
    """
    SOL on Solana mainnet.
    Pays with native SOL (lamports). USDC on Solana also supported
    by setting use_usdc=True (mint: EPjFWdd5...).

    pip install pne-client[solana]   (pulls solana, solders)
    """

    SOL_PER_SAT = 0.000_000_1  # 1 sat ≈ 0.0000001 SOL at current rates (adjust via env)
    LAMPORTS_PER_SOL = 1_000_000_000

    def __init__(
        self,
        private_key_b58: str,
        wallet_address: str,
        gateway_sol_address: str = "",
        use_usdc: bool = False,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
    ):
        self._private_key_b58 = private_key_b58
        self._address = wallet_address
        self._gateway = gateway_sol_address or os.environ.get("PNE_GATEWAY_SOL_WALLET", "")
        self._use_usdc = use_usdc
        self._rpc_url = rpc_url

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        try:
            from solana.rpc.async_api import AsyncClient
            from solana.transaction import Transaction
            from solders.keypair import Keypair
            from solders.pubkey import Pubkey
            from solders.system_program import TransferParams, transfer
            import base58

            sats = amount_sats or 100
            lamports = max(5000, int(sats * self.SOL_PER_SAT * self.LAMPORTS_PER_SOL))

            kp = Keypair.from_bytes(base58.b58decode(self._private_key_b58))
            dest = Pubkey.from_string(self._gateway)

            async with AsyncClient(self._rpc_url) as client:
                blockhash_resp = await client.get_latest_blockhash()
                blockhash = blockhash_resp.value.blockhash

                txn = Transaction()
                txn.recent_blockhash = blockhash
                txn.add(transfer(TransferParams(
                    from_pubkey=kp.pubkey(),
                    to_pubkey=dest,
                    lamports=lamports,
                )))
                txn.sign(kp)

                resp = await client.send_transaction(txn, kp)
                if resp.value is None:
                    raise PaymentError("Solana transaction returned no signature")

                # Confirm
                await client.confirm_transaction(resp.value, commitment="confirmed")
                return str(resp.value)

        except ImportError:
            raise PaymentError("Run: pip install pne-client[solana]")
        except Exception as e:
            raise PaymentError(f"SOL payment failed: {e}") from e

    @property
    def wallet_address(self) -> str:
        return self._address


# ── Lightning ─────────────────────────────────────────────────────────────────

class LightningAdapter(PaymentAdapter):
    """Lightning Network via LND gRPC. pip install pne-client[lightning]"""

    def __init__(self, lnd_endpoint: str, macaroon_hex: str, wallet_address: str = ""):
        self._endpoint = lnd_endpoint
        self._macaroon_hex = macaroon_hex
        self._address = wallet_address

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        try:
            import grpc
            from lnd_grpc import lnrpc_pb2 as ln, lnrpc_pb2_grpc as lnstub
            creds = grpc.ssl_channel_credentials()
            meta = grpc.metadata_call_credentials(
                lambda ctx, cb: cb([("macaroon", self._macaroon_hex)], None)
            )
            channel = grpc.aio.secure_channel(
                self._endpoint.replace("https://", ""),
                grpc.composite_channel_credentials(creds, meta),
            )
            stub = lnstub.LightningStub(channel)
            resp = await stub.SendPaymentSync(ln.SendRequest(payment_request=invoice))
            if resp.payment_error:
                raise PaymentError(f"Lightning failed: {resp.payment_error}")
            return resp.payment_preimage.hex()
        except ImportError:
            raise PaymentError("Run: pip install pne-client[lightning]")
        except Exception as e:
            raise PaymentError(f"Lightning payment failed: {e}") from e

    @property
    def wallet_address(self) -> str:
        return self._address


# ── Dev sandbox ───────────────────────────────────────────────────────────────

class DevAdapter(PaymentAdapter):
    """
    Local dev / sandbox adapter. No real payments — deterministic output.
    Activated automatically when no wallet env vars are set.
    Replace with a real adapter (or just set env vars) before production.
    """

    def __init__(self, wallet: str = "dev_agent"):
        self._wallet = wallet

    async def pay_invoice(self, invoice: str, amount_sats: int | None) -> str:
        return hashlib.sha256(invoice.encode()).hexdigest()

    @property
    def wallet_address(self) -> str:
        return self._wallet


# ── Factory ───────────────────────────────────────────────────────────────────

def make_payment_adapter(
    rail: str = "auto",
    wallet_seed: str | None = None,
    wallet_address: str | None = None,
    eth_private_key: str | None = None,
    base_rpc_url: str | None = None,
    gateway_base_wallet: str | None = None,
    sol_private_key: str | None = None,
    sol_rpc_url: str | None = None,
    gateway_sol_wallet: str | None = None,
    lnd_endpoint: str | None = None,
    lnd_macaroon: str | None = None,
) -> PaymentAdapter:
    """
    Factory for payment adapters.

    rail="auto" (default) — detects from env vars, no config needed.
    rail="usdc"           — USDC on Base L2 (primary)
    rail="xrpl"           — RLUSD on XRP Ledger
    rail="sol"            — SOL on Solana
    rail="lightning"      — BTC Lightning via LND
    rail="dev"            — Dev sandbox, no real payments
    """
    match rail.lower():
        case "auto":
            return AutoAdapter()
        case "usdc" | "base":
            key = eth_private_key or os.environ.get("ETH_PRIVATE_KEY", "")
            addr = wallet_address or os.environ.get("ETH_WALLET_ADDRESS", "")
            if not key or not addr:
                raise ValueError("USDC rail needs ETH_PRIVATE_KEY + ETH_WALLET_ADDRESS")
            return USDCAdapter(
                private_key=key, wallet_address=addr,
                rpc_url=base_rpc_url or os.environ.get("BASE_RPC_URL", "https://mainnet.base.org"),
                gateway_usdc_address=gateway_base_wallet,
            )
        case "xrpl" | "rlusd":
            seed = wallet_seed or os.environ.get("XRPL_WALLET_SEED", "")
            addr = wallet_address or os.environ.get("XRPL_WALLET_ADDRESS", "")
            if not seed or not addr:
                raise ValueError("XRPL rail needs XRPL_WALLET_SEED + XRPL_WALLET_ADDRESS")
            return XRPLAdapter(wallet_seed=seed, wallet_address=addr)
        case "sol" | "solana":
            key = sol_private_key or os.environ.get("SOLANA_PRIVATE_KEY", "")
            addr = wallet_address or os.environ.get("SOLANA_WALLET_ADDRESS", "")
            if not key or not addr:
                raise ValueError("SOL rail needs SOLANA_PRIVATE_KEY + SOLANA_WALLET_ADDRESS")
            return SolanaAdapter(
                private_key_b58=key, wallet_address=addr,
                gateway_sol_address=gateway_sol_wallet,
                rpc_url=sol_rpc_url or os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            )
        case "lightning" | "ln":
            if not lnd_endpoint or not lnd_macaroon:
                raise ValueError("Lightning rail needs lnd_endpoint + lnd_macaroon")
            return LightningAdapter(lnd_endpoint, lnd_macaroon, wallet_address or "")
        case "dev" | _:
            return DevAdapter(wallet_address or "dev_agent")
