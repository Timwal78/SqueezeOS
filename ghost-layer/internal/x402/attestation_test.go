package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"strings"
	"testing"

	"ghost-layer-core/internal/ledger"
)

func freshKey(t *testing.T) (ed25519.PublicKey, ed25519.PrivateKey) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	return pub, priv
}

func sampleRecord() ledger.BridgeRecord {
	return ledger.BridgeRecord{
		BridgeID: "br-123", TxHash: "ABC", Chain: "xrpl",
		SourceWallet: "rSrc", DestinationWallet: "rDst",
		GrossAmount: "1000", FeeAmount: "5", NetAmount: "995",
		EffectiveBPS: 50, AgentTier: "GOLD", SettledAt: 1700000000,
	}
}

func TestBuildSignVerifyRoundTrip(t *testing.T) {
	pub, priv := freshKey(t)
	env, err := BuildAndSign(sampleRecord(), priv)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	if env.Signature == "" {
		t.Fatal("signature should be populated")
	}
	if err := VerifyEnvelope(env, pub); err != nil {
		t.Fatalf("verify: %v", err)
	}
}

func TestVerifyRejectsTamperedField(t *testing.T) {
	pub, priv := freshKey(t)
	env, _ := BuildAndSign(sampleRecord(), priv)
	env.NetAmount = "999999" // tamper after signing
	if err := VerifyEnvelope(env, pub); err == nil {
		t.Fatal("verify should reject tampered envelope")
	}
}

func TestVerifyRejectsWrongPubKey(t *testing.T) {
	_, priv := freshKey(t)
	otherPub, _ := freshKey(t)
	env, _ := BuildAndSign(sampleRecord(), priv)
	if err := VerifyEnvelope(env, otherPub); err == nil {
		t.Fatal("verify should reject under wrong pubkey")
	}
}

func TestBuildRejectsInvalidPriv(t *testing.T) {
	_, err := BuildAndSign(sampleRecord(), ed25519.PrivateKey{1, 2, 3})
	if err == nil || !strings.Contains(err.Error(), "PRIVATE_KEY") {
		t.Fatalf("expected ERR_PRIVATE_KEY_INVALID, got %v", err)
	}
}

func TestCanonicalBytesDeterministic(t *testing.T) {
	rec := sampleRecord()
	pub, priv := freshKey(t)
	env, _ := BuildAndSign(rec, priv)
	b1 := CanonicalBytes(env)
	b2 := CanonicalBytes(env)
	if string(b1) != string(b2) {
		t.Fatal("CanonicalBytes must be deterministic for the same envelope")
	}
	// Sanity: pubkey verifies against the canonical bytes the verifier rebuilds.
	if err := VerifyEnvelope(env, pub); err != nil {
		t.Fatalf("verify after canonical compare: %v", err)
	}
}
