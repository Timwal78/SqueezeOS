# 06 — XAH Portal (Unified Xahau + XRPL Gateway)

**Live URL:** https://xah-portal.onrender.com
**Deploy:** Render (cloud, 24/7)

---

## What It Does
Unified gateway for all Xahau and XRPL operations across the stack. Single entry point for agents that need to interact with both chains without knowing which sub-service handles which operation. Routes to Ghost Layer (bridge, hooks, notary) and 402Proof (invoices, verification).

## Key Role
- Abstracts XRPL + Xahau chain operations behind a single URL
- Useful for agents that want one endpoint for all on-chain interactions
- Reduces integration surface for external consumers

## Links To
- **Ghost Layer [02]** — primary backend (bridge, stealth, hooks, notary, marketplace)
- **402Proof [03]** — payment verification backend
- **Xahau mainnet** — URITokenMint, Hook parameters (NetworkID=21337)
- **XRPL mainnet** — RLUSD payments, escrow
