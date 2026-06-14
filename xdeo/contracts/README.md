# xDEO Smart Contracts (Base L2)

> **Status: interface stage.** This directory defines the on-chain surface that
> the backend mirrors. Full implementations, Foundry tests, and an audit are
> Phase 3 work (see the root README roadmap). The off-chain backend is the
> source of truth for the MVP; these interfaces lock the shapes so the migration
> on-chain is mechanical.

## Zero-custody invariant

The protocol **never custodies user funds**. x402 payments settle peer-to-peer
(reader → analyst / protocol wallet) via the facilitator. The contracts here
track **reputation and accounting**, not balances of user money. `claimEarnings`
withdraws fees that were already routed to the protocol wallet on-chain — it is a
pull, never a custodial hold of third-party funds.

## Contracts

| Contract | Responsibility |
|----------|----------------|
| `xDEOCore.sol` | Analyst registry, estimate commitments, oracle-driven scoring, fee accounting. |
| `xDEOReputation.sol` | Soulbound (non-transferable) reputation + tier badge NFTs. |
| `xDEOTreasury.sol` | 5% community treasury; ORACLE-tier governance over allocations. |
| `xDEOAgentRewards.sol` | AI-agent affiliate registry + 15% reward accounting. |

## Design notes

- **Upgradeable:** deploy behind a UUPS/Transparent proxy (OpenZeppelin). Admin
  functions are timelocked + multisig-gated per the build spec.
- **Oracle:** `scoreEstimate` is permissioned to the xDEO scoring oracle (the
  Worker cron after it parses SEC EDGAR XBRL). The scoring math matches
  `src/reputation/engine.ts` exactly so on/off-chain results agree.
- **No securities:** estimates are opinions. Nothing here mints, trades, or
  references an investment product.
