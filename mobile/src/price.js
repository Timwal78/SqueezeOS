// Shared ETH/USD price cache — refreshes every 60 seconds max, shared across all modules.
// Single source of truth for loyalty volume calculations and UI balance display.

let _cachedPrice = null
let _cachedAt    = 0
const TTL = 60_000

export const Price = {
  getEth: async () => {
    if (_cachedPrice !== null && Date.now() - _cachedAt < TTL) return _cachedPrice
    try {
      const r = await fetch(
        'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd',
        { signal: AbortSignal.timeout(5000) },
      )
      if (!r.ok) throw new Error(r.status)
      const d = await r.json()
      _cachedPrice = d?.ethereum?.usd ?? _cachedPrice ?? 2000
      _cachedAt = Date.now()
    } catch {
      if (_cachedPrice === null) _cachedPrice = 2000
    }
    return _cachedPrice
  },

  getCached: () => _cachedPrice ?? 2000,
}
