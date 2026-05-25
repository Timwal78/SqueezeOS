package x402

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync"
)

// Product is one entry in the vending catalog.
type Product struct {
	ID         string                          `json:"id"`
	Name       string                          `json:"name"`
	BasePrice  int64                           `json:"base_price_drops"`
	Disabled   bool                            `json:"-"`
	Dispatcher func() (json.RawMessage, error) `json:"-"`
}

// TierDiscountPct maps a loyalty tier to a percent discount on catalog items.
// Mirrors the BPS discount schedule in internal/toll/loyalty.go.
var TierDiscountPct = map[string]int64{
	"BRONZE":   0,
	"SILVER":   5,
	"GOLD":     10,
	"PLATINUM": 20,
	"DIAMOND":  30,
}

// Price applies the tier discount, floored at 1 drop.
func Price(base int64, tier string) int64 {
	d := TierDiscountPct[tier] // unknown tier → 0 discount
	out := base - (base * d / 100)
	if out < 1 {
		return 1
	}
	return out
}

// Registry holds the live product map.
type Registry struct {
	mu    sync.RWMutex
	items map[string]*Product
}

func NewRegistry() *Registry {
	return &Registry{items: map[string]*Product{}}
}

func (r *Registry) Register(p *Product) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.items[p.ID] = p
}

// Lookup returns the product or ErrUnknownProduct / ErrDisabledProduct.
func (r *Registry) Lookup(id string) (*Product, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	p, ok := r.items[id]
	if !ok {
		return nil, ErrUnknownProduct
	}
	if p.Disabled {
		return nil, ErrDisabledProduct
	}
	return p, nil
}

// Listing returns the public product list for /api/config.
func (r *Registry) Listing() []map[string]interface{} {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]map[string]interface{}, 0, len(r.items))
	for _, p := range r.items {
		out = append(out, map[string]interface{}{
			"id":               p.ID,
			"name":             p.Name,
			"base_price_drops": p.BasePrice,
			"available":        !p.Disabled,
		})
	}
	return out
}

var (
	ErrUnknownProduct  = errors.New("ERR_UNKNOWN_PRODUCT")
	ErrDisabledProduct = errors.New("ERR_PRODUCT_DISABLED")
)

// Dispatch runs the product's dispatcher.
func (r *Registry) Dispatch(id string) (json.RawMessage, error) {
	p, err := r.Lookup(id)
	if err != nil {
		return nil, err
	}
	if p.Dispatcher == nil {
		return nil, fmt.Errorf("ERR_NO_DISPATCHER")
	}
	return p.Dispatcher()
}
