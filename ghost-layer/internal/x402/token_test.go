package x402

import (
	"strings"
	"testing"
	"time"
)

func TestSignVerifyRoundTrip(t *testing.T) {
	p := Payload{
		Pid: "routing.telemetry", Wlt: "rAgent", Iid: "01HQ1",
		Exp: time.Now().Add(5 * time.Minute).Unix(), Tier: "GOLD",
	}
	tok, err := Sign(p, "topsecret")
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	got, err := Verify(tok, "topsecret")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if got.Pid != p.Pid || got.Iid != p.Iid || got.Tier != p.Tier {
		t.Fatalf("payload mismatch: got %+v want %+v", got, p)
	}
}

func TestVerifyExpired(t *testing.T) {
	p := Payload{Pid: "x", Iid: "i", Exp: time.Now().Add(-1 * time.Second).Unix()}
	tok, _ := Sign(p, "s")
	_, err := Verify(tok, "s")
	if err == nil || !strings.Contains(err.Error(), "EXPIRED") {
		t.Fatalf("expected ERR_TOKEN_EXPIRED, got %v", err)
	}
}

func TestVerifyTamper(t *testing.T) {
	p := Payload{Pid: "x", Iid: "i", Exp: time.Now().Add(time.Minute).Unix()}
	tok, _ := Sign(p, "s")
	// Flip the first character of the payload section — guaranteed to break HMAC
	// regardless of original char.
	flipped := "A"
	if tok[0] == 'A' {
		flipped = "B"
	}
	tampered := flipped + tok[1:]
	_, err := Verify(tampered, "s")
	if err == nil || !strings.Contains(err.Error(), "INVALID") {
		t.Fatalf("expected ERR_TOKEN_INVALID, got %v", err)
	}
}

func TestVerifyWrongSecret(t *testing.T) {
	p := Payload{Pid: "x", Iid: "i", Exp: time.Now().Add(time.Minute).Unix()}
	tok, _ := Sign(p, "secret-a")
	_, err := Verify(tok, "secret-b")
	if err == nil || !strings.Contains(err.Error(), "INVALID") {
		t.Fatalf("expected ERR_TOKEN_INVALID with wrong secret, got %v", err)
	}
}

func TestVerifyMissingSecret(t *testing.T) {
	if _, err := Verify("a.b", ""); err == nil || !strings.Contains(err.Error(), "NOT_CONFIGURED") {
		t.Fatalf("expected ERR_SECRET_NOT_CONFIGURED, got %v", err)
	}
}

func TestVerifyMalformed(t *testing.T) {
	if _, err := Verify("nodothere", "s"); err == nil {
		t.Fatal("expected error for token with no dot")
	}
}
