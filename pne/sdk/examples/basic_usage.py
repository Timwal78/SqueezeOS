"""Basic PNE SDK usage examples."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("example")


async def example_basic():
    """Simplest possible usage — let the SDK handle everything."""
    from pne_client import PNEClient

    async with PNEClient(
        base_url="http://localhost:8402",
        max_tip=5000,
        strategy="optimal",
        # payment_rail="mock" by default — no real payments in dev
    ) as client:
        print("=== Gateway Status ===")
        status = await client.status()
        print(f"  Version: {status['version']}")
        print(f"  Upstream: {status['upstream']}")
        print(f"  Base price: {status['base_price_sats']} sats")

        print("\n=== Market Data (IWM) ===")
        resp = await client.get("/v1/market-data", params={"symbol": "IWM"})
        print(f"  HTTP {resp.status_code}")
        print(f"  Auction Rank: {resp.headers.get('x-auction-rank', 'N/A')}")
        print(f"  Grace Tip Paid: {resp.headers.get('x-grace-tip-paid', '0')} sats")
        print(f"  Merkle Leaf: {resp.headers.get('x-merkle-leaf', 'N/A')[:40]}...")
        print(f"  Data: {resp.json()}")


async def example_aggressive_bidder():
    """Aggressive strategy — always try to be rank 1."""
    from pne_client import PNEClient

    def on_rank(rank: int):
        log.info("Achieved auction rank: %d", rank)

    def on_payment(preimage: str, amount: int):
        log.info("Paid invoice: %d sats (preimage: %s...)", amount, preimage[:8])

    def on_budget_exhausted():
        log.warning("Budget exhausted — could not achieve target rank")

    async with PNEClient(
        base_url="http://localhost:8402",
        max_tip=50_000,       # Will bid up to 50k sats
        target_rank=1,         # Must be rank 1
        strategy="aggressive",
        on_rank=on_rank,
        on_payment=on_payment,
        on_budget_exhausted=on_budget_exhausted,
    ) as client:
        resp = await client.post(
            "/v1/council",
            json={"symbol": "NVDA"},
        )
        print(f"Council verdict: {resp.json()}")
        print(f"Final rank: {resp.headers.get('x-auction-rank')}")


async def example_conservative_budget():
    """Conservative strategy — spend as little as possible."""
    from pne_client import PNEClient, BudgetExhausted, MaxRetriesExceeded

    async with PNEClient(
        base_url="http://localhost:8402",
        max_tip=1000,         # Maximum 1000 sats
        target_rank=3,         # Happy with rank 3
        strategy="conservative",
    ) as client:
        try:
            resp = await client.get(
                "/v1/market-data",
                params={"symbol": "SPY", "fields": "bias,confidence"},
            )
            print(f"Response: {resp.json()}")
        except BudgetExhausted:
            print("Could not reach rank 3 within 1000 sat budget")
        except MaxRetriesExceeded:
            print("Max retries hit — network issue?")


async def example_audit_verification():
    """Verify a past auction using the Merkle proof system."""
    from pne_client import PNEClient, MerkleVerificationError

    async with PNEClient(base_url="http://localhost:8402") as client:
        # First, get a response with an auction ID
        resp = await client.get("/v1/market-data", params={"symbol": "QQQ"})
        merkle_leaf = client.get_merkle_leaf(resp)

        if merkle_leaf:
            print(f"Merkle leaf: {merkle_leaf[:40]}...")
            # Verify against the public Merkle root
            # Note: auction_id comes from request_id — normally tracked by the caller
            # Here we just show the pattern
            root = await client.auction_book()
            print(f"Current auction book: {root}")
        else:
            print("No Merkle leaf in response (auction may not have resolved yet)")


async def example_xrpl_payment():
    """Real XRPL payment — requires wallet credentials in env."""
    import os
    from pne_client import PNEClient

    wallet_seed = os.environ.get("XRPL_WALLET_SEED")
    wallet_address = os.environ.get("XRPL_WALLET_ADDRESS")

    if not wallet_seed or not wallet_address:
        print("Set XRPL_WALLET_SEED and XRPL_WALLET_ADDRESS to test real payments")
        return

    async with PNEClient(
        base_url="https://n-exchequer.io",   # Real production endpoint
        wallet_seed=wallet_seed,
        wallet_address=wallet_address,
        payment_rail="xrpl",
        max_tip=5000,
        strategy="optimal",
    ) as client:
        resp = await client.get("/v1/market-data", params={"symbol": "IWM"})
        print(f"Live response: {resp.json()}")
        print(f"Rank: {resp.headers.get('x-auction-rank')}")


async def main():
    print("PNE SDK Examples\n" + "=" * 40)
    print("\n[1] Basic Usage")
    await example_basic()

    print("\n[2] Aggressive Bidder")
    await example_aggressive_bidder()

    print("\n[3] Conservative Budget")
    await example_conservative_budget()

    print("\n[4] Audit Verification")
    await example_audit_verification()


if __name__ == "__main__":
    asyncio.run(main())
