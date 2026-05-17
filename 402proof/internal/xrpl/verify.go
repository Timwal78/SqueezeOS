package xrpl

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"strings"
	"time"
)

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

type rpcRequest struct {
	Method string        `json:"method"`
	Params []interface{} `json:"params"`
}

type rpcResponse struct {
	Result json.RawMessage `json:"result"`
}

func (c *Client) call(method string, params interface{}) (json.RawMessage, error) {
	body, err := json.Marshal(rpcRequest{Method: method, Params: []interface{}{params}})
	if err != nil {
		return nil, err
	}
	resp, err := c.httpClient.Post(c.RPCURL, "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("XRPL RPC: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	var r rpcResponse
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	return r.Result, nil
}

type PaymentResult struct {
	TxHash      string
	Amount      string
	Asset       string
	Destination string
	Validated   bool
}

// VerifyPayment confirms a validated XRPL payment meets all invoice requirements.
// rlusdIssuer is the XRPL account that issued RLUSD as currency "USD".
func (c *Client) VerifyPayment(txHash, expectedDest, expectedAmount, expectedAsset, expectedMemoHex, rlusdIssuer string) (*PaymentResult, error) {
	result, err := c.call("tx", map[string]interface{}{
		"transaction": txHash,
		"binary":      false,
	})
	if err != nil {
		return nil, fmt.Errorf("XRPL tx lookup: %w", err)
	}

	var tx struct {
		Validated       bool            `json:"validated"`
		TransactionType string          `json:"TransactionType"`
		Destination     string          `json:"Destination"`
		Amount          json.RawMessage `json:"Amount"`
		Memos           []struct {
			Memo struct {
				MemoData string `json:"MemoData"`
			} `json:"Memo"`
		} `json:"Memos"`
		Meta struct {
			TransactionResult string `json:"TransactionResult"`
		} `json:"meta"`
	}
	if err := json.Unmarshal(result, &tx); err != nil {
		return nil, fmt.Errorf("parse tx: %w", err)
	}

	if !tx.Validated {
		return nil, errors.New("transaction not yet validated on ledger")
	}
	if tx.Meta.TransactionResult != "tesSUCCESS" {
		return nil, fmt.Errorf("transaction failed: %s", tx.Meta.TransactionResult)
	}
	if tx.TransactionType != "Payment" {
		return nil, errors.New("transaction is not a Payment")
	}
	if !strings.EqualFold(tx.Destination, expectedDest) {
		return nil, fmt.Errorf("destination mismatch: got %s, want %s", tx.Destination, expectedDest)
	}

	var actualAmount, actualAsset string
	var amountStr string
	var amountObj struct {
		Currency string `json:"currency"`
		Issuer   string `json:"issuer"`
		Value    string `json:"value"`
	}

	if err := json.Unmarshal(tx.Amount, &amountStr); err == nil {
		actualAsset = "XRP"
		drops := new(big.Int)
		drops.SetString(amountStr, 10)
		xrp := new(big.Float).Quo(new(big.Float).SetInt(drops), big.NewFloat(1_000_000))
		actualAmount = fmt.Sprintf("%.6f", xrp)
	} else if err := json.Unmarshal(tx.Amount, &amountObj); err == nil {
		if amountObj.Currency == "USD" && strings.EqualFold(amountObj.Issuer, rlusdIssuer) {
			actualAsset = "RLUSD"
		} else {
			actualAsset = amountObj.Currency
		}
		actualAmount = amountObj.Value
	} else {
		return nil, errors.New("could not parse Amount field")
	}

	if !strings.EqualFold(actualAsset, expectedAsset) {
		return nil, fmt.Errorf("asset mismatch: got %s, want %s", actualAsset, expectedAsset)
	}
	if err := checkAmountSufficient(actualAmount, expectedAmount, actualAsset); err != nil {
		return nil, err
	}
	if expectedMemoHex != "" && !memoPresent(tx.Memos, expectedMemoHex) {
		return nil, errors.New("invoice memo not found in transaction")
	}

	return &PaymentResult{
		TxHash:      txHash,
		Amount:      actualAmount,
		Asset:       actualAsset,
		Destination: tx.Destination,
		Validated:   true,
	}, nil
}

func checkAmountSufficient(actual, expected, asset string) error {
	a, ok1 := new(big.Float).SetString(actual)
	e, ok2 := new(big.Float).SetString(expected)
	if !ok1 || !ok2 {
		return errors.New("could not parse amounts for comparison")
	}
	if a.Cmp(e) < 0 {
		return fmt.Errorf("insufficient payment: got %s %s, need %s %s", actual, asset, expected, asset)
	}
	return nil
}

func memoPresent(memos []struct {
	Memo struct {
		MemoData string `json:"MemoData"`
	} `json:"Memo"`
}, expectedHex string) bool {
	upper := strings.ToUpper(expectedHex)
	for _, m := range memos {
		if strings.EqualFold(m.Memo.MemoData, upper) {
			return true
		}
		decoded, err := hex.DecodeString(m.Memo.MemoData)
		if err == nil && strings.EqualFold(string(decoded), expectedHex) {
			return true
		}
	}
	return false
}
