package main

import (
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"

	"ghost-layer-core/internal/x402"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: %s <host:port>\nExample: %s localhost:8080 < env.json\n", os.Args[0], os.Args[0])
		os.Exit(1)
	}
	host := os.Args[1]

	// 1. Fetch public key
	resp, err := http.Get(fmt.Sprintf("http://%s/v1/x402/attestation/pubkey", host))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to fetch pubkey: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()
	var pubResp struct {
		PublicKey string `json:"public_key"`
		Alg       string `json:"alg"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&pubResp); err != nil {
		fmt.Fprintf(os.Stderr, "failed to decode pubkey response: %v\n", err)
		os.Exit(1)
	}
	if pubResp.Alg != "ed25519" {
		fmt.Fprintf(os.Stderr, "unsupported algorithm: %s\n", pubResp.Alg)
		os.Exit(1)
	}
	pubBytes, err := hex.DecodeString(pubResp.PublicKey)
	if err != nil || len(pubBytes) != ed25519.PublicKeySize {
		fmt.Fprintf(os.Stderr, "invalid public key format\n")
		os.Exit(1)
	}
	pub := ed25519.PublicKey(pubBytes)

	// 2. Read envelope from stdin
	envData, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to read stdin: %v\n", err)
		os.Exit(1)
	}
	var env x402.Envelope
	if err := json.Unmarshal(envData, &env); err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse envelope: %v\n", err)
		os.Exit(1)
	}

	// 3. Verify
	if err := x402.VerifyEnvelope(env, pub); err != nil {
		fmt.Fprintf(os.Stderr, "VERIFICATION FAILED: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("VERIFICATION SUCCESS: Signature is valid")
	os.Exit(0)
}
