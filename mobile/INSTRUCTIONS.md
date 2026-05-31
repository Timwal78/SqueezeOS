# Neural_OS — User Guide & Feature Reference

**Platform:** Android (Capacitor) | **Developer:** ScriptMasterLabs  
**App ID:** `com.neuralOS.institutional`

---

## Real vs Decorative — Read First

**This app handles real money on real blockchains. Every transaction is irreversible.**

| Component | Status | Source |
|-----------|--------|--------|
| Wallet connection | ✅ REAL | WalletConnect v2 — connects to your actual wallet |
| ETH/USDC balances | ✅ REAL | Alchemy RPC — live on-chain reads |
| Transaction history | ✅ REAL | Alchemy `getAssetTransfers` — your actual TX history |
| SEND / RECEIVE | ✅ REAL | On-chain transactions, requires wallet signature |
| ETH / BTC / XRP / $AIXBT prices | ✅ REAL | CoinGecko public API, refreshed every 60s |
| Gas price | ✅ REAL | Alchemy `eth_gasPrice`, refreshed every 15s |
| AIXBT signal feed | ✅ REAL | `api.aixbt.tech` — Virtuals Protocol live signals |
| XRP balance lookup | ✅ REAL | XRPL public RPC (`s1.ripple.com`) |
| Subscription payments (USDC) | ✅ REAL | On-chain ERC-20 transfer to billing address |
| Protocol fee on transfers | ✅ REAL | Deducted from your send amount and routed on-chain |
| Loyalty volume tracking | ✅ REAL | Accumulates from confirmed on-chain transactions |
| Agent Node Drain rates (wallet.html) | ⚠️ DECORATIVE | Hardcoded display values — not real agent billing |
| SYNT-01 "14ms latency / 99.9% integrity" | ⚠️ DECORATIVE | Static UI labels |
| Protocol fee breakdown (42%/35%/23%) | ⚠️ DECORATIVE | Visual illustration, not calculated per-transaction |
| Agent status counters (signals, processing %) | ⚠️ SIMULATED | Client-side counters in sessionStorage — not server-side AI |
| Subscription tier server verification | ⚠️ CLIENT-ONLY | Tier stored in localStorage after payment; no server-side check yet |

---

## How to Use the App

### 1. First Launch — Splash Screen

The app opens with a splash animation on `index.html` then redirects to `discover.html`. No action required.

**Working when:** Splash completes and Discover page loads within 2-3 seconds.

---

### 2. Discover Page

