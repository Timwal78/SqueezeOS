package credit

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"
	"time"
)

// tierRank orders loyalty tiers for minimum-tier gate enforcement.
var tierRank = map[string]int{
	"BRONZE":   0,
	"SILVER":   1,
	"GOLD":     2,
	"PLATINUM": 3,
	"DIAMOND":  4,
}

func tierMeetsMinimum(agentTier, minTier string) bool {
	return tierRank[agentTier] >= tierRank[minTier]
}

// Listing is a service offer posted by a seller agent.
type Listing struct {
	ID           string    `json:"id"`
	SellerWallet string    `json:"seller_wallet"`
	Description  string    `json:"description"`
	PriceDrops   uint64    `json:"price_drops"`
	MinBuyerTier string    `json:"min_buyer_tier"`
	TTLSeconds   int       `json:"ttl_seconds"`
	CreatedAt    time.Time `json:"created_at"`
	ExpiresAt    time.Time `json:"expires_at"`
	Active       bool      `json:"active"`
}

// EscrowState is the lifecycle state of a buyer-seller escrow.
type EscrowState string

const (
	StatePendingEscrow EscrowState = "PENDING_ESCROW"
	StateEscrowed      EscrowState = "ESCROWED"
	StateDelivered     EscrowState = "DELIVERED"
	StateReleased      EscrowState = "RELEASED"
	StateCancelled     EscrowState = "CANCELLED"
)

// EscrowRecord tracks one buyer-seller escrow transaction end-to-end.
// Ghost Layer holds the crypto-condition fulfillment (preimage) until the buyer
// confirms delivery, then fires EscrowFinish — funds go escrow → seller directly.
type EscrowRecord struct {
	ID            string      `json:"id"`
	ListingID     string      `json:"listing_id"`
	BuyerWallet   string      `json:"buyer_wallet"`
	SellerWallet  string      `json:"seller_wallet"`
	AmountDrops   uint64      `json:"amount_drops"`
	ConditionHex  string      `json:"condition_hex"`
	OfferSeq      uint32      `json:"offer_sequence,omitempty"`
	State         EscrowState `json:"state"`
	CreatedAt     time.Time   `json:"created_at"`
	ExpiresAt     time.Time   `json:"expires_at"`
	DeliveryProof string      `json:"delivery_proof,omitempty"`
	ReleaseTxHash string      `json:"release_tx_hash,omitempty"`
	preimage      []byte      // held in memory until release, then wiped
}

// Marketplace is the Ghost Layer Agent Credit Marketplace.
// Zero custody: Ghost Layer holds only the crypto-condition preimage. Funds
// are locked in XRPL native escrow between buyer and seller wallets.
type Marketplace struct {
	mu       sync.RWMutex
	listings map[string]*Listing
	escrows  map[string]*EscrowRecord

	agentTier    func(wallet string) string
	escrowFinish func(owner string, offerSeq uint32, condition, fulfillment []byte) (string, error)
	escrowCancel func(owner string, offerSeq uint32) (string, error)
	recordVolume func(wallet string, drops uint64)
}

// NewMarketplace creates an in-memory marketplace wired to the caller's XRPL
// client and loyalty ledger via the four injected functions.
func NewMarketplace(
	agentTier func(string) string,
	escrowFinish func(string, uint32, []byte, []byte) (string, error),
	escrowCancel func(string, uint32) (string, error),
	recordVolume func(string, uint64),
) *Marketplace {
	return &Marketplace{
		listings:     make(map[string]*Listing),
		escrows:      make(map[string]*EscrowRecord),
		agentTier:    agentTier,
		escrowFinish: escrowFinish,
		escrowCancel: escrowCancel,
		recordVolume: recordVolume,
	}
}

