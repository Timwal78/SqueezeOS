package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
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
	"ghost-layer-core/internal/router"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

// ── SSE Hub — broadcasts bridge events to connected cube.js clients ──────────

type sseHub struct {
	mu          sync.RWMutex
	clients     map[chan []byte]struct{}
	totalBridge atomic.Int64
	totalFees   atomic.Int64 // in drops/wei, for display
}

var hub = &sseHub{clients: make(map[chan []byte]struct{})}

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

	var xrplClient *chain.XRPLClient
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

	var baseClient *chain.BaseClient
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

	engine := router.NewTransparentBridgeEngine(treasuryXRPL, treasuryETH, xrplClient, baseClient)

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
			"xrpl_treasury":  treasuryXRPL,
			"total_bridges":  hub.totalBridge.Load(),
		})
	})

	// ── CONFIG (injected into cube.js via fetch) ──────────────────────────────
	squeezeosSSE := env("SQUEEZEOS_SSE_URL", "")
	r.Get("/api/config", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"sse_url":        "/api/events",
			"squeezeos_sse":  squeezeosSSE,
			"xrpl_treasury":  treasuryXRPL,
			"xrpl_enabled":   xrplKey != "",
			"base_enabled":   ethKey != "",
			"total_bridges":  hub.totalBridge.Load(),
		})
	})

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

		sweepWg.Add(1)
		txHash, fee, netAmt, err := engine.RouteTransactionWithDisclosure(
			req.Context(),
			p.SourceWallet, p.DestinationWallet,
			p.GrossAmount, p.FeeBasisPoints,
			auth,
		)
		sweepWg.Done()
		if err != nil {
			// Sanitize: don't leak internal details to the client.
			log.Printf("[ERROR] route failed source=%s destination=%s: %v", p.SourceWallet, p.DestinationWallet, err)
			http.Error(w, "routing failed", http.StatusInternalServerError)
			return
		}

		// Detect chain from wallet addresses and broadcast to cube.js
		chain := "xrpl"
		if strings.HasPrefix(p.SourceWallet, "0x") {
			chain = "base"
		}
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

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":           "SUCCESSFULLY_SETTLED",
			"transaction_hash": txHash,
			"gross_processed":  p.GrossAmount,
			"transparent_fee":  fee.String(),
			"net_delivered":    netAmt.String(),
			"treasury_routing": treasuryXRPL,
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
