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

	"proof402/internal/bureau"
	"proof402/internal/firewall"
	"proof402/internal/invoice"
	"proof402/internal/loyalty"
	"proof402/internal/models"
	"proof402/internal/notify"
	"proof402/internal/passport"
	"proof402/internal/receipt"
	"proof402/internal/seed"
	"proof402/internal/store"
	"proof402/internal/xrpl"
)

type ctxKey string

const merchantCtxKey ctxKey = "merchant"

func main() {
	port := env("PORT", "9090")
	xrplRPC := env("XRPL_RPC_URL", "https://xrplcluster.com")
	gatewayAddr := env("GATEWAY_XRPL_ADDRESS", "")
	gatewayXahau := env("GATEWAY_XAHAU_ADDRESS", "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q")
	xahauRPC := env("XAHAU_RPC_URL", "https://xahau.network")
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

	agentStatePath := env("AGENT_STATE_PATH", "/tmp/proof402_agents.json")

	db := store.NewMemory()
	if err := db.LoadAgentsFromDisk(agentStatePath); err != nil {
		log.Printf("[STORE] Could not load agent state from %s: %v (starting fresh)", agentStatePath, err)
	}
	seed.Run(db, gatewayAddr)
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
		writeJSON(w, 200, map[string]interface{}{
			"status":  "ok",
			"networks": map[string]interface{}{
				"xrpl":  map[string]string{"gateway": gatewayAddr, "rpc": xrplRPC, "currency": "RLUSD", "issuer": rlusdIssuer},
				"xahau": map[string]string{"gateway": gatewayXahau, "rpc": xahauRPC, "currency": "RLUSD", "issuer": rlusdIssuer},
			},
		})
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
			"memo_note":  "Set this as MemoData in your XRPL or Xahau payment transaction",
			"payment_options": []map[string]string{
				{"network": "XRPL", "pay_to": gatewayAddr, "currency": "RLUSD", "issuer": rlusdIssuer, "rpc": xrplRPC},
				{"network": "Xahau", "pay_to": gatewayXahau, "currency": "RLUSD", "issuer": rlusdIssuer, "rpc": xahauRPC, "note": "XAH trust line required for RLUSD on Xahau"},
			},
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

		accessToken, err := invoice.IssueToken(inv, tokenSecret, body.AgentWallet)
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
		claims, err := invoice.VerifyToken(body.Token, tokenSecret)
		if err != nil {
			http.Error(w, "invalid token: "+err.Error(), http.StatusUnauthorized)
			return
		}
		if body.EndpointID != "" && claims.EndpointID != body.EndpointID {
			http.Error(w, "token not valid for this endpoint", http.StatusUnauthorized)
			return
		}
		writeJSON(w, 200, map[string]string{
			"status":      "VALID",
			"endpoint_id": claims.EndpointID,
			"wallet":      claims.WalletAddr,
		})
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

		accessToken, err := invoice.IssueToken(inv, tokenSecret, body.AgentWallet)
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

		// POST /v1/admin/agent/{wallet}/kyb — elevate KYB tier for a trusted agent.
		// Elevated KYB directly reduces risk score: basic -10, verified -20.
		// Use this to whitelist institutional partners and reduce their friction.
		a.Post("/agent/{wallet}/kyb", func(w http.ResponseWriter, req *http.Request) {
			wallet := chi.URLParam(req, "wallet")
			req.Body = http.MaxBytesReader(w, req.Body, 8*1024)
			var body struct {
				Tier   string `json:"tier"`   // "basic" or "verified"
				Reason string `json:"reason"` // optional audit note
			}
			if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
				http.Error(w, "invalid body", http.StatusBadRequest)
				return
			}
			if body.Tier != "basic" && body.Tier != "verified" && body.Tier != "none" {
				http.Error(w, "tier must be 'basic', 'verified', or 'none'", http.StatusBadRequest)
				return
			}
			agent := db.GetOrCreateAgent(wallet)
			oldTier := agent.KYBTier
			agent.KYBTier = body.Tier
			agent.RiskScore = passport.Score(agent)
			db.UpdateAgent(agent)
			log.Printf("[KYB] %s elevated: %s → %s | risk=%.0f | note=%s",
				wallet, oldTier, body.Tier, agent.RiskScore, body.Reason)
			writeJSON(w, 200, map[string]interface{}{
				"status":     "KYB_UPDATED",
				"wallet":     wallet,
				"kyb_tier":   agent.KYBTier,
				"risk_score": agent.RiskScore,
			})
		})

		// POST /v1/admin/flush — force-write agent state to disk now.
		a.Post("/flush", func(w http.ResponseWriter, req *http.Request) {
			if err := db.FlushAgentsToDisk(agentStatePath); err != nil {
				log.Printf("[STORE] manual flush failed: %v", err)
				http.Error(w, "flush failed: "+err.Error(), http.StatusInternalServerError)
				return
			}
			writeJSON(w, 200, map[string]string{"status": "FLUSHED", "path": agentStatePath})
		})

		a.Get("/stats", func(w http.ResponseWriter, req *http.Request) {
			writeJSON(w, 200, db.Stats())
		})

		// All agents with computed credit scores — dashboard agent table
		a.Get("/agents", func(w http.ResponseWriter, req *http.Request) {
			agents := db.ListAgents()
			rows := make([]map[string]interface{}, 0, len(agents))
			for _, agent := range agents {
				rep := bureau.Compute(agent)
				rows = append(rows, map[string]interface{}{
					"wallet":       agent.Wallet,
					"domain":       agent.Domain,
					"score":        rep.Score,
					"grade":        rep.Grade,
					"loyalty_tier": agent.LoyaltyTier,
					"kyb_tier":     agent.KYBTier,
					"total_spend":  agent.SpendFloat,
					"total_calls":  agent.TotalCalls,
					"first_seen":   agent.FirstSeen,
					"last_seen":    agent.LastSeen,
					"is_blocked":   agent.IsBlocked,
					"risk_score":   agent.RiskScore,
				})
			}
			writeJSON(w, 200, map[string]interface{}{"agents": rows, "count": len(rows)})
		})

		// Recent payments as JSON — dashboard feed
		a.Get("/feed", func(w http.ResponseWriter, req *http.Request) {
			receipts := db.ListRecentReceiptsJSON(50)
			rows := make([]map[string]interface{}, 0, len(receipts))
			for _, r := range receipts {
				rows = append(rows, map[string]interface{}{
					"id":           r.ID[:8],
					"wallet":       r.AgentWallet,
					"domain":       r.AgentDomain,
					"endpoint_id":  r.EndpointID[:8],
					"path":         r.Path,
					"amount":       r.Amount,
					"asset":        r.Asset,
					"tx_hash":      r.TxHash[:min8(len(r.TxHash))],
					"risk_level":   r.RiskLevel,
					"settled_at":   r.SettledAt,
				})
			}
			writeJSON(w, 200, map[string]interface{}{"receipts": rows, "count": len(rows)})
		})
	})

	// ── AGENT CREDIT BUREAU ───────────────────────────────────────────────────────
	// Free public score — no payment, teaser only
	r.Get("/v1/bureau/score/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		wallet := chi.URLParam(req, "wallet")
		agent, ok := db.GetAgent(wallet)
		if !ok {
			http.Error(w, "no credit history found for wallet", http.StatusNotFound)
			return
		}
		rep := bureau.Compute(agent)
		writeJSON(w, 200, bureau.PublicScore{
			Wallet:      rep.Wallet,
			Score:       rep.Score,
			Grade:       rep.Grade,
			LoyaltyTier: rep.LoyaltyTier,
			IsBlocked:   rep.IsBlocked,
			GeneratedAt: rep.GeneratedAt,
		})
	})

	// Full credit report — paid by querier (0.01 RLUSD)
	r.Get("/v1/bureau/report/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		token := req.Header.Get("X-Payment-Token")
		if token == "" {
			writeJSON(w, http.StatusPaymentRequired, map[string]interface{}{
				"error":       "payment required",
				"endpoint_id": seed.BureauReportID,
				"price":       "0.01",
				"asset":       "RLUSD",
				"description": "Full agent credit report with score breakdown",
				"pay_via":     serverURL + "/v1/invoice",
			})
			return
		}
		if _, err := invoice.VerifyTokenForEndpoint(token, tokenSecret, seed.BureauReportID); err != nil {
			http.Error(w, "invalid or expired payment token", http.StatusUnauthorized)
			return
		}
		wallet := chi.URLParam(req, "wallet")
		agent, ok := db.GetAgent(wallet)
		if !ok {
			writeJSON(w, 200, map[string]interface{}{
				"wallet":  wallet,
				"score":   300,
				"grade":   "D",
				"message": "no payment history — wallet is unscored",
			})
			return
		}
		writeJSON(w, 200, bureau.Compute(agent))
	})

	// Boolean threshold check — paid by querier (0.005 RLUSD)
	// ?min_score=600  (default 600 if omitted; range 300–850)
	r.Get("/v1/bureau/verify/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		token := req.Header.Get("X-Payment-Token")
		if token == "" {
			writeJSON(w, http.StatusPaymentRequired, map[string]interface{}{
				"error":       "payment required",
				"endpoint_id": seed.BureauVerifyID,
				"price":       "0.005",
				"asset":       "RLUSD",
				"description": "Boolean creditworthiness check — does wallet meet minimum score threshold?",
				"pay_via":     serverURL + "/v1/invoice",
			})
			return
		}
		if _, err := invoice.VerifyTokenForEndpoint(token, tokenSecret, seed.BureauVerifyID); err != nil {
			http.Error(w, "invalid or expired payment token", http.StatusUnauthorized)
			return
		}
		wallet := chi.URLParam(req, "wallet")
		minScore := 600
		if s := req.URL.Query().Get("min_score"); s != "" {
			if n, err := strconv.Atoi(s); err == nil && n >= 300 && n <= 850 {
				minScore = n
			}
		}
		score, grade := 300, "D"
		if agent, ok := db.GetAgent(wallet); ok {
			rep := bureau.Compute(agent)
			score, grade = rep.Score, rep.Grade
		}
		writeJSON(w, 200, map[string]interface{}{
			"wallet":     wallet,
			"score":      score,
			"grade":      grade,
			"threshold":  minScore,
			"passes":     score >= minScore,
			"checked_at": time.Now(),
		})
	})

	// Signed portable attestation JWT — paid by subject agent (0.01 RLUSD)
	r.Get("/v1/bureau/attest/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		token := req.Header.Get("X-Payment-Token")
		if token == "" {
			writeJSON(w, http.StatusPaymentRequired, map[string]interface{}{
				"error":       "payment required",
				"endpoint_id": seed.BureauAttestID,
				"price":       "0.01",
				"asset":       "RLUSD",
				"description": "Signed portable credit attestation JWT (24h TTL)",
				"pay_via":     serverURL + "/v1/invoice",
			})
			return
		}
		if _, err := invoice.VerifyTokenForEndpoint(token, tokenSecret, seed.BureauAttestID); err != nil {
			http.Error(w, "invalid or expired payment token", http.StatusUnauthorized)
			return
		}
		wallet := chi.URLParam(req, "wallet")
		score, grade, tier, kyb, blocked := 300, "D", "Bronze", "none", false
		if agent, ok := db.GetAgent(wallet); ok {
			rep := bureau.Compute(agent)
			score, grade, tier, kyb, blocked = rep.Score, rep.Grade, rep.LoyaltyTier, rep.KYBTier, rep.IsBlocked
		}
		attestToken, err := bureau.IssueAttestation(wallet, score, grade, tier, kyb, blocked, tokenSecret)
		if err != nil {
			http.Error(w, "attestation issuance failed", http.StatusInternalServerError)
			return
		}
		writeJSON(w, 200, map[string]interface{}{
			"wallet":     wallet,
			"score":      score,
			"grade":      grade,
			"attest_jwt": attestToken,
			"expires_in": "24h",
			"verify_at":  serverURL + "/v1/bureau/verify-attest",
			"issued_at":  time.Now(),
		})
	})

	// Free verification endpoint — third parties call this to validate attestation JWTs
	r.Post("/v1/bureau/verify-attest", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 8*1024)
		var body struct {
			Token string `json:"token"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Token == "" {
			http.Error(w, "token required", http.StatusBadRequest)
			return
		}
		claims, err := bureau.VerifyAttestation(body.Token, tokenSecret)
		if err != nil {
			http.Error(w, "invalid attestation: "+err.Error(), http.StatusUnauthorized)
			return
		}
		writeJSON(w, 200, map[string]interface{}{
			"valid":        true,
			"wallet":       claims.Wallet,
			"score":        claims.Score,
			"grade":        claims.Grade,
			"loyalty_tier": claims.LoyaltyTier,
			"kyb_tier":     claims.KYBTier,
			"is_blocked":   claims.IsBlocked,
			"issued_at":    time.Unix(claims.IssuedAt, 0),
			"expires_at":   time.Unix(claims.ExpiresAt, 0),
		})
	})

	// ── AGENT CREDIT BUREAU ───────────────────────────────────────────────────────
	// Free public score — no payment, teaser only
	r.Get("/v1/bureau/score/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		wallet := chi.URLParam(req, "wallet")
		agent, ok := db.GetAgent(wallet)
		if !ok {
			http.Error(w, "no credit history found for wallet", http.StatusNotFound)
			return
		}
		rep := bureau.Compute(agent)
		writeJSON(w, 200, bureau.PublicScore{
			Wallet:      rep.Wallet,
			Score:       rep.Score,
			Grade:       rep.Grade,
			LoyaltyTier: rep.LoyaltyTier,
			IsBlocked:   rep.IsBlocked,
			GeneratedAt: rep.GeneratedAt,
		})
	})

	// Full credit report — paid by querier (0.01 RLUSD)
	r.Get("/v1/bureau/report/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		token := req.Header.Get("X-Payment-Token")
		if token == "" {
			writeJSON(w, http.StatusPaymentRequired, map[string]interface{}{
				"error":       "payment required",
				"endpoint_id": seed.BureauReportID,
				"price":       "0.01",
				"asset":       "RLUSD",
				"description": "Full agent credit report with score breakdown",
				"pay_via":     serverURL + "/v1/invoice",
			})
			return
		}
		if _, err := invoice.VerifyTokenForEndpoint(token, tokenSecret, seed.BureauReportID); err != nil {
			http.Error(w, "invalid or expired payment token", http.StatusUnauthorized)
			return
		}
		wallet := chi.URLParam(req, "wallet")
		agent, ok := db.GetAgent(wallet)
		if !ok {
			writeJSON(w, 200, map[string]interface{}{
				"wallet":  wallet,
				"score":   300,
				"grade":   "D",
				"message": "no payment history — wallet is unscored",
			})
			return
		}
		writeJSON(w, 200, bureau.Compute(agent))
	})

	// Boolean threshold check — paid by querier (0.005 RLUSD)
	// ?min_score=600  (default 600 if omitted; range 300–850)
	r.Get("/v1/bureau/verify/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		token := req.Header.Get("X-Payment-Token")
		if token == "" {
			writeJSON(w, http.StatusPaymentRequired, map[string]interface{}{
				"error":       "payment required",
				"endpoint_id": seed.BureauVerifyID,
				"price":       "0.005",
				"asset":       "RLUSD",
				"description": "Boolean creditworthiness check — does wallet meet minimum score threshold?",
				"pay_via":     serverURL + "/v1/invoice",
			})
			return
		}
		if _, err := invoice.VerifyTokenForEndpoint(token, tokenSecret, seed.BureauVerifyID); err != nil {
			http.Error(w, "invalid or expired payment token", http.StatusUnauthorized)
			return
		}
		wallet := chi.URLParam(req, "wallet")
		minScore := 600
		if s := req.URL.Query().Get("min_score"); s != "" {
			if n, err := strconv.Atoi(s); err == nil && n >= 300 && n <= 850 {
				minScore = n
			}
		}
		score, grade := 300, "D"
		if agent, ok := db.GetAgent(wallet); ok {
			rep := bureau.Compute(agent)
			score, grade = rep.Score, rep.Grade
		}
		writeJSON(w, 200, map[string]interface{}{
			"wallet":     wallet,
			"score":      score,
			"grade":      grade,
			"threshold":  minScore,
			"passes":     score >= minScore,
			"checked_at": time.Now(),
		})
	})

	// Signed portable attestation JWT — paid by subject agent (0.01 RLUSD)
	r.Get("/v1/bureau/attest/{wallet}", func(w http.ResponseWriter, req *http.Request) {
		token := req.Header.Get("X-Payment-Token")
		if token == "" {
			writeJSON(w, http.StatusPaymentRequired, map[string]interface{}{
				"error":       "payment required",
				"endpoint_id": seed.BureauAttestID,
				"price":       "0.01",
				"asset":       "RLUSD",
				"description": "Signed portable credit attestation JWT (24h TTL)",
				"pay_via":     serverURL + "/v1/invoice",
			})
			return
		}
		if _, err := invoice.VerifyTokenForEndpoint(token, tokenSecret, seed.BureauAttestID); err != nil {
			http.Error(w, "invalid or expired payment token", http.StatusUnauthorized)
			return
		}
		wallet := chi.URLParam(req, "wallet")
		score, grade, tier, kyb, blocked := 300, "D", "Bronze", "none", false
		if agent, ok := db.GetAgent(wallet); ok {
			rep := bureau.Compute(agent)
			score, grade, tier, kyb, blocked = rep.Score, rep.Grade, rep.LoyaltyTier, rep.KYBTier, rep.IsBlocked
		}
		attestToken, err := bureau.IssueAttestation(wallet, score, grade, tier, kyb, blocked, tokenSecret)
		if err != nil {
			http.Error(w, "attestation issuance failed", http.StatusInternalServerError)
			return
		}
		writeJSON(w, 200, map[string]interface{}{
			"wallet":     wallet,
			"score":      score,
			"grade":      grade,
			"attest_jwt": attestToken,
			"expires_in": "24h",
			"verify_at":  serverURL + "/v1/bureau/verify-attest",
			"issued_at":  time.Now(),
		})
	})

	// Free verification endpoint — third parties call this to validate attestation JWTs
	r.Post("/v1/bureau/verify-attest", func(w http.ResponseWriter, req *http.Request) {
		req.Body = http.MaxBytesReader(w, req.Body, 8*1024)
		var body struct {
			Token string `json:"token"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Token == "" {
			http.Error(w, "token required", http.StatusBadRequest)
			return
		}
		claims, err := bureau.VerifyAttestation(body.Token, tokenSecret)
		if err != nil {
			http.Error(w, "invalid attestation: "+err.Error(), http.StatusUnauthorized)
			return
		}
		writeJSON(w, 200, map[string]interface{}{
			"valid":        true,
			"wallet":       claims.Wallet,
			"score":        claims.Score,
			"grade":        claims.Grade,
			"loyalty_tier": claims.LoyaltyTier,
			"kyb_tier":     claims.KYBTier,
			"is_blocked":   claims.IsBlocked,
			"issued_at":    time.Unix(claims.IssuedAt, 0),
			"expires_at":   time.Unix(claims.ExpiresAt, 0),
		})
	})

	// ── MCP JSON-RPC 2.0 (Smithery / MCP client compatibility) ─────────────
	{
		type mcpTool struct {
			Name        string      `json:"name"`
			Description string      `json:"description"`
			InputSchema interface{} `json:"inputSchema"`
		}
		p4Tools := []mcpTool{
			{Name: "platform_stats", Description: "Live 402Proof platform stats: total payments, volume, active agents. Free.", InputSchema: map[string]interface{}{"type": "object", "properties": map[string]interface{}{}}},
			{Name: "get_invoice", Description: "Request a payment invoice for any SqueezeOS endpoint. Returns XRPL destination address, RLUSD amount, and memo_hex. Pay on XRPL then call verify_payment. Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"endpoint_id"}, "properties": map[string]interface{}{"endpoint_id": map[string]string{"type": "string", "description": "UUID of endpoint to pay for"}}}},
			{Name: "verify_payment", Description: "Submit XRPL tx_hash after paying an invoice. Returns a signed JWT access_token (1-hour TTL). Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"invoice_id", "tx_hash", "agent_wallet"}, "properties": map[string]interface{}{"invoice_id": map[string]string{"type": "string"}, "tx_hash": map[string]string{"type": "string", "description": "64-char hex XRPL tx hash"}, "agent_wallet": map[string]string{"type": "string"}, "agent_domain": map[string]string{"type": "string"}}}},
			{Name: "check_loyalty", Description: "Loyalty tier and free-call balance for any XRPL wallet. Automatic — no registration. Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"wallet"}, "properties": map[string]interface{}{"wallet": map[string]string{"type": "string"}}}},
			{Name: "get_compliance_receipt", Description: "Retrieve a tamper-evident compliance receipt by UUID. Contains XRPL tx hash, agent wallet, endpoint, amount, and timestamp. Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"receipt_id"}, "properties": map[string]interface{}{"receipt_id": map[string]string{"type": "string"}}}},
			{Name: "get_agent_passport", Description: "Full Agent Passport for any XRPL wallet: payment history, risk score 0-100, loyalty tier, passport hash. Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"wallet"}, "properties": map[string]interface{}{"wallet": map[string]string{"type": "string"}}}},
			{Name: "bureau_public_score", Description: "FICO-style 300-850 Agent Credit Bureau score for any XRPL wallet. Includes grade and loyalty tier. Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"wallet"}, "properties": map[string]interface{}{"wallet": map[string]string{"type": "string"}}}},
			{Name: "bureau_full_report", Description: "Full credit bureau report: score breakdown, spend history, risk factors. Cost: 0.01 RLUSD.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"wallet"}, "properties": map[string]interface{}{"wallet": map[string]string{"type": "string"}, "payment_token": map[string]string{"type": "string"}}}},
			{Name: "bureau_verify_threshold", Description: "Boolean creditworthiness check — is this wallet above a score threshold? Cost: 0.005 RLUSD.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"wallet"}, "properties": map[string]interface{}{"wallet": map[string]string{"type": "string"}, "payment_token": map[string]string{"type": "string"}}}},
			{Name: "bureau_get_attestation", Description: "Portable attestation JWT (24h TTL) proving creditworthiness. Cost: 0.01 RLUSD.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"wallet"}, "properties": map[string]interface{}{"wallet": map[string]string{"type": "string"}, "payment_token": map[string]string{"type": "string"}}}},
			{Name: "bureau_verify_attestation", Description: "Verify a bureau attestation JWT. Free.", InputSchema: map[string]interface{}{"type": "object", "required": []string{"token"}, "properties": map[string]interface{}{"token": map[string]string{"type": "string"}}}},
		}
		p4Self := &http.Client{Timeout: 20 * time.Second}

		r.Get("/mcp", func(w http.ResponseWriter, req *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{
				"server":      map[string]string{"name": "402proof", "version": "1.0.0", "description": "x402 payment compliance firewall + Agent Credit Bureau. RLUSD on XRPL."},
				"protocol":    "MCP JSON-RPC 2.0",
				"tools_count": len(p4Tools),
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
			proxy := func(method, path string, bodyBytes []byte, headers map[string]string) interface{} {
				var pr *http.Request
				if bodyBytes != nil {
					pr, _ = http.NewRequestWithContext(req.Context(), method, serverURL+path, strings.NewReader(string(bodyBytes)))
				} else {
					pr, _ = http.NewRequestWithContext(req.Context(), method, serverURL+path, nil)
				}
				pr.Header.Set("Content-Type", "application/json")
				for k, v := range headers {
					pr.Header.Set(k, v)
				}
				resp, err := p4Self.Do(pr)
				if err != nil {
					return map[string]string{"error": err.Error()}
				}
				defer resp.Body.Close()
				var out interface{}
				json.NewDecoder(resp.Body).Decode(&out)
				return out
			}

			switch body.Method {
			case "initialize":
				ok(map[string]interface{}{
					"protocolVersion": "2024-11-05",
					"serverInfo":      map[string]string{"name": "402proof", "version": "1.0.0"},
					"capabilities":    map[string]interface{}{"tools": map[string]interface{}{}},
				})
			case "ping":
				ok(map[string]interface{}{})
			case "tools/list":
				ok(map[string]interface{}{"tools": p4Tools, "nextCursor": nil})
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
				args := p.Arguments
				tok, _ := args["payment_token"].(string)
				wallet, _ := args["wallet"].(string)
				hdrs := map[string]string{}
				if tok != "" {
					hdrs["X-Payment-Token"] = tok
				}
				switch p.Name {
				case "platform_stats":
					ok(text(proxy("GET", "/v1/stats", nil, hdrs)))
				case "get_invoice":
					b, _ := json.Marshal(args)
					ok(text(proxy("POST", "/v1/invoice", b, hdrs)))
				case "verify_payment":
					b, _ := json.Marshal(args)
					ok(text(proxy("POST", "/v1/verify", b, hdrs)))
				case "check_loyalty":
					ok(text(proxy("GET", "/v1/loyalty/"+wallet, nil, hdrs)))
				case "get_compliance_receipt":
					id, _ := args["receipt_id"].(string)
					ok(text(proxy("GET", "/v1/receipt/"+id, nil, hdrs)))
				case "get_agent_passport":
					ok(text(proxy("GET", "/v1/agent/"+wallet, nil, hdrs)))
				case "bureau_public_score":
					ok(text(proxy("GET", "/v1/bureau/score/"+wallet, nil, hdrs)))
				case "bureau_full_report":
					ok(text(proxy("GET", "/v1/bureau/report/"+wallet, nil, hdrs)))
				case "bureau_verify_threshold":
					ok(text(proxy("GET", "/v1/bureau/verify/"+wallet, nil, hdrs)))
				case "bureau_get_attestation":
					ok(text(proxy("GET", "/v1/bureau/attest/"+wallet, nil, hdrs)))
				case "bureau_verify_attestation":
					b, _ := json.Marshal(args)
					ok(text(proxy("POST", "/v1/bureau/verify-attest", b, hdrs)))
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

	// Periodic agent state flush — every 2 minutes during operation.
	// Ensures loyalty and passport data survive process crashes.
	go func() {
		t := time.NewTicker(2 * time.Minute)
		defer t.Stop()
		for range t.C {
			if err := db.FlushAgentsToDisk(agentStatePath); err != nil {
				log.Printf("[STORE] periodic flush failed: %v", err)
			}
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("[402Proof] Shutting down — flushing agent state...")
	if err := db.FlushAgentsToDisk(agentStatePath); err != nil {
		log.Printf("[STORE] shutdown flush failed: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	srv.Shutdown(ctx)
	log.Println("[402Proof] Stopped.")
}

func min8(n int) int {
	if n < 8 {
		return n
	}
	return 8
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
