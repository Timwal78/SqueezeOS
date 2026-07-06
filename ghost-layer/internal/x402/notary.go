package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"log"
	"strconv"
	"sync/atomic"
	"time"

	"ghost-layer-core/internal/chain"
)

// LockKeyMemory is a no-op on Linux/container environments.
// VirtualLock is Windows-only and unavailable on Render (Linux).
// mlock(2) requires CAP_IPC_LOCK which Render containers do not grant.
func LockKeyMemory(_ ed25519.PrivateKey) error   { return nil }
func UnlockKeyMemory(_ ed25519.PrivateKey) error { return nil }

var globalNonceCounter uint64


// DecisionCertificate is the signed receipt returned by decision.notarize.certified
// and decision.notarize.sovereign. The Ed25519 signature lets any party
// independently verify that Ghost Layer attested to this decision at this time.
type DecisionCertificate struct {
	CertificateID string `json:"certificate_id"`
	Nonce         string `json:"nonce"`
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
		c.Nonce,
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
	
	// Generate strict 16-byte tracking nonce (8 bytes timestamp + 8 bytes atomic counter)
	nonceBytes := make([]byte, 16)
	binary.BigEndian.PutUint64(nonceBytes[0:8], uint64(time.Now().UnixNano()))
	binary.BigEndian.PutUint64(nonceBytes[8:16], atomic.AddUint64(&globalNonceCounter, 1))

	cert := DecisionCertificate{
		CertificateID: hex.EncodeToString(b),
		Nonce:         hex.EncodeToString(nonceBytes),
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

// SubmitToXahau mints cert as a real Xahau URIToken via xahauClient — the same
// MintURIToken call the HTTP /v1/notarize handler in cmd/bridge/main.go uses.
//
// This used to fabricate a random "ledger hash" and log it as a settled
// transaction (see git history) without ever contacting Xahau — a direct
// violation of this project's own no-fake-data policy: a SOVEREIGN-grade
// certificate implies real on-chain attestation, and nothing was on-chain.
//
// xahauClient may be nil (not yet configured on this deployment, matching
// the same "not yet configured" pattern used elsewhere in this codebase,
// e.g. SML-Vault-Executor / AEO Treasury) — in that case this logs the
// omission honestly instead of pretending to have submitted anything.
//
// Note: cert.Signature was already computed by SignDecision() before this
// runs (with XahauTx as passed in, often ""), so a real tx hash minted here
// is NOT retroactively folded back into the signed certificate already
// returned to the caller — this call is fire-and-forget specifically to
// keep the IPC hot path non-blocking, and its real result is only logged and
// broadcast to the FIX drop-copy stream, not re-signed. Anything reading a
// returned certificate's XahauTx field must not assume it reflects this
// call's outcome.
func SubmitToXahau(cert DecisionCertificate, xahauClient *chain.XahauClient) {
	if xahauClient == nil {
		log.Printf("[XAHAU] ERR_XAHAU_NOT_CONFIGURED — decision_hash=%s NOT notarized (no XahauClient configured)", cert.DecisionHash)
		return
	}

	memoJSON := fmt.Sprintf(`{"decision_hash":%q,"signature":%q,"certificate_id":%q}`,
		cert.DecisionHash, cert.Signature, cert.CertificateID)
	uniqueURI := fmt.Sprintf("%s-%d", cert.DecisionHash, time.Now().UnixNano())

	txHash, err := xahauClient.MintURIToken(uniqueURI, nil, memoJSON)
	if err != nil {
		log.Printf("[XAHAU] ERR_MINT_FAILED for decision_hash=%s: %v", cert.DecisionHash, err)
		return
	}

	log.Printf("[XAHAU] SUCCESS - decision_hash=%s minted as real Xahau tx: %s", cert.DecisionHash, txHash)
}
