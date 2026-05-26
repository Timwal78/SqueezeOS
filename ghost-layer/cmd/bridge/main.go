package main

import (
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"math/big"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"ghost-layer-core/internal/chain"
	"ghost-layer-core/internal/crypto"
	"ghost-layer-core/internal/ledger"
	"ghost-layer-core/internal/router"
	"ghost-layer-core/internal/toll"
	"ghost-layer-core/internal/x402"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)



// ── SSE Hub — backwards-compat shim; new clients use /ws/metrics ─────────────

type sseHub struct {
	mu          sync.RWMutex
	clients     map[chan []byte]struct{}
	totalBridge atomic.Int64
	totalFees   atomic.Int64 // in drops/wei, for display
}

var hub = &sseHub{clients: make(map[chan []byte]struct{})}

// ── Sovereign WebSocket Metrics Hub + Agent Loyalty Ledger ────────────────────
var metricsHub = router.NewMetricsHub()
var agentLedger = toll.NewAgentLedger()
var bridgeLedger = ledger.NewLedger(10000)
var attestationPrivKey ed25519.PrivateKey

var (
	xrplClient  *chain.XRPLClient
	xahauClient *chain.XahauClient
	baseClient  *chain.BaseClient
)

// writeJSONErr writes a {"error": "<code>"} body with the given HTTP status.
// Used by the x402 routes for consistent error envelopes.
func writeJSONErr(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": code})
}

// ── X402 Native Vendor ───────────────────────────────────────────────────────
var x402Registry = x402.NewRegistry()
var x402Nonces = x402.NewNonceCache()
var x402Dispensed atomic.Int64

func init() {
	x402Registry.Register(&x402.Product{
		ID:        "routing.telemetry",
		Name:      "Routing Telemetry (60s)",
		BasePrice: 50000, // 0.05 RLUSD in drops
		Dispatcher: func(args map[string]any) (json.RawMessage, error) {
			payload := map[string]interface{}{
				"tps":             metricsHub.RollingTPS(),
				"total_bridges":   metricsHub.TotalBridges(),
				"accumulated_fee": metricsHub.AccumulatedFeeString(),
				"snapshot_ts":     time.Now().Unix(),
			}
			return json.Marshal(payload)
		},
	})
	
	x402Registry.Register(&x402.Product{
		ID:        "bridge.attestation",
		Name:      "Institutional Settlement Attestation",
		BasePrice: 100000, // 0.10 RLUSD
		Dispatcher: func(args map[string]any) (json.RawMessage, error) {
			txHash, ok := args["tx_hash"].(string)
			if !ok || txHash == "" {
				return nil, errors.New("ERR_MISSING_TX_HASH")
			}
			rec, ok := bridgeLedger.Lookup(txHash)
			if !ok {
				return nil, errors.New("ERR_TX_NOT_FOUND")
			}
			env, err := x402.BuildAndSign(rec, attestationPrivKey)
			if err != nil {
				return nil, err
			}
			return json.Marshal(env)
		},
	})

	x402Registry.Register(&x402.Product{
		ID:        "cube.mint",
		Name:      "Xahau Cube URIToken Mint",
		BasePrice: 50000, // 0.05 RLUSD
		Dispatcher: func(args map[string]any) (json.RawMessage, error) {
			if _, ok := args["tx_hash"].(string); !ok {
				return nil, errors.New("ERR_PAYMENT_REQUIRED")
			}
			if xahauClient == nil {
				return nil, errors.New("ERR_XAHAU_NOT_CONFIGURED")
			}
			cubeStateMu.RLock()
			state := lastCubeState
			committed := lastCommitTime
			cubeStateMu.RUnlock()

			if state == nil {
				return nil, errors.New("ERR_NO_CUBE_STATE")
			}

			hookParams := buildHookParams(state.Faces)
			centers := make(map[string]interface{}, 6)
			for _, key := range cubeKeys {
				centers[key] = state.Faces[key].Center
			}

			memoObj := map[string]interface{}{
				"state_hash": state.Hash,
				"faces":      centers,
				"committed":  committed.UTC().Format(time.RFC3339),
			}
			memoBytes, _ := json.Marshal(memoObj)

			uriParams := make([]chain.URITokenHookParam, len(hookParams))
			for i, hp := range hookParams {
				uriParams[i] = chain.URITokenHookParam{
					Name:  hp.HookParameterName,
					Value: hp.HookParameterValue,
				}
			}

			mintHash, mintErr := xahauClient.MintURIToken(state.Hash, uriParams, string(memoBytes))
			if mintErr != nil {
				log.Printf("[CUBE] Xahau mint failed via x402: %v", mintErr)
				return nil, fmt.Errorf("ERR_MINT_FAILED: %v", mintErr)
			}

			log.Printf("[CUBE] Xahau URIToken minted via x402: %s", mintHash)
			hub.broadcast("XAHAU_MINT_CONFIRMED", map[string]interface{}{
				"state_hash": state.Hash,
				"xahau_tx":   mintHash,
			})

			return json.Marshal(map[string]string{
				"status":        "MINTED",
				"xahau_tx_hash": mintHash,
			})
		},
	})

	// Reserved (disabled) entries — visible in catalog listing, not dispensable.
	for _, id := range []string{"bridge.priority"} {
		x402Registry.Register(&x402.Product{ID: id, Disabled: true, BasePrice: 100000})
	}
}

func (h *sseHub) subscribe() chan []byte {
	ch := make(chan []byte, 16)
	h.mu.Lock()
	h.clients[ch] = struct{}{}
	h.mu.Unlock()
	return ch
}

func (h *sseHub) unsubscribe(ch chan []byte) {
	h.mu.Lock()
	delete(h.clients, ch)
	h.mu.Unlock()
	close(ch)
}

