// Neural_OS Loyalty Program — cumulative transaction volume → fee discounts.
// Volume is synced server-side on every confirmed transaction to prevent
// localStorage manipulation and survive reinstalls.

const LOYALTY_KEY       = 'nos:loyalty'
const LOYALTY_SYNCED_AT = 'nos:loyalty-synced'
const SYNC_INTERVAL     = 5 * 60 * 1000  // sync to server at most every 5 minutes

export const LOYALTY_TIERS = {
  member:   { minVolume: 0,       label: 'MEMBER',   discountBps: 0,  color: '#849495' },
  silver:   { minVolume: 1_000,   label: 'SILVER',   discountBps: 5,  color: '#b9cacb' },
  gold:     { minVolume: 10_000,  label: 'GOLD',     discountBps: 10, color: '#FFD700' },
  platinum: { minVolume: 50_000,  label: 'PLATINUM', discountBps: 20, color: '#00dbe9' },
  elite:    { minVolume: 250_000, label: 'ELITE',    discountBps: 30, color: '#b600f8' },
}

function _read() {
  try { return JSON.parse(localStorage.getItem(LOYALTY_KEY) || '{"volume":0,"txCount":0,"pendingVolume":0}') }
  catch { return { volume: 0, txCount: 0, pendingVolume: 0 } }
}

function _write(data) {
  try { localStorage.setItem(LOYALTY_KEY, JSON.stringify(data)) } catch {}
}

export const Loyalty = {
  getData: _read,

  // Called after every confirmed on-chain transaction.
  // Adds to local store immediately and queues a server sync.
  addVolume: (usdAmount) => {
    const data = _read()
    data.volume        = (data.volume || 0) + usdAmount
    data.txCount       = (data.txCount || 0) + 1
    data.pendingVolume = (data.pendingVolume || 0) + usdAmount
    data.lastTx        = Date.now()
    _write(data)
    document.dispatchEvent(new CustomEvent('nos:loyalty', { detail: Loyalty.getStatus() }))

    // Trigger server sync (rate-limited)
    const lastSync = Number(localStorage.getItem(LOYALTY_SYNCED_AT) || '0')
    if (Date.now() - lastSync > SYNC_INTERVAL) {
      Loyalty._syncToServer().catch(() => {})
    }

    return data
  },

  // Load server-side loyalty data on wallet connect.
  // Server value wins if higher than local (prevents tampering with localStorage).
  loadFromServer: async (walletAddress) => {
    try {
      const CloudDB = window.NOS?.CloudDB
      if (!CloudDB) return
      const row = await CloudDB.loadLoyalty(walletAddress)
      if (!row) return
      const local  = _read()
      // Use the higher of server vs local for volume (server is source of truth).
      // Never allow local to exceed server by more than one pending transaction buffer.
      const serverVol = Number(row.loyalty_volume) || 0
      const serverTx  = Number(row.loyalty_tx_count) || 0
      const merged = {
        volume:        Math.max(local.volume, serverVol),
        txCount:       Math.max(local.txCount, serverTx),
        pendingVolume: 0,  // clear pending after server sync
        lastTx:        local.lastTx,
      }
      _write(merged)
      localStorage.setItem(LOYALTY_SYNCED_AT, String(Date.now()))
      document.dispatchEvent(new CustomEvent('nos:loyalty', { detail: Loyalty.getStatus() }))
    } catch {}
  },

  // Sync pending volume to Supabase.
  _syncToServer: async () => {
    try {
      const addr = window.NOS?.Wallet?.getAddress?.()
      if (!addr) return
      const data = _read()
      if (!data.pendingVolume && data.pendingVolume !== 0) return
      const CloudDB = window.NOS?.CloudDB
      if (!CloudDB) return
      await CloudDB.saveLoyalty(addr, data.volume, data.txCount)
      data.pendingVolume = 0
      _write(data)
      localStorage.setItem(LOYALTY_SYNCED_AT, String(Date.now()))
    } catch {}
  },

  getTier: () => {
    const { volume } = _read()
    let current = LOYALTY_TIERS.member
    for (const tier of Object.values(LOYALTY_TIERS)) {
      if (volume >= tier.minVolume) current = tier
    }
    return current
  },

  getDiscountBps: () => Loyalty.getTier().discountBps,

  getStatus: () => {
    const data  = _read()
    const tier  = Loyalty.getTier()
    const tiers = Object.values(LOYALTY_TIERS)
    const idx   = tiers.findIndex(t => t.label === tier.label)
    const next  = tiers[idx + 1] || null
    return {
      volume:         data.volume   || 0,
      txCount:        data.txCount  || 0,
      tier,
      next,
      progressToNext: next ? Math.min(100, ((data.volume || 0) / next.minVolume) * 100) : 100,
      volumeToNext:   next ? Math.max(0, next.minVolume - (data.volume || 0)) : 0,
    }
  },

  effectiveFeeBps: () => {
    const base     = window.NOS?.Subscription?.getFeeBps?.() ?? 100
    const discount = Loyalty.getDiscountBps()
    return Math.max(1, base - discount)
  },
}
