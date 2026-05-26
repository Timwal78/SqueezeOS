/// <reference types="vite/client" />
import { useEffect, useRef } from 'react'
import { create } from 'zustand'

export type ParticleState = 0 | 1 | 2 | 3 | 4
// 0=dormant, 1=challenge(red), 2=bidding(cyan), 3=settled(gold), 4=executing(white)

export interface Particle {
  requestId: string
  state: ParticleState
  tipSats: number
  walletHash: string
  endpoint: string
  submittedMs: number
  rank?: number
}

export interface AuctionBid {
  rank: number
  tipSats: number
  walletHash: string
  submittedMs: number
}

export interface LeaderboardEntry {
  rank: number
  walletHash: string
  totalTipsSats: number
  winRate: number | null
}

export type AuctionEvent =
  | { type: 'CONNECTED'; ts: number; message: string }
  | { type: 'CHALLENGE_ISSUED'; ts: number; request_id: string; ip_hash: string; endpoint: string }
  | { type: 'BID_RECEIVED'; ts: number; request_id: string; tip_sats: number; wallet_hash: string; endpoint: string }
  | { type: 'AUCTION_RESOLVED'; ts: number; window_id: number; results: Array<{ rank: number; request_id: string; tip_sats: number; wallet_hash: string }> }
  | { type: 'UPSTREAM_COMPLETE'; ts: number; request_id: string; latency_ms: number }

interface AuctionStore {
  particles: Map<string, Particle>
  auctionBook: AuctionBid[]
  leaderboard: LeaderboardEntry[]
  lastWindowId: number
  totalVolumeSats: number
  connectedAgents: number
  connected: boolean
  addEvent: (event: AuctionEvent) => void
  setConnected: (v: boolean) => void
}

export const useAuctionStore = create<AuctionStore>((set, get) => ({
  particles: new Map(),
  auctionBook: [],
  leaderboard: [],
  lastWindowId: 0,
  totalVolumeSats: 0,
  connectedAgents: 0,
  connected: false,
  setConnected: (v) => set({ connected: v }),
  addEvent: (event) => {
    const state = get()
    const particles = new Map(state.particles)

    switch (event.type) {
      case 'CHALLENGE_ISSUED': {
        particles.set(event.request_id, {
          requestId: event.request_id,
          state: 1,
          tipSats: 0,
          walletHash: event.ip_hash,
          endpoint: event.endpoint,
          submittedMs: event.ts,
        })
        set({ particles, connectedAgents: state.connectedAgents + 1 })
        break
      }

      case 'BID_RECEIVED': {
        const existing = particles.get(event.request_id)
        particles.set(event.request_id, {
          requestId: event.request_id,
          state: 2,
          tipSats: event.tip_sats,
          walletHash: event.wallet_hash,
          endpoint: event.endpoint,
          submittedMs: event.ts,
          rank: existing?.rank,
        })

        const bids = [...state.auctionBook]
        const existingBidIdx = bids.findIndex(b => b.walletHash === event.wallet_hash)
        const newBid: AuctionBid = {
          rank: existingBidIdx >= 0 ? bids[existingBidIdx].rank : bids.length + 1,
          tipSats: event.tip_sats,
          walletHash: event.wallet_hash,
          submittedMs: event.ts,
        }
        if (existingBidIdx >= 0) {
          bids[existingBidIdx] = newBid
        } else {
          bids.push(newBid)
        }
        bids.sort((a, b) => b.tipSats - a.tipSats)
        bids.forEach((b, i) => { b.rank = i + 1 })

        set({
          particles,
          auctionBook: bids.slice(0, 50),
          totalVolumeSats: state.totalVolumeSats + event.tip_sats,
        })
        break
      }

      case 'AUCTION_RESOLVED': {
        for (const result of event.results) {
          const p = particles.get(result.request_id)
          if (p) {
            particles.set(result.request_id, {
              ...p,
              state: result.rank === 1 ? 3 : 4,
              rank: result.rank,
              tipSats: result.tip_sats,
            })
          }
        }
        set({ particles, lastWindowId: event.window_id, auctionBook: [] })
        break
      }

      case 'UPSTREAM_COMPLETE': {
        const p = particles.get(event.request_id)
        if (p) {
          // Fade to dormant after 2s
          setTimeout(() => {
            const store = get()
            const updated = new Map(store.particles)
            updated.delete(event.request_id)
            set({ particles: updated })
          }, 2000)
        }
        break
      }
    }
  },
}))

