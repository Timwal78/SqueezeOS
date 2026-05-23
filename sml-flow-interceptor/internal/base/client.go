package base

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"

	"sml-flow-interceptor/internal/events"
)

// Client streams pending transactions from a Base RPC websocket endpoint,
// filters them against a watchlist of ERC-20 contracts and counterparties,
// and emits decoded transfer events to an output channel.
type Client struct {
	url              string
	watchedContracts map[string]struct{}
	watchedCparties  map[string]struct{}
	minValueScaled   float64
	contractDecimals map[string]uint8
	out              chan<- events.Event
	log              *slog.Logger

	hashOnlyWarned atomic.Bool
}

type Params struct {
	URL                   string
	WatchedContracts      []string
	WatchedCounterparties []string
	MinValueScaled        float64
	ContractDecimals      map[string]uint8
	Out                   chan<- events.Event
	Log                   *slog.Logger
}

func New(p Params) *Client {
	wc := make(map[string]struct{}, len(p.WatchedContracts))
	for _, a := range p.WatchedContracts {
		wc[strings.ToLower(a)] = struct{}{}
	}
	cp := make(map[string]struct{}, len(p.WatchedCounterparties))
	for _, a := range p.WatchedCounterparties {
		cp[strings.ToLower(a)] = struct{}{}
	}
	dec := p.ContractDecimals
	if dec == nil {
		dec = map[string]uint8{}
	}
	return &Client{
		url:              p.URL,
		watchedContracts: wc,
		watchedCparties:  cp,
		minValueScaled:   p.MinValueScaled,
		contractDecimals: dec,
		out:              p.Out,
		log:              p.Log,
	}
}

// Run blocks until ctx is cancelled, reconnecting with exponential backoff
// on transport errors.
func (c *Client) Run(ctx context.Context) {
	backoff := time.Second
	const maxBackoff = 30 * time.Second
	for {
		err := c.runOnce(ctx)
		if ctx.Err() != nil {
			return
		}
		c.log.Error("base mempool session ended", "err", err, "backoff", backoff)
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		if backoff < maxBackoff {
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
		}
	}
}

func (c *Client) runOnce(ctx context.Context) error {
	dialer := websocket.DefaultDialer
	dialer.HandshakeTimeout = 10 * time.Second

	conn, _, err := dialer.DialContext(ctx, c.url, nil)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()
	c.log.Info("base mempool connected", "url", redactURL(c.url))

	// Close the connection when ctx is cancelled so the blocking ReadMessage
	// returns and runOnce can clean up.
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-done:
		}
	}()

	// Subscribe with the provider-extended full-object variant. Providers that
	// don't support it ignore the boolean and emit hashes; we handle that case
	// in handleMessage with a one-shot warning.
	sub := map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "eth_subscribe",
		"params":  []any{"newPendingTransactions", true},
	}
	if err := conn.WriteJSON(sub); err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}

	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			return fmt.Errorf("read: %w", err)
		}
		c.handleMessage(data)
	}
}

type rpcEnvelope struct {
	Method string `json:"method"`
	Params struct {
		Subscription string          `json:"subscription"`
		Result       json.RawMessage `json:"result"`
	} `json:"params"`
}

type pendingTx struct {
	Hash  string `json:"hash"`
	From  string `json:"from"`
	To    string `json:"to"`
	Input string `json:"input"`
}

func (c *Client) handleMessage(data []byte) {
	var env rpcEnvelope
	if err := json.Unmarshal(data, &env); err != nil {
		return
	}
	if env.Method != "eth_subscription" {
		return
	}

	// Result is either a tx-hash string (hash-only feed) or a full tx object.
	if len(env.Params.Result) > 0 && env.Params.Result[0] == '"' {
		if c.hashOnlyWarned.CompareAndSwap(false, true) {
			c.log.Warn("provider returned hash-only pending feed; per-tx eth_getTransactionByHash roundtrip required and not implemented in v1 logger — switch to a full-tx capable provider (Alchemy alchemy_pendingTransactions, Blocknative, etc.)")
		}
		return
	}

	var tx pendingTx
	if err := json.Unmarshal(env.Params.Result, &tx); err != nil {
		return
	}
	if tx.To == "" || tx.Input == "" || tx.Input == "0x" {
		return
	}

	contract := strings.ToLower(tx.To)
	if _, ok := c.watchedContracts[contract]; !ok {
		return
	}

	input, err := hex.DecodeString(strings.TrimPrefix(tx.Input, "0x"))
	if err != nil {
		return
	}
	decoded, err := DecodeERC20Transfer(input, tx.From)
	if err != nil {
		return
	}

	if len(c.watchedCparties) > 0 {
		_, fromHit := c.watchedCparties[decoded.From]
		_, toHit := c.watchedCparties[decoded.To]
		if !fromHit && !toHit {
			return
		}
	}

	decimals, ok := c.contractDecimals[contract]
	if !ok {
		decimals = 18
	}
	scaled := ScaleValue(decoded.Value, decimals)
	if scaled < c.minValueScaled {
		return
	}

	payload := events.BaseTransfer{
		TxHash:      tx.Hash,
		Contract:    contract,
		From:        decoded.From,
		To:          decoded.To,
		ValueRaw:    decoded.Value.String(),
		ValueScaled: scaled,
		Decimals:    decimals,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return
	}
	evt := events.Event{
		Source:  events.SourceBaseMempool,
		TSNanos: events.Now(),
		Payload: raw,
	}
	select {
	case c.out <- evt:
	default:
		c.log.Warn("event channel full, dropping base transfer", "tx", tx.Hash, "scaled", scaled)
	}
}

// redactURL strips API-key bearing fragments commonly placed in RPC URLs
// (Alchemy's /v2/<key>, query strings) so structured logs are shareable.
func redactURL(u string) string {
	if i := strings.Index(u, "?"); i >= 0 {
		u = u[:i]
	}
	if i := strings.Index(u, "/v2/"); i >= 0 {
		return u[:i+4] + "***"
	}
	if i := strings.Index(u, "/v1/"); i >= 0 {
		return u[:i+4] + "***"
	}
	return u
}
