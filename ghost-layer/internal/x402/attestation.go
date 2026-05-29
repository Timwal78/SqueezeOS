package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"strconv"
	"time"

	"ghost-layer-core/internal/ledger"
)

const (
	AttestationVersion = "1.0"
	AttestationAlg     = "ed25519"
	AttestationIssuer  = "ghost-layer.onrender.com"
)

// Envelope is the institutional attestation document. The signature is computed
// over CanonicalBytes(env) and stored as hex in env.Signature.
type Envelope struct {
	Version           string `json:"version"`
	AttestationID     string `json:"attestation_id"`
	BridgeID          string `json:"bridge_id"`
	TxHash            string `json:"tx_hash"`
	Chain             string `json:"chain"`
	SourceWallet      string `json:"source_wallet"`
	DestinationWallet string `json:"destination_wallet"`
	GrossAmount       string `json:"gross_amount"`
	FeeAmount         string `json:"fee_amount"`
	NetAmount         string `json:"net_amount"`
	EffectiveBPS      int64  `json:"effective_bps"`
	AgentTier         string `json:"agent_tier"`
	SettledAt         int64  `json:"settled_at"`
	IssuedAt          int64  `json:"issued_at"`
	Issuer            string `json:"issuer"`
	SignatureAlg      string `json:"signature_alg"`
	Signature         string `json:"signature"`
}

// CanonicalBytes returns the byte sequence that gets signed. Fixed-order
// field concatenation, newline-separated, signature field excluded.
// Verifier reproduces this exactly from the JSON envelope.
func CanonicalBytes(e Envelope) []byte {
	parts := []string{
		e.Version,
		e.AttestationID,
		e.BridgeID,
		e.TxHash,
		e.Chain,
		e.SourceWallet,
		e.DestinationWallet,
		e.GrossAmount,
		e.FeeAmount,
		e.NetAmount,
		strconv.FormatInt(e.EffectiveBPS, 10),
		e.AgentTier,
		strconv.FormatInt(e.SettledAt, 10),
		strconv.FormatInt(e.IssuedAt, 10),
		e.Issuer,
		e.SignatureAlg,
	}
	var out []byte
	for _, p := range parts {
		out = append(out, []byte(p)...)
		out = append(out, '\n')
	}
	return out
}

// BuildAndSign assembles a fresh envelope from a BridgeRecord and signs it.
// Returns the completed envelope.
func BuildAndSign(rec ledger.BridgeRecord, priv ed25519.PrivateKey) (Envelope, error) {
	if len(priv) != ed25519.PrivateKeySize {
		return Envelope{}, errors.New("ERR_PRIVATE_KEY_INVALID")
	}
	env := Envelope{
		Version:           AttestationVersion,
		AttestationID:     newAttestationID(),
		BridgeID:          rec.BridgeID,
		TxHash:            rec.TxHash,
		Chain:             rec.Chain,
		SourceWallet:      rec.SourceWallet,
		DestinationWallet: rec.DestinationWallet,
		GrossAmount:       rec.GrossAmount,
		FeeAmount:         rec.FeeAmount,
		NetAmount:         rec.NetAmount,
		EffectiveBPS:      rec.EffectiveBPS,
		AgentTier:         rec.AgentTier,
		SettledAt:         rec.SettledAt,
		IssuedAt:          time.Now().Unix(),
		Issuer:            AttestationIssuer,
		SignatureAlg:      AttestationAlg,
	}
	sig := ed25519.Sign(priv, CanonicalBytes(env))
	env.Signature = hex.EncodeToString(sig)
	return env, nil
}

// VerifyEnvelope checks the envelope's signature against the supplied pubkey.
// Returns nil on valid, an error otherwise.
func VerifyEnvelope(env Envelope, pub ed25519.PublicKey) error {
	if len(pub) != ed25519.PublicKeySize {
		return errors.New("ERR_PUBLIC_KEY_INVALID")
	}
	sig, err := hex.DecodeString(env.Signature)
	if err != nil {
		return errors.New("ERR_SIGNATURE_MALFORMED")
	}
	if !ed25519.Verify(pub, CanonicalBytes(env), sig) {
		return errors.New("ERR_SIGNATURE_INVALID")
	}
	return nil
}

func newAttestationID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
