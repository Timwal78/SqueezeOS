// SqueezeOS AI Market Intelligence — live signal feed
// Free endpoints: no auth required. Premium endpoints gated by 402Proof payment.
// Docs: https://squeezeos-api.onrender.com/.well-known/openapi.json

const BASE = 'https://squeezeos-api.onrender.com'

async function get(path) {
  try {
    const r = await fetch(`${BASE}${path}`, { signal: AbortSignal.timeout(8000) })
    if (!r.ok) return null
    return r.json()
  } catch { return null }
}

export const SqueezeOS = {
  // Recent signal ring-buffer — up to 200 events across all tracked symbols
  getHistory: async (limit = 20) => {
    const d = await get(`/api/history`)
    const arr = Array.isArray(d) ? d : (d?.signals ?? d?.data ?? d?.history ?? [])
    return arr.slice(0, limit)
  },

  // Oracle directive for a symbol: { directive, confidence, regime, symbol }
  getOracle: async (symbol = 'IWM') => {
    return get(`/api/oracle/${symbol}`)
  },

  // System health + processed counts
  getStatus: async () => get('/api/status'),

  // RecurrentDepthTransformer multi-symbol ranked analysis
  getRDT: async () => get('/api/graph/rdt'),

  // Preview bias for a symbol (15-min cache, free)
  getPreview: async (symbol) => get(`/api/preview/${symbol}`),
}
