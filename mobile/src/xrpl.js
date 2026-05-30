import { XRPL_RPC } from './config.js'

async function rpc(method, params) {
  const res = await fetch(XRPL_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, params: [params] }),
  })
  const json = await res.json()
  if (json.result?.error) throw new Error(json.result.error_message ?? json.result.error)
  return json.result
}

export const XRPL = {
  /** XRP balance in XRP (not drops) */
  getBalance: async (address) => {
    const { account_data } = await rpc('account_info', {
      account: address,
      ledger_index: 'current',
    })
    return (Number(account_data.Balance) / 1_000_000).toFixed(6)
  },

  /** Last `limit` transactions for an address */
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
