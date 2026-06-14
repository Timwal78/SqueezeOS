# xDEO Smart Contracts (Base L2)

> **Status: interface + canonical spec.** This directory defines the on-chain
> surface (`src/IxDEOCore.sol`) and the exact scoring math the contracts must
> implement, so the on-chain port agrees bit-for-bit with the off-chain engine
> in `../src/reputation/engine.ts`.
>
> ⚠️ **Not yet compiled/tested in CI.** A Hardhat scaffold is included
> (`hardhat.config.js`, `package.json`), but the Solidity compiler is fetched
> from `binaries.soliditylang.org`, which is **blocked by this build
> environment's network egress allowlist** (the same restriction that blocks
> `data.sec.gov`). Implementations + Foundry/Hardhat tests + an audit are Phase 3
> and must be done in an environment with compiler access. Until then the
> off-chain backend (fully tested) is the source of truth.

## Zero-custody invariant

The protocol **never custodies user funds**. x402 payments settle peer-to-peer
(reader → analyst / protocol wallet) via the facilitator. The contracts here
track **reputation and fee accounting**, not balances of user money.
`claimEarnings` is a pull of fees already routed to an analyst — never a
custodial hold of third-party funds.

## Contracts

| Contract | Responsibility |
|----------|----------------|
| `xDEOCore.sol` | Analyst registry, estimate commitments, oracle-driven scoring, fee accounting. |
| `xDEOReputation.sol` | Soulbound (non-transferable) reputation + tier badge NFTs. |
| `xDEOTreasury.sol` | 5% community treasury; ORACLE-tier governance over allocations. |
| `xDEOAgentRewards.sol` | AI-agent affiliate registry + 15% reward accounting. |

## Canonical scoring spec (must match `engine.ts`)

All values are UD60x18 fixed point (1e18). Inputs: `predicted`, `actual`
(scaled 1e8 ints), `confidence ∈ [0,1]`, `leadSeconds`.

```
errorPct   = |predicted - actual| / max(|actual|, ε)          // ε = 1e-9
accuracy   = 2^(-10 · errorPct)            = exp2(10·errorPct).inv()
w          = 0.5 + 0.5 · confidence                            // ∈ [0.5, 1]
base       = accuracy · w + (1 - w) / 2                         // ∈ [0, 1], unsigned
timeliness = 0.25 + 0.75 · min(leadSeconds / (30·86400), 1)     // ∈ [0.25, 1]
effective  = base · timeliness + 0.5 · (1 - timeliness)         // convex blend toward 0.5
score      = 100 · effective                                    // ∈ [0, 100]
```

> The `base` and `effective` forms above are the **unsigned algebraic
> equivalents** of the signed expressions in `engine.ts` (`signed = 2·acc - 1`,
> etc.), chosen so the on-chain port needs only PRBMath's unsigned `UD60x18`
> (no signed fixed point). They are mathematically identical.

Reputation update (EMA, matches `updateReputation`): `alpha = max(0.08, 1/(n+1))`,
streak boosts gains only, capped at 100. Streak multipliers: 7d→1.5×, 30d→2.5×,
100d→5×. Tiers (`computeTier`): OBSERVER → ANALYST (5 estimates) → SAGE (≥80%
accuracy, ≥20) → ORACLE/LEGEND (top-10 global, rep ≥90 / ≥97).

## Design notes

- **Upgradeable:** deploy behind a UUPS/Transparent proxy (OpenZeppelin). Admin
  functions timelocked + multisig-gated.
- **Oracle:** `scoreEstimate` is permissioned to the xDEO scoring oracle (the
  Worker cron after it parses SEC EDGAR XBRL).
- **No securities:** estimates are opinions. Nothing here mints, trades, or
  references an investment product.

## Building (in an environment with compiler egress)

```bash
cd contracts
npm install                 # hardhat + @openzeppelin/contracts + @prb/math
npx hardhat compile         # downloads solc 0.8.24 (needs binaries.soliditylang.org)
npx hardhat test
```
