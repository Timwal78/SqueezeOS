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
// Returns the principal tx hash plus the exact fee and net amounts.
func (e *TransparentBridgeEngine) RouteTransactionWithDisclosure(
	ctx context.Context,
	source, destination, amountStr string,
	bps int64,
	auth *chain.EIP3009Auth,
) (txHash string, fee *big.Int, net *big.Int, err error) {
	if source == "" || destination == "" {
		return "", nil, nil, errors.New("routing aborted: missing source or destination address")
	}

	fee, net = toll.CalculateBasisPointFee(amountStr, bps)
	gross, ok := new(big.Int).SetString(amountStr, 10)
	if !ok {
		return "", nil, nil, errors.New("invalid amount string")
	}

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

	// Auto-sweep: drain accumulated fees from hot gateway into cold treasury.
	// Runs async so it never blocks the caller's response.
	go e.sweep(ctx, source)

	return txHash, fee, net, nil
}

// Sweep manually triggers a fee sweep for the given chain type ("xrpl" or "evm").
// Returns the sweep tx hash, or "" if nothing was swept.
func (e *TransparentBridgeEngine) Sweep(ctx context.Context, chainType string) (string, error) {
	switch strings.ToLower(chainType) {
	case "xrpl":
		return e.sweepXRPL()
	case "evm", "base":
		return e.sweepBase(ctx)
	default:
		return "", fmt.Errorf("unknown chain type: %s (use 'xrpl' or 'evm')", chainType)
	}
}

func (e *TransparentBridgeEngine) sweep(ctx context.Context, sourceAddr string) {
	if isXRPL(sourceAddr) {
		if hash, err := e.sweepXRPL(); err != nil {
			log.Printf("[SWEEP] XRPL sweep error: %v", err)
		} else if hash != "" {
			log.Printf("[SWEEP] XRPL swept to treasury: %s", hash)
		}
	} else if isEVM(sourceAddr) {
		if hash, err := e.sweepBase(ctx); err != nil {
			log.Printf("[SWEEP] Base sweep error: %v", err)
		} else if hash != "" {
			log.Printf("[SWEEP] Base USDC swept to treasury: %s", hash)
		}
	}
}

func (e *TransparentBridgeEngine) sweepXRPL() (string, error) {
	if e.xrpl == nil {
		return "", errors.New("XRPL client not initialised")
	}
	if e.TreasuryXRPL == "" {
		return "", errors.New("TREASURY_ADDRESS not set")
	}
	return e.xrpl.SweepToTreasury(e.TreasuryXRPL)
}

func (e *TransparentBridgeEngine) sweepBase(ctx context.Context) (string, error) {
	if e.base == nil {
		return "", errors.New("Base client not initialised")
	}
	if e.TreasuryETH == "" {
		return "", errors.New("TREASURY_ETH_ADDRESS not set")
	}
	return e.base.SweepUSDCToTreasury(ctx, e.TreasuryETH)
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

func isXRPL(addr string) bool { return strings.HasPrefix(addr, "r") && len(addr) >= 25 }
func isEVM(addr string) bool  { return strings.HasPrefix(addr, "0x") && len(addr) == 42 }
