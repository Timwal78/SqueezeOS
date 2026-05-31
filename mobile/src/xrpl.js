import { XRPL_RPC } from './config.js'

const XRP_ADDR_KEY = 'nos:xrpl-addr'

async function rpc(method, params) {
  const res = await fetch(XRPL_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, params: [params] }),
    signal: AbortSignal.timeout(8000),
  })
  const json = await res.json()
  if (json.result?.error) throw new Error(json.result.error_message ?? json.result.error)
  return json.result
}

export const XRPL = {
  // Persist the last-used XRP address across pages and sessions.
  setAddress: (addr) => { try { localStorage.setItem(XRP_ADDR_KEY, addr || '') } catch {} },
  getAddress: () => { try { return localStorage.getItem(XRP_ADDR_KEY) || null } catch { return null } },
  clearAddress: () => { try { localStorage.removeItem(XRP_ADDR_KEY) } catch {} },

  // XRP balance in XRP (not drops).
  getBalance: async (address) => {
    const { account_data } = await rpc('account_info', { account: address, ledger_index: 'current' })
    return (Number(account_data.Balance) / 1_000_000).toFixed(6)
  },

  // Last `limit` transactions for an address.
  getTransactions: async (address, limit = 20) => {
    const { transactions } = await rpc('account_tx', { account: address, limit })
    return (transactions ?? []).map((t) => ({
      hash:        t.tx.hash,
      type:        t.tx.TransactionType,
      amount:      t.tx.Amount ? Number(t.tx.Amount) / 1_000_000 : 0,
      destination: t.tx.Destination ?? null,
      date:        new Date((t.tx.date + 946684800) * 1000).toISOString(),
      success:     t.meta.TransactionResult === 'tesSUCCESS',
    }))
  },
}
