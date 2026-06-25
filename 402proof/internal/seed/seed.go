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

	// Peer Signal Marketplace
	MarketplaceReadID = "d1a2b3c4-e001-4c3f-aa24-de6e3bc12b5a"

	// Cube Terminal — Ghost Layer dNFT mint
	CubeMintID = "c8b3e2f1-5a4d-4c3f-aa24-de6e3bc12b5a"

	// Real-World Data Oracle — regulatory event feeds (SqueezeOS)
	OracleReadID   = "e7f8a9b0-c001-4d2e-bb35-ef7f4cd23c6a"  // 0.02 RLUSD — latest + query
	OracleStreamID = "f8a9b0c1-d002-4e3f-cc46-f0845de34d7b"  // 0.05 RLUSD — SSE stream

	// 741 Pure Macro Matrix — 5-layer EMA structural alignment engine
	Macro741ID = "f3a7c891-2d54-4b8e-9a1f-6c3d8e5f7b2a"  // 0.04 RLUSD — dynamic ticker universe

	// TriageOS — Healthcare Prior Authorization Agent
	TriageAuthID = "c4a1e7b3-0001-4f5a-b900-de6e3bc12b5a"  // 0.08 RLUSD — prior auth package + on-chain audit commit

	// Sovereign Signal Suite — structural labels only, no raw indicator values
	Signal741ID        = "e5f6a7b8-c9d0-1234-5678-901234567890"  // 0.02 RLUSD — 741 macro alignment label
	Signal365ID        = "f6a7b8c9-d0e1-2345-6789-012345678901"  // 0.03 RLUSD — 365-day cycle bias label
	SignalTripleLockID = "a7b8c9d0-e1f2-3456-789a-123456789012"  // 0.05 RLUSD — triple-lock convergence label
	SignalFullID       = "b8c9d0e1-f2a3-4567-89ab-234567890123"  // 0.10 RLUSD — full sovereign suite label
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

var MarketplaceEndpoints = []EndpointSeed{
	{
		ID:          MarketplaceReadID,
		Path:        "/api/marketplace/read",
		Price:       "0.02",
		Asset:       "RLUSD",
		Description: "Peer signal full read — thesis, entry, target, stop from verified seller wallet",
	},
}

var GhostLayerEndpoints = []EndpointSeed{
	{
		ID:          CubeMintID,
		Path:        "/api/cube/state",
		Price:       "0.05",
		Asset:       "RLUSD",
		Description: "Cube Terminal dNFT mint — commit Rubik's Cube state as Xahau URIToken, permanent on-chain proof",
	},
}

var OracleEndpoints = []EndpointSeed{
	{
		ID:          OracleReadID,
		Path:        "/api/oracle/latest",
		Price:       "0.02",
		Asset:       "RLUSD",
		Description: "Real-World Data Oracle — latest events from SEC 8-K, SEC S-1 IPO, FDA drug approvals, USPTO patents. Sub-second vs Bloomberg's 5-10 min lag.",
	},
	{
		ID:          OracleStreamID,
		Path:        "/api/oracle/stream",
		Price:       "0.05",
		Asset:       "RLUSD",
		Description: "Real-World Data Oracle — real-time SSE stream of all regulatory events (SEC/FDA/USPTO). One-time payment per connection.",
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
	{
		ID:          Macro741ID,
		Path:        "/api/741macro",
		Price:       "0.04",
		Asset:       "RLUSD",
		Description: "741 Pure Macro Matrix — 5-layer EMA structural alignment (30/60/90/120/741). PERFECT_BULLISH/BEARISH_REGIME detection. Squeeze coil alert. Dynamic ticker universe.",
	},
}

var TriageEndpoints = []EndpointSeed{
	{
		ID:          TriageAuthID,
		Path:        "/api/auth",
		Price:       "0.08",
		Asset:       "RLUSD",
		Description: "TriageOS Prior Auth Agent — complete prior authorization package (medical necessity, ICD-10/CPT, payer strategy, appeal preemption, on-chain audit hash). No PHI stored.",
	},
}

var SovereignSignalEndpoints = []EndpointSeed{
	{
		ID:          Signal741ID,
		Path:        "/api/signals/741",
		Price:       "0.02",
		Asset:       "RLUSD",
		Description: "Sovereign Signal — 741 macro structural alignment label (BULLISH/BEARISH/NEUTRAL). No raw indicator values returned.",
	},
	{
		ID:          Signal365ID,
		Path:        "/api/signals/365",
		Price:       "0.03",
		Asset:       "RLUSD",
		Description: "Sovereign Signal — 365-day cycle bias label (EXPANSION/CONTRACTION/ACCUMULATION). No raw indicator values returned.",
	},
	{
		ID:          SignalTripleLockID,
		Path:        "/api/signals/triplelock",
		Price:       "0.05",
		Asset:       "RLUSD",
		Description: "Sovereign Signal — triple-lock convergence label (LOCKED_BULL/LOCKED_BEAR/NO_LOCK with lock count). No raw indicator values returned.",
	},
	{
		ID:          SignalFullID,
		Path:        "/api/signals/full",
		Price:       "0.10",
		Asset:       "RLUSD",
		Description: "Sovereign Signal Suite — all 4 structural labels in one call (741 macro + 365 cycle + triple-lock + composite bias). No raw indicator values returned.",
	},
}

// Run seeds the Script Master Labs merchant and all endpoints on every boot.
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

	// Seed all endpoints: SML market + Bureau + Relay bulk + Marketplace + Ghost Layer + Oracle + TriageOS + Sovereign Signals
	all := append(append(append(append(append(append(append(SMLEndpoints, BureauEndpoints...), RelayEndpoints...), MarketplaceEndpoints...), GhostLayerEndpoints...), OracleEndpoints...), TriageEndpoints...), SovereignSignalEndpoints...)
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

	log.Printf("[SEED] Script Master Labs ready — 5 market + 3 bureau + 4 relay + 1 marketplace + 1 ghost-layer + 2 oracle + 1 triageos + 4 sovereign-signals endpoints active")
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
