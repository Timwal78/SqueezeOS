// Neural_OS Cloud Sync — Supabase persistence for subscriptions and loyalty.
// Wallet address is the primary key — no traditional auth needed.
// IMPORTANT: Supabase RLS must restrict writes to the wallet's own row.

import { SUPABASE_URL, SUPABASE_ANON_KEY } from './config.js'

const SUB_TABLE    = 'neural_os_subscriptions'
const LOYALTY_TABLE = 'neural_os_loyalty'

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
  // ── Subscriptions ───────────────────────────────────────────────────────────

  saveSubscription: async (walletAddress, tier, txHash = null, period = 'monthly') => {
    const now = new Date().toISOString()
    return sbFetch('POST', `/${SUB_TABLE}`, {
      wallet_address: walletAddress.toLowerCase(),
      tier,
      tx_hash:    txHash,
      period,
      paid_at:    now,
      updated_at: now,
    })
  },

  loadSubscription: async (walletAddress) => {
    const rows = await sbFetch(
      'GET',
      `/${SUB_TABLE}?wallet_address=eq.${encodeURIComponent(walletAddress.toLowerCase())}&select=tier,period,paid_at&limit=1`,
    )
    if (!Array.isArray(rows) || !rows.length) return null
    return rows[0]
  },

  // ── Loyalty ─────────────────────────────────────────────────────────────────
  // These methods require a `neural_os_loyalty` table in Supabase:
  //   CREATE TABLE neural_os_loyalty (
  //     wallet_address text PRIMARY KEY,
  //     loyalty_volume numeric DEFAULT 0,
  //     loyalty_tx_count integer DEFAULT 0,
  //     updated_at timestamptz DEFAULT now()
  //   );
  //   ALTER TABLE neural_os_loyalty ENABLE ROW LEVEL SECURITY;
  //   CREATE POLICY "wallet owns row" ON neural_os_loyalty
  //     FOR ALL USING (wallet_address = lower(current_setting('request.jwt.claims', true)::json->>'wallet'))
  //     WITH CHECK (wallet_address = lower(current_setting('request.jwt.claims', true)::json->>'wallet'));

  saveLoyalty: async (walletAddress, volumeUsd, txCount) => {
    return sbFetch('POST', `/${LOYALTY_TABLE}`, {
      wallet_address:   walletAddress.toLowerCase(),
      loyalty_volume:   volumeUsd,
      loyalty_tx_count: txCount,
      updated_at:       new Date().toISOString(),
    })
  },

  loadLoyalty: async (walletAddress) => {
    const rows = await sbFetch(
      'GET',
      `/${LOYALTY_TABLE}?wallet_address=eq.${encodeURIComponent(walletAddress.toLowerCase())}&select=loyalty_volume,loyalty_tx_count&limit=1`,
    )
    if (!Array.isArray(rows) || !rows.length) return null
    return rows[0]
  },
}
