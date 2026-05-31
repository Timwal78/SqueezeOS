// Neural_OS x402 Agent Runtime — machine-to-machine payment sessions
// AI agents pay USDC on Base to acquire a signed session token (1-hour window).
// Endpoint pricing is defined here and mirrored in .well-known/openapi.json.

import { BILLING_WALLET, CHAIN_BASE, USDC_ADDRESS } from './config.js'

// Price per call in USDC micro-units (6 decimals)
export const ENDPOINTS = {
  'rwa/alpha':        { price: 500_000n,   label: 'RWA Alpha Signal',        tier: 'signal'        },
  'rwa/deep':         { price: 2_000_000n, label: 'Deep Institutional Read',  tier: 'sovereign'     },
  'rwa/council':      { price: 5_000_000n, label: 'Full Council Verdict',     tier: 'institutional' },
  'agents/hire':      { price: 1_000_000n, label: 'Agent Hire Request',       tier: 'sovereign'     },
  'agents/swarm':     { price: 250_000n,   label: 'Swarm Ping',               tier: 'signal'        },
  'market/sentiment': { price: 300_000n,   label: 'Market Sentiment Scan',    tier: 'signal'        },
  'xrpl/settlement':  { price: 750_000n,   label: 'XRPL Settlement Route',    tier: 'sovereign'     },
}

const SESSION_KEY = 'nos:agent-sessions'
const SWARM_KEY   = 'nos:swarm-hits'
const SECRET_KEY  = 'nos:agent-secret'
const SESSION_TTL = 60 * 60 * 1000  // 1 hour

function _now() { return Date.now() }

// Per-device HMAC secret — persisted so tokens survive page refresh
function _getOrCreateSecret() {
  let secret = localStorage.getItem(SECRET_KEY)
  if (!secret) {
    const bytes = new Uint8Array(32)
    crypto.getRandomValues(bytes)
    secret = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('')
    try { localStorage.setItem(SECRET_KEY, secret) } catch {}
  }
  return secret
}

async function _hmacKey(usage) {
  return crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(_getOrCreateSecret()),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    [usage],
  )
}

function _b64url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

function _b64urlDecode(s) {
  return Uint8Array.from(
    atob(s.replace(/-/g, '+').replace(/_/g, '/')),
    c => c.charCodeAt(0),
  )
}

// Mint a HMAC-SHA256 signed session token (Web Crypto — not forgeable client-side)
async function _mintToken(agentWallet, endpoint, exp) {
  const payload = btoa(JSON.stringify({ w: agentWallet, e: endpoint, exp }))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
  const key    = await _hmacKey('sign')
  const sigBuf = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload))
  return `${payload}.${_b64url(sigBuf)}`
}

// Verify HMAC signature AND expiry
async function _verifyToken(token) {
  try {
    const [payload, sig] = token.split('.')
    if (!payload || !sig) return null
    const data = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
    if (data.exp < _now()) return null
    const key   = await _hmacKey('verify')
    const valid = await crypto.subtle.verify(
      'HMAC', key, _b64urlDecode(sig), new TextEncoder().encode(payload),
    )
    return valid ? data : null
  } catch { return null }
}

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

export const AgentRuntime = {
  // Called by an AI agent to open a paid session.
  // Returns { token, exp, endpoint, priceUsdc } or throws.
  createSession: async (agentWallet, endpoint) => {
    const def = ENDPOINTS[endpoint]
    if (!def) throw new Error(`Unknown endpoint: ${endpoint}`)

    if (!window.NOS?.Wallet?.isConnected()) {
      throw new Error('Wallet not connected — agent must connect first')
    }

    const priceUsdc = Number(def.price) / 1_000_000
    await window.NOS.Wallet.sendUsdc(BILLING_WALLET, priceUsdc, CHAIN_BASE)

    const exp   = _now() + SESSION_TTL
    const token = await _mintToken(agentWallet, endpoint, exp)

    const sessions = _loadSessions()
    sessions[token] = { agentWallet, endpoint, exp, created: _now() }
    _saveSessions(sessions)

    const swarm = _loadSwarm()
    swarm.hits++
    swarm.volume = (swarm.volume || 0) + priceUsdc
    if (!swarm.agents.includes(agentWallet)) {
      swarm.agents = [...swarm.agents.slice(-99), agentWallet]
    }
    _saveSwarm(swarm)

    document.dispatchEvent(new CustomEvent('nos:agent-session', {
      detail: { agentWallet, endpoint, exp, priceUsdc },
    }))

    return { token, exp, endpoint, priceUsdc }
  },

  // Validate an existing session token — async due to HMAC verification
  verifySession: async (token) => {
    const data    = await _verifyToken(token)
    if (!data) return null
    const sessions = _loadSessions()
    const session  = sessions[token]
    if (!session) return null
    if (session.exp < _now()) { delete sessions[token]; _saveSessions(sessions); return null }
    return session
  },

  // Get swarm telemetry
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
