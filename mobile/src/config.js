// ─────────────────────────────────────────────────────────────────────────────
// Credentials — fill in .env before `npm run build`
// See .env.example for the full list
// ─────────────────────────────────────────────────────────────────────────────

export const WC_PROJECT_ID   = import.meta.env.VITE_WC_PROJECT_ID   || 'REPLACE_WALLETCONNECT_PROJECT_ID'
export const ALCHEMY_KEY     = import.meta.env.VITE_ALCHEMY_KEY     || 'REPLACE_ALCHEMY_API_KEY'
export const STRIPE_PK       = import.meta.env.VITE_STRIPE_PK       || 'REPLACE_STRIPE_PUBLISHABLE_KEY'

// Recipient wallet for crypto subscription payments — your address
export const BILLING_WALLET  = import.meta.env.VITE_BILLING_WALLET  || '0x0000000000000000000000000000000000000000'

// ─────────────────────────────────────────────────────────────────────────────
// Chain IDs
// ─────────────────────────────────────────────────────────────────────────────
export const CHAIN_ETH  = 1
export const CHAIN_BASE = 8453

// ─────────────────────────────────────────────────────────────────────────────
// RPC endpoints (Alchemy)
// ─────────────────────────────────────────────────────────────────────────────
export const RPC = {
  [CHAIN_ETH]:  `https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  [CHAIN_BASE]: `https://base-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
}

// ─────────────────────────────────────────────────────────────────────────────
// XRPL
// ─────────────────────────────────────────────────────────────────────────────
export const XRPL_RPC = 'https://s1.ripple.com:51234/'

// ─────────────────────────────────────────────────────────────────────────────
// USDC contract addresses
// ─────────────────────────────────────────────────────────────────────────────
export const USDC_ADDRESS = {
  [CHAIN_ETH]:  '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
  [CHAIN_BASE]: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
}

// ─────────────────────────────────────────────────────────────────────────────
// Subscription tiers (USDC, 6 decimals)
// ─────────────────────────────────────────────────────────────────────────────
export const TIERS = {
  sovereign:    { monthly: 64_000_000n,   annual: 614_400_000n  },  // $64/mo  · $512/yr
  institutional: { monthly: 256_000_000n, annual: 2_457_600_000n }, // $256/mo · $2,048/yr
}
