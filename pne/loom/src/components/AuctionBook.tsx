import React, { useEffect, useRef } from 'react'
import { useAuctionStore, AuctionBid } from '../hooks/useAuction'

const styles = {
  container: {
    position: 'fixed' as const,
    top: 24,
    right: 24,
    width: 280,
    background: 'rgba(10,10,15,0.85)',
    border: '1px solid rgba(0,255,231,0.2)',
    borderRadius: 4,
    padding: '12px 16px',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
    color: '#00FFE7',
    backdropFilter: 'blur(8px)',
    zIndex: 100,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
    borderBottom: '1px solid rgba(0,255,231,0.15)',
    paddingBottom: 8,
  },
  title: {
    fontSize: 10,
    letterSpacing: '0.15em',
    textTransform: 'uppercase' as const,
    color: '#00FFE7',
    opacity: 0.7,
  },
  windowBadge: {
    fontSize: 9,
    color: '#FFD700',
    opacity: 0.8,
  },
  bidRow: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '4px 0',
    borderBottom: '1px solid rgba(0,255,231,0.05)',
    transition: 'opacity 0.3s',
  },
  rank: {
    color: '#FFD700',
    minWidth: 24,
    fontSize: 10,
  },
  wallet: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    opacity: 0.7,
    fontSize: 10,
  },
  tip: {
    color: '#00FFE7',
    fontWeight: 600,
    marginLeft: 8,
    fontSize: 10,
  },
  empty: {
    textAlign: 'center' as const,
    opacity: 0.4,
    padding: '16px 0',
    fontSize: 10,
  },
  totalVolume: {
    marginTop: 8,
    display: 'flex',
    justifyContent: 'space-between',
    borderTop: '1px solid rgba(0,255,231,0.15)',
    paddingTop: 8,
    opacity: 0.7,
    fontSize: 10,
  },
}

function formatWallet(hash: string): string {
  if (hash.startsWith('sha256:')) {
    return hash.slice(7, 15) + '…'
  }
  return hash.slice(0, 8) + '…'
}

function formatSats(sats: number): string {
  if (sats >= 1_000_000) return `${(sats / 1_000_000).toFixed(1)}M`
  if (sats >= 1_000) return `${(sats / 1_000).toFixed(1)}k`
  return sats.toString()
}

export default function AuctionBook() {
  const auctionBook = useAuctionStore(s => s.auctionBook)
  const totalVolumeSats = useAuctionStore(s => s.totalVolumeSats)
  const lastWindowId = useAuctionStore(s => s.lastWindowId)
  const connected = useAuctionStore(s => s.connected)

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>Intent Auction</span>
        <span style={styles.windowBadge}>
          {connected ? '● LIVE' : '○ CONNECTING'}
        </span>
      </div>

      {auctionBook.length === 0 ? (
        <div style={styles.empty}>awaiting_intent</div>
      ) : (
        auctionBook.slice(0, 10).map((bid, i) => (
          <div key={bid.walletHash} style={styles.bidRow}>
            <span style={{ ...styles.rank, color: i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : '#CD7F32' }}>
              #{bid.rank}
            </span>
            <span style={styles.wallet}>{formatWallet(bid.walletHash)}</span>
            <span style={styles.tip}>{formatSats(bid.tipSats)} sat</span>
          </div>
        ))
      )}

      <div style={styles.totalVolume}>
        <span>24h Volume</span>
        <span style={{ color: '#FFD700' }}>{formatSats(totalVolumeSats)} sat</span>
      </div>

      {lastWindowId > 0 && (
        <div style={{ ...styles.totalVolume, borderTop: 'none', paddingTop: 2 }}>
          <span>Last Window</span>
          <span style={{ color: '#00FFE7', opacity: 0.5 }}>
            #{lastWindowId.toString().slice(-6)}
          </span>
        </div>
      )}
    </div>
  )
}
