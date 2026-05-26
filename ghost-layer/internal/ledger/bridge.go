package ledger

import (
	"sync"
)

// BridgeRecord is the complete settlement record for one bridge tx.
// Used by bridge.attestation to build a signed envelope.
type BridgeRecord struct {
	BridgeID          string
	TxHash            string
	Chain             string
	SourceWallet      string
	DestinationWallet string
	GrossAmount       string
	FeeAmount         string
	NetAmount         string
	EffectiveBPS      int64
	AgentTier         string
	SettledAt         int64
}

// Ledger is a bounded in-memory store keyed by tx_hash with FIFO eviction.
type Ledger struct {
	mu         sync.RWMutex
	items      map[string]BridgeRecord
	order      []string // insertion order — index 0 is oldest
	maxRecords int
}

func NewLedger(maxRecords int) *Ledger {
	if maxRecords <= 0 {
		maxRecords = 10000
	}
	return &Ledger{
		items:      make(map[string]BridgeRecord, maxRecords),
		order:      make([]string, 0, maxRecords),
		maxRecords: maxRecords,
	}
}

// Record inserts the record. If size exceeds maxRecords, the oldest is evicted.
// Records for an existing tx_hash overwrite (settle-then-resettle is impossible
// in practice but the overwrite keeps the data consistent).
func (l *Ledger) Record(r BridgeRecord) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if _, exists := l.items[r.TxHash]; !exists {
		l.order = append(l.order, r.TxHash)
		if len(l.order) > l.maxRecords {
			delete(l.items, l.order[0])
			l.order = l.order[1:]
		}
	}
	l.items[r.TxHash] = r
}

func (l *Ledger) Lookup(txHash string) (BridgeRecord, bool) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	r, ok := l.items[txHash]
	return r, ok
}

func (l *Ledger) Size() int {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return len(l.items)
}
