package darkpool

import (
	"fmt"
	"strconv"
	"sync"
	"time"
)

// MatchResult is returned when two orders are paired.
type MatchResult struct {
	BuyOrderID  string
	SellOrderID string
	BuyWallet   string
	SellWallet  string
	Pair        string
	AmountDrops string
	FeeBPS      int64
}

// Book is a concurrency-safe in-memory dark pool order book.
type Book struct {
	mu     sync.RWMutex
	orders map[string]*Order
}

// NewBook creates an empty order book.
func NewBook() *Book {
	return &Book{orders: make(map[string]*Order)}
}

// Submit adds an order and attempts immediate FIFO price-time matching.
func (b *Book) Submit(o *Order) (*MatchResult, error) {
	if err := ValidateOrder(o); err != nil {
		return nil, err
	}
	canonical := CanonicalString(o.Wallet, o.Pair, string(o.Side), o.AmountDrops, o.LimitPrice, o.ExpiresAt)
	o.ID = OrderID(canonical)
	o.SubmittedAt = time.Now()
	o.Status = "open"

	b.mu.Lock()
	defer b.mu.Unlock()

	if _, exists := b.orders[o.ID]; exists {
		return nil, fmt.Errorf("duplicate order ID %s", o.ID)
	}
	b.orders[o.ID] = o
	return b.matchLocked(o)
}

func (b *Book) matchLocked(o *Order) (*MatchResult, error) {
	counterSide := SideSell
	if o.Side == SideSell {
		counterSide = SideBuy
	}
	var best *Order
	for _, candidate := range b.orders {
		if candidate.Status != "open"                  { continue }
		if candidate.ID == o.ID                        { continue }
		if candidate.Pair != o.Pair                    { continue }
		if candidate.Side != counterSide               { continue }
		if candidate.Wallet == o.Wallet                { continue }
		if candidate.ExpiresAt.Before(time.Now())      { continue }
		if !pricesMatch(o, candidate)                  { continue }
		if best == nil || candidate.SubmittedAt.Before(best.SubmittedAt) {
			best = candidate
		}
	}
	if best == nil {
		return nil, nil
	}
	settled := minDrops(o.AmountDrops, best.AmountDrops)
	o.Status = "matched"
	o.MatchedWith = best.ID
	best.Status = "matched"
	best.MatchedWith = o.ID

	buy, sell := o, best
	if o.Side == SideSell {
		buy, sell = best, o
	}
	return &MatchResult{
		BuyOrderID:  buy.ID,
		SellOrderID: sell.ID,
		BuyWallet:   buy.Wallet,
		SellWallet:  sell.Wallet,
		Pair:        o.Pair,
		AmountDrops: settled,
		FeeBPS:      5,
	}, nil
}

// Cancel marks an order cancelled if it belongs to the given wallet.
func (b *Book) Cancel(orderID, wallet string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	o, ok := b.orders[orderID]
	if !ok {
		return fmt.Errorf("order %s not found", orderID)
	}
	if o.Wallet != wallet {
		return fmt.Errorf("order does not belong to wallet")
	}
	if o.Status != "open" {
		return fmt.Errorf("order is %s — cannot cancel", o.Status)
	}
	o.Status = "cancelled"
	return nil
}

// ListOpen returns open orders for a given wallet.
func (b *Book) ListOpen(wallet string) []*Order {
	b.mu.RLock()
	defer b.mu.RUnlock()
	b.sweepExpiredLocked()
	var result []*Order
	for _, o := range b.orders {
		if o.Wallet == wallet && o.Status == "open" {
			result = append(result, o)
		}
	}
	return result
}

// Depth returns public aggregate depth — no wallet info exposed.
func (b *Book) Depth(pair string) map[string]interface{} {
	b.mu.RLock()
	defer b.mu.RUnlock()
	b.sweepExpiredLocked()
	buyCount, sellCount := 0, 0
	var buyDrops, sellDrops int64
	for _, o := range b.orders {
		if o.Pair != pair || o.Status != "open" { continue }
		drops, _ := strconv.ParseInt(o.AmountDrops, 10, 64)
		if o.Side == SideBuy  { buyCount++;  buyDrops  += drops }
		if o.Side == SideSell { sellCount++; sellDrops += drops }
	}
	return map[string]interface{}{
		"pair":              pair,
		"buy_orders":        buyCount,
		"sell_orders":       sellCount,
		"buy_volume_drops":  fmt.Sprintf("%d", buyDrops),
		"sell_volume_drops": fmt.Sprintf("%d", sellDrops),
		"note":              "Individual orders are private — NEXUS402 Ghost Layer shows aggregate depth only",
		"powered_by":        "NEXUS402 Dark Pool",
	}
}

func (b *Book) sweepExpiredLocked() {
	now := time.Now()
	for _, o := range b.orders {
		if o.Status == "open" && o.ExpiresAt.Before(now) {
			o.Status = "expired"
		}
	}
}

func pricesMatch(a, b *Order) bool {
	if a.LimitPrice == "" || b.LimitPrice == "" {
		return true
	}
	ap, errA := strconv.ParseFloat(a.LimitPrice, 64)
	bp, errB := strconv.ParseFloat(b.LimitPrice, 64)
	if errA != nil || errB != nil {
		return true
	}
	buyer, seller := ap, bp
	if a.Side == SideSell {
		buyer, seller = bp, ap
	}
	return buyer >= seller
}

func minDrops(a, b string) string {
	ai, _ := strconv.ParseInt(a, 10, 64)
	bi, _ := strconv.ParseInt(b, 10, 64)
	if ai < bi { return a }
	return b
}
