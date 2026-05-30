// Neural_OS x402 Agent Runtime — machine-to-machine payment sessions
// AI agents pay USDC on Base to acquire a signed session token (1-hour window).
// Endpoint pricing is defined here and mirrored in .well-known/openapi.json.

import { BILLING_WALLET, CHAIN_BASE, USDC_ADDRESS } from './config.js'

// Price per call in USDC micro-units (6 decimals)
export const ENDPOINTS = {
  'rwa/alpha':        { price: 500_000n,   label: 'RWA Alpha Signal',      tier: 'signal'        },
  'rwa/deep':         { price: 2_000_000n, label: 'Deep Institutional Read', tier: 'sovereign'    },
  'rwa/council':      { price: 5_000_000n, label: 'Full Council Verdict',   tier: 'institutional' },
  'agents/hire':      { price: 1_000_000n, label: 'Agent Hire Request',     tier: 'sovereign'     },
  'agents/swarm':     { price: 250_000n,   label: 'Swarm Ping',             tier: 'signal'        },
  'market/sentiment': { price: 300_000n,   label: 'Market Sentiment Scan',  tier: 'signal'        },
  'xrpl/settlement':  { price: 750_000n,   label: 'XRPL Settlement Route',  tier: 'sovereign'     },
}

const SESSION_KEY  = 'nos:agent-sessions'
const SWARM_KEY    = 'nos:swarm-hits'
const SESSION_TTL  = 60 * 60 * 1000  // 1 hour

function _now() { return Date.now() }

function _loadSessions() {
  try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || '{}') }
  catch { return {} }
}

function _saveSessions(s) {
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)) } catch {}
}

function _loadSwarm() {
  try { return JSON.parse(localStorage.getItem(SWARM_KEY) || '{"hits":0,"volume":0,"agents":[]}') }
  catch { return { hits: 0, volume: 0, agents: [] } }
}

function _saveSwarm(s) {
  try { localStorage.setItem(SWARM_KEY, JSON.stringify(s)) } catch {}
}

// Generates a simple signed token string (not cryptographic — demo-grade).
// Production: replace with HMAC-SHA256 via SubtleCrypto.
function _mintToken(agentWallet, endpoint, exp) {
  const payload = btoa(JSON.stringify({ w: agentWallet, e: endpoint, exp }))
  const sig     = btoa(`${agentWallet}:${endpoint}:${exp}:NOS_RUNTIME_v1`)
  return `${payload}.${sig}`
}

function _verifyToken(token) {
  try {
    const [payload] = token.split('.')
    const data = JSON.parse(atob(payload))
    if (data.exp < _now()) return null
    return data
  } catch { return null }
}

export const AgentRuntime = {
  // Called by an AI agent to open a paid session.
  // Returns { token, exp, endpoint, price } or throws.
  createSession: async (agentWallet, endpoint) => {
    const def = ENDPOINTS[endpoint]
    if (!def) throw new Error(`Unknown endpoint: ${endpoint}`)

    // Check wallet connected — agent must own a wallet to pay
    if (!window.NOS?.Wallet?.isConnected()) {
      throw new Error('Wallet not connected — agent must connect first')
    }

    // Charge the agent: transfer USDC on Base to BILLING_WALLET
    const priceUsdc = Number(def.price) / 1_000_000
    await window.NOS.Wallet.sendUsdc(BILLING_WALLET, priceUsdc, CHAIN_BASE)

    const exp   = _now() + SESSION_TTL
    const token = _mintToken(agentWallet, endpoint, exp)

    // Persist session
    const sessions = _loadSessions()
    sessions[token] = { agentWallet, endpoint, exp, created: _now() }
    _saveSessions(sessions)

    // Track swarm activity
    const swarm = _loadSwarm()
    swarm.hits++
    swarm.volume = (swarm.volume || 0) + priceUsdc
    if (!swarm.agents.includes(agentWallet)) {
      swarm.agents = [...swarm.agents.slice(-99), agentWallet]
    }
    _saveSwarm(swarm)

    document.dispatchEvent(new CustomEvent('nos:agent-session', {
      detail: { agentWallet, endpoint, exp, priceUsdc }
    }))

    return { token, exp, endpoint, priceUsdc }
  },

  // Validate an existing session token.
  verifySession: (token) => {
    const data = _verifyToken(token)
    if (!data) return null
    const sessions = _loadSessions()
    const session  = sessions[token]
    if (!session) return null
    if (session.exp < _now()) { delete sessions[token]; _saveSessions(sessions); return null }
    return session
  },

  // Get swarm telemetry (how many AI agents have transacted through Neural_OS)
  getSwarmStats: () => {
    const swarm = _loadSwarm()
    return {
      totalHits:    swarm.hits    || 0,
      totalVolume:  swarm.volume  || 0,
      uniqueAgents: (swarm.agents || []).length,
      recentAgents: (swarm.agents || []).slice(-5),
    }
  },

  // Purge expired sessions
  gc: () => {
    const sessions = _loadSessions()
    const now = _now()
    let pruned = 0
    for (const [k, v] of Object.entries(sessions)) {
      if (v.exp < now) { delete sessions[k]; pruned++ }
    }
    if (pruned) _saveSessions(sessions)
    return pruned
  },
}
