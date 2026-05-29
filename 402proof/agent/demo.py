"""
402Proof Agent Demo — autonomous x402 payment cycle on XRPL.

Runs the full flow:
  1. Load/generate agent wallet
  2. Check XRP balance
  3. Call protected endpoint → receive 402 + invoice
  4. Pay XRPL (XRP or RLUSD) with memo_hex
  5. Verify → receive access_token
  6. Retry with token → get data
  7. Print receipt

Usage:
  AGENT_XRPL_SEED=sXXX python demo.py
  python demo.py --testnet   # generate funded testnet wallet
"""

import os
import sys
import json
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("proof402.demo")

PROOF402_SERVER = "https://four02proof.onrender.com"

# SqueezeOS server hosts the actual protected endpoints.
# Set SQUEEZEOS_URL env var to your Railway deployment URL.
_SQUEEZEOS = os.environ.get(
    "SQUEEZEOS_URL",
    "https://squeezeos-api.onrender.com"
).rstrip("/")

ENDPOINTS = {
    "council": f"{_SQUEEZEOS}/api/council",
    "scan":    f"{_SQUEEZEOS}/api/scan",
    "options": f"{_SQUEEZEOS}/api/options",
    "iwm":     f"{_SQUEEZEOS}/api/iwm",
}


def load_wallet(testnet: bool = False):
    from xrpl_pay import wallet_from_seed, new_testnet_wallet, get_balance_xrp

    seed = os.environ.get("AGENT_XRPL_SEED")
    if seed:
        wallet = wallet_from_seed(seed)
        log.info(f"Loaded wallet: {wallet.classic_address}")
    elif testnet:
        log.info("Generating funded testnet wallet...")
        wallet = new_testnet_wallet()
        log.info(f"Testnet wallet: {wallet.classic_address}  seed={wallet.seed}")
    else:
        log.error("Set AGENT_XRPL_SEED or pass --testnet")
        sys.exit(1)

    balance = get_balance_xrp(wallet)
    log.info(f"Balance: {balance:.6f} XRP")
    if balance < 1.0 and not testnet:
        log.warning("Low XRP balance — payments may fail. Fund: " + wallet.classic_address)

    return wallet


def run_demo(endpoint_name: str, testnet: bool, agent_domain: str):
    from client import Proof402Client

    wallet = load_wallet(testnet)
    client = Proof402Client(wallet, agent_domain=agent_domain, server=PROOF402_SERVER)

    url = ENDPOINTS.get(endpoint_name)
    if not url:
        log.error(f"Unknown endpoint '{endpoint_name}'. Choices: {list(ENDPOINTS)}")
        sys.exit(1)

    log.info(f"Calling {url}")
    log.info("(Will auto-pay any 402 invoice encountered)")

    resp = client.get(url)

    print("\n" + "=" * 60)
    print(f"  Status:  {resp.status_code}")
    print(f"  URL:     {url}")
    print("=" * 60)

    try:
        data = resp.json()
        print(json.dumps(data, indent=2))
    except Exception:
        print(resp.text[:2000])

    if client.receipts:
        print("\n--- Payment Receipts ---")
        for r in client.receipts:
            print(json.dumps(r, indent=2))
    else:
        print("\n(No payments made — token was cached or endpoint was free)")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="402Proof Agent Demo")
    parser.add_argument(
        "--endpoint", "-e",
        default="council",
        choices=list(ENDPOINTS),
        help="Which protected endpoint to call (default: council)",
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Generate a funded testnet wallet (dev only)",
    )
    parser.add_argument(
        "--domain",
        default="demo-agent.scriptmasterlabs.com",
        help="Agent domain for passport identity",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Call all 4 protected endpoints in sequence",
    )
    args = parser.parse_args()

    if args.run_all:
        for name in ENDPOINTS:
            log.info(f"\n{'='*60}\nRunning endpoint: {name}\n{'='*60}")
            run_demo(name, args.testnet, args.domain)
    else:
        run_demo(args.endpoint, args.testnet, args.domain)


if __name__ == "__main__":
    main()
