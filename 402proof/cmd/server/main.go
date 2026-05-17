package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"

	"proof402/internal/firewall"
	"proof402/internal/invoice"
	"proof402/internal/loyalty"
	"proof402/internal/models"
	"proof402/internal/notify"
	"proof402/internal/passport"
	"proof402/internal/receipt"
	"proof402/internal/store"
	"proof402/internal/xrpl"
)

type ctxKey string

const merchantCtxKey ctxKey = "merchant"

func main() {
	port := env("PORT", "9090")
	xrplRPC := env("XRPL_RPC_URL", "https://xrplcluster.com")
	gatewayAddr := env("GATEWAY_XRPL_ADDRESS", "")
	tokenSecret := env("TOKEN_SECRET", "")
	adminToken := env("ADMIN_TOKEN", "")
	rlusdIssuer := env("RLUSD_ISSUER", "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De")
	serverURL := env("SERVER_URL", "http://localhost:9090")

	if gatewayAddr == "" {
		log.Fatalf("[FATAL] GATEWAY_XRPL_ADDRESS not set")
	}
	if tokenSecret == "" {
		log.Fatalf("[FATAL] TOKEN_SECRET not set — generate with: openssl rand -hex 32")
	}
	if adminToken == "" {
		log.Fatalf("[FATAL] ADMIN_TOKEN not set — generate with: openssl rand -hex 32")
	}

	db := store.NewMemory()
	xrplClient := xrpl.NewClient(xrplRPC)
	emailCfg := notify.LoadConfig()
	if emailCfg.Enabled {
		log.Printf("[NOTIFY] Email receipts → %s via %s", emailCfg.To, emailCfg.Host)
	} else {
		log.Printf("[NOTIFY] Email disabled — set SMTP_HOST, SMTP_USER, SMTP_PASS to enable")
	}

	r := chi.NewRouter()
	r.Use(corsMiddleware)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))

	// ── HEALTH ──────────────────────────────────────────────────────────────────
	r.Get("/health", func(w http.ResponseWriter, req *http.Request) {
		writeJSON(w, 200, map[string]string{"status": "ok", "gateway": gatewayAddr})
	})

	// ── PUBLIC STATS + LEADERBOARD ───────────────────────────────────────────────
	r.Get("/v1/stats", func(w http.ResponseWriter, req *http.Request) {
		writeJSON(w, 200, db.Stats())
	})

	r.Get("/v1/leaderboard", func(w http.ResponseWriter, req *http.Request) {
		writeJSON(w, 200, map[string]interface{}{"endpoints": db.ListEndpoints("")})
	})

	// ── MERCHANT REGISTRATION ────────────────────────────────────────────────────
	r.Post("/v1/merchant/register", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 64*1024)
		var body struct {
			Name  string `json:"name"`
			Email string `json:"email"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Name == "" || body.Email == "" {
			http.Error(w, "name and email required", http.StatusBadRequest)
			return
		}
		m := &models.Merchant{
			ID:        uuid.New().String(),
			Name:      body.Name,
			Email:     body.Email,
			APIKey:    uuid.New().String(),
			Plan:      "free",
			CreatedAt: time.Now(),
		}
		db.SaveMerchant(m)
		writeJSON(w, 201, m)
	})

	// ── ENDPOINT MANAGEMENT ──────────────────────────────────────────────────────
	r.Route("/v1/endpoint", func(ep chi.Router) {
		ep.Use(merchantAuthMiddleware(db))

		ep.Post("/", func(w http.ResponseWriter, req *http.Request) {
			req.Body = http.MaxBytesReader(w, req.Body, 64*1024)
			merchant := merchantFromCtx(req)
			var body struct {
				Path        string `json:"path"`
				Price       string `json:"price"`
				Asset       string `json:"asset"`
				Description string `json:"description"`
			}
			if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Path == "" || body.Price == "" {
				http.Error(w, "path and price required", http.StatusBadRequest)
				return
			}
			asset := body.Asset
			if asset == "" {
				asset = "RLUSD"
			}
			if asset != "XRP" && asset != "RLUSD" {
				http.Error(w, "asset must be XRP or RLUSD", http.StatusBadRequest)
				return
			}
			e := &models.Endpoint{
				ID:          uuid.New().String(),
				MerchantID:  merchant.ID,
				Path:        body.Path,
				Price:       body.Price,
				Asset:       asset,
				Description: body.Description,
				Active:      true,
				CreatedAt:   time.Now(),
			}
			db.SaveEndpoint(e)
			writeJSON(w, 201, e)
		})

		ep.Get("/", func(w http.ResponseWriter, req *http.Request) {
			merchant := merchantFromCtx(req)
			writeJSON(w, 200, db.ListEndpoints(merchant.ID))
		})
	})

	// ── POLICY MANAGEMENT ────────────────────────────────────────────────────────
	r.Route("/v1/policy", func(p chi.Router) {
		p.Use(merchantAuthMiddleware(db))

		p.Put("/{endpointID}", func(w http.ResponseWriter, req *http.Request) {
			req.Body = http.MaxBytesReader(w, req.Body, 64*1024)
			endpointID := chi.URLParam(req, "endpointID")
			merchant := merchantFromCtx(req)
			ep, ok := db.GetEndpoint(endpointID)
			if !ok || ep.MerchantID != merchant.ID {
				http.Error(w, "endpoint not found", http.StatusNotFound)
				return
			}
			var pol models.Policy
			if err := json.NewDecoder(req.Body).Decode(&pol); err != nil {
				http.Error(w, "invalid body", http.StatusBadRequest)
				return
			}
			pol.EndpointID = endpointID
			db.SavePolicy(&pol)
			writeJSON(w, 200, pol)
		})

		p.Get("/{endpointID}", func(w http.ResponseWriter, req *http.Request) {
			endpointID := chi.URLParam(req, "endpointID")
			merchant := merchantFromCtx(req)
			ep, ok := db.GetEndpoint(endpointID)
			if !ok || ep.MerchantID != merchant.ID {
				http.Error(w, "endpoint not found", http.StatusNotFound)
				return
			}
			pol, ok := db.GetPolicy(endpointID)
			if !ok {
				writeJSON(w, 200, map[string]string{"endpoint_id": endpointID, "policy": "none"})
				return
			}
			writeJSON(w, 200, pol)
		})
	})

	// ── CORE x402 FLOW ───────────────────────────────────────────────────────────

	// Step 1: Generate invoice
	r.Post("/v1/invoice", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 64*1024)
		var body struct {
			EndpointID string `json:"endpoint_id"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.EndpointID == "" {
			http.Error(w, "endpoint_id required", http.StatusBadRequest)
			return
		}
		ep, ok := db.GetEndpoint(body.EndpointID)
		if !ok || !ep.Active {
			http.Error(w, "endpoint not found", http.StatusNotFound)
			return
		}
		inv := invoice.New(ep, gatewayAddr)
		db.SaveInvoice(inv)
		writeJSON(w, 200, map[string]interface{}{
			"invoice_id": inv.ID,
			"pay_to":     inv.PayTo,
			"amount":     inv.Price,
			"asset":      inv.Asset,
			"network":    inv.Network,
			"memo_hex":   inv.MemoHex,
			"expires_at": inv.ExpiresAt.Unix(),
			"memo_note":  "Set this as MemoData in your XRPL payment transaction",
		})
	})

	// Step 2: Verify payment + issue access token
	r.Post("/v1/verify", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 64*1024)
		var body struct {
			InvoiceID   string `json:"invoice_id"`
			TxHash      string `json:"tx_hash"`
			AgentWallet string `json:"agent_wallet"`
			AgentDomain string `json:"agent_domain"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			http.Error(w, "invalid body", http.StatusBadRequest)
			return
		}
		if body.InvoiceID == "" || body.TxHash == "" || body.AgentWallet == "" {
			http.Error(w, "invoice_id, tx_hash, and agent_wallet required", http.StatusBadRequest)
			return
		}

		inv, ok := db.GetInvoice(body.InvoiceID)
		if !ok {
			http.Error(w, "invoice not found", http.StatusNotFound)
			return
		}
		if inv.Status == "paid" {
			http.Error(w, "invoice already settled — replay rejected", http.StatusConflict)
			return
		}
		if invoice.IsExpired(inv) {
			http.Error(w, "invoice expired", http.StatusGone)
			return
		}
		if !db.MarkTxUsed(body.TxHash) {
			http.Error(w, "transaction already used — replay rejected", http.StatusConflict)
			return
		}

		if _, err := xrplClient.VerifyPayment(body.TxHash, gatewayAddr, inv.Price, inv.Asset, inv.MemoHex, rlusdIssuer); err != nil {
			log.Printf("[VERIFY] failed invoice=%s tx=%s: %v", body.InvoiceID, body.TxHash, err)
			http.Error(w, "payment verification failed", http.StatusPaymentRequired)
			return
		}

		agent := db.GetOrCreateAgent(body.AgentWallet)
		if body.AgentDomain != "" {
			agent.Domain = body.AgentDomain
		}

		pol, _ := db.GetPolicy(inv.EndpointID)
		dailyCalls := db.DailyCallCount(inv.EndpointID, body.AgentWallet)
		if err := firewall.Check(pol, agent, inv, dailyCalls); err != nil {
			log.Printf("[FIREWALL] blocked agent=%s endpoint=%s: %v", body.AgentWallet, inv.EndpointID, err)
			http.Error(w, "access denied: "+err.Error(), http.StatusForbidden)
			return
		}

		accessToken, err := invoice.IssueToken(inv, tokenSecret)
		if err != nil {
			log.Printf("[TOKEN] issue failed: %v", err)
			http.Error(w, "token issuance failed", http.StatusInternalServerError)
			return
		}

		db.MarkInvoicePaid(inv.ID, body.TxHash, body.AgentWallet)
		passport.UpdateAfterPayment(agent)

		// Loyalty: accumulate spend, award free credits, detect tier upgrade
		amountFloat := 0.0
		if inv.Asset == "RLUSD" || inv.Asset == "XRP" {
			amountFloat, _ = strconv.ParseFloat(inv.Price, 64)
		}
		creditsAwarded, tierChanged, newTier := loyalty.ProcessPayment(agent, amountFloat)

		db.UpdateAgent(agent)
		db.IncrDailyCall(inv.EndpointID, body.AgentWallet)
		db.IncrEndpointCalls(inv.EndpointID)

		riskScore := passport.Score(agent)
		r := receipt.New(inv, body.TxHash, body.AgentWallet, body.AgentDomain, passport.RiskLevel(riskScore), accessToken)
		db.SaveReceipt(r)

		if tierChanged {
			log.Printf("[LOYALTY] %s upgraded to %s %s (credits=%d)", body.AgentWallet, newTier.Badge, newTier.Name, agent.FreeCredits)
		}
		if creditsAwarded > 0 {
			log.Printf("[LOYALTY] %s earned %d free credit(s) — balance=%d", body.AgentWallet, creditsAwarded, agent.FreeCredits)
		}

		ep, _ := db.GetEndpoint(inv.EndpointID)
		notify.SendReceipt(emailCfg, notify.Receipt{
			ID:           r.ID,
			InvoiceID:    inv.ID,
			EndpointID:   inv.EndpointID,
			EndpointPath: ep.Path,
			Amount:       inv.Price,
			Asset:        inv.Asset,
			TxHash:       body.TxHash,
			AgentWallet:  body.AgentWallet,
			AgentDomain:  body.AgentDomain,
			RiskLevel:    r.RiskLevel,
			SettledAt:    r.SettledAt,
		})

		writeJSON(w, 200, map[string]interface{}{
			"status":          "PAYMENT_VERIFIED",
			"access_token":    accessToken,
			"receipt_id":      r.ID,
			"risk_level":      r.RiskLevel,
			"settled_at":      r.SettledAt,
			"loyalty_tier":    newTier.Name,
			"loyalty_badge":   newTier.Badge,
			"free_credits":    agent.FreeCredits,
			"credits_awarded": creditsAwarded,
			"tier_upgraded":   tierChanged,
		})
	})

	// Step 3: Verify access token (called by middleware on each protected request)
	r.Post("/v1/token/verify", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 8*1024)
		var body struct {
			Token      string `json:"token"`
			EndpointID string `json:"endpoint_id"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Token == "" {
			http.Error(w, "token required", http.StatusBadRequest)
			return
		}
		endpointID, err := invoice.VerifyToken(body.Token, tokenSecret)
		if err != nil {
			http.Error(w, "invalid token: "+err.Error(), http.StatusUnauthorized)
			return
		}
		if body.EndpointID != "" && endpointID != body.EndpointID {
			http.Error(w, "token not valid for this endpoint", http.StatusUnauthorized)
			return
		}
		writeJSON(w, 200, map[string]string{"status": "VALID", "endpoint_id": endpointID})
	})

	// ── RECEIPTS ──────────────────────────────────────────────────────────────────
	r.Get("/v1/receipt/{id}", func(w http.ResponseWriter, req *http.Request) {
		id := chi.URLParam(req, "id")
		rec, ok := db.GetReceipt(id)
		if !ok {
			http.Error(w, "receipt not found", http.StatusNotFound)
			return
		}
		export := *rec
		export.AccessToken = ""
		writeJSON(w, 200, export)
	})

	r.Get("/v1/receipt/{id}/json", func(w http.ResponseWriter, req *http.Request) {
		id := chi.URLParam(req, "id")
		rec, ok := db.GetReceipt(id)
		if !ok {
			http.Error(w, "receipt not found", http.StatusNotFound)
			return
		}
		b, _ := receipt.ToJSON(rec)
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="receipt-%s.json"`, id[:8]))
		w.Write(b)
	})

	r.Get("/v1/receipt/{id}/csv", func(w http.ResponseWriter, req *http.Request) {
		id := chi.URLParam(req, "id")
		rec, ok := db.GetReceipt(id)
		if !ok {
			http.Error(w, "receipt not found", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "text/csv")
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="receipt-%s.csv"`, id[:8]))
		fmt.Fprint(w, receipt.ToCSV(rec))
	})

	// ── LOYALTY ───────────────────────────────────────────────────────────────────

	// GET /v1/loyalty/{wallet} — tier, credits, progress to next tier
	r.Get("/v1/loyalty/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		wallet := chi.URLParam(req, "wallet")
		agent, ok := db.GetAgent(wallet)
		if !ok {
			// Return bronze for unknown wallets
			agent = &models.Agent{Wallet: wallet}
		}
		writeJSON(w, 200, loyalty.Summary(agent))
	})

	// POST /v1/loyalty/redeem — burn 1 credit, receive access token (no XRPL payment needed)
	r.Post("/v1/loyalty/redeem", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 8*1024)
		var body struct {
			AgentWallet string `json:"agent_wallet"`
			EndpointID  string `json:"endpoint_id"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.AgentWallet == "" || body.EndpointID == "" {
			http.Error(w, "agent_wallet and endpoint_id required", http.StatusBadRequest)
			return
		}
		agent, ok := db.GetAgent(body.AgentWallet)
		if !ok || agent.FreeCredits <= 0 {
			http.Error(w, "no free credits available", http.StatusPaymentRequired)
			return
		}
		ep, ok := db.GetEndpoint(body.EndpointID)
		if !ok || !ep.Active {
			http.Error(w, "endpoint not found", http.StatusNotFound)
			return
		}
		if !loyalty.RedeemCredit(agent) {
			http.Error(w, "no free credits available", http.StatusPaymentRequired)
			return
		}
		db.UpdateAgent(agent)

		// Issue a synthetic invoice and token for the credit redemption
		inv := invoice.New(ep, gatewayAddr)
		inv.Status = "paid"
		db.SaveInvoice(inv)

		accessToken, err := invoice.IssueToken(inv, tokenSecret)
		if err != nil {
			http.Error(w, "token issuance failed", http.StatusInternalServerError)
			return
		}

		log.Printf("[LOYALTY] credit redeemed: agent=%s endpoint=%s credits_remaining=%d", body.AgentWallet, body.EndpointID, agent.FreeCredits)

		writeJSON(w, 200, map[string]interface{}{
			"status":           "CREDIT_REDEEMED",
			"access_token":     accessToken,
			"credits_remaining": agent.FreeCredits,
			"loyalty_tier":     agent.LoyaltyTier,
		})
	})

	// ── AGENT PASSPORT ────────────────────────────────────────────────────────────
	r.Get("/v1/agent/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		wallet := chi.URLParam(req, "wallet")
		agent, ok := db.GetAgent(wallet)
		if !ok {
			http.Error(w, "agent not found", http.StatusNotFound)
			return
		}
		writeJSON(w, 200, agent)
	})

	// ── BADGE ─────────────────────────────────────────────────────────────────────
	// /v1/badge/:id  — full live badge page (linked from badge anchor)
	r.Get("/v1/badge/{endpointID}", func(w http.ResponseWriter, req *http.Request) {
		endpointID := chi.URLParam(req, "endpointID")
		if _, ok := db.GetEndpoint(endpointID); !ok {
			http.Error(w, "endpoint not found", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "text/html")
		fmt.Fprintf(w, `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>402Proof Verified Endpoint</title>
<style>body{background:#050508;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;font-family:monospace}</style>
</head><body>
<script src="%s/badge.js?endpoint=%s"></script>
</body></html>`, serverURL, endpointID)
	})

	// /badge/:id  — shortlink for badge page
	r.Get("/badge/{endpointID}", func(w http.ResponseWriter, req *http.Request) {
		endpointID := chi.URLParam(req, "endpointID")
		http.Redirect(w, req, "/v1/badge/"+endpointID, http.StatusFound)
	})

	// ── ADMIN ─────────────────────────────────────────────────────────────────────
	r.Route("/v1/admin", func(a chi.Router) {
		a.Use(adminAuthMiddleware(adminToken))

		a.Get("/receipts", func(w http.ResponseWriter, req *http.Request) {
			receipts := db.ListRecentReceipts(500)
			w.Header().Set("Content-Type", "text/csv")
			w.Header().Set("Content-Disposition", `attachment; filename="receipts.csv"`)
			fmt.Fprint(w, receipt.BulkCSV(receipts))
		})

		a.Post("/agent/{wallet}/block", func(w http.ResponseWriter, req *http.Request) {
			wallet := chi.URLParam(req, "wallet")
			req.Body = http.MaxBytesReader(w, req.Body, 8*1024)
			var body struct {
				Reason string `json:"reason"`
			}
			json.NewDecoder(req.Body).Decode(&body)
			agent := db.GetOrCreateAgent(wallet)
			agent.IsBlocked = true
			agent.BlockReason = body.Reason
			db.UpdateAgent(agent)
			writeJSON(w, 200, map[string]string{"status": "blocked", "wallet": wallet})
		})

		a.Delete("/agent/{wallet}/block", func(w http.ResponseWriter, req *http.Request) {
			wallet := chi.URLParam(req, "wallet")
			agent, ok := db.GetAgent(wallet)
			if !ok {
				http.Error(w, "agent not found", http.StatusNotFound)
				return
			}
			agent.IsBlocked = false
			agent.BlockReason = ""
			db.UpdateAgent(agent)
			writeJSON(w, 200, map[string]string{"status": "unblocked", "wallet": wallet})
		})

		a.Get("/stats", func(w http.ResponseWriter, req *http.Request) {
			writeJSON(w, 200, db.Stats())
		})
	})

	// ── STATIC DASHBOARD ──────────────────────────────────────────────────────────
	fs := http.FileServer(http.Dir("./public"))
	r.Handle("/*", fs)

	// ── GRACEFUL SHUTDOWN ─────────────────────────────────────────────────────────
	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		log.Printf("[402Proof] Active on :%s | Gateway: %s", port, gatewayAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[FATAL] %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("[402Proof] Shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	srv.Shutdown(ctx)
	log.Println("[402Proof] Stopped.")
}

func writeJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Payment-Token")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func merchantAuthMiddleware(db *store.Memory) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			apiKey := r.Header.Get("X-API-Key")
			if apiKey == "" {
				apiKey = strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			}
			merchant, ok := db.GetMerchantByKey(apiKey)
			if !ok {
				http.Error(w, "invalid API key", http.StatusUnauthorized)
				return
			}
			ctx := context.WithValue(r.Context(), merchantCtxKey, merchant)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func merchantFromCtx(r *http.Request) *models.Merchant {
	return r.Context().Value(merchantCtxKey).(*models.Merchant)
}

func adminAuthMiddleware(token string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			provided := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if provided != token {
				http.Error(w, "forbidden", http.StatusForbidden)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
