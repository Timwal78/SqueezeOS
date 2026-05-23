package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config is loaded from environment variables (Render-friendly).
type Config struct {
	// BaseWSURL is the JSON-RPC websocket endpoint for the Base mainnet
	// RPC provider. Must support `eth_subscribe newPendingTransactions`
	// with the provider-extended full-object variant (Alchemy, Blocknative,
	// or QuickNode). Hash-only feeds are accepted but logged as a warning
	// because the required per-tx eth_getTransactionByHash roundtrip
	// destroys the read-side latency budget.
	BaseWSURL string

	// WatchedContracts is the lowercased, 0x-prefixed list of ERC-20
	// token contracts to monitor (e.g. USDC, RLUSD).
	WatchedContracts []string

	// ContractDecimals maps a watched contract to its token decimals.
	// Defaults to 18 if a contract is not present.
	ContractDecimals map[string]uint8

	// WatchedCounterparties, if non-empty, restricts emission to transfers
	// where either the sender or recipient matches one of these addresses
	// (lowercased, 0x-prefixed). Use for bridges, exchange hot wallets,
	// large collateral vaults.
	WatchedCounterparties []string

	// MinTransferValue is the scaled token amount below which transfers
	// are dropped (e.g. 1_000_000 = $1M USDC).
	MinTransferValue float64

	// CoinbaseWSURL is the Advanced Trade public market data endpoint.
	CoinbaseWSURL string

	// CEXProducts is the list of CEX symbols to subscribe to
	// (e.g. XRP-USD, SOL-USD).
	CEXProducts []string

	// EventLogPath is the NDJSON sink for offline correlation analysis.
	EventLogPath string

	// HUDWebhookURL receives a POST per Base-mempool hit, formatted for
	// the Pine Script HUD's external data ingestion. Empty disables.
	HUDWebhookURL string
}

func FromEnv() (*Config, error) {
	c := &Config{
		BaseWSURL:             os.Getenv("BASE_WS_URL"),
		WatchedContracts:      splitCSV(os.Getenv("WATCHED_CONTRACTS")),
		WatchedCounterparties: splitCSV(os.Getenv("WATCHED_COUNTERPARTIES")),
		CoinbaseWSURL:         envDefault("COINBASE_WS_URL", "wss://advanced-trade-ws.coinbase.com"),
		CEXProducts:           splitCSV(envDefault("CEX_PRODUCTS", "XRP-USD,SOL-USD")),
		EventLogPath:          envDefault("EVENT_LOG_PATH", "./events.ndjson"),
		HUDWebhookURL:         os.Getenv("HUD_WEBHOOK_URL"),
	}

	minStr := envDefault("MIN_TRANSFER_VALUE", "1000000")
	v, err := strconv.ParseFloat(minStr, 64)
	if err != nil {
		return nil, fmt.Errorf("MIN_TRANSFER_VALUE: %w", err)
	}
	c.MinTransferValue = v

	if c.BaseWSURL == "" {
		return nil, errors.New("BASE_WS_URL is required")
	}
	if len(c.WatchedContracts) == 0 {
		return nil, errors.New("WATCHED_CONTRACTS is required (comma-separated 0x addresses)")
	}

	c.WatchedContracts = normalizeAddrs(c.WatchedContracts)
	c.WatchedCounterparties = normalizeAddrs(c.WatchedCounterparties)

	c.ContractDecimals = parseDecimals(os.Getenv("CONTRACT_DECIMALS"))
	// USDC on Base mainnet defaults to 6 decimals if caller did not override.
	if _, ok := c.ContractDecimals["0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"]; !ok {
		c.ContractDecimals["0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"] = 6
	}

	return c, nil
}

// parseDecimals reads a CSV of `address:decimals` pairs:
//   0xabc...:6,0xdef...:18
func parseDecimals(s string) map[string]uint8 {
	out := map[string]uint8{}
	if s == "" {
		return out
	}
	for _, pair := range strings.Split(s, ",") {
		pair = strings.TrimSpace(pair)
		colon := strings.Index(pair, ":")
		if colon <= 0 || colon == len(pair)-1 {
			continue
		}
		addr := strings.ToLower(strings.TrimSpace(pair[:colon]))
		d, err := strconv.ParseUint(strings.TrimSpace(pair[colon+1:]), 10, 8)
		if err != nil {
			continue
		}
		out[addr] = uint8(d)
	}
	return out
}

func envDefault(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func splitCSV(s string) []string {
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := parts[:0]
	for _, p := range parts {
		if t := strings.TrimSpace(p); t != "" {
			out = append(out, t)
		}
	}
	return out
}

func normalizeAddrs(in []string) []string {
	out := make([]string, len(in))
	for i, a := range in {
		out[i] = strings.ToLower(strings.TrimSpace(a))
	}
	return out
}
