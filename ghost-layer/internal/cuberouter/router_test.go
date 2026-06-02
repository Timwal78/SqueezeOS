package cuberouter

import (
	"encoding/json"
	"testing"
)

type fakeRPC struct {
	response json.RawMessage
	err      error
}

func (f *fakeRPC) Call(_ string, _ map[string]interface{}) (json.RawMessage, error) {
	return f.response, f.err
}

func TestFindBestRoutes_DirectXRP(t *testing.T) {
	rpc := &fakeRPC{response: json.RawMessage(`{"alternatives":[]}`)}
	routes, err := FindBestRoutes(rpc, FindRequest{
		SourceAccount: "rTestAccount",
		FromCurrency:  "XRP",
		ToCurrency:    "XRP",
		Amount:        "1000000",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(routes) != 1 {
		t.Fatalf("expected 1 fallback route, got %d", len(routes))
	}
	if routes[0].Rank != 1 {
		t.Errorf("expected rank 1, got %d", routes[0].Rank)
	}
}

func TestFindBestRoutes_MultiHop(t *testing.T) {
	resp := `{
		"alternatives": [
			{
				"paths_computed": [[{"currency":"USD","issuer":"rIssuer1"}]],
				"destination_amount": "980000"
			},
			{
				"paths_computed": [[{"currency":"EUR","issuer":"rIssuer2"},{"currency":"USD","issuer":"rIssuer1"}]],
				"destination_amount": "970000"
			}
		]
	}`
	rpc := &fakeRPC{response: json.RawMessage(resp)}
	routes, err := FindBestRoutes(rpc, FindRequest{
		SourceAccount:   "rTestAccount",
		FromCurrency:    "XRP",
		ToCurrency:      "USD",
		ToIssuer:        "rIssuer1",
		Amount:          "1000000",
		MaxAlternatives: 4,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(routes) != 2 {
		t.Fatalf("expected 2 routes, got %d", len(routes))
	}
	if routes[0].Rank != 1 || routes[1].Rank != 2 {
		t.Errorf("ranks wrong: %d %d", routes[0].Rank, routes[1].Rank)
	}
	if routes[0].EstimatedOut != "980000" {
		t.Errorf("expected 980000, got %s", routes[0].EstimatedOut)
	}
	if routes[1].PriceImpact <= routes[0].PriceImpact {
		t.Error("expected rank-2 to have higher price impact than rank-1")
	}
}

func TestDropsToCurrency(t *testing.T) {
	cases := []struct{ in, want string }{
		{"1000000", "1.000000"},
		{"500000", "0.500000"},
		{"bad", "bad"},
	}
	for _, c := range cases {
		got := DropsToCurrency(c.in)
		if got != c.want {
			t.Errorf("DropsToCurrency(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}
