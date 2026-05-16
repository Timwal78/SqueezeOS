package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"

	"ghost-layer-core/internal/router"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

type BridgePayload struct {
	SourceWallet      string `json:"source_wallet"`
	DestinationWallet string `json:"destination_wallet"`
	GrossAmount       string `json:"gross_amount"`
	FeeBasisPoints    int64  `json:"fee_basis_points"`
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	treasury := os.Getenv("TREASURY_ADDRESS")
	if treasury == "" {
		treasury = "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q"
	}
	rpcURL := os.Getenv("BASE_RPC_URL")
	if rpcURL == "" {
		rpcURL = "https://xrplcluster.com"
	}

	r := chi.NewRouter()
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	engine := router.NewTransparentBridgeEngine(treasury, rpcURL)

	r.Get("/health", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})

	r.Post("/v1/bridge/execute", func(w http.ResponseWriter, req *http.Request) {
		var p BridgePayload
		if err := json.NewDecoder(req.Body).Decode(&p); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}

		txHash, fee, netAmount, err := engine.RouteTransactionWithDisclosure(
			context.Background(),
			p.SourceWallet,
			p.DestinationWallet,
			p.GrossAmount,
			p.FeeBasisPoints,
		)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":           "SUCCESSFULLY_ROUTED",
			"transaction_hash": txHash,
			"gross_processed":  p.GrossAmount,
			"transparent_fee":  fee.String(),
			"net_delivered":    netAmount.String(),
			"treasury_routing": treasury,
		})
	})

	log.Printf("[SERVER] Transparent Routing Engine active on :%s | Treasury: %s", port, treasury)
	if err := http.ListenAndServe(":"+port, r); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
