// ─────────────────────────────────────────────────────────────────────────────
// Credentials — override with .env before `npm run build`
// ─────────────────────────────────────────────────────────────────────────────

export const WC_PROJECT_ID   = import.meta.env.VITE_WC_PROJECT_ID   || '4c6399222d72daa6e53904504334501b'
export const ALCHEMY_KEY     = import.meta.env.VITE_ALCHEMY_KEY     || 'xR7Tl0576BmgNMvF4q_Y8'
export const STRIPE_PK       = import.meta.env.VITE_STRIPE_PK       || 'pk_live_51S07wtQL50L4TFzsw97jG66buYDIPAO1C4LVPO30GbTCsUiq2nG257s138hpPaP2lxduzaYfUWStb1k2L3O9bGnX00SkdNCnct'

// Recipient wallet for crypto subscription payments (Base USDC)
export const BILLING_WALLET  = import.meta.env.VITE_BILLING_WALLET  || '0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700'

// ─────────────────────────────────────────────────────────────────────────────
// Supabase — subscription persistence (public anon key, safe to bundle)
// ─────────────────────────────────────────────────────────────────────────────
export const SUPABASE_URL      = import.meta.env.VITE_SUPABASE_URL      || 'https://mkftltqjxeqejztzomzf.supabase.co'
export const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1rZnRsdHFqeGVxZWp6dHpvbXpmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4MzMwODEsImV4cCI6MjA5MDQwOTA4MX0.n_OPmJFg2bOmNn1Gdc4gPsgor5iSgQbS04uZ_EFOYlY'

// ─────────────────────────────────────────────────────────────────────────────
// Chain IDs
// ─────────────────────────────────────────────────────────────────────────────
export const CHAIN_ETH         = 1
export const CHAIN_BASE        = 8453
export const CHAIN_ZKSYNC      = 324
export const CHAIN_HYPERLIQUID = 999
export const CHAIN_ZETA        = 7000  // ZetaChain — omnichain (ETH + BTC + XRPL native)

// ─────────────────────────────────────────────────────────────────────────────
// RPC endpoints (Alchemy)
// ─────────────────────────────────────────────────────────────────────────────
export const RPC = {
  [CHAIN_ETH]:         `https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  [CHAIN_BASE]:        `https://base-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  [CHAIN_ZKSYNC]:      `https://zksync-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  [CHAIN_HYPERLIQUID]: `https://hyperliquid-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
  [CHAIN_ZETA]:        `https://zetachain-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`,
}

// ─────────────────────────────────────────────────────────────────────────────
// XRPL
// ─────────────────────────────────────────────────────────────────────────────
export const XRPL_RPC = 'https://s1.ripple.com:51234/'

// ─────────────────────────────────────────────────────────────────────────────
// USDC contract addresses
// ─────────────────────────────────────────────────────────────────────────────
export const USDC_ADDRESS = {
  [CHAIN_ETH]:         '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
  [CHAIN_BASE]:        '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
  [CHAIN_ZKSYNC]:      '0x1d17CBcF0D6D143135aE902365D2E5e2A16538D4',
  [CHAIN_HYPERLIQUID]: null, // HyperEVM USDC — fill in contract address when available
  [CHAIN_ZETA]:        '0x0cbe0dF132a6c6B4a2974Fa1b7Fb953CF0Cc798', // ZRC-20 USDC on ZetaChain
}

// ─────────────────────────────────────────────────────────────────────────────
// Subscription tiers (USDC, 6 decimals) — see src/subscription.js for full defs
// ─────────────────────────────────────────────────────────────────────────────
export const TIERS = {
  signal:        { monthly: 49_000_000n,  annual: 490_000_000n  },  // $49/mo  · $490/yr
  sovereign:     { monthly: 199_000_000n, annual: 1_990_000_000n }, // $199/mo · $1,990/yr
  institutional: { monthly: 749_000_000n, annual: 7_490_000_000n }, // $749/mo · $7,490/yr
}
