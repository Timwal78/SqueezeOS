package cex

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/gorilla/websocket"

	"sml-flow-interceptor/internal/events"
)

// Coinbase subscribes to the Advanced Trade public `ticker` channel for one
// or more spot products and emits each price update as a CEXTick event.
// The ticker channel is rate-limited to one update per product per second;
// for tick-by-tick fidelity swap to `market_trades` in v2.
type Coinbase struct {
	url      string
	products []string
	out      chan<- events.Event
	log      *slog.Logger
}

func NewCoinbase(url string, products []string, out chan<- events.Event, log *slog.Logger) *Coinbase {
	return &Coinbase{url: url, products: products, out: out, log: log}
}

func (c *Coinbase) Run(ctx context.Context) {
	backoff := time.Second
	const maxBackoff = 30 * time.Second
	for {
		err := c.runOnce(ctx)
		if ctx.Err() != nil {
			return
		}
		c.log.Error("coinbase session ended", "err", err, "backoff", backoff)
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

func (c *Coinbase) runOnce(ctx context.Context) error {
	dialer := websocket.DefaultDialer
	dialer.HandshakeTimeout = 10 * time.Second

	conn, _, err := dialer.DialContext(ctx, c.url, nil)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()
	c.log.Info("coinbase connected", "products", c.products)

	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-done:
		}
	}()

	sub := map[string]any{
		"type":        "subscribe",
		"channel":     "ticker",
		"product_ids": c.products,
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
		c.handle(data)
	}
}

type cbEnvelope struct {
	Channel   string `json:"channel"`
	Timestamp string `json:"timestamp"`
	Events    []struct {
		Type    string `json:"type"`
		Tickers []struct {
			ProductID string `json:"product_id"`
			Price     string `json:"price"`
		} `json:"tickers"`
	} `json:"events"`
}

func (c *Coinbase) handle(data []byte) {
	var env cbEnvelope
	if err := json.Unmarshal(data, &env); err != nil {
		return
	}
	if env.Channel != "ticker" {
		return
	}
	now := events.Now()
	for _, ev := range env.Events {
		for _, t := range ev.Tickers {
			price, err := strconv.ParseFloat(t.Price, 64)
			if err != nil {
				continue
			}
			payload := events.CEXTick{
				Venue:   "coinbase",
				Product: t.ProductID,
				Price:   price,
				VenueTS: env.Timestamp,
			}
			raw, err := json.Marshal(payload)
			if err != nil {
				continue
			}
			evt := events.Event{
				Source:  events.SourceCEXTicker,
				TSNanos: now,
				Payload: raw,
			}
			select {
			case c.out <- evt:
			default:
				c.log.Warn("event channel full, dropping cex tick", "product", t.ProductID)
			}
		}
	}
}
