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

func IsExpired(inv *models.Invoice) bool {
	return time.Now().After(inv.ExpiresAt)
}

type tokenPayload struct {
	InvoiceID  string `json:"iid"`
	EndpointID string `json:"eid"`
	IssuedAt   int64  `json:"iat"`
	ExpiresAt  int64  `json:"exp"`
}

func IssueToken(inv *models.Invoice, secret string) (string, error) {
	if secret == "" {
		return "", errors.New("token secret not configured")
	}
	payload := tokenPayload{
		InvoiceID:  inv.ID,
		EndpointID: inv.EndpointID,
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

func VerifyToken(token, secret string) (string, error) {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return "", errors.New("malformed token")
	}
	encoded, sig := parts[0], parts[1]
	expected := hmacSign(encoded, secret)
	if !hmac.Equal([]byte(sig), []byte(expected)) {
		return "", errors.New("invalid token signature")
	}
	payloadJSON, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return "", errors.New("malformed token payload")
	}
	var payload tokenPayload
	if err := json.Unmarshal(payloadJSON, &payload); err != nil {
		return "", errors.New("malformed token payload")
	}
	if time.Now().Unix() > payload.ExpiresAt {
		return "", errors.New("token expired")
	}
	return payload.EndpointID, nil
}

func hmacSign(data, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(data))
	return hex.EncodeToString(mac.Sum(nil))
}
