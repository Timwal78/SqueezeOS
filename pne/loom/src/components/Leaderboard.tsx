import { useAuctionStore } from '../hooks/useAuction'

const styles = {
  container: {
    position: 'fixed' as const,
    bottom: 24,
    left: 24,
    width: 300,
    background: 'rgba(10,10,15,0.85)',
    border: '1px solid rgba(139,92,246,0.25)',
    borderRadius: 4,
    padding: '12px 16px',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
    color: '#8B5CF6',
    backdropFilter: 'blur(8px)',
    zIndex: 100,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    marginBottom: 10,
    borderBottom: '1px solid rgba(139,92,246,0.15)',
    paddingBottom: 8,
  },
  title: {
    fontSize: 10,
    letterSpacing: '0.15em',
    textTransform: 'uppercase' as const,
    color: '#8B5CF6',
    opacity: 0.8,
  },
  period: {
    fontSize: 9,
    color: '#00FFE7',
    opacity: 0.6,
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '28px 1fr 80px 50px',
    gap: 4,
    padding: '4px 0',
    borderBottom: '1px solid rgba(139,92,246,0.07)',
    alignItems: 'center',
  },
  rank: {
    color: '#FFD700',
    fontSize: 10,
    fontWeight: 700,
  },
  wallet: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    color: '#00FFE7',
    opacity: 0.8,
    fontSize: 10,
  },
  tips: {
    color: '#FFD700',
    fontSize: 10,
    textAlign: 'right' as const,
  },
  winRate: {
    color: '#8B5CF6',
    fontSize: 10,
    textAlign: 'right' as const,
    opacity: 0.8,
  },
  colHeader: {
    display: 'grid',
    gridTemplateColumns: '28px 1fr 80px 50px',
    gap: 4,
    fontSize: 9,
    opacity: 0.5,
    marginBottom: 4,
  },
  empty: {
    textAlign: 'center' as const,
    opacity: 0.4,
    padding: '12px 0',
    fontSize: 10,
    color: '#8B5CF6',
  },
}

function formatWallet(hash: string): string {
  if (hash.startsWith('sha256:')) return hash.slice(7, 15) + '…'
  return hash.slice(0, 8) + '…'
}

function formatSats(sats: number): string {
  if (sats >= 1_000_000) return `${(sats / 1_000_000).toFixed(1)}M`
  if (sats >= 1_000) return `${(sats / 1_000).toFixed(1)}k`
  return sats.toString()
}

const RANK_COLORS: Record<number, string> = {
  1: '#FFD700',
  2: '#C0C0C0',
  3: '#CD7F32',
}

export default function Leaderboard() {
  const leaderboard = useAuctionStore(s => s.leaderboard)
  const connectedAgents = useAuctionStore(s => s.connectedAgents)

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>Leaderboard of Grace</span>
        <span style={styles.period}>{connectedAgents} agents seen</span>
      </div>

      {leaderboard.length === 0 ? (
        <div style={styles.empty}>awaiting_intent</div>
      ) : (
        <>
          <div style={styles.colHeader}>
            <span>#</span>
            <span>Agent</span>
            <span style={{ textAlign: 'right' }}>Tips (sat)</span>
            <span style={{ textAlign: 'right' }}>Win%</span>
          </div>
          {leaderboard.slice(0, 10).map((entry, i) => (
            <div key={entry.walletHash} style={styles.row}>
              <span style={{ ...styles.rank, color: RANK_COLORS[i + 1] ?? '#8B5CF6' }}>
                {i + 1}
              </span>
              <span style={styles.wallet}>{formatWallet(entry.walletHash)}</span>
              <span style={styles.tips}>{formatSats(entry.totalTipsSats)}</span>
              <span style={styles.winRate}>
                {entry.winRate != null ? `${(entry.winRate * 100).toFixed(0)}%` : '—'}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
