package bureau

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
)

const AttestTTL = 24 * time.Hour

// AttestClaims is the payload embedded in a portable attestation JWT.
type AttestClaims struct {
	Wallet      string `json:"wlt"`
	Score       int    `json:"score"`
	Grade       string `json:"grade"`
	LoyaltyTier string `json:"tier"`
	KYBTier     string `json:"kyb"`
	IsBlocked   bool   `json:"blocked"`
	IssuedAt    int64  `json:"iat"`
	ExpiresAt   int64  `json:"exp"`
}

// IssueAttestation mints a signed portable attestation JWT the agent can present
// to any third-party service without that service calling 402Proof directly.
// Third parties verify at POST /v1/bureau/verify-attest (free endpoint).
func IssueAttestation(wallet string, score int, grade, tier, kyb string, blocked bool, secret string) (string, error) {
	if secret == "" {
		return "", errors.New("token secret not configured")
	}
	now := time.Now()
	claims := AttestClaims{
		Wallet:      wallet,
		Score:       score,
		Grade:       grade,
		LoyaltyTier: tier,
		KYBTier:     kyb,
		IsBlocked:   blocked,
		IssuedAt:    now.Unix(),
		ExpiresAt:   now.Add(AttestTTL).Unix(),
	}
	b, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	encoded := base64.RawURLEncoding.EncodeToString(b)
	sig := attestSign(encoded, secret)
	return fmt.Sprintf("%s.%s", encoded, sig), nil
}

// VerifyAttestation validates a portable attestation JWT and returns its claims.
// Called by POST /v1/bureau/verify-attest — free, no payment required.
func VerifyAttestation(token, secret string) (*AttestClaims, error) {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return nil, errors.New("malformed attestation token")
	}
	encoded, sig := parts[0], parts[1]
	expected := attestSign(encoded, secret)
	if !hmac.Equal([]byte(sig), []byte(expected)) {
		return nil, errors.New("invalid attestation signature")
	}
	b, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return nil, errors.New("malformed attestation payload")
	}
	var claims AttestClaims
	if err := json.Unmarshal(b, &claims); err != nil {
		return nil, errors.New("malformed attestation payload")
	}
	if time.Now().Unix() > claims.ExpiresAt {
		return nil, errors.New("attestation expired")
	}
	return &claims, nil
}

func attestSign(data, secret string) string {
	mac := hmac.New(sha256.New, []byte("bureau:"+secret))
	mac.Write([]byte(data))
	return hex.EncodeToString(mac.Sum(nil))
}
