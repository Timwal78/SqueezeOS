package x402

import (
	"encoding/json"
	"testing"
)

func TestPriceTiers(t *testing.T) {
	cases := []struct {
		tier string
		base int64
		want int64
	}{
		{"BRONZE", 50000, 50000},
		{"SILVER", 50000, 47500},
		{"GOLD", 50000, 45000},
		{"PLATINUM", 50000, 40000},
		{"DIAMOND", 50000, 35000},
		{"UNKNOWN", 50000, 50000},
		{"DIAMOND", 1, 1}, // floor
	}
	for _, c := range cases {
		got := Price(c.base, c.tier)
		if got != c.want {
			t.Errorf("Price(%d, %s) = %d, want %d", c.base, c.tier, got, c.want)
		}
	}
}

func TestRegistryLookup(t *testing.T) {
	r := NewRegistry()
	r.Register(&Product{ID: "live", Dispatcher: func(args map[string]any) (json.RawMessage, error) { return []byte(`{"ok":true}`), nil }})
	r.Register(&Product{ID: "dead", Disabled: true})

	if _, err := r.Lookup("live"); err != nil {
		t.Errorf("live lookup failed: %v", err)
	}
	if _, err := r.Lookup("dead"); err != ErrDisabledProduct {
		t.Errorf("disabled lookup: want ErrDisabledProduct, got %v", err)
	}
	if _, err := r.Lookup("ghost"); err != ErrUnknownProduct {
		t.Errorf("unknown lookup: want ErrUnknownProduct, got %v", err)
	}
}