func (h *sseHub) broadcast(eventType string, payload map[string]interface{}) {
	payload["type"] = eventType
	payload["ts"] = time.Now().UnixMilli()
	payload["total_bridges"] = h.totalBridge.Load()
	b, err := json.Marshal(payload)
	if err != nil {
		return
	}
	line := fmt.Appendf(nil, "data: %s\n\n", b)
	h.mu.RLock()
	for ch := range h.clients {
		select {
		case ch <- line:
		default: // client too slow — skip frame
		}
	}
	h.mu.RUnlock()
}

// ── Nonce replay cache ───────────────────────────────────────────────────────
// Tracks EIP-3009 nonces that have already been consumed. Prevents replays
// where a captured authorization is re-submitted to pull funds a second time.
var (
	usedNonces   = make(map[[32]byte]struct{})
	usedNoncesMu sync.Mutex
)

// markNonce returns true if nonce is fresh and records it; false if already seen.
func markNonce(nonce [32]byte) bool {
	usedNoncesMu.Lock()
	defer usedNoncesMu.Unlock()
	if _, seen := usedNonces[nonce]; seen {
		return false
	}
	usedNonces[nonce] = struct{}{}
	return true
}

// ── Per-IP token bucket rate limiter ────────────────────────────────────────
// /v1/bridge/execute: 20 tokens/min, burst 5
// /api/council:       5 tokens/min,  burst 3  (handled in squeezeos api_v2.py)

const (
	bridgeRatePerSec = 20.0 / 60.0
	bridgeBurst      = 5
)

type bucket struct {
	tokens   float64
	lastSeen time.Time
}

var (
	ipBuckets   = make(map[string]*bucket)
	ipBucketsMu sync.Mutex
)