// PostListing creates a new service offer. Any wallet can list; min_buyer_tier
// gates which buyers can respond.
func (m *Marketplace) PostListing(sellerWallet, description string, priceDrops uint64, minBuyerTier string, ttlSeconds int) (*Listing, error) {
	if sellerWallet == "" {
		return nil, errors.New("ERR_SELLER_WALLET_REQUIRED")
	}
	if description == "" || len(description) > 500 {
		return nil, errors.New("ERR_DESCRIPTION_INVALID")
	}
	if priceDrops == 0 {
		return nil, errors.New("ERR_PRICE_REQUIRED")
	}
	if _, ok := tierRank[minBuyerTier]; !ok {
		minBuyerTier = "BRONZE"
	}
	if ttlSeconds <= 0 || ttlSeconds > 86400*30 {
		ttlSeconds = 3600
	}

	id := randomID()
	now := time.Now()
	listing := &Listing{
		ID:           id,
		SellerWallet: sellerWallet,
		Description:  description,
		PriceDrops:   priceDrops,
		MinBuyerTier: minBuyerTier,
		TTLSeconds:   ttlSeconds,
		CreatedAt:    now,
		ExpiresAt:    now.Add(time.Duration(ttlSeconds) * time.Second),
		Active:       true,
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.listings) >= 500 {
		return nil, errors.New("ERR_MARKETPLACE_FULL")
	}
	m.listings[id] = listing
	return listing, nil
}

// GetListings returns active, non-expired listings the buyer can access.
// Pass empty buyerTier to return all listings regardless of gate.
func (m *Marketplace) GetListings(buyerTier string) []*Listing {
	now := time.Now()
	m.mu.RLock()
	defer m.mu.RUnlock()

	var out []*Listing
	for _, l := range m.listings {
		if !l.Active || now.After(l.ExpiresAt) {
			continue
		}
		if buyerTier != "" && !tierMeetsMinimum(buyerTier, l.MinBuyerTier) {
			continue
		}
		out = append(out, l)
	}
	return out
}

// QuoteResult carries the escrow parameters for the buyer to create an XRPL EscrowCreate.
type QuoteResult struct {
	EscrowID       string `json:"escrow_id"`
	ListingID      string `json:"listing_id"`
	SellerWallet   string `json:"seller_wallet"`
	AmountDrops    uint64 `json:"amount_drops"`
	ConditionHex   string `json:"condition_hex"`
	FulfillmentHex string `json:"fulfillment_hex"`
	ExpiresAt      string `json:"expires_at"`
	ExpiresAtUnix  int64  `json:"expires_at_unix"`
	Instructions   string `json:"instructions"`
}

// Quote issues an escrow quote for a listing, enforcing the min_buyer_tier gate.
// The returned condition_hex goes in the buyer's EscrowCreate; Ghost Layer holds
// the matching fulfillment until Release() is called.
func (m *Marketplace) Quote(listingID, buyerWallet string) (*QuoteResult, error) {
	if buyerWallet == "" {
		return nil, errors.New("ERR_BUYER_WALLET_REQUIRED")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	listing, ok := m.listings[listingID]
	if !ok || !listing.Active || time.Now().After(listing.ExpiresAt) {
		return nil, errors.New("ERR_LISTING_NOT_FOUND")
	}
	if listing.SellerWallet == buyerWallet {
		return nil, errors.New("ERR_CANNOT_BUY_OWN_LISTING")
	}

	buyerTier := m.agentTier(buyerWallet)
	if !tierMeetsMinimum(buyerTier, listing.MinBuyerTier) {
		return nil, fmt.Errorf("ERR_TIER_INSUFFICIENT: need %s, have %s", listing.MinBuyerTier, buyerTier)
	}

	preimage := make([]byte, 32)
	if _, err := rand.Read(preimage); err != nil {
		return nil, errors.New("ERR_ENTROPY")
	}
	condition := preimageCondition(preimage)
	fulfillment := preimageFullfillment(preimage)

	escrowID := randomID()
	now := time.Now()
	exp := now.Add(time.Duration(listing.TTLSeconds) * time.Second)

	rec := &EscrowRecord{
		ID:           escrowID,
		ListingID:    listingID,
		BuyerWallet:  buyerWallet,
		SellerWallet: listing.SellerWallet,
		AmountDrops:  listing.PriceDrops,
		ConditionHex: hex.EncodeToString(condition),
		preimage:     preimage,
		State:        StatePendingEscrow,
		CreatedAt:    now,
		ExpiresAt:    exp,
	}
	m.escrows[escrowID] = rec

	return &QuoteResult{
		EscrowID:       escrowID,
		ListingID:      listingID,
		SellerWallet:   listing.SellerWallet,
		AmountDrops:    listing.PriceDrops,
		ConditionHex:   hex.EncodeToString(condition),
		FulfillmentHex: hex.EncodeToString(fulfillment),
		ExpiresAt:      exp.UTC().Format(time.RFC3339),
		ExpiresAtUnix:  exp.Unix(),
		Instructions: "1. Submit XRPL EscrowCreate: Destination=seller_wallet, Amount=amount_drops, " +
			"Condition=condition_hex, CancelAfter=expires_at_unix. " +
			"2. Call POST /v1/credit/escrow/register with your escrow_id and the OfferSequence of the EscrowCreate tx.",
	}, nil
}

// RegisterEscrow records the on-chain EscrowCreate sequence number from the buyer.
// Transitions state from PENDING_ESCROW → ESCROWED.
func (m *Marketplace) RegisterEscrow(escrowID string, offerSeq uint32) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	rec, ok := m.escrows[escrowID]
	if !ok {
		return errors.New("ERR_ESCROW_NOT_FOUND")
	}
	if rec.State != StatePendingEscrow {
		return fmt.Errorf("ERR_INVALID_STATE: expected PENDING_ESCROW, got %s", rec.State)
	}
	if time.Now().After(rec.ExpiresAt) {
		rec.State = StateCancelled
		return errors.New("ERR_ESCROW_EXPIRED")
	}
	rec.OfferSeq = offerSeq
	rec.State = StateEscrowed
	return nil
}

