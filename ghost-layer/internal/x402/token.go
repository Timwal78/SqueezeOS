package x402

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

// Payload is the JSON body embedded in an x402 token.
// Mirrors proof402_integration.py field naming so a SqueezeOS-style
// verifier can be reused unchanged on either side.
type Payload struct {
	Pid  string         `json:"pid"`
	Wlt  string         `json:"wlt"`
	Iid  string         `json:"iid"`
	Exp  int64          `json:"exp"`
	Tier string         `json:"tier"`
	Args map[string]any `json:"args,omitempty"`
}

// Sign returns "<base64url(payload)>.<hex(hmac_sha256(secret, base64url(payload)))>".
func Sign(p Payload, secret string) (string, error) {
	if secret == "" {
		return "", errors.New("ERR_SECRET_NOT_CONFIGURED")
	}
	raw, err := json.Marshal(p)
	if err != nil {
		return "", err
	}
	encoded := base64.RawURLEncoding.EncodeToString(raw)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(encoded))
	sig := hex.EncodeToString(mac.Sum(nil))
	return encoded + "." + sig, nil
}

// Verify parses a token, checks HMAC + expiry, and returns the decoded payload.
// Does NOT check product ID match — callers do that after Verify returns ok.
func Verify(token, secret string) (Payload, error) {
	var zero Payload
	if secret == "" {
		return zero, errors.New("ERR_SECRET_NOT_CONFIGURED")
	}
	dot := strings.LastIndex(token, ".")
	if dot < 0 {
		return zero, errors.New("ERR_TOKEN_MALFORMED")
	}
	encoded, sig := token[:dot], token[dot+1:]

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(encoded))
	expected := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(sig), []byte(expected)) {
		return zero, errors.New("ERR_TOKEN_INVALID")
	}

	raw, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return zero, errors.New("ERR_TOKEN_MALFORMED")
	}
	var p Payload
	if err := json.Unmarshal(raw, &p); err != nil {
		return zero, errors.New("ERR_TOKEN_MALFORMED")
	}
	if time.Now().Unix() > p.Exp {
		return zero, errors.New("ERR_TOKEN_EXPIRED")
	}
	return p, nil
}
