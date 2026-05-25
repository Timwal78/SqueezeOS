package x402

import (
	"crypto/rand"
	"encoding/hex"
	"time"
)

// Invoice is the response body of POST /v1/x402/quote.
type Invoice struct {
	InvoiceID       string `json:"invoice_id"`
	ProductID       string `json:"product_id"`
	PriceDrops      int64  `json:"price_drops"`
	Currency        string `json:"currency"`
	Destination     string `json:"destination"`
	MemoRequired    string `json:"memo_required"`
	ExpiresAt       int64  `json:"expires_at"`
	AgentTier       string `json:"agent_tier"`
	TierDiscountPct int64  `json:"tier_discount_pct"`
	Token           string `json:"token"`
}

const InvoiceTTL = 5 * time.Minute

// Issue mints a new invoice for productID, signs the token, and returns the
// full Invoice. Caller passes treasury address and HMAC secret from config.
func Issue(productID, wallet, tier string, basePrice int64, treasury, secret string) (Invoice, error) {
	iid := newIID()
	exp := time.Now().Add(InvoiceTTL).Unix()
	price := Price(basePrice, tier)

	tok, err := Sign(Payload{
		Pid: productID, Wlt: wallet, Iid: iid, Exp: exp, Tier: tier,
	}, secret)
	if err != nil {
		return Invoice{}, err
	}

	return Invoice{
		InvoiceID:       iid,
		ProductID:       productID,
		PriceDrops:      price,
		Currency:        "RLUSD",
		Destination:     treasury,
		MemoRequired:    iid,
		ExpiresAt:       exp,
		AgentTier:       tier,
		TierDiscountPct: TierDiscountPct[tier],
		Token:           tok,
	}, nil
}

// newIID returns a 24-char hex random ID. crypto/rand hex over ULID to avoid
// an extra dep — 96 bits of entropy is plenty for nonce uniqueness within a
// 5-min window.
func newIID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
