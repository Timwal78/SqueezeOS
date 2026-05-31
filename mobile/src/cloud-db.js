// Neural_OS Cloud Subscription Sync
// Persists wallet→tier mapping in Supabase so tier survives app reinstall / cleared storage.
// Wallet address is the primary key — no traditional auth needed.

import { SUPABASE_URL, SUPABASE_ANON_KEY } from './config.js'

const TABLE = 'neural_os_subscriptions'

async function sbFetch(method, path, body) {
  try {
    const res = await fetch(`${SUPABASE_URL}/rest/v1${path}`, {
      method,
      headers: {
        'Content-Type':  'application/json',
        'apikey':        SUPABASE_ANON_KEY,
        'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
        'Prefer':        method === 'POST' ? 'resolution=merge-duplicates,return=minimal' : '',
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(6000),
    })
    if (res.status === 204 || res.status === 201) return true
    if (!res.ok) return null
    const text = await res.text()
    return text ? JSON.parse(text) : null
  } catch { return null }
}

export const CloudDB = {
  // Upsert subscription record after confirmed on-chain payment
  saveSubscription: async (walletAddress, tier, txHash = null, period = 'monthly') => {
    return sbFetch('POST', `/${TABLE}`, {
      wallet_address: walletAddress.toLowerCase(),
      tier,
      tx_hash:    txHash,
      period,
      paid_at:    new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
  },

  // Load subscription on wallet connect — returns { tier, period, paid_at } or null
  loadSubscription: async (walletAddress) => {
    const rows = await sbFetch(
      'GET',
      `/${TABLE}?wallet_address=eq.${encodeURIComponent(walletAddress.toLowerCase())}&select=tier,period,paid_at&limit=1`,
    )
    if (!Array.isArray(rows) || !rows.length) return null
    return rows[0]
  },
}
