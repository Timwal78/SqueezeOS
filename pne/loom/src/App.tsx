import Loom from './components/Loom'
import AuctionBook from './components/AuctionBook'
import Leaderboard from './components/Leaderboard'
import { useAuctionWebSocket, useAuctionStore } from './hooks/useAuction'

const styles = {
  root: {
    width: '100vw',
    height: '100vh',
    background: '#0A0A0F',
    overflow: 'hidden',
    position: 'relative' as const,
  },
  title: {
    position: 'fixed' as const,
    top: 24,
    left: 24,
    zIndex: 100,
    fontFamily: "'Space Mono', monospace",
    pointerEvents: 'none' as const,
  },
  titleMain: {
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: '0.08em',
    color: '#FFD700',
    textShadow: '0 0 20px rgba(255,215,0,0.4)',
  },
  titleSub: {
    fontSize: 11,
    color: '#00FFE7',
    opacity: 0.6,
    letterSpacing: '0.2em',
    marginTop: 2,
  },
  statusBar: {
    position: 'fixed' as const,
    bottom: 24,
    right: 24,
    zIndex: 100,
    textAlign: 'right' as const,
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 10,
    color: '#00FFE7',
    opacity: 0.5,
    pointerEvents: 'none' as const,
  },
  particleCount: {
    position: 'fixed' as const,
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    zIndex: 50,
    fontFamily: "'Space Mono', monospace",
    fontSize: 64,
    fontWeight: 700,
    color: 'rgba(255,215,0,0.06)',
    pointerEvents: 'none' as const,
    letterSpacing: '0.1em',
    userSelect: 'none' as const,
  },
}

function StatusBar() {
  const connected = useAuctionStore(s => s.connected)
  const totalVolumeSats = useAuctionStore(s => s.totalVolumeSats)

  return (
    <div style={styles.statusBar}>
      <div>{connected ? '● SOVEREIGN AUCTION ACTIVE' : '○ AWAITING CONNECTION'}</div>
      <div style={{ marginTop: 2 }}>
        {totalVolumeSats > 0 ? `${totalVolumeSats.toLocaleString()} sat total volume` : 'no volume yet'}
      </div>
    </div>
  )
}

export default function App() {
  useAuctionWebSocket()

  const particles = useAuctionStore(s => s.particles)
  const activeCount = Array.from(particles.values()).filter(p => p.state > 0).length

  return (
    <div style={styles.root}>
      {/* Three.js canvas fills entire background */}
      <Loom />

      {/* Watermark particle count */}
      {activeCount > 0 && (
        <div style={styles.particleCount}>{activeCount}</div>
      )}

      {/* Title */}
      <div style={styles.title}>
        <div style={styles.titleMain}>NEURAL EXCHEQUER</div>
        <div style={styles.titleSub}>SOVEREIGN INTENT AUCTION</div>
      </div>

      {/* Right overlay: live auction book */}
      <AuctionBook />

      {/* Left overlay: agent leaderboard */}
      <Leaderboard />

      {/* Status bar */}
      <StatusBar />
    </div>
  )
}
