package x402

import (
	"sync"
	"time"
)

// NonceCache tracks consumed invoice IDs (iid) with per-entry TTL.
// Replay attempts return false from Consume.
type NonceCache struct {
	mu    sync.Mutex
	items map[string]int64 // iid → unix expiry
}

func NewNonceCache() *NonceCache {
	c := &NonceCache{items: make(map[string]int64)}
	go c.sweepLoop()
	return c
}

// Consume returns true if iid is fresh and records it; false if already seen.
// expiry is unix seconds — entry is removed after that point.
func (c *NonceCache) Consume(iid string, expiry int64) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, seen := c.items[iid]; seen {
		return false
	}
	c.items[iid] = expiry
	return true
}

// Size returns the current count. Test-only helper.
func (c *NonceCache) Size() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.items)
}

func (c *NonceCache) sweepLoop() {
	t := time.NewTicker(60 * time.Second)
	defer t.Stop()
	for range t.C {
		c.sweepOnce(time.Now().Unix())
	}
}

func (c *NonceCache) sweepOnce(now int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for k, exp := range c.items {
		if exp < now {
			delete(c.items, k)
		}
	}
}
