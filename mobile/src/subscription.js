import { CHAIN_ETH, CHAIN_BASE, CHAIN_ZKSYNC, CHAIN_ZETA, CHAIN_HYPERLIQUID, OWNER_WALLETS, TESTER_WALLETS } from './config.js'

// ─────────────────────────────────────────────────────────────────────────────
// Tier definitions
// ─────────────────────────────────────────────────────────────────────────────
export const TIER_DEFS = {
  free: {
    label:        'FREE',
    priceMonth:   0,
    priceAnnual:  0,
    usdcMonth:    0n,
    usdcAnnual:   0n,
    chains:       [CHAIN_ETH],
    agents:       0,
    byok:         false,
    xrpl:         false,
    feeBps:       100,
    agentToAgent: false,
    color:        '#849495',
  },
  signal: {
    label:       'SIGNAL',
    priceMonth:  49,
    priceAnnual: 490,
    usdcMonth:   49_000_000n,
    usdcAnnual:  490_000_000n,
    chains:      [CHAIN_ETH, CHAIN_BASE],
    agents:      1,
    byok:        false,
    xrpl:        false,
    feeBps:      50,
    agentToAgent:false,
    color:       '#00dbe9',
  },
  sovereign: {
    label:       'SOVEREIGN',
    priceMonth:  199,
    priceAnnual: 1_990,
    usdcMonth:   199_000_000n,
    usdcAnnual:  1_990_000_000n,
    chains:      [CHAIN_ETH, CHAIN_BASE, CHAIN_ZKSYNC, CHAIN_ZETA],
    agents:      3,
    byok:        true,
    xrpl:        true,
    feeBps:      25,
    agentToAgent:true,
    color:       '#b600f8',
  },
  institutional: {
    label:       'INSTITUTIONAL',
    priceMonth:  749,
    priceAnnual: 7_490,
    usdcMonth:   749_000_000n,
    usdcAnnual:  7_490_000_000n,
    chains:      [CHAIN_ETH, CHAIN_BASE, CHAIN_ZKSYNC, CHAIN_ZETA, CHAIN_HYPERLIQUID],
    agents:      Infinity,
    byok:        true,
    xrpl:        true,
    feeBps:      10,
    agentToAgent:true,
    color:       '#00fb40',
  },
}

const TIER_KEY          = 'nos:tier'
const BYOK_KEY          = 'nos:byok'
const TIER_VERIFIED_KEY = 'nos:tier-verified'
const TIER_PERIOD_KEY   = 'nos:tier-period'
const TIER_PAID_AT_KEY  = 'nos:tier-paid-at'

// Subscription validity windows — how long a payment lasts before re-verification required.
const PERIOD_TTL = {
  monthly: 32 * 24 * 60 * 60 * 1000,  // 32 days (buffer)
  annual:  370 * 24 * 60 * 60 * 1000, // 370 days (buffer)
}

function _getConnectedAddr() {
  try { return (window.NOS?.Wallet?.getAddress?.() || '').toLowerCase() } catch { return '' }
}

