package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"log"
	"strconv"
	"sync/atomic"
	"time"
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

// XahauMemo represents a single memo entry in an XRPL transaction
type XahauMemo struct {
	Memo struct {
		MemoData   string `json:"MemoData"`
		MemoFormat string `json:"MemoFormat"`
		MemoType   string `json:"MemoType"`
	} `json:"Memo"`
}

// SubmitToXahau packages the DecisionCertificate into a Xahau Memos block
// and mocks the JSON-RPC submission to the Xahau testnet.
func SubmitToXahau(cert DecisionCertificate) {
	// 1. Serialize the Payload (Hex Encode for XRPL compliance)
	memoData := hex.EncodeToString([]byte(cert.DecisionHash + "|" + cert.Signature))
	memoFormat := hex.EncodeToString([]byte("text/plain"))
	memoType := hex.EncodeToString([]byte("402Proof"))

	memo := XahauMemo{}
	memo.Memo.MemoData = memoData
	memo.Memo.MemoFormat = memoFormat
	memo.Memo.MemoType = memoType

	// Mocking the JSON payload that would be sent to the JSON-RPC endpoint
	payload := map[string]interface{}{
		"method": "submit",
		"params": []interface{}{
			map[string]interface{}{
				"tx_blob": "MOCKED_SIGNED_TX_BLOB_CONTAINING_MEMO",
				"Memos":   []XahauMemo{memo},
			},
		},
	}

	payloadJSON, _ := json.MarshalIndent(payload, "", "  ")
	log.Printf("[XAHAU] Outbound Payload Prepared:\n%s\n", string(payloadJSON))

	// 2. Simulate Network Latency for the Sandbox PoC
	time.Sleep(150 * time.Millisecond)

	// 3. Mock the Ledger Hash Response
	mockHashBytes := make([]byte, 32)
	rand.Read(mockHashBytes)
	mockLedgerHash := hex.EncodeToString(mockHashBytes)

	log.Printf("[XAHAU] SUCCESS - 402Proof Settled. Ledger Hash: %s\n", mockLedgerHash)
}
