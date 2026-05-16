package router

import (
	"context"
	"errors"
	"fmt"
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
// and returns the tx hash plus the exact fee and net amounts for the caller to surface to users.
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

	fmt.Printf("[AUDIT] Route %s → %s | gross=%s fee=%s net=%s bps=%d\n",
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

	fmt.Printf("[AUDIT] ✓ tx=%s fee→treasury net→%s\n", txHash, destination)
	return txHash, fee, net, nil
}

func (e *TransparentBridgeEngine) routeXRPL(destination string, fee, net *big.Int) (string, error) {
	if e.xrpl == nil {
		return "", errors.New("XRPL client not initialised — set GATEWAY_XRPL_PRIVATE_KEY")
	}
	// Fee payment to treasury
	if _, err := e.xrpl.SendPayment(e.TreasuryXRPL, fee.Uint64()); err != nil {
		return "", fmt.Errorf("XRPL fee payment: %w", err)
	}
	// Net payment to destination
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
