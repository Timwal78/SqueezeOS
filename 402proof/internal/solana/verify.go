// Package solana provides a minimal Solana JSON-RPC client for verifying
// USDC-SPL inbound payments. Used by 402Proof to accept USDC on Solana mainnet
// as an alternative payment rail alongside RLUSD on XRPL and USDC on Base.
package solana

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"strings"
	"time"
)

const usdcDecimals = 6

// Client is a lightweight Solana JSON-RPC client.
type Client struct {
	RPCURL     string
	httpClient *http.Client
}

func NewClient(rpcURL string) *Client {
	return &Client{
		RPCURL:     rpcURL,
		httpClient: &http.Client{Timeout: 20 * time.Second},
	}
}

type rpcReq struct {
	JSONRPC string        `json:"jsonrpc"`
	Method  string        `json:"method"`
	Params  []interface{} `json:"params"`
	ID      int           `json:"id"`
}

type rpcResp struct {
	Result json.RawMessage `json:"result"`
	Error  *struct {
		Message string `json:"message"`
	} `json:"error"`
}

func (c *Client) call(method string, params []interface{}) (json.RawMessage, error) {
	body, _ := json.Marshal(rpcReq{JSONRPC: "2.0", Method: method, Params: params, ID: 1})
	resp, err := c.httpClient.Post(c.RPCURL, "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("Solana RPC: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	var r rpcResp
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	if r.Error != nil {
		return nil, errors.New(r.Error.Message)
	}
	return r.Result, nil
}

type tokenBalance struct {
	AccountIndex  int    `json:"accountIndex"`
	Mint          string `json:"mint"`
	Owner         string `json:"owner"`
	UITokenAmount struct {
		Amount string `json:"amount"` // base units as string, e.g. "100000" = 0.1 USDC
	} `json:"uiTokenAmount"`
}

type txResult struct {
	Meta *struct {
		Err               interface{}    `json:"err"`
		PreTokenBalances  []tokenBalance `json:"preTokenBalances"`
		PostTokenBalances []tokenBalance `json:"postTokenBalances"`
	} `json:"meta"`
}

// VerifyUSDCPayment confirms that signature is a finalized Solana USDC-SPL transfer
// to treasuryOwner for at least expectedAmount (decimal string, e.g. "0.10").
// usdcMint is the USDC mint address (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v on mainnet).
//
// Detection uses the preTokenBalances→postTokenBalances delta: any token account
// owned by treasuryOwner with the USDC mint that increased by >= expectedAmount passes.
// This handles both direct transfers and transfers via ATAs without needing to
// derive or look up the destination ATA address.
func (c *Client) VerifyUSDCPayment(signature, treasuryOwner, expectedAmount, usdcMint string) error {
	raw, err := c.call("getTransaction", []interface{}{
		signature,
		map[string]interface{}{
			"encoding":                       "jsonParsed",
			"commitment":                     "finalized",
			"maxSupportedTransactionVersion": 0,
		},
	})
	if err != nil {
		return err
	}
	if string(raw) == "null" {
		return errors.New("transaction not found or not yet finalized")
	}

	var tx txResult
	if err := json.Unmarshal(raw, &tx); err != nil {
		return fmt.Errorf("parse transaction: %w", err)
	}
	if tx.Meta == nil {
		return errors.New("transaction has no metadata")
	}
	if tx.Meta.Err != nil {
		return fmt.Errorf("transaction failed on-chain: %v", tx.Meta.Err)
	}

	expectedBaseUnits, ok := usdcToBaseUnits(expectedAmount)
	if !ok {
		return errors.New("invalid expected USDC amount")
	}

	// Index pre-balances by accountIndex for treasury USDC accounts.
	preBals := make(map[int]*big.Int)
	for _, b := range tx.Meta.PreTokenBalances {
		if strings.EqualFold(b.Mint, usdcMint) && strings.EqualFold(b.Owner, treasuryOwner) {
			if amt, ok := new(big.Int).SetString(b.UITokenAmount.Amount, 10); ok {
				preBals[b.AccountIndex] = amt
			}
		}
	}

	// Check post-balances: any treasury USDC account that gained >= expected amount passes.
	for _, b := range tx.Meta.PostTokenBalances {
		if !strings.EqualFold(b.Mint, usdcMint) || !strings.EqualFold(b.Owner, treasuryOwner) {
			continue
		}
		post, ok := new(big.Int).SetString(b.UITokenAmount.Amount, 10)
		if !ok {
			continue
		}
		pre, hasPre := preBals[b.AccountIndex]
		if !hasPre {
			pre = big.NewInt(0)
		}
		received := new(big.Int).Sub(post, pre)
		if received.Cmp(expectedBaseUnits) >= 0 {
			return nil
		}
	}

	return fmt.Errorf("no USDC transfer of >= %s USDC to %s found in tx %s", expectedAmount, treasuryOwner, signature)
}

func usdcToBaseUnits(amount string) (*big.Int, bool) {
	f, ok := new(big.Float).SetString(amount)
	if !ok {
		return nil, false
	}
	scale := new(big.Float).SetInt(
		new(big.Int).Exp(big.NewInt(10), big.NewInt(usdcDecimals), nil),
	)
	f.Mul(f, scale)
	result, _ := f.Int(nil)
	return result, true
}