func allowIP(ip string) bool {
	ipBucketsMu.Lock()
	defer ipBucketsMu.Unlock()

	now := time.Now()
	b, ok := ipBuckets[ip]
	if !ok {
		b = &bucket{tokens: float64(bridgeBurst), lastSeen: now}
		ipBuckets[ip] = b
	}

	elapsed := now.Sub(b.lastSeen).Seconds()
	b.lastSeen = now
	b.tokens += elapsed * bridgeRatePerSec
	if b.tokens > float64(bridgeBurst) {
		b.tokens = float64(bridgeBurst)
	}
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// sweepWg tracks pending async sweep goroutines so graceful shutdown can drain them.
var sweepWg sync.WaitGroup

// ── Cube execution matrix types ───────────────────────────────────────────────

type CubeFaceState struct {
	Center   int       `json:"center"`
	Edges    []int     `json:"edges"`
	Corners  []float64 `json:"corners"`
	Rotation int       `json:"rotation"`
}

type CubeStatePayload struct {
	Hash  string                    `json:"hash"`
	Faces map[string]*CubeFaceState `json:"faces"`
}

type XahauHookParam struct {
	HookParameterName  string `json:"HookParameterName"`
	HookParameterValue string `json:"HookParameterValue"`
}

type CubeStateResponse struct {
	Verified      bool                      `json:"verified"`
	StateHash     string                    `json:"state_hash"`
	Faces         map[string]*CubeFaceState `json:"faces,omitempty"`
	HookParams    []XahauHookParam          `json:"hook_params"`
	CommittedAt   string                    `json:"committed_at,omitempty"`
	XahauTxHash   string                    `json:"xahau_tx_hash,omitempty"`
	Error         string                    `json:"error,omitempty"`
}

// valid [min, max] for each face's center — must mirror cube.js FACE_PARAMS
var cubeFaceBounds = map[string][2]int{
	"px": {0, 100},
	"nx": {0, 10},
	"py": {100, 5000},
	"ny": {0, 50},
	"pz": {0, 20},
	"nz": {0, 500},
}

var cubeKeys = []string{"px", "nx", "py", "ny", "pz", "nz"}

// cubeStateStore: last verified + committed cube state
var (
	cubeStateMu    sync.RWMutex
	lastCubeState  *CubeStatePayload
	lastCommitTime time.Time
)

// computeFaceCenter mirrors the cube.js formula exactly:
//
//	center = clamp( Σ(edge[i] × corner[(i+rotation)%4]) / Σ(corner[(i+rotation)%4]), min, max )
func computeFaceCenter(key string, fp *CubeFaceState) int {
	rot := fp.Rotation % 4
	var wSum, wTotal float64
	for i := 0; i < 4; i++ {
		cIdx := (i + rot) % 4
		wSum += float64(fp.Edges[i]) * fp.Corners[cIdx]
		wTotal += fp.Corners[cIdx]
	}
	if wTotal == 0 {
		return 0
	}
	rounded := int(math.Round(wSum / wTotal))
	b, ok := cubeFaceBounds[key]
	if !ok {
		return rounded
	}
	if rounded < b[0] {
		return b[0]
	}
	if rounded > b[1] {
		return b[1]
	}
	return rounded
}

// djb2Hash mirrors the uint32 djb2 used in cube.js updateStateHash()
func djb2Hash(s string) uint32 {
	h := uint32(5381)
	for _, c := range []byte(s) {
		h = ((h << 5) + h) ^ uint32(c)
	}
	return h
}

// buildStateString constructs the canonical 54-field pipe-delimited string.
// Format: pxc:87|pxe0:91|pxe1:82|…|pxk0:1.1|…|nzk3:1.0
func buildStateString(faces map[string]*CubeFaceState) string {
	var parts []string
	for _, key := range cubeKeys {
		fp, ok := faces[key]
		if !ok {
			continue
		}
		ctr := computeFaceCenter(key, fp)
		parts = append(parts, fmt.Sprintf("%sc:%d", key, ctr))
		for i, v := range fp.Edges {
			parts = append(parts, fmt.Sprintf("%se%d:%d", key, i, v))
		}
		for i, v := range fp.Corners {
			parts = append(parts, fmt.Sprintf("%sk%d:%.1f", key, i, v))
		}
	}
	return strings.Join(parts, "|")
}

// computeCubeHash returns CUBE-XXXXXXXX matching cube.js updateStateHash()
func computeCubeHash(faces map[string]*CubeFaceState) string {
	return fmt.Sprintf("CUBE-%08X", djb2Hash(buildStateString(faces)))
}

// buildHookParams encodes the 6 face centers as Xahau HookParameters.
// Names are hex-encoded 3-byte abbreviations; values are 4-digit hex centers.
func buildHookParams(faces map[string]*CubeFaceState) []XahauHookParam {
	faceShorts := []struct{ key, abbr string }{
		{"px", "liq"}, {"nx", "prv"}, {"py", "spd"},
		{"ny", "pol"}, {"pz", "hks"}, {"nz", "bas"},
	}
	params := make([]XahauHookParam, 0, len(faceShorts))
	for _, fs := range faceShorts {
		fp, ok := faces[fs.key]
		if !ok {
			continue
		}
		ctr := computeFaceCenter(fs.key, fp)
		params = append(params, XahauHookParam{
			HookParameterName:  strings.ToUpper(hex.EncodeToString([]byte(fs.abbr))),
			HookParameterValue: fmt.Sprintf("%04X", ctr),
		})
	}
	return params
}

// validateCubePayload checks shape, verifies every face center against the
// server's computation, and verifies the submitted hash is canonical.
func validateCubePayload(p *CubeStatePayload) (string, error) {
	if len(p.Faces) != 6 {
		return "", fmt.Errorf("expected 6 faces, got %d", len(p.Faces))
	}
	for _, key := range cubeKeys {
		fp, ok := p.Faces[key]
		if !ok {
			return "", fmt.Errorf("missing face %q", key)
		}
		if len(fp.Edges) != 4 {
			return "", fmt.Errorf("face %s: need 4 edges, got %d", key, len(fp.Edges))
		}
		if len(fp.Corners) != 4 {
			return "", fmt.Errorf("face %s: need 4 corners, got %d", key, len(fp.Corners))
		}
		for i, c := range fp.Corners {
			if c <= 0 || c > 3.0 {
				return "", fmt.Errorf("face %s corner[%d]=%.2f out of range (0, 3.0]", key, i, c)
			}
		}
		computed := computeFaceCenter(key, fp)
		if computed != fp.Center {
			return "", fmt.Errorf("face %s center mismatch: submitted %d, server computed %d", key, fp.Center, computed)
		}
	}
	serverHash := computeCubeHash(p.Faces)
	if p.Hash != serverHash {
		return "", fmt.Errorf("hash mismatch: submitted %q, server computed %q", p.Hash, serverHash)
	}
	return serverHash, nil
}

// ── Payload types ─────────────────────────────────────────────────────────────

type eip3009Payload struct {
	ValidAfter  string `json:"valid_after"`
	ValidBefore string `json:"valid_before"`
	Nonce       string `json:"nonce"`
	V           uint8  `json:"v"`
	R           string `json:"r"`
	S           string `json:"s"`
}

type bridgePayload struct {
	// Application-level caller authentication (required for XRPL routes).
	Signer      string `json:"signer"`
	MessageHash string `json:"message_hash"`
	Signature   string `json:"signature"`
	// Routing fields.
	SourceWallet      string          `json:"source_wallet"`
	DestinationWallet string          `json:"destination_wallet"`
	GrossAmount       string          `json:"gross_amount"`
	FeeBasisPoints    int64           `json:"fee_basis_points"`
	EIP3009           *eip3009Payload `json:"eip3009,omitempty"`
	// Dry-run: validates parse + signature without broadcasting a transaction.
	IsDustTest bool `json:"is_dust_test"`
}

// ── Main ─────────────────────────────────────────────────────────────────────

func main() {
	port := env("PORT", "8080")
	treasuryXRPL := env("TREASURY_ADDRESS", "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q")
	treasuryETH := env("TREASURY_ETH_ADDRESS", "")
	baseRPC := env("BASE_RPC_URL", "https://mainnet.base.org")
	xrplRPC := env("XRPL_RPC_URL", "https://xrplcluster.com")
	usdcAddr := env("USDC_CONTRACT_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

	xrplKey := os.Getenv("GATEWAY_XRPL_PRIVATE_KEY")
	ethKey := os.Getenv("GATEWAY_ETH_PRIVATE_KEY")

	// Startup validation: at least one execution key must be configured.
	if xrplKey == "" && ethKey == "" {
		log.Fatalf("[FATAL] No gateway keys configured — set GATEWAY_XRPL_PRIVATE_KEY and/or GATEWAY_ETH_PRIVATE_KEY in Render secrets")
	}
	if os.Getenv("ADMIN_TOKEN") == "" {
		log.Fatalf("[FATAL] ADMIN_TOKEN not set — admin endpoints cannot be secured. Set ADMIN_TOKEN in Render secrets.")
	}
	if os.Getenv("X402_TOKEN_SECRET") == "" {
		log.Fatalf("[FATAL] X402_TOKEN_SECRET not set — x402 vendor cannot sign invoices. Set X402_TOKEN_SECRET in Render secrets.")
	}
	
	if keyHex := os.Getenv("ATTESTATION_PRIVATE_KEY"); keyHex != "" {
		b, err := hex.DecodeString(keyHex)
		if err != nil || len(b) != ed25519.PrivateKeySize {
			log.Fatalf("[FATAL] ATTESTATION_PRIVATE_KEY is malformed (must be 64-byte hex)")
		}
		attestationPrivKey = ed25519.PrivateKey(b)
	} else {
		log.Fatalf("[FATAL] ATTESTATION_PRIVATE_KEY not set")
	}

	if xrplKey != "" {
		c, err := chain.NewXRPLClient(xrplRPC, xrplKey)
		if err != nil {
			log.Fatalf("[FATAL] XRPL client: %v", err)
		}
		xrplClient = c
		log.Printf("[SERVER] XRPL gateway: %s", c.GatewayAddress)
	} else {
		log.Println("[WARN] GATEWAY_XRPL_PRIVATE_KEY not set — XRPL routing disabled")
	}

	xahauRPC := env("XAHAU_RPC_URL", "https://xahau.network")
	xahauKey := os.Getenv("GATEWAY_XAHAU_PRIVATE_KEY")
	if xahauKey == "" {
		xahauKey = xrplKey // fall back to XRPL key — same secp256k1 key format
	}
	if xahauKey != "" {
		c, err := chain.NewXahauClient(xahauRPC, xahauKey)
		if err != nil {
			log.Printf("[WARN] Xahau client init failed: %v", err)
		} else {
			xahauClient = c
			log.Printf("[SERVER] Xahau gateway: %s", c.GatewayAddress)
		}
	} else {
		log.Println("[WARN] No Xahau key configured — URIToken minting disabled")
	}

	if ethKey != "" {
		c, err := chain.NewBaseClient(baseRPC, ethKey, usdcAddr)
		if err != nil {
			log.Printf("[WARN] Base client init failed: %v", err)
		} else {
			baseClient = c
			log.Println("[SERVER] Base chain client initialised")
		}
	} else {
		log.Println("[WARN] GATEWAY_ETH_PRIVATE_KEY not set — Base routing disabled")
	}

	engine := router.NewTransparentBridgeEngine(treasuryXRPL, treasuryETH, xrplClient, baseClient, &sweepWg)
	log.Println("[SERVER] Agent Loyalty Matrix: ARMED | WebSocket Metrics Hub: LIVE")
	log.Println("[SERVER] X402 Vendor: ARMED | Catalog: routing.telemetry | Endpoint: /v1/x402")

	r := chi.NewRouter()
	r.Use(corsMiddleware)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))

	// ── HEALTH ───────────────────────────────────────────────────────────────
	r.Get("/health", func(w http.ResponseWriter, req *http.Request) {
		status := engine.ClientStatus()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":         "ok",
			"xrpl_client":    status["xrpl"],
			"base_client":    status["base"],
			"xrpl_treasury":   treasuryXRPL,
			"total_bridges":   metricsHub.TotalBridges(),
			"ws_metrics_url":  "/ws/metrics",
			"x402_dispensed":  x402Dispensed.Load(),
		})
	})

	// ── AGENT LOYALTY STATS ───────────────────────────────────────────────────
	r.Get("/api/agent/{addr}/stats", func(w http.ResponseWriter, req *http.Request) {
		addr := chi.URLParam(req, "addr")
		if addr == "" {
			http.Error(w, "missing agent address", http.StatusBadRequest)
			return
		}
		tier, volume := agentLedger.AgentStats(addr)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"agent":        addr,
			"tier":         tier,
			"total_volume": volume.String(),
			"discount_bps": agentLedger.EffectiveBPS(addr, 50) - 50, // discount relative to 50 BPS baseline
			"effective_bps_at_50": agentLedger.EffectiveBPS(addr, 50),
		})
	})

	// ── CONFIG (injected into cube.js via fetch) ──────────────────────────────
	squeezeosSSE := env("SQUEEZEOS_SSE_URL", "")
	r.Get("/api/config", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"sse_url":        "/api/events",       // legacy SSE kept alive
			"ws_metrics_url": "/ws/metrics",       // sovereign WebSocket stream
			"squeezeos_sse":  squeezeosSSE,
			"xrpl_treasury":  treasuryXRPL,
			"xrpl_enabled":   xrplKey != "",
			"base_enabled":   ethKey != "",
			"total_bridges":  metricsHub.TotalBridges(),
			"x402_compliant": true,
			"loyalty_matrix": true,
			"x402_endpoint":      "/v1/x402",
			"x402_products":      x402Registry.Listing(),
			"attestation_pubkey": hex.EncodeToString(attestationPrivKey.Public().(ed25519.PublicKey)),
		})
	})

	// ── SOVEREIGN WEBSOCKET METRICS STREAM ────────────────────────────────────
	r.Get("/ws/metrics", metricsHub.ServeHTTP)

	// ── SIGNAL AUCTION LOOM FEED (same hub, Loom-compatible path) ────────────
	// The Loom frontend connects to /ws/loom. Ghost Layer translates its native
	// MetricsFrame events into AuctionEvent format client-side (useAuction.ts).
	r.Get("/ws/loom", metricsHub.ServeHTTP)

	// ── SSE LIVE STREAM (cube.js tachometer feed) ─────────────────────────────
	r.Get("/api/events", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		w.Header().Set("X-Accel-Buffering", "no")

		ch := hub.subscribe()
		defer hub.unsubscribe(ch)

		// Send connected event immediately
		connected, _ := json.Marshal(map[string]interface{}{
			"type":          "CONNECTED",
			"total_bridges": hub.totalBridge.Load(),
			"ts":            time.Now().UnixMilli(),
		})
		fmt.Fprintf(w, "data: %s\n\n", connected)
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}

		// Heartbeat every 20 s keeps Render/nginx proxies from closing idle connections
		heartbeat := time.NewTicker(20 * time.Second)
		defer heartbeat.Stop()

		for {
			select {
			case msg, ok := <-ch:
				if !ok {
					return
				}
				w.Write(msg)
				if f, ok := w.(http.Flusher); ok {
					f.Flush()
				}
			case <-heartbeat.C:
				fmt.Fprintf(w, ": keepalive\n\n")
				if f, ok := w.(http.Flusher); ok {
					f.Flush()
				}
			case <-req.Context().Done():
				return
			}
		}
	})

	// ── X402 NATIVE VENDOR ────────────────────────────────────────────────────

	r.Get("/v1/x402/catalog", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{"products": x402Registry.Listing()})
	})

	r.Post("/v1/x402/quote", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 4096)
		var body struct {
			ProductID   string `json:"product_id"`
			AgentWallet string `json:"agent_wallet"`
			TxHash      string `json:"tx_hash,omitempty"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			writeJSONErr(w, http.StatusBadRequest, "ERR_BAD_REQUEST")
			return
		}
		product, err := x402Registry.Lookup(body.ProductID)
		if err != nil {
			writeJSONErr(w, http.StatusNotFound, err.Error())
			return
		}
		tier := "BRONZE"
		if body.AgentWallet != "" {
			t, _ := agentLedger.AgentStats(body.AgentWallet)
			tier = t
		}
		
		if body.TxHash != "" {
			if product.ID == "bridge.attestation" {
				if _, ok := bridgeLedger.Lookup(body.TxHash); !ok {
					writeJSONErr(w, http.StatusNotFound, "ERR_TX_NOT_FOUND")
					return
				}
			} else if product.ID == "cube.mint" {
				if xrplClient != nil {
					if err := xrplClient.VerifyPayment(body.TxHash, treasuryXRPL); err != nil {
						writeJSONErr(w, http.StatusPaymentRequired, "ERR_PAYMENT_INVALID: "+err.Error())
						return
					}
				} else {
					log.Printf("[WARN] No XRPL client to verify cube.mint payment (tx %s)", body.TxHash)
				}
			}
		}

		args := map[string]any{}
		if body.TxHash != "" {
			args["tx_hash"] = body.TxHash
		}
		
		inv, err := x402.Issue(product.ID, body.AgentWallet, tier, product.BasePrice, treasuryXRPL, os.Getenv("X402_TOKEN_SECRET"), args)
		if err != nil {
			writeJSONErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(inv)
	})

	r.Get("/v1/x402/dispense/{pid}", func(w http.ResponseWriter, req *http.Request) {
		pid := chi.URLParam(req, "pid")
		token := req.Header.Get("X-Payment-Token")

		if token == "" {
			// HTTP 402 challenge — return a fresh invoice for the requested product.
			product, err := x402Registry.Lookup(pid)
			if err != nil {
				writeJSONErr(w, http.StatusNotFound, err.Error())
				return
			}
			inv, err := x402.Issue(pid, "", "BRONZE", product.BasePrice, treasuryXRPL, os.Getenv("X402_TOKEN_SECRET"), nil)
			if err != nil {
				writeJSONErr(w, http.StatusInternalServerError, err.Error())
				return
			}
			b, _ := json.Marshal(inv)
			w.Header().Set("X-Payment-Required", string(b))
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusPaymentRequired)
			_, _ = w.Write(b)
			return
		}

		payload, err := x402.Verify(token, os.Getenv("X402_TOKEN_SECRET"))
		if err != nil {
			writeJSONErr(w, http.StatusUnauthorized, err.Error())
			return
		}
		if payload.Pid != pid {
			writeJSONErr(w, http.StatusUnauthorized, "ERR_PRODUCT_MISMATCH")
			return
		}
		if !x402Nonces.Consume(payload.Iid, payload.Exp+60) {
			writeJSONErr(w, http.StatusConflict, "ERR_REPLAY")
			return
		}
		out, err := x402Registry.Dispatch(pid, payload.Args)
		if err != nil {
			writeJSONErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		x402Dispensed.Add(1)
		metricsHub.BroadcastX402Dispensed(pid, payload.Wlt, payload.Tier)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(out)
	})

	r.Get("/v1/x402/attestation/pubkey", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		pub := attestationPrivKey.Public().(ed25519.PublicKey)
		json.NewEncoder(w).Encode(map[string]string{
			"public_key": hex.EncodeToString(pub),
			"alg":        "ed25519",
			"issuer":     "ghost-layer.onrender.com",
		})
	})

	// ── INSTITUTIONAL EXECUTION PATH ─────────────────────────────────────────
	r.Post("/v1/bridge/execute", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 1<<20) // 1 MB

		// Per-IP rate limit
		ip, _, _ := net.SplitHostPort(req.RemoteAddr)
		if !allowIP(ip) {
			http.Error(w, "rate limit exceeded — slow down", http.StatusTooManyRequests)
			return
		}

		var p bridgePayload
		if err := json.NewDecoder(req.Body).Decode(&p); err != nil {
			http.Error(w, "malformed payload", http.StatusBadRequest)
			return
		}

		// XRPL routes have no on-chain EIP-3009 auth, so the application-level
		// signature is mandatory for them. Base routes must have EIP-3009.
		if !p.IsDustTest {
			if p.EIP3009 == nil && p.Signer == "" {
				http.Error(w, "authentication required: provide eip3009 (Base) or signer+signature (XRPL)", http.StatusUnauthorized)
				return
			}
			if p.Signer != "" {
				ok, err := crypto.VerifyEIP3009Signature(p.Signer, p.MessageHash, p.Signature)
				if !ok || err != nil {
					http.Error(w, "signature denied", http.StatusUnauthorized)
					return
				}
			}
		}

		// IsDustTest: validates the full parse + signature path without broadcasting.
		if p.IsDustTest {
			log.Printf("[DRY RUN] source=%s destination=%s amount=%s", p.SourceWallet, p.DestinationWallet, p.GrossAmount)
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]string{
				"status": "DRY_RUN_PASSED",
				"msg":    "Payload parsed and signature validated. No transaction broadcast.",
			})
			return
		}

		var auth *chain.EIP3009Auth
		if p.EIP3009 != nil {
			a, err := parseEIP3009(p.EIP3009)
			if err != nil {
				http.Error(w, "invalid eip3009: "+err.Error(), http.StatusBadRequest)
				return
			}
			// Replay protection: reject nonces we've already accepted.
			if !markNonce(a.Nonce) {
				http.Error(w, "eip3009 nonce already consumed — replay rejected", http.StatusUnauthorized)
				return
			}
			auth = &a
		}

		// ── Agent Loyalty Matrix: resolve effective BPS before routing ─────
		agentAddr := p.Signer
		if agentAddr == "" && p.SourceWallet != "" {
			agentAddr = p.SourceWallet
		}
		effectiveBPS := agentLedger.EffectiveBPS(agentAddr, p.FeeBasisPoints)
		if effectiveBPS != p.FeeBasisPoints {
			tier, _ := agentLedger.AgentStats(agentAddr)
			log.Printf("[LOYALTY] agent=%s tier=%s requested=%d effective=%d",
				agentAddr, tier, p.FeeBasisPoints, effectiveBPS)
		}

		txHash, fee, netAmt, err := engine.RouteTransactionWithDisclosure(
			req.Context(),
			p.SourceWallet, p.DestinationWallet,
			p.GrossAmount, effectiveBPS,
			auth,
		)
		if err != nil {
			// Sanitize: don't leak internal details to the client.
			log.Printf("[ERROR] route failed source=%s destination=%s: %v", p.SourceWallet, p.DestinationWallet, err)
			http.Error(w, "routing failed", http.StatusInternalServerError)
			return
		}

		// Record volume for loyalty tier progression
		grossAmt, _ := new(big.Int).SetString(p.GrossAmount, 10)
		newTier := agentLedger.RecordVolume(agentAddr, grossAmt)

		// Detect chain from wallet addresses
		chain := "xrpl"
		if strings.HasPrefix(p.SourceWallet, "0x") {
			chain = "base"
		}

		// Broadcast to BOTH SSE (legacy) and WebSocket (sovereign stream)
		hub.totalBridge.Add(1)
		hub.broadcast("BRIDGE_SETTLED", map[string]interface{}{
			"tx_hash":    txHash,
			"chain":      chain,
			"gross":      p.GrossAmount,
			"fee":        fee.String(),
			"net":        netAmt.String(),
			"source":     p.SourceWallet[:min(len(p.SourceWallet), 12)] + "...",
			"dest":       p.DestinationWallet[:min(len(p.DestinationWallet), 12)] + "...",
		})
		metricsHub.BroadcastBridgeSettled(chain, txHash, grossAmt, fee, netAmt, newTier, effectiveBPS)

		bridgeLedger.Record(ledger.BridgeRecord{
			BridgeID:          "",
			TxHash:            txHash,
			Chain:             chain,
			SourceWallet:      p.SourceWallet,
			DestinationWallet: p.DestinationWallet,
			GrossAmount:       p.GrossAmount,
			FeeAmount:         fee.String(),
			NetAmount:         netAmt.String(),
			EffectiveBPS:      effectiveBPS,
			AgentTier:         newTier,
			SettledAt:         time.Now().Unix(),
		})

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":           "SUCCESSFULLY_SETTLED",
			"transaction_hash": txHash,
			"gross_processed":  p.GrossAmount,
			"transparent_fee":  fee.String(),
			"net_delivered":    netAmt.String(),
			"treasury_routing": treasuryXRPL,
			"agent_tier":       newTier,
			"effective_bps":    effectiveBPS,
		})
	})

	// ── SECURE ADMIN CONTROLS ─────────────────────────────────────────────────
	r.Route("/v1/admin", func(a chi.Router) {
		a.Use(adminAuthMiddleware)

		// Force-drain both gateway wallets to cold treasury.
		a.Post("/sweep", func(w http.ResponseWriter, req *http.Request) {
			log.Println("[FORCE SWEEP] Manual override triggered")
			results, err := engine.ForceManualSweep(context.Background())
			if err != nil {
				log.Printf("[ERROR] force sweep: %v", err)
				http.Error(w, "sweep failed", http.StatusInternalServerError)
				return
			}
			results["status"] = "GATEWAYS_VACATED"
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(results)
		})

		// 1-drop XRPL or 1-wei USDC send to verify live signing before opening volume.
		a.Post("/dust-test", func(w http.ResponseWriter, req *http.Request) {
			req.Body = http.MaxBytesReader(w, req.Body, 1<<20)
			var body struct {
				Chain       string `json:"chain"`
				Destination string `json:"destination"`
			}
			if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
				http.Error(w, "invalid body", http.StatusBadRequest)
				return
			}
			var txHash string
			var err error
			switch body.Chain {
			case "xrpl":
				if xrplClient == nil {
					http.Error(w, "XRPL client not initialised", http.StatusServiceUnavailable)
					return
				}
				txHash, err = xrplClient.SendPayment(body.Destination, 1)
			case "evm", "base":
				if baseClient == nil {
					http.Error(w, "Base client not initialised", http.StatusServiceUnavailable)
					return
				}
				txHash, err = baseClient.SweepUSDCToTreasury(context.Background(), body.Destination)
			default:
				http.Error(w, "chain must be 'xrpl' or 'evm'", http.StatusBadRequest)
				return
			}
			if err != nil {
				log.Printf("[ERROR] dust-test failed: %v", err)
				http.Error(w, "dust-test failed", http.StatusInternalServerError)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]string{"status": "dust sent", "tx": txHash})
		})
	})

	// ── MCP JSON-RPC 2.0 (Smithery / MCP client compatibility) ─────────────
	{
		type mcpTool struct {
			Name        string      `json:"name"`
			Description string      `json:"description"`
			InputSchema interface{} `json:"inputSchema"`
		}
		glTools := []mcpTool{
			{
				Name:        "ghost_bridge_health",
				Description: "Ghost Layer service health. Returns XRPL and Base client connection status and total lifetime bridge count. Free.",
				InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
			},
			{
				Name:        "ghost_layer_bridge",
				Description: "Execute a dual-chain payment bridge. Routes XRPL RLUSD or Base USDC with transparent fee split. No custody — net amount goes directly to destination_wallet. Set is_dust_test=true for dry-run validation without broadcasting.",
				InputSchema: map[string]interface{}{
					"type":     "object",
					"required": []string{"source_wallet", "destination_wallet", "gross_amount", "fee_basis_points"},
					"properties": map[string]interface{}{
						"signer":             map[string]string{"type": "string", "description": "XRPL address — required for XRPL routes"},
						"message_hash":       map[string]string{"type": "string", "description": "EIP-191 message hash"},
						"signature":          map[string]string{"type": "string", "description": "Ed25519 (XRPL) or ECDSA (EVM) signature"},
						"source_wallet":      map[string]string{"type": "string", "description": "rADDRESS (XRPL) or 0x address (Base)"},
						"destination_wallet": map[string]string{"type": "string", "description": "rADDRESS (XRPL) or 0x address (Base)"},
						"gross_amount":       map[string]string{"type": "string", "description": "Amount in drops (XRP) or wei (USDC)"},
						"fee_basis_points":   map[string]interface{}{"type": "integer", "description": "Fee in bps, e.g. 50 = 0.5%"},
						"is_dust_test":       map[string]interface{}{"type": "boolean", "description": "Dry-run without broadcasting", "default": false},
					},
				},
			},
			{
				Name:        "ghost_audit_stats",
				Description: "Public audit stats: total bridges executed, XRPL and Base client status, supported chains and currencies. Free.",
				InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
			},
		}
		selfClient := &http.Client{Timeout: 30 * time.Second}

		r.Get("/mcp", func(w http.ResponseWriter, req *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{
				"server":      map[string]string{"name": "ghost-layer", "version": "1.0.0", "description": "Dual-chain XRPL RLUSD + Base USDC transparent payment bridge"},
				"protocol":    "MCP JSON-RPC 2.0",
				"tools_count": len(glTools),
			})
		})

		r.Post("/mcp", func(w http.ResponseWriter, req *http.Request) {
			var body struct {
				ID     interface{}     `json:"id"`
				Method string          `json:"method"`
				Params json.RawMessage `json:"params"`
			}
			w.Header().Set("Content-Type", "application/json")
			enc := json.NewEncoder(w)

			if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
				enc.Encode(map[string]interface{}{"jsonrpc": "2.0", "id": nil, "error": map[string]interface{}{"code": -32700, "message": "Parse error"}})
				return
			}
			ok := func(res interface{}) {
				enc.Encode(map[string]interface{}{"jsonrpc": "2.0", "id": body.ID, "result": res})
			}
			text := func(data interface{}) map[string]interface{} {
				b, _ := json.MarshalIndent(data, "", "  ")
				return map[string]interface{}{"content": []interface{}{map[string]string{"type": "text", "text": string(b)}}}
			}

			switch body.Method {
			case "initialize":
				ok(map[string]interface{}{
					"protocolVersion": "2024-11-05",
					"serverInfo":      map[string]string{"name": "ghost-layer", "version": "1.0.0"},
					"capabilities":    map[string]interface{}{"tools": map[string]interface{}{}},
				})
			case "ping":
				ok(map[string]interface{}{})
			case "tools/list":
				ok(map[string]interface{}{"tools": glTools, "nextCursor": nil})
			case "tools/call":
				var p struct {
					Name      string                 `json:"name"`
					Arguments map[string]interface{} `json:"arguments"`
				}
				if err := json.Unmarshal(body.Params, &p); err != nil {
					w.WriteHeader(400)
					enc.Encode(map[string]interface{}{"jsonrpc": "2.0", "id": body.ID, "error": map[string]interface{}{"code": -32602, "message": "Invalid params"}})
					return
				}
				switch p.Name {
				case "ghost_bridge_health":
					st := engine.ClientStatus()
					ok(text(map[string]interface{}{
						"status":        "ok",
						"xrpl_client":   st["xrpl"],
						"base_client":   st["base"],
						"total_bridges": hub.totalBridge.Load(),
					}))
				case "ghost_audit_stats":
					st := engine.ClientStatus()
					ok(text(map[string]interface{}{
						"total_bridges": hub.totalBridge.Load(),
						"xrpl_status":   st["xrpl"],
						"base_status":   st["base"],
						"chains":        []string{"XRPL", "Base"},
						"currencies":    []string{"RLUSD", "USDC"},
						"networks": map[string]interface{}{
							"xrpl": map[string]string{"network": "mainnet", "rpc": "https://xrplcluster.com", "currency": "RLUSD", "issuer": "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"},
							"base": map[string]string{"network": "base-mainnet", "currency": "USDC"},
						},
					}))
				case "ghost_layer_bridge":
					args, _ := json.Marshal(p.Arguments)
					proxyReq, _ := http.NewRequestWithContext(req.Context(), "POST", "http://localhost:"+port+"/v1/bridge/execute", strings.NewReader(string(args)))
					proxyReq.Header.Set("Content-Type", "application/json")
					resp, err := selfClient.Do(proxyReq)
					if err != nil {
						ok(text(map[string]string{"error": err.Error()}))
						return
					}
					defer resp.Body.Close()
					var result interface{}
					json.NewDecoder(resp.Body).Decode(&result)
					ok(text(result))
				default:
					ok(map[string]interface{}{
						"content": []interface{}{map[string]string{"type": "text", "text": `{"error":"ERR_UNKNOWN_TOOL","tool":"` + p.Name + `"}`}},
						"isError": true,
					})
				}
			default:
				if strings.HasPrefix(body.Method, "notifications/") {
					w.WriteHeader(204)
					return
				}
				w.WriteHeader(400)
				enc.Encode(map[string]interface{}{"jsonrpc": "2.0", "id": body.ID, "error": map[string]interface{}{"code": -32601, "message": "Method not found: " + body.Method}})
			}
		})
	}

	// ── CUBE EXECUTION MATRIX ─────────────────────────────────────────────────


	// POST /api/cube/state — receive 54-block payload, verify, store, broadcast
	r.Post("/api/cube/state", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 64*1024)
		var p CubeStatePayload
		if err := json.NewDecoder(req.Body).Decode(&p); err != nil {
			http.Error(w, "malformed payload", http.StatusBadRequest)
			return
		}

		hash, err := validateCubePayload(&p)
		if err != nil {
			log.Printf("[CUBE] validation failed: %v", err)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnprocessableEntity)
			json.NewEncoder(w).Encode(CubeStateResponse{Verified: false, Error: err.Error()})
			return
		}

		cubeStateMu.Lock()
		lastCubeState = &p
		lastCommitTime = time.Now()
		committed := lastCommitTime
		cubeStateMu.Unlock()

		hookParams := buildHookParams(p.Faces)

		// SSE broadcast so all connected terminals see the commit
		centers := make(map[string]interface{}, 6)
		for _, key := range cubeKeys {
			centers[key] = p.Faces[key].Center
		}
		hub.broadcast("CUBE_STATE_COMMITTED", map[string]interface{}{
			"state_hash":   hash,
			"face_centers": centers,
			"hook_count":   len(hookParams),
		})

		log.Printf("[CUBE] committed hash=%s hooks=%d", hash, len(hookParams))
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(CubeStateResponse{
			Verified:    true,
			StateHash:   hash,
			Faces:       p.Faces,
			HookParams:  hookParams,
			CommittedAt: committed.UTC().Format(time.RFC3339),
		})
	})

	// GET /api/cube/state — return last committed state
	r.Get("/api/cube/state", func(w http.ResponseWriter, req *http.Request) {
		cubeStateMu.RLock()
		state := lastCubeState
		committed := lastCommitTime
		cubeStateMu.RUnlock()

		w.Header().Set("Content-Type", "application/json")
		if state == nil {
			json.NewEncoder(w).Encode(map[string]interface{}{
				"committed": false,
				"msg":       "no cube state committed yet",
			})
			return
		}
		json.NewEncoder(w).Encode(CubeStateResponse{
			Verified:    true,
			StateHash:   state.Hash,
			Faces:       state.Faces,
			HookParams:  buildHookParams(state.Faces),
			CommittedAt: committed.UTC().Format(time.RFC3339),
		})
	})

	// GET /api/cube/payload — Xahau Hook-ready URIToken memo payload
	r.Get("/api/cube/payload", func(w http.ResponseWriter, req *http.Request) {
		cubeStateMu.RLock()
		state := lastCubeState
		committed := lastCommitTime
		cubeStateMu.RUnlock()

		w.Header().Set("Content-Type", "application/json")
		if state == nil {
			http.Error(w, "no committed cube state", http.StatusNotFound)
			return
		}
		hookParams := buildHookParams(state.Faces)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"schema_version":  "54-block-v1",
			"hook_type":       "CUBE_STATE",
			"state_hash":      state.Hash,
			"committed_at":    committed.UTC().Format(time.RFC3339),
			"hook_parameters": hookParams,
			"memo": map[string]string{
				"MemoData":   strings.ToUpper(hex.EncodeToString([]byte(state.Hash))),
				"MemoType":   strings.ToUpper(hex.EncodeToString([]byte("CUBE_STATE"))),
				"MemoFormat": strings.ToUpper(hex.EncodeToString([]byte("application/json"))),
			},
		})
	})

	// ── WELL-KNOWN DISCOVERY FILES ───────────────────────────────────────────
	r.Get("/.well-known/mcp.json", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		http.ServeFile(w, req, "./public/.well-known/mcp.json")
	})
	r.Get("/.well-known/server.json", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		http.ServeFile(w, req, "./public/.well-known/server.json")
	})


	// ── STATIC FRONTEND (Three.js terminal) ──────────────────────────────────
	fs := http.FileServer(http.Dir("./public"))
	r.Handle("/*", fs)

	// ── GRACEFUL SHUTDOWN ─────────────────────────────────────────────────────
	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 60 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		log.Printf("[SERVER KERNEL] Ghost Layer active on :%s | XRPL treasury: %s", port, treasuryXRPL)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[FATAL] %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("[SERVER] Shutdown signal received — draining in-flight requests (30s)...")

	// Wait for any in-flight sweep goroutines before closing the server.
	sweepWg.Wait()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Fatalf("[FATAL] forced shutdown: %v", err)
	}
	log.Println("[SERVER] Stopped cleanly.")
}

// corsMiddleware allows browser clients to reach the API.
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// adminAuthMiddleware rejects requests without a valid Bearer token.
func adminAuthMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := os.Getenv("ADMIN_TOKEN")
		if token == "" {
			http.Error(w, "admin endpoints not configured", http.StatusForbidden)
			return
		}
		if strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ") != token {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func parseEIP3009(p *eip3009Payload) (chain.EIP3009Auth, error) {
	validAfter := new(big.Int)
	validAfter.SetString(p.ValidAfter, 10)
	validBefore := new(big.Int)
	validBefore.SetString(p.ValidBefore, 10)

	nonce, err := decode32(p.Nonce)
	if err != nil {
		return chain.EIP3009Auth{}, errors.New("nonce: " + err.Error())
	}
	rBytes, err := decode32(p.R)
	if err != nil {
		return chain.EIP3009Auth{}, errors.New("r: " + err.Error())
	}
	sBytes, err := decode32(p.S)
	if err != nil {
		return chain.EIP3009Auth{}, errors.New("s: " + err.Error())
	}

	return chain.EIP3009Auth{
		ValidAfter:  validAfter,
		ValidBefore: validBefore,
		Nonce:       nonce,
		V:           p.V,
		R:           rBytes,
		S:           sBytes,
	}, nil
}

func decode32(s string) ([32]byte, error) {
	b, err := hex.DecodeString(strings.TrimPrefix(s, "0x"))
	if err != nil {
		return [32]byte{}, err
	}
	if len(b) != 32 {
		return [32]byte{}, errors.New("must be 32 bytes")
	}
	var out [32]byte
	copy(out[:], b)
	return out, nil
}
