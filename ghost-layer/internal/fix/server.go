package fix

import (
	"bufio"
	"fmt"
	"net"
	"strings"
	"sync"
)

var GlobalServer *FixServer

type FixServer struct {
	ListenAddress string
	SenderCompID  string // Expected TargetCompID from client
	TargetCompID  string // Server's ID (SenderCompID in server responses)
	OutboundQueue chan ExecutionTelemetry
	mu            sync.Mutex
	clients       map[string]net.Conn
}

func NewFixServer(addr, sender, target string) *FixServer {
	return &FixServer{
		ListenAddress: addr,
		SenderCompID:  sender,
		TargetCompID:  target,
		OutboundQueue: make(chan ExecutionTelemetry, 1000),
		clients:       make(map[string]net.Conn),
	}
}

// Start running the TCP server and listening for institutional logons
func (s *FixServer) Start() error {
	listener, err := net.Listen("tcp", s.ListenAddress)
	if err != nil {
		return err
	}
	defer listener.Close()

	// Run the broadcast loop to distribute executions asynchronously
	go s.broadcaster()

	for {
		conn, err := listener.Accept()
		if err != nil {
			continue
		}
		go s.handleClient(conn)
	}
}

// handleClient manages individual connection states and enforces the Logon sequence
func (s *FixServer) handleClient(conn net.Conn) {
	defer conn.Close()
	reader := bufio.NewReader(conn)
	soh := "\x01"

	// Enforce immediate authentication: First packet must be Logon (35=A)
	line, err := reader.ReadString('\n')
	if err != nil {
		return
	}

	// Basic parsing logic to verify session fields
	if !strings.Contains(line, "35=A") || 
	   !strings.Contains(line, fmt.Sprintf("49=%s", s.SenderCompID)) || 
	   !strings.Contains(line, fmt.Sprintf("56=%s", s.TargetCompID)) {
		// Authentication fail: Drop connection silently without leak
		return
	}

	// Send Logon Confirmation Response
	clientAddr := conn.RemoteAddr().String()
	logonAck := fmt.Sprintf("8=FIX.4.4%s9=57%s35=A%s34=1%s49=%s%s56=%s%s10=000%s\n", 
		soh, soh, soh, soh, s.TargetCompID, soh, s.SenderCompID, soh, soh)
	conn.Write([]byte(logonAck))

	// Register authenticated client to receive execution feed
	s.mu.Lock()
	s.clients[clientAddr] = conn
	s.mu.Unlock()

	// Keep connection open to monitor heartbeat or disconnection state
	for {
		_, err := reader.ReadByte()
		if err != nil {
			s.mu.Lock()
			delete(s.clients, clientAddr)
			s.mu.Unlock()
			break
		}
	}
}

// broadcaster reads from the internal telemetry queue and serializes outbound strings
func (s *FixServer) broadcaster() {
	for telemetry := range s.OutboundQueue {
		// Serialize into a raw SOH-delimited FIX execution report
		fixMessage := EncodeExecutionReport(s.TargetCompID, s.SenderCompID, telemetry) + "\n"

		s.mu.Lock()
		for addr, conn := range s.clients {
			_, err := conn.Write([]byte(fixMessage))
			if err != nil {
				conn.Close()
				delete(s.clients, addr)
			}
		}
		s.mu.Unlock()
	}
}
