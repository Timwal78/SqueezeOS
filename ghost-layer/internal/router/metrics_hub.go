package router

import (
	"encoding/json"
	"log"
	"math/big"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

// ── WebSocket Metrics Hub ─────────────────────────────────────────────────────
// Broadcasts real-time bridge metrics to all connected cube.js clients.
// Replaces the SSE hub for live tachometer feeds: TPS, volume, fee accumulation.

// MetricsFrame is the payload broadcast to every WebSocket subscriber on each event.
type MetricsFrame struct {
	Type           string  `json:"type"`
	TimestampMS    int64   `json:"ts"`
	TotalBridges   int64   `json:"total_bridges"`
	TPS            float64 `json:"tps"`            // transactions/second (rolling 60-s window)
	AccumulatedFee string  `json:"accumulated_fee"` // raw big.Int string (drops or wei)
	Chain          string  `json:"chain,omitempty"`
	TxHash         string  `json:"tx_hash,omitempty"`
	GrossAmount    string  `json:"gross_amount,omitempty"`
	NetAmount      string  `json:"net_amount,omitempty"`
	FeeAmount      string  `json:"fee_amount,omitempty"`
	AgentTier      string  `json:"agent_tier,omitempty"`
	EffectiveBPS   int64   `json:"effective_bps,omitempty"`
	// State-machine label for the cube.js tachometer
	StateLabel string `json:"state_label,omitempty"`
	// X402 dispense fields (only populated for X402_DISPENSED frames)
	ProductID string `json:"product_id,omitempty"`
	Wallet    string `json:"wallet,omitempty"`
}

// wsClient wraps a gorilla WebSocket connection with a send channel.
type wsClient struct {
	conn *websocket.Conn
	send chan []byte
}

// MetricsHub is the sovereign WebSocket broadcasting engine.
type MetricsHub struct {
	mu             sync.RWMutex
	clients        map[*wsClient]struct{}
	totalBridges   atomic.Int64
	accumulatedFee *big.Int
	feeMu          sync.Mutex

	// TPS rolling window — timestamps of recent bridge executions
	tpsTimes []time.Time
	tpsMu    sync.Mutex

	upgrader websocket.Upgrader
}

// NewMetricsHub creates and returns a live-streaming metrics hub.
func NewMetricsHub() *MetricsHub {
	return &MetricsHub{
		clients:        make(map[*wsClient]struct{}),
		accumulatedFee: big.NewInt(0),
		upgrader: websocket.Upgrader{
			ReadBufferSize:  512,
			WriteBufferSize: 4096,
			CheckOrigin:     func(r *http.Request) bool { return true }, // CORS open for M2M agents
		},
	}
}

// ServeHTTP upgrades HTTP to WebSocket and registers the client.
func (h *MetricsHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	conn, err := h.upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("[WS] upgrade failed: %v", err)
		return
	}

	client := &wsClient{conn: conn, send: make(chan []byte, 64)}

	h.mu.Lock()
	h.clients[client] = struct{}{}
	h.mu.Unlock()

	log.Printf("[WS] client connected from %s | total_ws=%d", r.RemoteAddr, h.clientCount())

	// Send CONNECTED frame immediately with current state
	frame := h.buildFrame("CONNECTED", "LIVE", "", "", nil, nil, nil, 0, "")
	if b, err := json.Marshal(frame); err == nil {
		client.send <- b
	}

	// Writer goroutine — drains send channel to the wire
	go func() {
		defer func() {
			conn.Close()
			h.mu.Lock()
			delete(h.clients, client)
			h.mu.Unlock()
			log.Printf("[WS] client disconnected | total_ws=%d", h.clientCount())
		}()
		// Heartbeat every 25 s to prevent proxy timeouts
		ticker := time.NewTicker(25 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case msg, ok := <-client.send:
				if !ok {
					conn.WriteMessage(websocket.CloseMessage, []byte{})
					return
				}
				conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
				if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
					return
				}
			case <-ticker.C:
				ping := h.buildFrame("HEARTBEAT", "LIVE", "", "", nil, nil, nil, 0, "")
				if b, err := json.Marshal(ping); err == nil {
					conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
					if err := conn.WriteMessage(websocket.TextMessage, b); err != nil {
						return
					}
				}
			}
		}
	}()

	// Reader goroutine — consumes pings and close frames from client
	for {
		_, _, err := conn.ReadMessage()
		if err != nil {
			close(client.send)
			break
		}
	}
}