// MarkDelivered is called by the seller to signal service delivery.
// Transitions ESCROWED → DELIVERED.
func (m *Marketplace) MarkDelivered(escrowID, sellerWallet, deliveryProof string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	rec, ok := m.escrows[escrowID]
	if !ok {
		return errors.New("ERR_ESCROW_NOT_FOUND")
	}
	if rec.SellerWallet != sellerWallet {
		return errors.New("ERR_NOT_SELLER")
	}
	if rec.State != StateEscrowed {
		return fmt.Errorf("ERR_INVALID_STATE: expected ESCROWED, got %s", rec.State)
	}
	rec.State = StateDelivered
	rec.DeliveryProof = deliveryProof
	return nil
}

// Release confirms delivery and fires EscrowFinish. Funds flow escrow → seller.
// Ghost Layer never holds funds — it only knows the fulfillment preimage.
// Returns the EscrowFinish transaction hash.
func (m *Marketplace) Release(escrowID, buyerWallet string) (string, error) {
	m.mu.Lock()
	rec, ok := m.escrows[escrowID]
	if !ok {
		m.mu.Unlock()
		return "", errors.New("ERR_ESCROW_NOT_FOUND")
	}
	if rec.BuyerWallet != buyerWallet {
		m.mu.Unlock()
		return "", errors.New("ERR_NOT_BUYER")
	}
	if rec.State != StateDelivered && rec.State != StateEscrowed {
		m.mu.Unlock()
		return "", fmt.Errorf("ERR_INVALID_STATE: got %s", rec.State)
	}
	owner := rec.BuyerWallet
	offerSeq := rec.OfferSeq
	conditionBytes, _ := hex.DecodeString(rec.ConditionHex)
	preimage := make([]byte, len(rec.preimage))
	copy(preimage, rec.preimage)
	fulfillment := preimageFullfillment(preimage)
	seller := rec.SellerWallet
	amount := rec.AmountDrops
	m.mu.Unlock()

	txHash, err := m.escrowFinish(owner, offerSeq, conditionBytes, fulfillment)
	if err != nil {
		return "", fmt.Errorf("ERR_ESCROW_FINISH: %w", err)
	}

	m.mu.Lock()
	rec.State = StateReleased
	rec.ReleaseTxHash = txHash
	rec.preimage = nil
	m.mu.Unlock()

	// Both parties earn volume credit — builds loyalty tier through marketplace activity.
	m.recordVolume(seller, amount)
	m.recordVolume(buyerWallet, amount)

	return txHash, nil
}

