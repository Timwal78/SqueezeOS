package invoice

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"proof402/internal/models"
)

const (
	InvoiceTTL = 5 * time.Minute
	TokenTTL   = 1 * time.Hour
)

func New(ep *models.Endpoint, payTo string) *models.Invoice {
	id := uuid.New().String()
	now := time.Now()
	memoHex := strings.ToUpper(hex.EncodeToString([]byte(id)))
	return &models.Invoice{
		ID:         id,
		EndpointID: ep.ID,
		MerchantID: ep.MerchantID,
		Path:       ep.Path,
		Price:      ep.Price,
		Asset:      ep.Asset,
		Network:    "XRPL",
		PayTo:      payTo,
		MemoHex:    memoHex,
		ExpiresAt:  now.Add(InvoiceTTL),
		CreatedAt:  now,
		Status:     "pending",
	}
}

// NewBase creates a USDC-on-Base invoice. Price is the same decimal amount
// as the RLUSD endpoint price (1:1 USD peg). PayTo is the Ghost Layer ETH address.
// MemoHex encodes the invoice ID as hex — agents that support calldata memos
// should include it; verification falls back to amount+destination matching.
func NewBase(ep *models.Endpoint, ghostLayerETH string) *models.Invoice {
	id := uuid.New().String()
	now := time.Now()
	memoHex := strings.ToUpper(hex.EncodeToString([]byte(id)))
	return &models.Invoice{
		ID:         id,
		EndpointID: ep.ID,
		MerchantID: ep.MerchantID,
		Path:       ep.Path,
		Price:      ep.Price,
		Asset:      "USDC",
		Network:    "Base",
		PayTo:      ghostLayerETH,
		MemoHex:    memoHex,
		ExpiresAt:  now.Add(InvoiceTTL),
		CreatedAt:  now,
		Status:     "pending",
	}
}

func IsExpired(inv *models.Invoice) bool {
	return time.Now().After(inv.ExpiresAt)
}

// TokenClaims holds the verified claims extracted from an access token.
type TokenClaims struct {
	EndpointID string // eid — which endpoint this token unlocks
	WalletAddr string // wlt — XRPL classic address of the paying wallet
	InvoiceID  string // iid — invoice that originated this token
}

type tokenPayload struct {
	InvoiceID  string `json:"iid"`
	EndpointID string `json:"eid"`
	WalletAddr string `json:"wlt"` // bound paying wallet — prevents token sharing
	IssuedAt   int64  `json:"iat"`
	ExpiresAt  int64  `json:"exp"`
}

// IssueToken mints a signed JWT-style access token bound to the paying wallet.
// Tokens encode the wallet address so middleware can reject cross-wallet reuse.
func IssueToken(inv *models.Invoice, secret, walletAddr string) (string, error) {
	if secret == "" {
		return "", errors.New("token secret not configured")
	}
	payload := tokenPayload{
		InvoiceID:  inv.ID,
		EndpointID: inv.EndpointID,
		WalletAddr: walletAddr,
		IssuedAt:   time.Now().Unix(),
		ExpiresAt:  time.Now().Add(TokenTTL).Unix(),
	}
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	encoded := base64.RawURLEncoding.EncodeToString(payloadJSON)
	mac := hmacSign(encoded, secret)
	return fmt.Sprintf("%s.%s", encoded, mac), nil
}

// VerifyToken validates the HMAC signature, checks expiry, and returns TokenClaims.
// The wlt field is present in all tokens issued after this version. Tokens issued
// before the upgrade will have an empty WalletAddr — the caller decides enforcement.
func VerifyToken(token, secret string) (*TokenClaims, error) {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return nil, errors.New("malformed token")
	}
	encoded, sig := parts[0], parts[1]
	expected := hmacSign(encoded, secret)
	if !hmac.Equal([]byte(sig), []byte(expected)) {
		return nil, errors.New("invalid token signature")
	}
	payloadJSON, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return nil, errors.New("malformed token payload")
	}
	var payload tokenPayload
	if err := json.Unmarshal(payloadJSON, &payload); err != nil {
		return nil, errors.New("malformed token payload")
	}
	if time.Now().Unix() > payload.ExpiresAt {
		return nil, errors.New("token expired")
	}
	return &TokenClaims{
		EndpointID: payload.EndpointID,
		WalletAddr: payload.WalletAddr,
		InvoiceID:  payload.InvoiceID,
	}, nil
}

// VerifyTokenForEndpoint is a convenience wrapper: verifies the token AND enforces
// that it was issued for the given endpoint. Used by the SqueezeOS middleware.
func VerifyTokenForEndpoint(token, secret, endpointID string) (*TokenClaims, error) {
	claims, err := VerifyToken(token, secret)
	if err != nil {
		return nil, err
	}
	if endpointID != "" && claims.EndpointID != endpointID {
		return nil, errors.New("token not valid for this endpoint")
	}
	return claims, nil
}

func hmacSign(data, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(data))
	return hex.EncodeToString(mac.Sum(nil))
}
