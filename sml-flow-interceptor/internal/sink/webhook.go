package sink

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"sml-flow-interceptor/internal/events"
)

// Webhook posts an event as JSON to a configured URL. Used to push Base
// mempool hits to the HUD's external data receiver. Timeout is short so a
// hung HUD endpoint cannot back-pressure the event pipeline.
type Webhook struct {
	url    string
	client *http.Client
}

func NewWebhook(url string) *Webhook {
	return &Webhook{
		url:    url,
		client: &http.Client{Timeout: 3 * time.Second},
	}
}

func (w *Webhook) Send(ctx context.Context, e events.Event) error {
	if w.url == "" {
		return nil
	}
	body, err := json.Marshal(e)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, w.url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "sml-flow-interceptor/1.0")

	resp, err := w.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("hud webhook status %d", resp.StatusCode)
	}
	return nil
}
