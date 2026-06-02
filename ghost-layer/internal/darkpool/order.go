// Package darkpool implements NEXUS402's private order matching engine.
// Institutions submit signed trade intents off-chain. Ghost Layer matches them
// silently and settles atomically on XRPL. No public order book exposure.
package darkpool

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"time"
)

// Side is buy or sell.
type Side string

const (
	SideBuy  Side = "BUY"
	SideSell Side = "SELL"
)

// Order is a private trade intent submitted by an institution.
type Order struct {
	ID           string    `json:"id"`
	Wallet       string    `json:"wallet"`
	Pair         string    `json:"pair"`
	Side         Side      `json:"side"`
	AmountDrops  string    `json:"amount_drops"`
	LimitPrice   string    `json:"limit_price"`
	Signature    string    `json:"signature"`
	SubmittedAt  time.Time `json:"submitted_at"`
	ExpiresAt    time.Time `json:"expires_at"`
	Status       string    `json:"status"` // "open" | "matched" | "expired" | "cancelled"
	MatchedWith  string    `json:"matched_with,omitempty"`
	SettlementTx string    `json:"settlement_tx,omitempty"`
}

// CanonicalString is the deterministic string the institution must sign.
func CanonicalString(wallet, pair, side, amountDrops, limitPrice string, expiresAt time.Time) string {
	return fmt.Sprintf("NEXUS402:DARKPOOL:%s:%s:%s:%s:%s:%d",
		wallet, pair, side, amountDrops, limitPrice, expiresAt.Unix())
}

// OrderID computes a deterministic short ID from the canonical string.
func OrderID(canonical string) string {
	h := sha256.Sum256([]byte(canonical))
	return hex.EncodeToString(h[:8])
}

// ValidateOrder checks required fields and sanity bounds.
func ValidateOrder(o *Order) error {
	if o.Wallet == "" || len(o.Wallet) < 25 {
		return errors.New("invalid wallet address")
	}
	if o.Pair == "" {
		return errors.New("pair required (e.g. XRP/RLUSD)")
	}
	if o.Side != SideBuy && o.Side != SideSell {
		return errors.New("side must be BUY or SELL")
	}
	if o.AmountDrops == "" {
		return errors.New("amount_drops required")
	}
	amt, err := strconv.ParseInt(o.AmountDrops, 10, 64)
	if err != nil || amt <= 0 {
		return errors.New("amount_drops must be a positive integer")
	}
	if amt < 1_000_000 {
		return errors.New("minimum order size is 1 XRP (1000000 drops)")
	}
	if o.ExpiresAt.IsZero() || o.ExpiresAt.Before(time.Now()) {
		return errors.New("expires_at must be a future timestamp")
	}
	if o.ExpiresAt.After(time.Now().Add(24 * time.Hour)) {
		return errors.New("maximum order TTL is 24 hours")
	}
	return nil
}
