package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log"
	"math/big"
	"net/http"
	"os"
	"strings"

	"ghost-layer-core/internal/chain"
	"ghost-layer-core/internal/router"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

type eip3009Payload struct {
	ValidAfter  string `json:"valid_after"`
	ValidBefore string `json:"valid_before"`
	Nonce       string `json:"nonce"`
	V           uint8  `json:"v"`
	R           string `json:"r"`
	S           string `json:"s"`
}

type bridgePayload struct {
	SourceWallet      string          `json:"source_wallet"`
	DestinationWallet string          `json:"destination_wallet"`
	GrossAmount       string          `json:"gross_amount"`
	FeeBasisPoints    int64           `json:"fee_basis_points"`
	EIP3009           *eip3009Payload `json:"eip3009,omitempty"`
}

func main() {
	port := env("PORT", "8080")
	treasuryXRPL := env("TREASURY_ADDRESS", "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q")
	treasuryETH := env("TREASURY_ETH_ADDRESS", "")
	baseRPC := env("BASE_RPC_URL", "https://mainnet.base.org")
	xrplRPC := env("XRPL_RPC_URL", "https://xrplcluster.com")
	usdcAddr := env("USDC_CONTRACT_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

	var xrplClient *chain.XRPLClient
	if key := os.Getenv("GATEWAY_XRPL_PRIVATE_KEY"); key != "" {
		c, err := chain.NewXRPLClient(xrplRPC, key)
		if err != nil {
			log.Fatalf("[FATAL] XRPL client: %v", err)
		}
		xrplClient = c
		log.Printf("[SERVER] XRPL gateway: %s", c.GatewayAddress)
	} else {
		log.Println("[WARN] GATEWAY_XRPL_PRIVATE_KEY not set — XRPL routing disabled")
	}

	var baseClient *chain.BaseClient
	if key := os.Getenv("GATEWAY_ETH_PRIVATE_KEY"); key != "" {
		c, err := chain.NewBaseClient(baseRPC, key, usdcAddr)
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
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	r.Get("/health", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})

	r.Post("/v1/bridge/execute", func(w http.ResponseWriter, req *http.Request) {
		var p bridgePayload
		if err := json.NewDecoder(req.Body).Decode(&p); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}

		var auth *chain.EIP3009Auth
		if p.EIP3009 != nil {
			a, err := parseEIP3009(p.EIP3009)
			if err != nil {
				http.Error(w, "invalid eip3009: "+err.Error(), http.StatusBadRequest)
				return
			}
			auth = &a
		}

		txHash, fee, net, err := engine.RouteTransactionWithDisclosure(
			context.Background(),
			p.SourceWallet, p.DestinationWallet,
			p.GrossAmount, p.FeeBasisPoints,
			auth,
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
			"net_delivered":    net.String(),
			"treasury_routing": treasuryXRPL,
		})
	})

	log.Printf("[SERVER] Ghost Layer active on :%s | XRPL treasury: %s", port, treasuryXRPL)
	if err := http.ListenAndServe(":"+port, r); err != nil {
		log.Fatalf("server: %v", err)
	}
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
