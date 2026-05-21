// Package base provides a minimal Base chain RPC client for verifying
// USDC ERC-20 payments. Used by 402Proof to accept USDC on Base as an
// alternative payment rail alongside RLUSD on XRPL.
package base

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

// ERC-20 Transfer event topic: keccak256("Transfer(address,address,uint256)")
const transferTopic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

// Client is a lightweight Base chain JSON-RPC client.
type Client struct {
	RPCURL     string
	httpClient *http.Client
}

func NewClient(rpcURL string) *Client {
	return &Client{
		RPCURL:     rpcURL,
		httpClient: &http.Client{Timeout: 15 * time.Second},
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
		return nil, fmt.Errorf("Base RPC: %w", err)
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

type txReceipt struct {
	Status string `json:"status"`
	Logs   []struct {
		Address string   `json:"address"`
		Topics  []string `json:"topics"`
		Data    string   `json:"data"`
	} `json:"logs"`
}

func (c *Client) getReceipt(txHash string) (*txReceipt, error) {
	raw, err := c.call("eth_getTransactionReceipt", []interface{}{txHash})
	if err != nil {
		return nil, err
	}
	if string(raw) == "null" {
		return nil, errors.New("transaction not found — may not be mined yet")
	}
	var r txReceipt
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	return &r, nil
}

// VerifyUSDCPayment checks that txHash is a confirmed Base chain USDC transfer
// to expectedDest for at least expectedAmount (decimal string, e.g. "0.10").
// usdcContract is the USDC ERC-20 contract address on Base.
func (c *Client) VerifyUSDCPayment(txHash, expectedDest, expectedAmount, usdcContract string) error {
	rec, err := c.getReceipt(txHash)
	if err != nil {
		return err
	}
	if rec.Status != "0x1" {
		return errors.New("transaction failed on Base chain (status != 0x1)")
	}

	expectedWei, ok := usdcToWei(expectedAmount)
	if !ok {
		return errors.New("invalid expected USDC amount")
	}
	destNorm := strings.ToLower(strings.TrimPrefix(expectedDest, "0x"))
	usdcNorm := strings.ToLower(usdcContract)

	for _, log := range rec.Logs {
		if strings.ToLower(log.Address) != usdcNorm {
			continue
		}
		if len(log.Topics) < 3 {
			continue
		}
		if strings.ToLower(log.Topics[0]) != transferTopic {
			continue
		}
		// topics[2] = `to` address, padded to 32 bytes — extract last 20 bytes
		toRaw := strings.TrimPrefix(strings.ToLower(log.Topics[2]), "0x")
		if len(toRaw) < 40 {
			continue
		}
		toAddr := toRaw[len(toRaw)-40:] // last 20 bytes = address
		if toAddr != destNorm {
			continue
		}
		// data field = uint256 value (hex)
		value, ok2 := new(big.Int).SetString(strings.TrimPrefix(log.Data, "0x"), 16)
		if !ok2 {
			continue
		}
		if value.Cmp(expectedWei) >= 0 {
			return nil // ✅ valid USDC transfer found
		}
	}
	return fmt.Errorf("no USDC Transfer to %s for >= %s USDC in tx %s", expectedDest, expectedAmount, txHash)
}

// usdcToWei converts a decimal USDC amount string to its 6-decimal wei big.Int.
func usdcToWei(amount string) (*big.Int, bool) {
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
