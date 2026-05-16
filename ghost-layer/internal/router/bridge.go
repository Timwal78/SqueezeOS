package router

import (
	"context"
	"errors"
	"fmt"
	"log"
	"math/big"
	"strings"

	"ghost-layer-core/internal/chain"
	"ghost-layer-core/internal/toll"
)

// TransparentBridgeEngine routes payments on XRPL or Base chain with full fee disclosure.
type TransparentBridgeEngine struct {
	TreasuryXRPL string
	TreasuryETH  string
	xrpl         *chain.XRPLClient
	base         *chain.BaseClient
}

func NewTransparentBridgeEngine(treasuryXRPL, treasuryETH string, xrpl *chain.XRPLClient, base *chain.BaseClient) *TransparentBridgeEngine {
	return &TransparentBridgeEngine{
		TreasuryXRPL: treasuryXRPL,
		TreasuryETH:  treasuryETH,
		xrpl:         xrpl,
		base:         base,
	}
}

// RouteTransactionWithDisclosure calculates the fee split, executes on-chain routing,
// then auto-sweeps accumulated gateway fees to cold-storage treasury.
func (e *TransparentBridgeEngine) RouteTransactionWithDisclosure(
	ctx context.Context,
	source, destination, amountStr string,
	bps int64,
	auth *chain.EIP3009Auth,
) (txHash string, fee *big.Int, net *big.Int, err error) {
	if source == "" || destination == "" {
		return "", nil, nil, errors.New("routing aborted: missing source or destination address")
	}

	fee, net, err = toll.CalculateBasisPointFee(amountStr, bps)
	if err != nil {
		return "", nil, nil, err
	}
	gross, _ := new(big.Int).SetString(amountStr, 10) // safe: toll already validated

	log.Printf("[AUDIT] Route %s → %s | gross=%s fee=%s net=%s bps=%d",
		source, destination, gross.String(), fee.String(), net.String(), bps)

	switch {
	case isXRPL(source) && isXRPL(destination):
		txHash, err = e.routeXRPL(destination, fee, net)
	case isEVM(source) && isEVM(destination):
		if auth == nil {
			return "", nil, nil, errors.New("EIP-3009 authorization required for Base chain routing")
		}
		txHash, err = e.routeBase(ctx, source, destination, gross, net, *auth)
	default:
		return "", nil, nil, errors.New("mismatched or unsupported address formats")
	}
	if err != nil {
		return "", nil, nil, err
	}

	log.Printf("[AUDIT] ✓ tx=%s | fee=%s → treasury | net=%s → %s", txHash, fee.String(), net.String(), destination)

	// Auto-sweep: drain accumulated fees to cold treasury after each execution.
	// Uses a detached context so it survives after the HTTP response is sent.
	go func() {
		if err := e.sweepBestEffort(source); err != nil {
			log.Printf("[SWEEP] error: %v", err)
		}
	}()

	return txHash, fee, net, nil
}

// RouteWithAutoSweep is a convenience wrapper that returns only the tx hash.
func (e *TransparentBridgeEngine) RouteWithAutoSweep(ctx context.Context, source, destination, amount string, bps int64, auth *chain.EIP3009Auth) (string, error) {
	txHash, _, _, err := e.RouteTransactionWithDisclosure(ctx, source, destination, amount, bps, auth)
	return txHash, err
}

// ForceManualSweep drains both gateway wallets immediately. Returns per-chain results.
func (e *TransparentBridgeEngine) ForceManualSweep(ctx context.Context) (map[string]string, error) {
	results := map[string]string{}

	if hash, err := e.sweepXRPL(); err != nil {
		results["xrpl_error"] = err.Error()
	} else if hash != "" {
		results["xrpl_tx"] = hash
		log.Printf("[FORCE SWEEP] XRPL → treasury: %s", hash)
	} else {
		results["xrpl"] = "nothing to sweep"
	}

	if hash, err := e.sweepBase(ctx); err != nil {
		results["base_error"] = err.Error()
	} else if hash != "" {
		results["base_tx"] = hash
		log.Printf("[FORCE SWEEP] Base USDC → treasury: %s", hash)
	} else {
		results["base"] = "nothing to sweep"
	}

	return results, nil
}

// Sweep manually triggers a single-chain fee sweep.
func (e *TransparentBridgeEngine) Sweep(ctx context.Context, chainType string) (string, error) {
	switch strings.ToLower(chainType) {
	case "xrpl":
		return e.sweepXRPL()
	case "evm", "base":
		return e.sweepBase(ctx)
	default:
		return "", fmt.Errorf("unknown chain type %q (use 'xrpl' or 'evm')", chainType)
	}
}

// ClientStatus returns which chain clients are live, for the health endpoint.
func (e *TransparentBridgeEngine) ClientStatus() map[string]bool {
	return map[string]bool{
		"xrpl": e.xrpl != nil,
		"base": e.base != nil,
	}
}

// ---- internal ----

func (e *TransparentBridgeEngine) sweepBestEffort(sourceAddr string) error {
	if isXRPL(sourceAddr) {
		hash, err := e.sweepXRPL()
		if err != nil {
			return err
		}
		if hash != "" {
			log.Printf("[SWEEP] XRPL swept to treasury: %s", hash)
		}
	} else if isEVM(sourceAddr) {
		hash, err := e.sweepBase(context.Background())
		if err != nil {
			return err
		}
		if hash != "" {
			log.Printf("[SWEEP] Base USDC swept to treasury: %s", hash)
		}
	}
	return nil
}

func (e *TransparentBridgeEngine) routeXRPL(destination string, fee, net *big.Int) (string, error) {
	if e.xrpl == nil {
		return "", errors.New("XRPL client not initialised — set GATEWAY_XRPL_PRIVATE_KEY")
	}
	if _, err := e.xrpl.SendPayment(e.TreasuryXRPL, fee.Uint64()); err != nil {
		return "", fmt.Errorf("XRPL fee payment: %w", err)
	}
	txHash, err := e.xrpl.SendPayment(destination, net.Uint64())
	if err != nil {
		return "", fmt.Errorf("XRPL principal payment: %w", err)
	}
	return txHash, nil
}

func (e *TransparentBridgeEngine) routeBase(ctx context.Context, source, destination string, gross, net *big.Int, auth chain.EIP3009Auth) (string, error) {
	if e.base == nil {
		return "", errors.New("Base client not initialised — set GATEWAY_ETH_PRIVATE_KEY")
	}
	return e.base.PullAndRoute(ctx, source, destination, gross, net, auth)
}

func (e *TransparentBridgeEngine) sweepXRPL() (string, error) {
	if e.xrpl == nil || e.TreasuryXRPL == "" {
		return "", nil
	}
	return e.xrpl.SweepToTreasury(e.TreasuryXRPL)
}

func (e *TransparentBridgeEngine) sweepBase(ctx context.Context) (string, error) {
	if e.base == nil || e.TreasuryETH == "" {
		return "", nil
	}
	return e.base.SweepUSDCToTreasury(ctx, e.TreasuryETH)
}

func isXRPL(addr string) bool { return strings.HasPrefix(addr, "r") && len(addr) >= 25 }
func isEVM(addr string) bool  { return strings.HasPrefix(addr, "0x") && len(addr) == 42 }
