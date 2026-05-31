// Neural_OS Loyalty Program — rewards cumulative transaction volume with fee discounts
// Stacks on top of subscription tier: effective fee = tier_fee - loyalty_discount

const LOYALTY_KEY = 'nos:loyalty'

export const LOYALTY_TIERS = {
  member:   { minVolume: 0,       label: 'MEMBER',   discountBps: 0,  color: '#849495' },
  silver:   { minVolume: 1_000,   label: 'SILVER',   discountBps: 5,  color: '#b9cacb' },
  gold:     { minVolume: 10_000,  label: 'GOLD',     discountBps: 10, color: '#FFD700' },
  platinum: { minVolume: 50_000,  label: 'PLATINUM', discountBps: 20, color: '#00dbe9' },
  elite:    { minVolume: 250_000, label: 'ELITE',    discountBps: 30, color: '#b600f8' },
}

export const Loyalty = {
  getData: () => {
    try {
      return JSON.parse(localStorage.getItem(LOYALTY_KEY) || '{"volume":0,"txCount":0}')
    } catch {
      return { volume: 0, txCount: 0 }
    }
  },

  // Call after every confirmed transaction — usdAmount is approximate USD value
  addVolume: (usdAmount) => {
    const data = Loyalty.getData()
    data.volume   = (data.volume   || 0) + usdAmount
    data.txCount  = (data.txCount  || 0) + 1
    data.lastTx   = Date.now()
    try { localStorage.setItem(LOYALTY_KEY, JSON.stringify(data)) } catch {}
    document.dispatchEvent(new CustomEvent('nos:loyalty', { detail: Loyalty.getStatus() }))
    return data
  },

  getTier: () => {
    const { volume } = Loyalty.getData()
    let current = LOYALTY_TIERS.member
    for (const tier of Object.values(LOYALTY_TIERS)) {
      if (volume >= tier.minVolume) current = tier
    }
    return current
  },

  getDiscountBps: () => Loyalty.getTier().discountBps,

  getStatus: () => {
    const data  = Loyalty.getData()
    const tier  = Loyalty.getTier()
    const tiers = Object.values(LOYALTY_TIERS)
    const idx   = tiers.findIndex(t => t.label === tier.label)
    const next  = tiers[idx + 1] || null
    return {
      volume:          data.volume   || 0,
      txCount:         data.txCount  || 0,
      tier,
      next,
      progressToNext:  next ? Math.min(100, ((data.volume || 0) / next.minVolume) * 100) : 100,
      volumeToNext:    next ? Math.max(0, next.minVolume - (data.volume || 0)) : 0,
    }
  },

  // Returns the effective fee in bps after stacking subscription + loyalty
  effectiveFeeBps: () => {
    const base     = window.NOS?.Subscription?.getFeeBps?.() ?? 100
    const discount = Loyalty.getDiscountBps()
    return Math.max(1, base - discount) // floor at 0.01%
  },
}
