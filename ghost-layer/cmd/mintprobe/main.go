// mintprobe — direct Xahau URIToken mint diagnostic.
//
// Tests the full on-chain state commit path without going through the HTTP server
// or the X402 payment gate. Run after setting env vars to confirm the gateway
// wallet is funded and the Xahau RPC is reachable.
//
// Usage:
//
//	export GATEWAY_XRPL_PRIVATE_KEY=<secp256k1-hex>
//	export XAHAU_RPC_URL=https://xahau.network        # optional, this is the default
//	go run ./cmd/mintprobe
//
// On success prints the Xahau transaction hash and a link to the explorer.
package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strings"
	"time"

	"ghost-layer-core/internal/chain"
)

// defaultFaces mirrors the cube.js FACE_PARAMS initial values exactly.
// These produce a deterministic CUBE-XXXXXXXX hash for smoke testing.
var defaultFaces = map[string]*faceState{
	"px": {Edges: [4]int{91, 82, 88, 85}, Corners: [4]float64{1.1, 0.9, 1.0, 1.1}, Rotation: 0, min: 0, max: 100},
	"nx": {Edges: [4]int{4, 2, 3, 3}, Corners: [4]float64{1.0, 0.9, 1.1, 1.0}, Rotation: 0, min: 0, max: 10},
	"py": {Edges: [4]int{400, 450, 420, 410}, Corners: [4]float64{1.0, 1.0, 1.0, 1.0}, Rotation: 0, min: 100, max: 5000},
	"ny": {Edges: [4]int{14, 10, 13, 11}, Corners: [4]float64{1.0, 0.9, 1.1, 1.0}, Rotation: 0, min: 0, max: 50},
	"pz": {Edges: [4]int{5, 7, 6, 8}, Corners: [4]float64{1.1, 0.9, 1.0, 1.0}, Rotation: 0, min: 0, max: 20},
	"nz": {Edges: [4]int{9, 11, 10, 8}, Corners: [4]float64{0.9, 1.1, 1.0, 1.0}, Rotation: 0, min: 0, max: 500},
}

var faceOrder = []string{"px", "nx", "py", "ny", "pz", "nz"}
var faceAbbr = map[string]string{
	"px": "liq", "nx": "prv", "py": "spd",
	"ny": "pol", "pz": "hks", "nz": "bas",
}

type faceState struct {
	Edges    [4]int
	Corners  [4]float64
	Rotation int
	min, max int
}

func (f *faceState) center() int {
	rot := f.Rotation % 4
	var wSum, wTotal float64
	for i := 0; i < 4; i++ {
		cIdx := (i + rot) % 4
		wSum += float64(f.Edges[i]) * f.Corners[cIdx]
		wTotal += f.Corners[cIdx]
	}
	if wTotal == 0 {
		return 0
	}
	v := int(math.Round(wSum / wTotal))
	if v < f.min {
		return f.min
	}
	if v > f.max {
		return f.max
	}
	return v
}

func djb2(s string) uint32 {
	h := uint32(5381)
	for _, c := range []byte(s) {
		h = ((h << 5) + h) ^ uint32(c)
	}
	return h
}

func stateString(faces map[string]*faceState) string {
	var parts []string
	for _, key := range faceOrder {
		fp := faces[key]
		parts = append(parts, fmt.Sprintf("%sc:%d", key, fp.center()))
		for i, v := range fp.Edges {
			parts = append(parts, fmt.Sprintf("%se%d:%d", key, i, v))
		}
		for i, v := range fp.Corners {
			parts = append(parts, fmt.Sprintf("%sk%d:%.1f", key, i, v))
		}
	}
	return strings.Join(parts, "|")
}

func cubeHash(faces map[string]*faceState) string {
	return fmt.Sprintf("CUBE-%08X", djb2(stateString(faces)))
}

func buildHookParams(faces map[string]*faceState) []chain.URITokenHookParam {
	params := make([]chain.URITokenHookParam, 0, 6)
	for _, key := range faceOrder {
		abbr := faceAbbr[key]
		ctr := faces[key].center()
		params = append(params, chain.URITokenHookParam{
			Name:  strings.ToUpper(hex.EncodeToString([]byte(abbr))),
			Value: fmt.Sprintf("%04X", ctr),
		})
	}
	return params
}

func main() {
	xahauRPC := env("XAHAU_RPC_URL", "https://xahau.network")
	privKey   := os.Getenv("GATEWAY_XAHAU_PRIVATE_KEY")
	if privKey == "" {
		privKey = os.Getenv("GATEWAY_XRPL_PRIVATE_KEY")
	}
	if privKey == "" {
		fatalf("[mintprobe] FAIL — set GATEWAY_XRPL_PRIVATE_KEY or GATEWAY_XAHAU_PRIVATE_KEY")
	}

	c, err := chain.NewXahauClient(xahauRPC, privKey)
	if err != nil {
		fatalf("[mintprobe] client init: %v", err)
	}
	fmt.Printf("[mintprobe] gateway wallet : %s\n", c.GatewayAddress)
	fmt.Printf("[mintprobe] Xahau RPC      : %s\n", xahauRPC)

	hash       := cubeHash(defaultFaces)
	hookParams := buildHookParams(defaultFaces)

	fmt.Printf("[mintprobe] state hash     : %s\n", hash)
	fmt.Printf("[mintprobe] hook params    : %d faces encoded\n", len(hookParams))
	for _, hp := range hookParams {
		name, _ := hex.DecodeString(hp.Name)
		fmt.Printf("             %-6s → %s (0x%s)\n", name, hp.Value, hp.Value)
	}

	centers := map[string]int{}
	for _, key := range faceOrder {
		centers[key] = defaultFaces[key].center()
	}
	memoObj := map[string]interface{}{
		"probe":     true,
		"hash":      hash,
		"faces":     centers,
		"committed": time.Now().UTC().Format(time.RFC3339),
	}
	memoBytes, _ := json.Marshal(memoObj)

	fmt.Printf("\n[mintprobe] submitting URITokenMint to Xahau…\n")
	start := time.Now()
	txHash, err := c.MintURIToken(hash, hookParams, string(memoBytes))
	elapsed := time.Since(start)
	if err != nil {
		fatalf("[mintprobe] FAIL mint: %v", err)
	}

	fmt.Printf("\n[mintprobe] ✓ MINTED in %s\n", elapsed.Round(time.Millisecond))
	fmt.Printf("[mintprobe] tx hash   : %s\n", txHash)
	fmt.Printf("[mintprobe] explorer  : https://xahau.network/tx/%s\n", txHash)
	fmt.Printf("[mintprobe] state URI : %s\n", hash)
	fmt.Printf("\n[mintprobe] OK — Xahau URITokenMint end-to-end PASS\n")
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func fatalf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
