import { loadStripe } from '@stripe/stripe-js'
import { STRIPE_PK, BILLING_WALLET, TIERS } from './config.js'
import { Wallet } from './wallet.js'

let _stripe = null
async function stripe() {
  if (!_stripe) _stripe = await loadStripe(STRIPE_PK)
  return _stripe
}

export const Billing = {
  /**
   * Open Stripe Checkout.
   * Requires a server endpoint POST /api/create-checkout → { url }
   * (Stripe secret key must NEVER be in the client bundle)
   */
  subscribeStripe: async (tier, period = 'monthly') => {
    const res = await fetch('/api/create-checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier, period }),
    })
    if (!res.ok) throw new Error('Failed to create checkout session')
    const { url } = await res.json()
    window.location.href = url
  },

  /**
   * Pay subscription in USDC on Base (low gas).
   * Caller must have wallet connected.
   */
  subscribeCrypto: async (tier, period = 'monthly') => {
    if (!Wallet.isConnected()) throw new Error('Connect wallet first')
    const amount = TIERS[tier]?.[period]
    if (amount === undefined) throw new Error(`Unknown tier "${tier}" / period "${period}"`)

    // Use Base for cheap USDC transfer
    await Wallet.switchChain(8453)
    const usdcAmount = Number(amount) / 1e6
    const hash = await Wallet.sendUsdc(BILLING_WALLET, usdcAmount, 8453)
    return hash
  },

  /** Check if a wallet address has an active subscription (stub — wire to your backend) */
  getStatus: async (address) => {
    // TODO: query your backend or an on-chain event index
    return { active: false, tier: null, expiresAt: null }
  },
}
