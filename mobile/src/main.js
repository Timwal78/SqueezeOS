import { Wallet }       from './wallet.js'
import { XRPL }         from './xrpl.js'
import { Billing }      from './billing.js'
import { AIXBT }        from './aixbt.js'
import { Agents }       from './agents.js'
import { Subscription } from './subscription.js'
import { Loyalty }      from './loyalty.js'
import { AgentRuntime } from './agent-runtime.js'
import { SqueezeOS }    from './squeezeos.js'
import { CloudDB }      from './cloud-db.js'
import { Price }        from './price.js'

// ─────────────────────────────────────────────────────────────────────────────
// Global API — every HTML page accesses blockchain + AI logic via window.NOS
// ─────────────────────────────────────────────────────────────────────────────
window.NOS = { Wallet, XRPL, Billing, AIXBT, Agents, Subscription, Loyalty, AgentRuntime, SqueezeOS, CloudDB, Price }

// Pre-warm WalletConnect provider and start ETH price cache immediately.
Wallet.init().catch(() => {})
Price.getEth().catch(() => {})

// ─────────────────────────────────────────────────────────────────────────────
// Wallet sync — runs on connect, restores tier + loyalty from server.
// Owner and tester wallets receive appropriate access instantly.
// ─────────────────────────────────────────────────────────────────────────────
async function syncWalletUI(address) {
  if (!address) return

  // Resolve owner/tester wallet access first — no server call needed.
  if (Subscription.isOwner()) {
    Subscription.markOwnerVerified()
  }

  // Fetch balances in parallel with server sync.
  const [ethBal] = await Promise.allSettled([
    Wallet.getEthBalance(address).catch(() => '0.0000'),
  ])
  const bal = ethBal.status === 'fulfilled' ? (ethBal.value || '0.0000') : '0.0000'

  document.querySelectorAll('[data-nos="eth-balance"]').forEach((el) => {
    el.textContent = `${bal} ETH`
  })
  document.querySelectorAll('[data-nos="address"]').forEach((el) => {
    el.textContent = `${address.slice(0, 6)}...${address.slice(-4)}`
  })
  document.querySelectorAll('[data-nos="connect-btn"]').forEach((el) => {
    el.textContent = `${address.slice(0, 6)}...${address.slice(-4)}`
  })

  // Update USD display using cached price.
  Price.getEth().then((ethPrice) => {
    const usd = (parseFloat(bal) * ethPrice).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
    document.querySelectorAll('[data-nos="usd-balance"]').forEach((el) => {
      el.textContent = `≈ ${usd}`
    })
  }).catch(() => {})

  // Restore subscription from server — upgrades localStorage if server has higher tier.
  if (!Subscription.isOwner()) {
    CloudDB.loadSubscription(address).then((sub) => {
      if (!sub?.tier || sub.tier === 'free') return
      const order = ['free', 'signal', 'sovereign', 'institutional']
      const current = localStorage.getItem('nos:tier') || 'free'
      if (order.indexOf(sub.tier) > order.indexOf(current)) {
        Subscription.markVerified(sub.tier, sub.period || 'monthly', sub.paid_at)
        document.dispatchEvent(new CustomEvent('nos:tier', { detail: { tier: sub.tier } }))
      } else if (sub.tier !== 'free') {
        // Re-verify the existing tier timestamp so it stays valid.
        Subscription.markVerified(current, sub.period || 'monthly', sub.paid_at)
      }
    }).catch(() => {})
  }

  // Restore loyalty volume from server.
  Loyalty.loadFromServer(address).catch(() => {})
}

function clearWalletUI() {
  document.querySelectorAll('[data-nos="eth-balance"]').forEach((el) => { el.textContent = '-- ETH' })
  document.querySelectorAll('[data-nos="usd-balance"]').forEach((el) => { el.textContent = '' })
  document.querySelectorAll('[data-nos="address"]').forEach((el)  => { el.textContent = '' })
  document.querySelectorAll('[data-nos="connect-btn"]').forEach((el) => { el.textContent = 'CONNECT' })
}

document.addEventListener('nos:account',    ({ detail }) => syncWalletUI(detail.address))
document.addEventListener('nos:disconnect', clearWalletUI)

if (Wallet.isConnected()) {
  syncWalletUI(Wallet.getAddress())
}

// ─────────────────────────────────────────────────────────────────────────────
// Offline detection — red banner across all pages while network is unavailable
// ─────────────────────────────────────────────────────────────────────────────
function injectOfflineBanner() {
  const banner = document.createElement('div')
  banner.id = 'nos-offline-banner'
  banner.style.cssText = [
    'display:none', 'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:9999',
    'background:#93000a', 'color:#ffdad6', 'text-align:center', 'padding:8px 16px',
    'font-family:"JetBrains Mono",monospace', 'font-size:11px', 'letter-spacing:0.05em',
    'border-bottom:1px solid #ff6b6b',
  ].join(';')
  banner.textContent = '⚠ OFFLINE — Wallet operations suspended. Check your connection before transacting.'
  document.body.appendChild(banner)
  const update = () => { banner.style.display = navigator.onLine ? 'none' : 'block' }
  window.addEventListener('online', update)
  window.addEventListener('offline', update)
  update()
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', injectOfflineBanner)
} else {
  injectOfflineBanner()
}

// ─────────────────────────────────────────────────────────────────────────────
// Global event forwarding — nos:sync-warn → page toast (if present)
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('nos:sync-warn', ({ detail }) => {
  const t = document.getElementById('toast')
  if (!t) return
  t.textContent = '⚠ ' + detail.message
  t.classList.remove('hidden')
  clearTimeout(t._t)
  t._t = setTimeout(() => t.classList.add('hidden'), 8000)
})
