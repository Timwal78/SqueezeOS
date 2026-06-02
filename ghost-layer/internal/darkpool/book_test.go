package darkpool

import (
	"testing"
	"time"
)

func newOrder(wallet, side, drops, limit string) *Order {
	return &Order{
		Wallet:      wallet,
		Pair:        "XRP/RLUSD",
		Side:        Side(side),
		AmountDrops: drops,
		LimitPrice:  limit,
		ExpiresAt:   time.Now().Add(1 * time.Hour),
	}
}

func TestSubmit_NoMatch(t *testing.T) {
	b := NewBook()
	match, err := b.Submit(newOrder("rBuyer111111111111111111111", "BUY", "10000000", "0.50"))
	if err != nil { t.Fatalf("unexpected error: %v", err) }
	if match != nil { t.Error("expected no match for first order") }
}

func TestSubmit_Match(t *testing.T) {
	b := NewBook()
	_, _ = b.Submit(newOrder("rSeller11111111111111111111", "SELL", "10000000", "0.50"))
	match, err := b.Submit(newOrder("rBuyer111111111111111111111", "BUY", "10000000", "0.55"))
	if err != nil { t.Fatalf("unexpected error: %v", err) }
	if match == nil { t.Fatal("expected a match") }
	if match.BuyWallet != "rBuyer111111111111111111111"  { t.Errorf("wrong buyer: %s", match.BuyWallet) }
	if match.SellWallet != "rSeller11111111111111111111" { t.Errorf("wrong seller: %s", match.SellWallet) }
	if match.AmountDrops != "10000000" { t.Errorf("wrong amount: %s", match.AmountDrops) }
}

func TestSubmit_NoSelfMatch(t *testing.T) {
	b := NewBook()
	_, _ = b.Submit(newOrder("rSameWallet1111111111111111", "SELL", "10000000", "0.50"))
	match, err := b.Submit(newOrder("rSameWallet1111111111111111", "BUY", "10000000", "0.55"))
	if err != nil { t.Fatalf("unexpected error: %v", err) }
	if match != nil { t.Error("self-match must be rejected") }
}

func TestSubmit_PriceMismatch(t *testing.T) {
	b := NewBook()
	_, _ = b.Submit(newOrder("rSeller11111111111111111111", "SELL", "10000000", "0.60"))
	match, _ := b.Submit(newOrder("rBuyer111111111111111111111", "BUY", "10000000", "0.50"))
	if match != nil { t.Error("price mismatch should not match") }
}

func TestCancel(t *testing.T) {
	b := NewBook()
	_, _ = b.Submit(newOrder("rWallet11111111111111111111", "BUY", "10000000", "0.50"))
	orders := b.ListOpen("rWallet11111111111111111111")
	if len(orders) != 1 { t.Fatalf("expected 1 order, got %d", len(orders)) }
	err := b.Cancel(orders[0].ID, "rWallet11111111111111111111")
	if err != nil { t.Errorf("cancel failed: %v", err) }
	if len(b.ListOpen("rWallet11111111111111111111")) != 0 { t.Error("order should be cancelled") }
}

func TestMinimumSize(t *testing.T) {
	b := NewBook()
	_, err := b.Submit(newOrder("rWallet11111111111111111111", "BUY", "999999", "0.50"))
	if err == nil { t.Error("expected error for sub-minimum order") }
}
