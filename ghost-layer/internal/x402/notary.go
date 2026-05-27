package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"strconv"
	"time"
)

// DecisionCertificate is the signed receipt returned by decision.notarize.certified
// and decision.notarize.sovereign. The Ed25519 signature lets any party
// independently verify that Ghost Layer attested to this decision at this time.
type DecisionCertificate struct {
	CertificateID string `json:"certificate_id"`
	DecisionHash  string `json:"decision_hash"`
	XahauTx       string `json:"xahau_tx"`
	AgentWallet   string `json:"agent_wallet"`
	Model         string `json:"model,omitempty"`
	Endpoint      string `json:"endpoint,omitempty"`
	AgentTier     string `json:"agent_tier"`
	Grade         string `json:"grade"` // CERTIFIED or SOVEREIGN
	IssuedAt      int64  `json:"issued_at"`
	Issuer        string `json:"issuer"`
	SignatureAlg  string `json:"signature_alg"`
	Signature     string `json:"signature"`
}

// certCanonical returns the byte sequence that gets signed — fixed field order,
// newline-separated, Signature excluded. Verifiers reproduce this from the JSON.
func certCanonical(c DecisionCertificate) []byte {
	parts := []string{
		c.CertificateID,
		c.DecisionHash,
		c.XahauTx,
		c.AgentWallet,
		c.Model,
		c.Endpoint,
		c.AgentTier,
		c.Grade,
		strconv.FormatInt(c.IssuedAt, 10),
		c.Issuer,
		c.SignatureAlg,
	}
	var out []byte
	for _, p := range parts {
		out = append(out, []byte(p)...)
		out = append(out, '\n')
	}
	return out
}

// SignDecision builds and signs a DecisionCertificate with Ghost Layer's
// attestation key. grade should be "CERTIFIED" or "SOVEREIGN".
func SignDecision(decisionHash, xahauTx, agentWallet, model, endpoint, tier, grade string, priv ed25519.PrivateKey) (DecisionCertificate, error) {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	cert := DecisionCertificate{
		CertificateID: hex.EncodeToString(b),
		DecisionHash:  decisionHash,
		XahauTx:       xahauTx,
		AgentWallet:   agentWallet,
		Model:         model,
		Endpoint:      endpoint,
		AgentTier:     tier,
		Grade:         grade,
		IssuedAt:      time.Now().Unix(),
		Issuer:        AttestationIssuer,
		SignatureAlg:  AttestationAlg,
	}
	cert.Signature = hex.EncodeToString(ed25519.Sign(priv, certCanonical(cert)))
	return cert, nil
}
