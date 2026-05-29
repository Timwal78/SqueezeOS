package events

import (
	"encoding/json"
	"time"
)

type Source string

const (
	SourceBaseMempool Source = "base_mempool"
	SourceCEXTicker   Source = "cex_ticker"
)

// Event is the unified record written to the NDJSON log. Offline correlation
// joins Base mempool hits against CEX ticks on TSNanos within a sliding window.
// TSNanos is wall-clock UTC nanoseconds at the moment the local process saw the
// data; correlation accuracy assumes the host's NTP discipline is healthy.
type Event struct {
	Source  Source          `json:"source"`
	TSNanos int64           `json:"ts_ns"`
	Payload json.RawMessage `json:"payload"`
}

// BaseTransfer is the decoded ERC-20 transfer observed in the Base mempool.
type BaseTransfer struct {
	TxHash      string  `json:"tx_hash"`
	Contract    string  `json:"contract"`
	From        string  `json:"from"`
	To          string  `json:"to"`
	ValueRaw    string  `json:"value_raw"`
	ValueScaled float64 `json:"value_scaled"`
	Decimals    uint8   `json:"decimals"`
}

// CEXTick is a single price update from a CEX ticker channel.
type CEXTick struct {
	Venue   string  `json:"venue"`
	Product string  `json:"product"`
	Price   float64 `json:"price"`
	VenueTS string  `json:"venue_ts,omitempty"`
}

func Now() int64 { return time.Now().UTC().UnixNano() }
