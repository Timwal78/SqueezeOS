// AIXBT — AI market intelligence agent on Base (Virtuals Protocol)
// Signals feed + $AIXBT token price

const AIXBT_API = 'https://api.aixbt.tech'
const CG_AIXBT  = 'https://api.coingecko.com/api/v3/simple/price?ids=aixbt-by-virtuals&vs_currencies=usd&include_24hr_change=true&include_market_cap=true'

export const AIXBT = {
  // Latest AI-generated market signals from AIXBT
  getSignals: async (limit = 20) => {
    try {
      const r = await fetch(`${AIXBT_API}/v1/insights?limit=${limit}`, {
        headers: { Accept: 'application/json' },
      })
      if (!r.ok) throw new Error(r.status)
      const d = await r.json()
      return Array.isArray(d) ? d : (d.data ?? d.insights ?? d.results ?? [])
    } catch {
      return []
    }
  },

  // Trending tokens by AIXBT mindshare score
  getTrending: async () => {
    try {
      const r = await fetch(`${AIXBT_API}/v1/trending`, {
        headers: { Accept: 'application/json' },
      })
      if (!r.ok) throw new Error(r.status)
      const d = await r.json()
      return Array.isArray(d) ? d : (d.data ?? d.tokens ?? [])
    } catch {
      return []
    }
  },

  // $AIXBT token price + 24h change via CoinGecko
  getTokenPrice: async () => {
    try {
      const r = await fetch(CG_AIXBT)
      if (!r.ok) throw new Error(r.status)
      const d = await r.json()
      const t = d['aixbt-by-virtuals']
      return t ? {
        usd:       t.usd,
        change24h: t.usd_24h_change,
        mcap:      t.usd_market_cap,
      } : null
    } catch {
      return null
    }
  },

  // Signal summary — total count + last signal time from public feed
  getSummary: async () => {
    const [signals, price] = await Promise.allSettled([
      AIXBT.getSignals(5),
      AIXBT.getTokenPrice(),
    ])
    return {
      signals:    signals.status === 'fulfilled' ? signals.value : [],
      tokenPrice: price.status   === 'fulfilled' ? price.value   : null,
    }
  },
}
