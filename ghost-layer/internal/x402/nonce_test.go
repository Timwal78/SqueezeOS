package x402

import (
	"testing"
	"time"
)

func TestNonceFreshThenReplay(t *testing.T) {
	c := NewNonceCache()
	exp := time.Now().Add(time.Minute).Unix()
	if !c.Consume("iid-1", exp) {
		t.Fatal("first consume should succeed")
	}
	if c.Consume("iid-1", exp) {
		t.Fatal("second consume of same iid must be rejected")
	}
}

func TestNonceSweepRemovesExpired(t *testing.T) {
	c := &NonceCache{items: map[string]int64{}}
	c.Consume("old", time.Now().Add(-10*time.Second).Unix())
	c.Consume("new", time.Now().Add(10*time.Second).Unix())
	c.sweepOnce(time.Now().Unix())
	if c.Size() != 1 {
		t.Fatalf("expected 1 entry after sweep, got %d", c.Size())
	}
}
