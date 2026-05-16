package chain

import (
	"context"
	"crypto/ecdsa"
	"fmt"
	"math/big"
	"strings"

	ethereum "github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
)

const usdcABIJSON = `[
	{
		"name":"transferWithAuthorization","type":"function",
		"inputs":[
			{"name":"from","type":"address"},
			{"name":"to","type":"address"},
			{"name":"value","type":"uint256"},
			{"name":"validAfter","type":"uint256"},
			{"name":"validBefore","type":"uint256"},
			{"name":"nonce","type":"bytes32"},
			{"name":"v","type":"uint8"},
			{"name":"r","type":"bytes32"},
			{"name":"s","type":"bytes32"}
		],
		"outputs":[]
	},
	{
		"name":"transfer","type":"function",
		"inputs":[
			{"name":"to","type":"address"},
			{"name":"value","type":"uint256"}
		],
		"outputs":[{"name":"","type":"bool"}]
	}
]`

// EIP3009Auth holds the transferWithAuthorization signature parameters.
type EIP3009Auth struct {
	ValidAfter  *big.Int
	ValidBefore *big.Int
	Nonce       [32]byte
	V           uint8
	R           [32]byte
	S           [32]byte
}

// BaseClient executes USDC routing on Base L2.
type BaseClient struct {
	client         *ethclient.Client
	privKey        *ecdsa.PrivateKey
	gatewayAddress common.Address
	usdcAddress    common.Address
	parsedABI      abi.ABI
}

func NewBaseClient(rpcURL, privateKeyHex, usdcAddr string) (*BaseClient, error) {
	client, err := ethclient.Dial(rpcURL)
	if err != nil {
		return nil, fmt.Errorf("connect to Base: %w", err)
	}
	privKey, err := crypto.HexToECDSA(strings.TrimPrefix(privateKeyHex, "0x"))
	if err != nil {
		return nil, fmt.Errorf("invalid ETH private key: %w", err)
	}
	parsedABI, err := abi.JSON(strings.NewReader(usdcABIJSON))
	if err != nil {
		return nil, fmt.Errorf("parse ABI: %w", err)
	}
	return &BaseClient{
		client:         client,
		privKey:        privKey,
		gatewayAddress: crypto.PubkeyToAddress(privKey.PublicKey),
		usdcAddress:    common.HexToAddress(usdcAddr),
		parsedABI:      parsedABI,
	}, nil
}

// PullAndRoute executes an EIP-3009 pull from source to gateway, then transfers
// netAmount to destination. The fee (gross − net) remains in the gateway wallet.
func (b *BaseClient) PullAndRoute(ctx context.Context, source, destination string, grossAmount, netAmount *big.Int, auth EIP3009Auth) (string, error) {
	chainID, err := b.client.ChainID(ctx)
	if err != nil {
		return "", fmt.Errorf("get chain ID: %w", err)
	}

	// Step 1 — pull gross from source → gateway via EIP-3009 authorization
	pullData, err := b.parsedABI.Pack("transferWithAuthorization",
		common.HexToAddress(source),
		b.gatewayAddress,
		grossAmount,
		auth.ValidAfter,
		auth.ValidBefore,
		auth.Nonce,
		auth.V,
		auth.R,
		auth.S,
	)
	if err != nil {
		return "", fmt.Errorf("pack transferWithAuthorization: %w", err)
	}
	if _, err := b.sendTx(ctx, chainID, pullData); err != nil {
		return "", fmt.Errorf("pull tx: %w", err)
	}

	// Step 2 — send net to destination
	sendData, err := b.parsedABI.Pack("transfer", common.HexToAddress(destination), netAmount)
	if err != nil {
		return "", fmt.Errorf("pack transfer: %w", err)
	}
	txHash, err := b.sendTx(ctx, chainID, sendData)
	if err != nil {
		return "", fmt.Errorf("send tx: %w", err)
	}
	return txHash, nil
}

func (b *BaseClient) sendTx(ctx context.Context, chainID *big.Int, data []byte) (string, error) {
	nonce, err := b.client.PendingNonceAt(ctx, b.gatewayAddress)
	if err != nil {
		return "", err
	}
	gasPrice, err := b.client.SuggestGasPrice(ctx)
	if err != nil {
		return "", err
	}
	gasLimit, err := b.client.EstimateGas(ctx, ethereum.CallMsg{
		From: b.gatewayAddress,
		To:   &b.usdcAddress,
		Data: data,
	})
	if err != nil {
		gasLimit = 120_000 // safe fallback
	}

	tx := types.NewTransaction(nonce, b.usdcAddress, big.NewInt(0), gasLimit, gasPrice, data)
	signed, err := types.SignTx(tx, types.NewEIP155Signer(chainID), b.privKey)
	if err != nil {
		return "", err
	}
	if err := b.client.SendTransaction(ctx, signed); err != nil {
		return "", err
	}
	return signed.Hash().Hex(), nil
}
