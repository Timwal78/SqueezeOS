// x402probe — end-to-end WebSocket wire test for the native x402 vendor.
//
// Connects to /ws/metrics, triggers a quote+dispense pair, captures the
// X402_DISPENSED frame, and asserts the byte-level schema is correct.
//
// Usage:
//   X402_PROBE_BASE=http://localhost:8181 go run ./cmd/x402probe
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

type quote struct {
	Token string `json:"token"`
	IID   string `json:"invoice_id"`
}

type frame struct {
	Type           string  `json:"type"`
	TimestampMS    int64   `json:"ts"`
	TotalBridges   int64   `json:"total_bridges"`
	TPS            float64 `json:"tps"`
	AccumulatedFee string  `json:"accumulated_fee"`
	StateLabel     string  `json:"state_label,omitempty"`
	ProductID      string  `json:"product_id,omitempty"`
	Wallet         string  `json:"wallet,omitempty"`
	AgentTier      string  `json:"agent_tier,omitempty"`
}

func main() {
	base := flag.String("base", envOr("X402_PROBE_BASE", "http://localhost:8181"), "Ghost Layer base URL")
	product := flag.String("product", "routing.telemetry", "Product ID to dispense")
	wallet := flag.String("wallet", "rProbeAgent", "Agent wallet to use in the quote")
	flag.Parse()

	httpURL, err := url.Parse(*base)
	if err != nil {
		die("bad base URL: %v", err)
	}
	wsScheme := "ws"
	if httpURL.Scheme == "https" {
		wsScheme = "wss"
	}
	wsURL := fmt.Sprintf("%s://%s/ws/metrics", wsScheme, httpURL.Host)

	// 1. Connect to /ws/metrics
	fmt.Printf("[probe] connecting → %s\n", wsURL)
	c, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		die("ws dial: %v", err)
	}
	defer c.Close()

	// 2. Drain the CONNECTED frame
	_, _, err = c.ReadMessage()
	if err != nil {
		die("read CONNECTED: %v", err)
	}
	fmt.Println("[probe] ws connected")

	// 3. Quote
	q, err := postQuote(*base, *product, *wallet)
	if err != nil {
		die("quote: %v", err)
	}
	fmt.Printf("[probe] quote ok — iid=%s\n", q.IID)

	// 4. Dispense in a goroutine (so we can race the WS read)
	dispenseErr := make(chan error, 1)
	go func() {
		dispenseErr <- doDispense(*base, *product, q.Token)
	}()

	// 5. Wait for the X402_DISPENSED frame (skip heartbeats / TPS-only frames)
	c.SetReadDeadline(time.Now().Add(10 * time.Second))
	var got *frame
	for {
		_, msg, err := c.ReadMessage()
		if err != nil {
			die("ws read: %v", err)
		}
		var f frame
		if err := json.Unmarshal(msg, &f); err != nil {
			fmt.Printf("[probe] unparseable frame, skipping: %s\n", msg)
			continue
		}
		if f.Type == "X402_DISPENSED" {
			got = &f
			fmt.Printf("[probe] captured X402_DISPENSED frame:\n%s\n", pretty(msg))
			break
		}
		fmt.Printf("[probe] ignoring frame type=%s\n", f.Type)
	}

	if err := <-dispenseErr; err != nil {
		die("dispense: %v", err)
	}

	// 6. Schema assertions
	fail := false
	check := func(name string, ok bool, detail string) {
		mark := "PASS"
		if !ok {
			mark, fail = "FAIL", true
		}
		fmt.Printf("  [%s] %s — %s\n", mark, name, detail)
	}

	check("type",          got.Type == "X402_DISPENSED",       fmt.Sprintf("got %q", got.Type))
	check("product_id",    got.ProductID == *product,          fmt.Sprintf("got %q want %q", got.ProductID, *product))
	check("wallet",        got.Wallet == *wallet,              fmt.Sprintf("got %q want %q", got.Wallet, *wallet))
	check("agent_tier",    got.AgentTier != "",                fmt.Sprintf("got %q", got.AgentTier))
	check("state_label",   got.StateLabel == "VENDING",        fmt.Sprintf("got %q", got.StateLabel))
	check("ts",            got.TimestampMS > 0,                fmt.Sprintf("got %d", got.TimestampMS))
	check("total_bridges", got.TotalBridges >= 0,              fmt.Sprintf("got %d", got.TotalBridges))
	check("accumulated_fee numeric", isNumeric(got.AccumulatedFee), fmt.Sprintf("got %q", got.AccumulatedFee))

	if fail {
		die("schema assertion failed")
	}
	fmt.Println("\n[probe] OK — frame schema valid end-to-end")
}

func postQuote(base, product, wallet string) (*quote, error) {
	body, _ := json.Marshal(map[string]string{"product_id": product, "agent_wallet": wallet})
	resp, err := http.Post(base+"/v1/x402/quote", "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("quote %d: %s", resp.StatusCode, b)
	}
	var q quote
	if err := json.NewDecoder(resp.Body).Decode(&q); err != nil {
		return nil, err
	}
	return &q, nil
}

func doDispense(base, product, token string) error {
	req, _ := http.NewRequest("GET", base+"/v1/x402/dispense/"+product, nil)
	req.Header.Set("X-Payment-Token", token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("dispense %d: %s", resp.StatusCode, b)
	}
	return nil
}

func pretty(b []byte) string {
	var v interface{}
	if json.Unmarshal(b, &v) != nil {
		return string(b)
	}
	out, _ := json.MarshalIndent(v, "  ", "  ")
	return "  " + string(out)
}

func isNumeric(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func die(f string, a ...interface{}) {
	fmt.Fprintln(os.Stderr, "[probe] "+strings.TrimRight(fmt.Sprintf(f, a...), "\n"))
	os.Exit(1)
}