export const Subscription = {
  // ── Tier state ─────────────────────────────────────────────────────────────

  getTier: () => {
    const addr = _getConnectedAddr()

    // Owner wallets — hardcoded lifetime institutional, immune to localStorage manipulation.
    if (addr && OWNER_WALLETS.includes(addr)) return 'institutional'

    // Tester wallets — can switch tiers freely via UI, no payment needed.
    if (addr && TESTER_WALLETS.includes(addr)) {
      return localStorage.getItem(TIER_KEY) || 'free'
    }

    const tier = localStorage.getItem(TIER_KEY) || 'free'
    if (tier === 'free') return 'free'

    // Paid tier — verify the server-confirmed timestamp is within subscription window.
    // This prevents tier from persisting indefinitely if subscription lapses.
    const verifiedAt = Number(localStorage.getItem(TIER_VERIFIED_KEY) || '0')
    const period     = localStorage.getItem(TIER_PERIOD_KEY) || 'monthly'
    const ttl        = PERIOD_TTL[period] || PERIOD_TTL.monthly

    if (Date.now() - verifiedAt > ttl) {
      // Subscription window elapsed — downgrade until wallet reconnects + server re-confirms.
      return 'free'
    }

    return tier
  },

  setTier: (tier) => {
    if (!TIER_DEFS[tier]) throw new Error(`Unknown tier: ${tier}`)
    try { localStorage.setItem(TIER_KEY, tier) } catch {}
    document.dispatchEvent(new CustomEvent('nos:tier', { detail: { tier } }))
  },

  // Called by CloudDB sync after confirmed server-side payment record is found.
  // Sets the tier, period, and verification timestamp atomically.
  markVerified: (tier, period = 'monthly', paidAt = null) => {
    try {
      localStorage.setItem(TIER_KEY,          tier)
      localStorage.setItem(TIER_VERIFIED_KEY, String(Date.now()))
      localStorage.setItem(TIER_PERIOD_KEY,   period)
      if (paidAt) localStorage.setItem(TIER_PAID_AT_KEY, paidAt)
    } catch {}
  },

  // Called when owner/tester wallets connect — marks their tier as permanently verified.
  markOwnerVerified: () => {
    try {
      localStorage.setItem(TIER_KEY,          'institutional')
      localStorage.setItem(TIER_VERIFIED_KEY, String(Date.now() + 100 * 365 * 24 * 60 * 60 * 1000))
      localStorage.setItem(TIER_PERIOD_KEY,   'annual')
    } catch {}
  },

  getDef: (tier) => TIER_DEFS[tier ?? Subscription.getTier()] ?? TIER_DEFS.free,

  // ── Feature gates ──────────────────────────────────────────────────────────

  canAccessChain: (chainId) => Subscription.getDef().chains.includes(chainId),
  canRunAgents:   (count = 1) => { const max = Subscription.getDef().agents; return max === Infinity || max >= count },
  canByok:        () => Subscription.getDef().byok,
  canXrpl:        () => Subscription.getDef().xrpl,
  canAgentToAgent:() => Subscription.getDef().agentToAgent,
  getFeeBps:      () => Subscription.getDef().feeBps,

  isOwner: () => {
    const addr = _getConnectedAddr()
    return addr ? OWNER_WALLETS.includes(addr) : false
  },

  isTester: () => {
    const addr = _getConnectedAddr()
    return addr ? TESTER_WALLETS.includes(addr) : false
  },

  // ── BYOK key management ────────────────────────────────────────────────────

  setBYOK: (service, key) => {
    if (!Subscription.canByok()) throw new Error('BYOK requires Sovereign or Institutional tier')
    const current = Subscription.getBYOK()
    current[service] = key
    try { localStorage.setItem(BYOK_KEY, JSON.stringify(current)) } catch {}
    document.dispatchEvent(new CustomEvent('nos:byok', { detail: { service } }))
  },

  getBYOK: () => {
    try { return JSON.parse(localStorage.getItem(BYOK_KEY) || '{}') } catch { return {} }
  },

  clearBYOK: (service) => {
    const current = Subscription.getBYOK()
    delete current[service]
    try { localStorage.setItem(BYOK_KEY, JSON.stringify(current)) } catch {}
  },

  getAlchemyKey: () => {
    if (!Subscription.canByok()) return null
    return Subscription.getBYOK().alchemy || null
  },

  // ── Upgrade prompt helper ──────────────────────────────────────────────────

  requireTier: (needed, action) => {
    const order = ['free', 'signal', 'sovereign', 'institutional']
    const current = Subscription.getTier()
    if (order.indexOf(current) < order.indexOf(needed)) {
      document.dispatchEvent(new CustomEvent('nos:upgrade-required', { detail: { needed, action } }))
      return false
    }
    return true
  },
}
