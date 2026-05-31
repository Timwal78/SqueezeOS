// Neural_OS Agent Runtime — in-memory agent state manager
// Agents persist state for the session; status survives page navigation via sessionStorage

const STORE_KEY = 'nos:agents'

function load() {
  try { return JSON.parse(sessionStorage.getItem(STORE_KEY) || '{}') }
  catch { return {} }
}

function save(state) {
  try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)) }
  catch {}
}

const DEFAULTS = {
  'aixbt-watcher':  { status: 'running',  label: 'AIXBT Watcher',    signalCount: 0 },
  'alpha-scanner':  { status: 'running',  label: 'Alpha Scanner',     signalCount: 0 },
  'wallet-guard':   { status: 'running',  label: 'Wallet Guard',      signalCount: 0 },
  'synt-01':        { status: 'running',  label: 'SYNT-01',           signalCount: 0 },
  'aegis-x':        { status: 'idle',     label: 'AEGIS-X',           signalCount: 0 },
  'cron-b':         { status: 'running',  label: 'CRON-B',            signalCount: 0 },
  'sync-mesh':      { status: 'running',  label: 'SYNC-MESH',         signalCount: 0 },
}

export const Agents = {
  get: (id) => {
    const stored = load()
    return stored[id] ?? DEFAULTS[id] ?? { status: 'idle', label: id, signalCount: 0 }
  },

  toggle: (id) => {
    const stored = load()
    const current = Agents.get(id)
    if (current.status === 'error' || current.status === 'killed') return current
    const next = { ...current, status: current.status === 'running' ? 'paused' : 'running', lastUpdate: Date.now() }
    stored[id] = next
    save(stored)
    document.dispatchEvent(new CustomEvent('nos:agent', { detail: { id, ...next } }))
    return next
  },

  kill: (id) => {
    const stored = load()
    const next = { ...Agents.get(id), status: 'killed', lastUpdate: Date.now() }
    stored[id] = next
    save(stored)
    document.dispatchEvent(new CustomEvent('nos:agent', { detail: { id, ...next } }))
    return next
  },

  deploy: (id) => {
    const stored = load()
    const next = { ...Agents.get(id), status: 'running', lastUpdate: Date.now() }
    stored[id] = next
    save(stored)
    document.dispatchEvent(new CustomEvent('nos:agent', { detail: { id, ...next } }))
    return next
  },

  incrementSignal: (id) => {
    const stored = load()
    const current = Agents.get(id)
    const next = { ...current, signalCount: (current.signalCount || 0) + 1, lastUpdate: Date.now() }
    stored[id] = next
    save(stored)
    return next
  },

  all: () => {
    const stored = load()
    return Object.fromEntries(
      Object.keys(DEFAULTS).map(id => [id, stored[id] ?? DEFAULTS[id]])
    )
  },
}