// Cancel fires EscrowCancel, returning funds to the buyer. Can be called by either
// participant or automatically by CleanupExpired() on TTL breach.
func (m *Marketplace) Cancel(escrowID, callerWallet string) (string, error) {
	m.mu.Lock()
	rec, ok := m.escrows[escrowID]
	if !ok {
		m.mu.Unlock()
		return "", errors.New("ERR_ESCROW_NOT_FOUND")
	}
	if rec.BuyerWallet != callerWallet && rec.SellerWallet != callerWallet {
		m.mu.Unlock()
		return "", errors.New("ERR_NOT_PARTICIPANT")
	}
	if rec.State == StateReleased || rec.State == StateCancelled {
		m.mu.Unlock()
		return "", fmt.Errorf("ERR_ALREADY_FINAL: %s", rec.State)
	}
	if rec.State == StatePendingEscrow {
		rec.State = StateCancelled
		rec.preimage = nil
		m.mu.Unlock()
		return "no_onchain_escrow", nil
	}
	owner := rec.BuyerWallet
	offerSeq := rec.OfferSeq
	m.mu.Unlock()

	txHash, err := m.escrowCancel(owner, offerSeq)
	if err != nil {
		return "", fmt.Errorf("ERR_ESCROW_CANCEL: %w", err)
	}

	m.mu.Lock()
	rec.State = StateCancelled
	rec.preimage = nil
	m.mu.Unlock()

	return txHash, nil
}

// GetEscrow returns a public view of an escrow (preimage excluded).
func (m *Marketplace) GetEscrow(escrowID string) (*EscrowRecord, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	rec, ok := m.escrows[escrowID]
	return rec, ok
}

// CleanupExpired fires EscrowCancel on all TTL-breached, unfinalised escrows.
// Run from a background goroutine.
func (m *Marketplace) CleanupExpired() {
	now := time.Now()
	m.mu.RLock()
	var toCancel []string
	for id, rec := range m.escrows {
		active := rec.State == StateEscrowed || rec.State == StateDelivered || rec.State == StatePendingEscrow
		if active && now.After(rec.ExpiresAt) {
			toCancel = append(toCancel, id)
		}
	}
	m.mu.RUnlock()

	for _, id := range toCancel {
		m.mu.RLock()
		rec, ok := m.escrows[id]
		m.mu.RUnlock()
		if !ok {
			continue
		}
		if rec.State == StatePendingEscrow {
			m.mu.Lock()
			rec.State = StateCancelled
			rec.preimage = nil
			m.mu.Unlock()
			continue
		}
		owner := rec.BuyerWallet
		offerSeq := rec.OfferSeq
		if txHash, err := m.escrowCancel(owner, offerSeq); err == nil {
			m.mu.Lock()
			rec.State = StateCancelled
			rec.ReleaseTxHash = txHash
			rec.preimage = nil
			m.mu.Unlock()
		}
	}
}

// ── PREIMAGE-SHA-256 Crypto-Conditions (RFC 3547 / draft-thomas-crypto-conditions)
// These are the only condition type XRPL EscrowCreate/Finish supports natively.

// preimageCondition builds a 40-byte PREIMAGE-SHA-256 condition:
//
//	A0 26 80 20 [sha256(preimage) 32 bytes] 81 02 00 20
func preimageCondition(preimage []byte) []byte {
	h := sha256.Sum256(preimage)
	out := make([]byte, 0, 40)
	out = append(out, 0xA0, 0x26, 0x80, 0x20)
	out = append(out, h[:]...)
	out = append(out, 0x81, 0x02, 0x00, 0x20)
	return out
}

// preimageFullfillment builds a 36-byte PREIMAGE-SHA-256 fulfillment:
//
//	A0 22 80 20 [preimage 32 bytes]
func preimageFullfillment(preimage []byte) []byte {
	out := make([]byte, 0, 36)
	out = append(out, 0xA0, 0x22, 0x80, 0x20)
	return append(out, preimage...)
}

func randomID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