**What it does:**
- Shows live prices for ETH, BTC, XRP, $AIXBT in a scrolling ticker strip
- Pulls live market intelligence signals from AIXBT (Virtuals Protocol)
- Shows your swarm stats (how many agent sessions you've opened, USDC paid)
- Agent marketplace — browse and hire agents by tier

**How to know it's working:**
- Ticker strip at top of screen fills with prices (not "LOADING MARKET DATA...")
- ETH/BTC/XRP prices in the Network Intelligence grid show real numbers
- AIXBT signals feed shows actual signal cards with timestamps (e.g., "12m ago")
- If signals show "SIGNALS REQUIRE WALLET CONNECTION" — connect your wallet first

**Gas price:** Shown top-right of swarm banner. Uses your Alchemy key if BYOK is set, otherwise the app's shared Alchemy key.

---

### 3. Wallet Page

**What it does:**
- Connects your EVM wallet via WalletConnect v2
- Shows your real ETH balance and approximate USD value
- Shows your USDC balance on Base
- Lets you load any XRP Ledger address to check XRP balance
- Lists your real on-chain transaction history (ETH + ERC-20)
- SEND modal: sends ETH or USDC to any address (real transaction)
- RECEIVE modal: shows your address for copying

**How to connect:**
1. Tap **CONNECT_WALLET** button or the wallet icon in the header
2. WalletConnect QR modal appears — scan with MetaMask, Rainbow, Coinbase Wallet, or any WC-compatible wallet
3. Approve the connection in your wallet app
4. Your ETH balance and address appear automatically

**How to know it's working:**
- Header shows your ETH balance (e.g., "0.1234 ETH") not "--"
- Hero section shows your balance in large text
- Transaction table loads your real on-chain history
- "Connect Wallet" text in header changes to "Wallet_Live"

**Sending funds:**
1. Tap **SEND** (only visible when connected)
2. Select asset: ETH, USDC (ETH), or USDC (Base)
3. Enter recipient address and amount
4. Tap **EXECUTE_TRANSFER** → wallet prompts for signature
5. Wait for 1 confirmation — toast shows TX hash

**Protocol fee:** A percentage of every send is automatically deducted and routed to the Neural_OS billing address. The percentage depends on your subscription tier:
- FREE: 1.00% deducted from sent amount
- SIGNAL: 0.50%
- SOVEREIGN: 0.25%
- INSTITUTIONAL: 0.10%
- Loyalty discounts stack on top (up to −0.30%)

**Note on AGENT_NODE_DRAIN section:** The "Commerce_Strategist_Pro" and "Yield_Optimizer_v4" entries with ETH/hr rates are decorative placeholders. They do not represent real active billing.

---

### 4. Agents Page

**What it does:**
- Displays 7 AI agent slots with live status indicators
- AIXBT Watcher: pulls live $AIXBT price and signals from Virtuals Protocol API
- Alpha Scanner: animated progress bar showing simulated scan activity
- Wallet Guard: shows wallet monitoring status (active when wallet is connected)
- SYNT-01, AEGIS-X, CRON-B, SYNC-MESH: status-tracked agent slots

**How to know it's working:**
- AIXBT Watcher card shows real $AIXBT price (e.g., "$0.1234") and 24h change %
- "Latest Alpha" box shows an actual AIXBT signal message
- Stats bar at bottom shows running/paused counts and total signals
- All agents show "Active" (green) badge by default

**Controls per agent:**
- **PAUSE**: Suspends the agent (card dims to 60% opacity) — state saved in sessionStorage
- **KILL**: Permanently disables agent for session (card grays out, 35% opacity)
- **DEPLOY**: Restarts a killed or idle agent
- **AEGIS-X**: Starts as idle, tap DEPLOY AGENT to activate it

**Agent state is session-scoped:** Closing and reopening the app resets agent states to defaults. This is intentional for the MVP — agents are UI representations of your active monitoring configuration.

**Honest note on agent "activity":** The signal counts and progress bars are client-side counters. They are not connected to running server-side AI processes. The agents represent features you're enabling in the app, not autonomous background workers on a server.

---

### 5. Config Page (Subscription)

**What it does:**
- Shows subscription tier cards with pricing
- Lets you pay for a tier with USDC on Base or by card (Stripe)
- Shows your loyalty tier and fee discount progress
- BYOK (Bring Your Own Key): save your own Alchemy API key

**Current tier display:**
- A banner at the top shows your active tier (defaults to INSTITUTIONAL for testing)
- The FREE card always shows with a "Current" badge as the base plan

**Paying with USDC:**
1. Tap **USDC** on any tier card
2. Pay modal opens — confirm the amount and period
3. Tap **Pay with USDC (Base)** — app switches your wallet to Base network
4. Wallet prompts for USDC transfer signature
5. On confirmation: tier is updated in the app automatically

**Paying with Card (Stripe):**
- Requires a live backend endpoint at `/api/create-checkout`
- Not yet active — this stub is for future server-side Stripe integration

**How to know payment worked:**
- Tier banner at top updates to the new tier immediately after TX confirms
- BYOK fields unlock if you're on Sovereign or Institutional
- Effective fee % in the loyalty panel decreases

**Loyalty tier:**
Your protocol fee discount grows with cumulative transaction volume:

| Tier | Volume | Discount |
|------|--------|----------|
| MEMBER | $0 | 0 bps |
| SILVER | $1,000 | −5 bps |
| GOLD | $10,000 | −10 bps |
| PLATINUM | $50,000 | −20 bps |
| ELITE | $250,000 | −30 bps |

**BYOK (Bring Your Own Key):**
- Sovereign and Institutional tiers only
- Enter your Alchemy API key — it's stored encrypted on-device, never sent to our servers
- Using your own key gives higher rate limits for balance lookups and TX history

**Important:** Subscription tier is stored on-device only (localStorage). If you clear app data, the tier resets to FREE. Server-side subscription records will be added in a future update.

---

## Subscription Tiers — Feature Matrix

| Feature | FREE | SIGNAL | SOVEREIGN | INSTITUTIONAL |
|---------|------|--------|-----------|---------------|
| Chains | ETH only | ETH + Base | ETH + Base + zkSync + ZetaChain | All 6 incl. HyperEVM |
| Protocol fee | 1.00% | 0.50% | 0.25% | 0.10% |
| AI Agent slots | 0 | 1 | 3 | Unlimited |
| BYOK API keys | ✗ | ✗ | ✓ | ✓ |
| XRPL access | ✗ | ✗ | ✓ | ✓ |
| Agent-to-agent payments | ✗ | ✗ | ✓ | ✓ |
| Monthly price | $0 | $49 | $199 | $749 |
| Annual price | $0 | $490 | $1,990 | $7,490 |

---

## Known Limitations (Honest)

1. **Subscription not server-verified.** After USDC payment, the tier is set in localStorage. The app does not query a server to verify your subscription status. Clearing app data resets your tier. A future backend verification step will fix this.

2. **Stripe / card payment not live.** The "Card" buttons open a modal but require a `/api/create-checkout` server endpoint that is not yet deployed.

3. **Agent session tokens are not cryptographically signed.** The x402 agent runtime uses base64 encoding internally for session tracking. This is an internal bookkeeping mechanism — actual payments are on-chain. Production HMAC-SHA256 signing is planned.

4. **Agents do not run server-side.** Agents (AIKBT Watcher, Alpha Scanner, etc.) are UI state representations. They track your activation preferences and display live external data (AIXBT signals, prices) — they do not spawn background server processes.

5. **TX history requires Alchemy key.** If the shared Alchemy key hits rate limits, transaction history shows "Add Alchemy API key to .env to view history." Fix: add your own Alchemy key via BYOK on Sovereign/Institutional tier.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| CONNECT WALLET button does nothing | App still loading | Wait 1-2s and try again |
| Balances show "--" after connecting | Alchemy RPC rate limited | Add BYOK Alchemy key |
| TX history blank | Alchemy key rate limited | Add BYOK Alchemy key |
| AIXBT signals show "FETCHING..." forever | api.aixbt.tech offline / rate limited | Retry in 60s |
| BYOK Save button greyed out | Not on Sovereign/Institutional tier | Upgrade first |
| Pay modal button cut off | Phone screen too small — scroll up inside the modal | Scroll the modal sheet upward |
| Tier shows FREE after USDC payment | localStorage wasn't updated — payment may have failed | Check TX on explorer; if confirmed, reload app |
| CRON-B shows error | Old session state in sessionStorage | Clear app data and reopen |

---

## Data Sources Reference

| Data | Provider | Refresh Rate |
|------|----------|-------------|
| ETH / BTC / XRP / $AIXBT price | CoinGecko public API | 60 seconds |
| $AIXBT intelligence signals | api.aixbt.tech (Virtuals Protocol) | 30 seconds |
| ETH wallet balance | Alchemy (eth-mainnet) | On wallet connect / event |
| USDC balance (Base) | Alchemy (base-mainnet) | On wallet connect / event |
| Gas price | Alchemy eth_gasPrice | 15 seconds |
| Transaction history | Alchemy getAssetTransfers | On wallet connect |
| XRP balance | xrpl.org public RPC | On demand (tap LOAD XRP) |

---

## Security Model

- **Private keys are never accessed.** WalletConnect only requests transaction signing — your keys stay in your wallet app.
- **BYOK keys are stored on-device only.** Never transmitted to Neural_OS servers in plaintext.
- **Every financial transaction requires your explicit wallet signature.** The app cannot move funds without your approval.
- **Seed phrases and private keys are never requested** under any circumstances. Any prompt asking for these is a scam.

---

*Neural_OS is developed by ScriptMasterLabs — timothy.walton45@gmail.com*
