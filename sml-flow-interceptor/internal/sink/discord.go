package sink

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"sml-flow-interceptor/internal/events"
)

// Discord posts Base transfer alerts to a Discord webhook as rich embeds.
// CEX ticks are intentionally skipped — too chatty.
type Discord struct {
	url    string
	client *http.Client
}

func NewDiscord(url string) *Discord {
	return &Discord{
		url:    url,
		client: &http.Client{Timeout: 5 * time.Second},
	}
}

type discordEmbed struct {
	Title       string         `json:"title"`
	Description string         `json:"description,omitempty"`
	Color       int            `json:"color"`
	Fields      []embedField   `json:"fields"`
	Footer      *embedFooter   `json:"footer,omitempty"`
	Timestamp   string         `json:"timestamp"`
}

type embedField struct {
	Name   string `json:"name"`
	Value  string `json:"value"`
	Inline bool   `json:"inline"`
}

type embedFooter struct {
	Text string `json:"text"`
}

type discordPayload struct {
	Username  string         `json:"username"`
	AvatarURL string         `json:"avatar_url,omitempty"`
	Embeds    []discordEmbed `json:"embeds"`
}

func (d *Discord) Send(ctx context.Context, e events.Event) error {
	if d.url == "" || e.Source != events.SourceBaseMempool {
		return nil
	}

	var transfer events.BaseTransfer
	if err := json.Unmarshal(e.Payload, &transfer); err != nil {
		return fmt.Errorf("unmarshal transfer: %w", err)
	}

	color := colorForValue(transfer.ValueScaled)
	label := contractLabel(transfer.Contract)
	amount := formatAmount(transfer.ValueScaled, label)

	short := func(addr string) string {
		if len(addr) > 10 {
			return addr[:6] + "..." + addr[len(addr)-4:]
		}
		return addr
	}

	txURL := fmt.Sprintf("https://basescan.org/tx/%s", transfer.TxHash)
	fromURL := fmt.Sprintf("https://basescan.org/address/%s", transfer.From)
	toURL := fmt.Sprintf("https://basescan.org/address/%s", transfer.To)

	ts := time.Unix(0, e.TSNanos).UTC().Format(time.RFC3339)

	embed := discordEmbed{
		Title: fmt.Sprintf("🚨 Large %s Transfer on Base", label),
		Color: color,
		Fields: []embedField{
			{Name: "Amount", Value: amount, Inline: true},
			{Name: "Token", Value: label, Inline: true},
			{Name: "From", Value: fmt.Sprintf("[%s](%s)", short(transfer.From), fromURL), Inline: false},
			{Name: "To", Value: fmt.Sprintf("[%s](%s)", short(transfer.To), toURL), Inline: false},
			{Name: "Tx", Value: fmt.Sprintf("[%s](%s)", short(transfer.TxHash), txURL), Inline: false},
		},
		Footer:    &embedFooter{Text: "SML Flow Interceptor — Base Mempool"},
		Timestamp: ts,
	}

	payload := discordPayload{
		Username: "SML Flow Interceptor",
		Embeds:   []discordEmbed{embed},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, d.url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "sml-flow-interceptor/1.0")

	resp, err := d.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	// Discord returns 204 on success
	if resp.StatusCode >= 400 {
		return fmt.Errorf("discord webhook status %d", resp.StatusCode)
	}
	return nil
}

func colorForValue(v float64) int {
	switch {
	case v >= 10_000_000:
		return 0xE74C3C // red — $10M+
	case v >= 5_000_000:
		return 0xE67E22 // orange — $5M+
	default:
		return 0xF1C40F // yellow — $1M+
	}
}

func contractLabel(contract string) string {
	labels := map[string]string{
		"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
		"0x4200000000000000000000000000000000000006": "WETH",
		"0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
	}
	if label, ok := labels[strings.ToLower(contract)]; ok {
		return label
	}
	if len(contract) > 10 {
		return contract[:6] + "..." + contract[len(contract)-4:]
	}
	return contract
}

func formatAmount(v float64, label string) string {
	switch {
	case v >= 1_000_000_000:
		return fmt.Sprintf("$%.2fB %s", v/1_000_000_000, label)
	case v >= 1_000_000:
		return fmt.Sprintf("$%.2fM %s", v/1_000_000, label)
	case v >= 1_000:
		return fmt.Sprintf("$%.2fK %s", v/1_000, label)
	default:
		return fmt.Sprintf("$%.2f %s", v, label)
	}
}
