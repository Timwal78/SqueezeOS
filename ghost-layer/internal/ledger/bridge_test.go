package ledger

import (
	"fmt"
	"testing"
)

func TestRecordAndLookup(t *testing.T) {
	l := NewLedger(0)
	l.Record(BridgeRecord{TxHash: "tx1", Chain: "xrpl"})
	r, ok := l.Lookup("tx1")
	if !ok || r.Chain != "xrpl" {
		t.Fatalf("lookup tx1: got ok=%v rec=%+v", ok, r)
	}
	_, ok = l.Lookup("nope")
	if ok {
		t.Fatal("lookup of missing tx_hash should return ok=false")
	}
}

func TestEvictionFIFO(t *testing.T) {
	l := NewLedger(3)
	for i := 0; i < 5; i++ {
		l.Record(BridgeRecord{TxHash: fmt.Sprintf("tx%d", i)})
	}
	if l.Size() != 3 {
		t.Fatalf("expected 3 records after 5 inserts, got %d", l.Size())
	}
	// Oldest two (tx0, tx1) should have been evicted.
	for _, gone := range []string{"tx0", "tx1"} {
		if _, ok := l.Lookup(gone); ok {
			t.Errorf("expected %s to be evicted", gone)
		}
	}
	for _, kept := range []string{"tx2", "tx3", "tx4"} {
		if _, ok := l.Lookup(kept); !ok {
			t.Errorf("expected %s to still be present", kept)
		}
	}
}

func TestRecordOverwriteDoesNotDoubleCount(t *testing.T) {
	l := NewLedger(3)
	l.Record(BridgeRecord{TxHash: "tx1", Chain: "xrpl"})
	l.Record(BridgeRecord{TxHash: "tx1", Chain: "base"})
	if l.Size() != 1 {
		t.Fatalf("re-recording same tx_hash should not grow size; got %d", l.Size())
	}
	r, _ := l.Lookup("tx1")
	if r.Chain != "base" {
		t.Errorf("expected overwrite to apply, got chain=%s", r.Chain)
	}
}
