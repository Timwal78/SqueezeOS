# xDEO Smart Contracts (Base L2)

> **Status: implemented, pending compile/audit.** Full Solidity implementations
> of all four contracts plus the shared scoring library are here, with a Hardhat
> test suite. The scoring port agrees with the off-chain engine in
> `../src/reputation/engine.ts` by construction (see canonical spec below) and is
> checked against parity vectors generated from that tested engine.
>
> ⚠️ **Not yet compiled/tested in CI.** The Solidity compiler is fetched from
> `binaries.soliditylang.org`, which is **blocked by this build environment's
> network egress allowlist** (the same restriction that blocks `data.sec.gov`).
> So these contracts have **not been compiled or run here** — they are written to
> compile and pass `npx hardhat test` the moment they are in an environment with
> compiler access. A professional audit remains required before mainnet. Until
> then the off-chain backend (fully tested) is the source of truth.

## Zero-custody invariant

The protocol **never custodies user funds**. x402 payments settle peer-to-peer
(reader → analyst / protocol wallet) via the facilitator. The contracts here
track **reputation and fee accounting**, not balances of user money.
`claimEarnings` is a pull of fees already routed to an analyst — never a
custodial hold of third-party funds.

## Contracts

| Contract | Responsibility |
|----------|----------------|
| `src/lib/ReputationMath.sol` | UD60x18 scoring + EMA + streak math — the on-chain port of `engine.ts`. |
| `src/xDEOCore.sol` | Analyst registry, estimate commitments, oracle scoring, pull-based fee accounting. |
| `src/xDEOReputation.sol` | Soulbound (non-transferable) reputation + tier badge NFTs (ERC721). |
| `src/xDEOTreasury.sol` | 5% community treasury; ORACLE/LEGEND-tier governance over allocations. |
| `src/xDEOAgentRewards.sol` | AI-agent affiliate registry + 15% reward accounting. |
| `src/test/*` | Test-only harness + MockERC20 (compiled only for tests). |

## Tests

- `test/ReputationMath.parity.test.js` — asserts the on-chain scoring matches the
  off-chain engine within tolerance, using `test/parity-vectors.json` (generated
  from the tested `engine.ts`; regenerate via the script in the repo history).
- `test/xDEOCore.lifecycle.test.js` — register → submit → oracle score →
  reputation update → settle paid read → pull 95%/referral; soulbound enforcement.

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
