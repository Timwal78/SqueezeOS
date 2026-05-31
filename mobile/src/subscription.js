import { CHAIN_ETH, CHAIN_BASE, CHAIN_ZKSYNC, CHAIN_ZETA, CHAIN_HYPERLIQUID } from './config.js'

// ─────────────────────────────────────────────────────────────────────────────
// Tier definitions — enforced client-side; validate server-side before shipping
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
    feeBps:       100,  // 1% — upgrade to reduce
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
    feeBps:      50,   // 0.5%
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
    feeBps:      25,   // 0.25%
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
    feeBps:      10,   // 0.1%
    agentToAgent:true,
    color:       '#00fb40',
  },
}

const TIER_KEY = 'nos:tier'
const BYOK_KEY = 'nos:byok'

export const Subscription = {
  // ── Tier state ─────────────────────────────────────────────────────────────
  getTier: () => localStorage.getItem(TIER_KEY) || 'institutional',

  setTier: (tier) => {
    if (!TIER_DEFS[tier]) throw new Error(`Unknown tier: ${tier}`)
    try { localStorage.setItem(TIER_KEY, tier) } catch {}
    document.dispatchEvent(new CustomEvent('nos:tier', { detail: { tier } }))
  },

  getDef: (tier) => TIER_DEFS[tier ?? Subscription.getTier()] ?? TIER_DEFS.signal,

  // ── Feature gates ──────────────────────────────────────────────────────────
  canAccessChain: (chainId) => {
    return Subscription.getDef().chains.includes(chainId)
  },

  canRunAgents: (count = 1) => {
    const max = Subscription.getDef().agents
    return max === Infinity || max >= count
  },

  canByok: () => Subscription.getDef().byok,

  canXrpl: () => Subscription.getDef().xrpl,

  canAgentToAgent: () => Subscription.getDef().agentToAgent,

  getFeeBps: () => Subscription.getDef().feeBps,

  // ── BYOK key management ────────────────────────────────────────────────────
  setBYOK: (service, key) => {
    if (!Subscription.canByok()) {
      throw new Error('BYOK requires Sovereign or Institutional tier')
    }
    const current = Subscription.getBYOK()
    current[service] = key
    try { localStorage.setItem(BYOK_KEY, JSON.stringify(current)) } catch {}
    document.dispatchEvent(new CustomEvent('nos:byok', { detail: { service } }))
  },

  getBYOK: () => {
    try { return JSON.parse(localStorage.getItem(BYOK_KEY) || '{}') }
    catch { return {} }
  },

  clearBYOK: (service) => {
    const current = Subscription.getBYOK()
    delete current[service]
    try { localStorage.setItem(BYOK_KEY, JSON.stringify(current)) } catch {}
  },

  // Returns user's Alchemy key if BYOK enabled, else null (falls back to app key)
  getAlchemyKey: () => {
    if (!Subscription.canByok()) return null
    return Subscription.getBYOK().alchemy || null
  },

  // ── Upgrade prompt helper ──────────────────────────────────────────────────
  requireTier: (needed, action) => {
    const order = ['free', 'signal', 'sovereign', 'institutional']
    const current = Subscription.getTier()
    if (order.indexOf(current) < order.indexOf(needed)) {
      document.dispatchEvent(new CustomEvent('nos:upgrade-required', {
        detail: { needed, action }
      }))
      return false
    }
    return true
  },
}
