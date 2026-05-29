package router

import (
	"sync"
	"testing"
)

// TestNewEngineAcceptsWaitGroup verifies the constructor stores the WaitGroup reference.
// Fails until Task 4 adds the sweepWg parameter.
func TestNewEngineAcceptsWaitGroup(t *testing.T) {
	var wg sync.WaitGroup
	e := NewTransparentBridgeEngine("rTreasury", "0xTreasury", nil, nil, &wg)
	if e == nil {
		t.Fatal("expected non-nil engine")
	}
	if e.sweepWg != &wg {
		t.Fatal("sweepWg field not set on engine")
	}
}

// TestRouteXRPLNilClient verifies routeXRPL short-circuits safely when xrpl is nil.
func TestRouteXRPLNilClient(t *testing.T) {
	var wg sync.WaitGroup
	e := NewTransparentBridgeEngine("rTreasury", "0xTreasury", nil, nil, &wg)
	_, err := e.routeXRPL("rDest", nil, nil)
	if err == nil {
		t.Fatal("expected error for nil xrpl client, got nil")
	}
	const want = "XRPL client not initialised"
	if len(err.Error()) < len(want) || err.Error()[:len(want)] != want {
		t.Errorf("error prefix: want %q, got %q", want, err.Error())
	}
}