const WS_URL = import.meta.env.VITE_GATEWAY_WS
  ? `${import.meta.env.VITE_GATEWAY_WS}/ws/loom`
  : `wss://ghost-layer.onrender.com/ws/loom`

// Ghost Layer MetricsFrame — the native broadcast format from ghost-layer.onrender.com
interface MetricsFrame {
  type: string
  ts: number
  total_bridges: number
  tps: number
  accumulated_fee: string
  chain?: string
  tx_hash?: string
  gross_amount?: string
  fee_amount?: string
  net_amount?: string
  agent_tier?: string
  effective_bps?: number
  state_label?: string
  product_id?: string
  wallet?: string
}

// Translate Ghost Layer MetricsFrame → AuctionEvent so the Loom visualizer
// works when connected to ghost-layer.onrender.com instead of a PNE gateway.
function translateFrame(frame: MetricsFrame): AuctionEvent | null {
  const requestId = frame.tx_hash || frame.product_id || `gl-${frame.ts}`
  const tipAmount = parseInt(frame.fee_amount || frame.accumulated_fee || '0', 10)
  const walletHash = frame.wallet || frame.agent_tier || 'anon'

  switch (frame.type) {
    case 'CONNECTED':
    case 'HEARTBEAT':
      return { type: 'CONNECTED', ts: frame.ts, message: 'Connected to Ghost Layer' }

    case 'AGENT_PROBE':
      return {
        type: 'CHALLENGE_ISSUED',
        ts: frame.ts,
        request_id: requestId,
        ip_hash: frame.tx_hash || 'probe',
        endpoint: '/probe',
      }

    case 'X402_DISPENSED':
      return {
        type: 'BID_RECEIVED',
        ts: frame.ts,
        request_id: requestId,
        tip_sats: tipAmount,
        wallet_hash: walletHash,
        endpoint: frame.product_id || '/x402',
      }

    case 'BRIDGE_SETTLED':
      return {
        type: 'AUCTION_RESOLVED',
        ts: frame.ts,
        window_id: frame.total_bridges,
        results: [{ rank: 1, request_id: requestId, tip_sats: tipAmount, wallet_hash: walletHash }],
      }

    default:
      return null
  }
}

export function useAuctionWebSocket() {
  const addEvent = useAuctionStore(s => s.addEvent)
  const setConnected = useAuctionStore(s => s.setConnected)
  const wsRef = useRef<WebSocket | null>(null)
  const retryDelayRef = useRef(1000)

  useEffect(() => {
    let destroyed = false

    const connect = () => {
      if (destroyed) return
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        retryDelayRef.current = 1000
        ws.send(JSON.stringify({ action: 'subscribe', channels: ['auctions', 'leaderboard'] }))
      }

      ws.onmessage = (e) => {
        try {
          const raw = JSON.parse(e.data)
          // Native PNE AuctionEvent has a known type enum; anything else is a
          // Ghost Layer MetricsFrame that needs translation.
          const knownTypes = new Set(['CONNECTED','CHALLENGE_ISSUED','BID_RECEIVED','AUCTION_RESOLVED','UPSTREAM_COMPLETE'])
          const event: AuctionEvent | null = knownTypes.has(raw.type)
            ? raw as AuctionEvent
            : translateFrame(raw as MetricsFrame)
          if (event) addEvent(event)
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        setConnected(false)
        if (!destroyed) {
          setTimeout(connect, retryDelayRef.current)
          retryDelayRef.current = Math.min(retryDelayRef.current * 2, 30000)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()
    return () => {
      destroyed = true
      wsRef.current?.close()
    }
  }, [addEvent, setConnected])
}
