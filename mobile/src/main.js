import { Wallet } from './wallet.js'
import { XRPL }  from './xrpl.js'
import { Billing } from './billing.js'

// ─────────────────────────────────────────────────────────────────────────────
// Global API — every HTML page accesses blockchain logic via window.NOS
// ─────────────────────────────────────────────────────────────────────────────
window.NOS = { Wallet, XRPL, Billing }

// Pre-warm WalletConnect provider on every page load.
// If a session already exists it reconnects silently.
Wallet.init().catch(() => {})

// ─────────────────────────────────────────────────────────────────────────────
// Global DOM sync — update any element with data-nos attributes on wallet events
// ─────────────────────────────────────────────────────────────────────────────
async function syncWalletUI(address) {
  if (!address) return

  // Fetch real ETH balance
  const ethBal = await Wallet.getEthBalance(address).catch(() => '0.0000')

  // Update all balance display elements
  document.querySelectorAll('[data-nos="eth-balance"]').forEach((el) => {
    el.textContent = `${ethBal} ETH`
  })

  // Update all address display elements
  document.querySelectorAll('[data-nos="address"]').forEach((el) => {
    el.textContent = `${address.slice(0, 6)}...${address.slice(-4)}`
  })

  // Update all connect buttons to show address
  document.querySelectorAll('[data-nos="connect-btn"]').forEach((el) => {
    el.textContent = `${address.slice(0, 6)}...${address.slice(-4)}`
  })

  // Optionally fetch ETH → USD price (non-blocking, best-effort)
  fetch('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd')
    .then((r) => r.json())
    .then((data) => {
      const usd = (parseFloat(ethBal) * data.ethereum.usd).toLocaleString('en-US', {
        style: 'currency', currency: 'USD',
      })
      document.querySelectorAll('[data-nos="usd-balance"]').forEach((el) => {
        el.textContent = `≈ ${usd}`
      })
    })
    .catch(() => {})
}

function clearWalletUI() {
  document.querySelectorAll('[data-nos="eth-balance"]').forEach((el) => { el.textContent = '-- ETH' })
  document.querySelectorAll('[data-nos="usd-balance"]').forEach((el) => { el.textContent = '' })
  document.querySelectorAll('[data-nos="address"]').forEach((el)  => { el.textContent = '' })
  document.querySelectorAll('[data-nos="connect-btn"]').forEach((el) => { el.textContent = 'CONNECT' })
}

document.addEventListener('nos:account',    ({ detail }) => syncWalletUI(detail.address))
document.addEventListener('nos:disconnect', clearWalletUI)

// Sync immediately if session already restored
if (Wallet.isConnected()) {
  syncWalletUI(Wallet.getAddress())
}