// BroadcastBridgeSettled records a completed bridge and pushes metrics to all clients.
func (h *MetricsHub) BroadcastBridgeSettled(chain, txHash string, gross, fee, net *big.Int, agentTier string, effectiveBPS int64) {
	h.totalBridges.Add(1)
	h.recordTPS()
	h.feeMu.Lock()
	h.accumulatedFee.Add(h.accumulatedFee, fee)
	h.feeMu.Unlock()

	frame := h.buildFrame("BRIDGE_SETTLED", "SETTLING", chain, txHash, gross, fee, net, effectiveBPS, agentTier)
	h.broadcast(frame)
}

// BroadcastAgentProbe notifies clients of an inbound agent health probe.
func (h *MetricsHub) BroadcastAgentProbe(agentAddr string) {
	frame := h.buildFrame("AGENT_PROBE", "ROUTING", "", agentAddr, nil, nil, nil, 0, "")
	h.broadcast(frame)
}

// TotalBridges returns the lifetime bridge counter.
func (h *MetricsHub) TotalBridges() int64 { return h.totalBridges.Load() }

// RollingTPS returns the current rolling 60-second TPS reading.
// Exported wrapper so callers outside the package (e.g. x402 dispatchers)
// can snapshot the live tachometer reading.
func (h *MetricsHub) RollingTPS() float64 { return h.rollingTPS() }

// AccumulatedFeeString returns the lifetime accumulated fee as a base-10 string.
// Safe for concurrent callers — uses the internal feeMu.
func (h *MetricsHub) AccumulatedFeeString() string {
	h.feeMu.Lock()
	defer h.feeMu.Unlock()
	return new(big.Int).Set(h.accumulatedFee).String()
}

// BroadcastX402Dispensed pushes an X402_DISPENSED frame to all WebSocket clients
// after a successful native x402 vend. Mirrors BroadcastBridgeSettled but for
// the catalog dispense path — product/wallet/tier ride in the dedicated fields.
func (h *MetricsHub) BroadcastX402Dispensed(productID, wallet, tier string) {
	frame := h.buildFrame("X402_DISPENSED", "VENDING", "", "", nil, nil, nil, 0, tier)
	frame.ProductID = productID
	frame.Wallet = wallet
	h.broadcast(frame)
}

// ── internal ──────────────────────────────────────────────────────────────────

func (h *MetricsHub) broadcast(frame *MetricsFrame) {
	b, err := json.Marshal(frame)
	if err != nil {
		return
	}
	h.mu.RLock()
	defer h.mu.RUnlock()
	for client := range h.clients {
		select {
		case client.send <- b:
		default: // slow client — skip frame, never block the hot path
		}
	}
}

func (h *MetricsHub) buildFrame(eventType, stateLabel, chain, txHash string, gross, fee, net *big.Int, bps int64, tier string) *MetricsFrame {
	h.feeMu.Lock()
	accFee := new(big.Int).Set(h.accumulatedFee)
	h.feeMu.Unlock()

	f := &MetricsFrame{
		Type:           eventType,
		TimestampMS:    time.Now().UnixMilli(),
		TotalBridges:   h.totalBridges.Load(),
		TPS:            h.rollingTPS(),
		AccumulatedFee: accFee.String(),
		StateLabel:     stateLabel,
		Chain:          chain,
		TxHash:         txHash,
		EffectiveBPS:   bps,
		AgentTier:      tier,
	}
	if gross != nil {
		f.GrossAmount = gross.String()
	}
	if fee != nil {
		f.FeeAmount = fee.String()
	}
	if net != nil {
		f.NetAmount = net.String()
	}
	return f
}

// recordTPS adds a timestamp to the rolling window.
func (h *MetricsHub) recordTPS() {
	h.tpsMu.Lock()
	defer h.tpsMu.Unlock()
	now := time.Now()
	h.tpsTimes = append(h.tpsTimes, now)
	// Purge entries older than 60 s
	cutoff := now.Add(-60 * time.Second)
	i := 0
	for i < len(h.tpsTimes) && h.tpsTimes[i].Before(cutoff) {
		i++
	}
	h.tpsTimes = h.tpsTimes[i:]
}

// rollingTPS computes transactions/second over the last 60-second window.
func (h *MetricsHub) rollingTPS() float64 {
	h.tpsMu.Lock()
	defer h.tpsMu.Unlock()
	n := len(h.tpsTimes)
	if n == 0 {
		return 0
	}
	window := 60.0 // seconds
	return float64(n) / window
}

func (h *MetricsHub) clientCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}
