// Package seed pre-populates the store on startup so registered merchants
// and endpoints survive Render redeploys (in-memory store resets on restart).
package seed

import (
	"log"
	"os"
	"time"

	"proof402/internal/models"
	"proof402/internal/store"
)

// Fixed stable IDs — never change these after first deploy
const (
	MerchantID    = "3a5db2f8-6812-4c3f-aa24-de6e3bc12b5a"
	DefaultAPIKey = "sml-402proof-api-key-scriptmasterlabs-2026"

	// Agent Credit Bureau endpoint IDs
	BureauReportID = "b1c2d3e4-0001-4c3f-aa24-de6e3bc12b5a"
	BureauVerifyID = "b1c2d3e4-0002-4c3f-aa24-de6e3bc12b5a"
	BureauAttestID = "b1c2d3e4-0003-4c3f-aa24-de6e3bc12b5a"

	// Signal Relay Mesh — bulk discount endpoint IDs (40% off standard)
	RelayCouncilID = "b2r1e1a4-c001-4c3f-aa24-de6e3bc12b5a"
	RelayScanID    = "b2r1e1a4-c002-4c3f-aa24-de6e3bc12b5a"
	RelayOptionsID = "b2r1e1a4-c003-4c3f-aa24-de6e3bc12b5a"
	RelayIwmID     = "b2r1e1a4-c004-4c3f-aa24-de6e3bc12b5a"
)

type EndpointSeed struct {
	ID          string
	Path        string
	Price       string
	Asset       string
	Description string
}

var RelayEndpoints = []EndpointSeed{
	{
		ID:          RelayCouncilID,
		Path:        "/api/council",
		Price:       "0.06",
		Asset:       "RLUSD",
		Description: "AI Council Verdict — relay bulk rate (40% off, registered relay nodes only)",
	},
	{
		ID:          RelayScanID,
		Path:        "/api/scan",
		Price:       "0.03",
		Asset:       "RLUSD",
		Description: "Market Scan — relay bulk rate (40% off)",
	},
	{
		ID:          RelayOptionsID,
		Path:        "/api/options",
		Price:       "0.03",
		Asset:       "RLUSD",
		Description: "Options Intelligence — relay bulk rate (40% off)",
	},
	{
		ID:          RelayIwmID,
		Path:        "/api/iwm",
		Price:       "0.018",
		Asset:       "RLUSD",
		Description: "IWM 0DTE — relay bulk rate (40% off)",
	},
}

var BureauEndpoints = []EndpointSeed{
	{
		ID:          BureauReportID,
		Path:        "/v1/bureau/report",
		Price:       "0.01",
		Asset:       "RLUSD",
		Description: "Full agent credit report — score breakdown, spend history, risk level, account age",
	},
	{
		ID:          BureauVerifyID,
		Path:        "/v1/bureau/verify",
		Price:       "0.005",
		Asset:       "RLUSD",
		Description: "Boolean creditworthiness check — does wallet meet minimum score threshold?",
	},
	{
		ID:          BureauAttestID,
		Path:        "/v1/bureau/attest",
		Price:       "0.01",
		Asset:       "RLUSD",
		Description: "Signed portable attestation JWT — present to third-party services without them calling 402Proof",
	},
}

var SMLEndpoints = []EndpointSeed{
	{
		ID:          "12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a",
		Path:        "/api/council",
		Price:       "0.10",
		Asset:       "RLUSD",
		Description: "AI council verdict — multi-engine signal aggregate (SML + Battle Computer)",
	},
	{
		ID:          "160cf28d-b364-44eb-adbd-2489c5cc2cf8",
		Path:        "/api/scan",
		Price:       "0.05",
		Asset:       "RLUSD",
		Description: "Full $1-$50 market scanner — live squeeze signals and options picks",
	},
	{
		ID:          "c951a374-2424-4064-ab80-35afe8053d29",
		Path:        "/api/options",
		Price:       "0.05",
		Asset:       "RLUSD",
		Description: "Options intelligence — institutional sweeps, whale detection, unusual volume",
	},
	{
		ID:          "60f48ce0-6002-4385-9b60-03a0d2bbebab",
		Path:        "/api/iwm",
		Price:       "0.03",
		Asset:       "RLUSD",
		Description: "IWM 0DTE institutional scanner — scored contracts and parity watch",
	},
}

// Run seeds the Script Master Labs merchant and all 4 endpoints on every boot.
// Idempotent — skips anything already present.
func Run(db *store.Memory, gatewayAddr string) {
	merchantName  := env("SEED_MERCHANT_NAME",  "Script Master Labs")
	merchantEmail := env("SEED_MERCHANT_EMAIL", "admin@scriptmasterlabs.com")
	apiKey := env("SEED_MERCHANT_API_KEY", DefaultAPIKey)

	// Seed merchant with fixed stable ID
	if _, ok := db.GetMerchant(MerchantID); !ok {
		m := &models.Merchant{
			ID:        MerchantID,
			Name:      merchantName,
			Email:     merchantEmail,
			APIKey:    apiKey,
			Plan:      "free",
			CreatedAt: time.Now(),
		}
		db.SaveMerchant(m)
		log.Printf("[SEED] Merchant: %s id=%s", merchantName, MerchantID)
	}

	// Seed all endpoints: SML market + Bureau + Relay bulk
	all := append(append(SMLEndpoints, BureauEndpoints...), RelayEndpoints...)
	for _, e := range all {
		if _, ok := db.GetEndpoint(e.ID); !ok {
			ep := &models.Endpoint{
				ID:          e.ID,
				MerchantID:  MerchantID,
				Path:        e.Path,
				Price:       e.Price,
				Asset:       e.Asset,
				Description: e.Description,
				Active:      true,
				CreatedAt:   time.Now(),
			}
			db.SaveEndpoint(ep)
			log.Printf("[SEED] Endpoint: %s %s %s RLUSD", e.Path, e.ID[:8], e.Price)
		}
	}

	log.Printf("[SEED] Script Master Labs ready — 4 market + 3 bureau + 4 relay endpoints active")
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
