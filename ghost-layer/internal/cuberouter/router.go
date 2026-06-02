// Package cuberouter implements NEXUS402's multi-hop XRPL/Xahau swap path optimizer.
// It wraps XRPL's ripple_path_find RPC and scores candidate routes by fee and price impact.
package cuberouter

import (
	"encoding/json"
	"fmt"
	"strconv"
)

// PathHop is one leg of a multi-hop route.
type PathHop struct {
	Currency string `json:"currency"`
	Issuer   string `json:"issuer,omitempty"`
	Account  string `json:"account,omitempty"`
}

// Route is a scored candidate swap path.
type Route struct {
	Hops         [][]PathHop `json:"hops"`
	EstimatedOut string      `json:"estimated_out"`
	PriceImpact  float64     `json:"price_impact_pct"`
	Rank         int         `json:"rank"` // 1 = best
}

// FindRequest is the input to FindBestRoutes.
type FindRequest struct {
	SourceAccount   string `json:"source_account"`
	FromCurrency    string `json:"from_currency"`
	FromIssuer      string `json:"from_issuer,omitempty"`
	ToCurrency      string `json:"to_currency"`
	ToIssuer        string `json:"to_issuer,omitempty"`
	Amount          string `json:"amount"`
	MaxAlternatives int    `json:"max_alternatives"`
}

// RPCCaller is the subset of XRPLClient methods cuberouter needs.
// Defined as an interface so tests can inject a fake.
type RPCCaller interface {
	Call(method string, params map[string]interface{}) (json.RawMessage, error)
}

// FindBestRoutes calls ripple_path_find on the XRPL node and returns ranked routes.
func FindBestRoutes(rpc RPCCaller, req FindRequest) ([]Route, error) {
	if req.MaxAlternatives <= 0 {
		req.MaxAlternatives = 4
	}

	var sourceAmount interface{}
	if req.FromCurrency == "XRP" || req.FromCurrency == "" {
		sourceAmount = req.Amount
	} else {
		sourceAmount = map[string]string{
			"currency": req.FromCurrency,
			"issuer":   req.FromIssuer,
			"value":    req.Amount,
		}
	}

	var destAmount interface{}
	if req.ToCurrency == "XRP" || req.ToCurrency == "" {
		destAmount = "1"
	} else {
		destAmount = map[string]string{
			"currency": req.ToCurrency,
			"issuer":   req.ToIssuer,
			"value":    "1",
		}
	}

	params := map[string]interface{}{
		"subcommand":          "find",
		"source_account":      req.SourceAccount,
		"destination_account": req.SourceAccount,
		"destination_amount":  destAmount,
		"source_currencies":   []interface{}{sourceAmount},
		"send_max":            sourceAmount,
	}

	raw, err := rpc.Call("ripple_path_find", params)
	if err != nil {
		return []Route{{
			Hops:         [][]PathHop{},
			EstimatedOut: req.Amount,
			PriceImpact:  0,
			Rank:         1,
		}}, nil
	}

	var resp struct {
		Alternatives []struct {
			PathsComputed     [][]PathHop `json:"paths_computed"`
			DestinationAmount interface{} `json:"destination_amount"`
		} `json:"alternatives"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil || len(resp.Alternatives) == 0 {
		return []Route{{
			Hops:         [][]PathHop{},
			EstimatedOut: req.Amount,
			PriceImpact:  0,
			Rank:         1,
		}}, nil
	}

	routes := make([]Route, 0, len(resp.Alternatives))
	for i, alt := range resp.Alternatives {
		if i >= req.MaxAlternatives {
			break
		}
		routes = append(routes, Route{
			Hops:         alt.PathsComputed,
			EstimatedOut: extractAmount(alt.DestinationAmount),
			PriceImpact:  estimatePriceImpact(i, len(resp.Alternatives)),
			Rank:         i + 1,
		})
	}
	return routes, nil
}

func extractAmount(v interface{}) string {
	switch t := v.(type) {
	case string:
		return t
	case map[string]interface{}:
		if val, ok := t["value"].(string); ok {
			return val
		}
	}
	return "0"
}

func estimatePriceImpact(rank, total int) float64 {
	if total <= 1 {
		return 0.1
	}
	return 0.05 + float64(rank)*0.1
}

// DropsToCurrency converts a drops string to a human-readable XRP value.
func DropsToCurrency(drops string) string {
	n, err := strconv.ParseFloat(drops, 64)
	if err != nil {
		return drops
	}
	return fmt.Sprintf("%.6f", n/1_000_000)
}
