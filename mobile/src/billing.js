import { loadStripe } from '@stripe/stripe-js'
import { STRIPE_PK, BILLING_WALLET, TIERS, SUPABASE_URL, SUPABASE_ANON_KEY } from './config.js'
import { Wallet } from './wallet.js'
import { CloudDB } from './cloud-db.js'

let _stripe = null
async function stripe() {
  if (!_stripe) _stripe = await loadStripe(STRIPE_PK)
  return _stripe
}

export const Billing = {
  /**
   * Card payment via Stripe Checkout.
   * Opens Stripe's hosted checkout page. Tier is applied server-side via
   * the stripe-webhook Edge Function when payment completes.
   * User returns to app and reconnects wallet to restore their tier from DB.
   */
  subscribeStripe: async (tier, period = 'monthly') => {
    const walletAddress = Wallet.getAddress()
    const res = await fetch(`${SUPABASE_URL}/functions/v1/create-checkout`, {
      method: 'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        tier,
        period,
        wallet_address: walletAddress ?? '',
        success_url: 'https://signal-auction-loom.vercel.app/?payment=success&tier=' + tier,
        cancel_url:  'https://signal-auction-loom.vercel.app/',
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || 'Failed to create checkout session')
    }
    const { url, error } = await res.json()
    if (error) throw new Error(error)
    // Open Stripe checkout — system browser in Capacitor, tab in web
    window.open(url, '_blank')
  },

  /**
   * Pay subscription in USDC on Base.
   * Immediately sets tier and syncs to Supabase after on-chain confirmation.
   */
  subscribeCrypto: async (tier, period = 'monthly') => {
    if (!Wallet.isConnected()) throw new Error('Connect wallet first')
    const amount = TIERS[tier]?.[period]
    if (amount === undefined) throw new Error(`Unknown tier "${tier}" / period "${period}"`)

    await Wallet.switchChain(8453)
    const usdcAmount = Number(amount) / 1e6
    const hash = await Wallet.sendUsdc(BILLING_WALLET, usdcAmount, 8453)

    // Persist to Supabase — survives app reinstall
    const address = Wallet.getAddress()
    if (address) {
      CloudDB.saveSubscription(address, tier, hash, period).catch(() => {})
    }

    return hash
  },

  /** Server-side subscription lookup — reads from Supabase */
  getStatus: async (address) => {
    const sub = await CloudDB.loadSubscription(address)
    if (!sub) return { active: false, tier: 'free', expiresAt: null }
    return { active: sub.tier !== 'free', tier: sub.tier, period: sub.period, paidAt: sub.paid_at }
  },
}
