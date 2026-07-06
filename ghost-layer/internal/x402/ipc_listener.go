package x402

import (
	"bytes"
	"crypto/ed25519"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"runtime"

	"ghost-layer-core/internal/chain"
	"ghost-layer-core/internal/fix"
)

// ExecutionPayload must mirror the Python struct layout exactly (48 bytes, LittleEndian)
type ExecutionPayload struct {
	Timestamp       int64   // 8 bytes
	Qty             int64   // 8 bytes
	LimitPrice      float64 // 8 bytes
	DynamicDiscount float64 // 8 bytes
	Symbol          [8]byte // 8 bytes
	Directive       [8]byte // 8 bytes
}

// StartIPCListener boots the OS-gated socket listener for Python payloads.
// xahauClient may be nil when Xahau isn't configured on this deployment —
// decisions are still hashed and signed, but SubmitToXahau() will log that
// notarization was skipped rather than fabricate a result (see notary.go).
func StartIPCListener(privKey ed25519.PrivateKey, xahauClient *chain.XahauClient) {
	var listener net.Listener
	var err error

	if runtime.GOOS == "windows" {
		listener, err = net.Listen("tcp", "127.0.0.1:4020")
		log.Println("[402PROOF] IPC Listener active on Windows TCP Loopback (127.0.0.1:4020)")
	} else {
		os.Remove("/tmp/x402_notary.sock")
		listener, err = net.Listen("unix", "/tmp/x402_notary.sock")
		log.Println("[402PROOF] IPC Listener active on Linux Unix Domain Socket (/tmp/x402_notary.sock)")
	}

	if err != nil {
		log.Fatalf("Failed to start IPC listener: %v", err)
	}

	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				continue
			}
			go handleConnection(conn, privKey, xahauClient)
		}
	}()
}

func handleConnection(conn net.Conn, priv ed25519.PrivateKey, xahauClient *chain.XahauClient) {
	defer conn.Close()
	var payload ExecutionPayload

	for {
		// Read directly from the socket stream into the struct memory layout
		err := binary.Read(conn, binary.LittleEndian, &payload)
		if err == io.EOF {
			break // Connection closed cleanly by Python backend
		}
		if err != nil {
			log.Printf("[402PROOF] IPC Read Error: %v\n", err)
			return
		}

		// Strip null padding from 8-byte arrays
		symbol := string(bytes.Trim(payload.Symbol[:], "\x00"))
		directive := string(bytes.Trim(payload.Directive[:], "\x00"))

		// Construct decision hash representation for the attestation
		decisionHash := fmt.Sprintf("EXEC_%s_%s_%d", directive, symbol, payload.Timestamp)

		// Ask Notary to mint the certificate
		// Ghost Layer asynchronous ledger stub for Phase 2: XahauTx remains blank
		cert, err := SignDecision(
			decisionHash,
			"", // xahauTx
			"rHxGhostWallet",
			"SqueezeOS_Engine7",
			"core/engine7_parabolic",
			"TIER_1",
			"SOVEREIGN",
			priv,
		)

		if err != nil {
			log.Printf("[402PROOF] Failed to mint certificate: %v\n", err)
			return
		}

		// Dispatch the real Xahau mint asynchronously — keeps the 0.43 ms IPC
		// loop non-blocking regardless of Xahau's ledger confirmation time.
		// See SubmitToXahau's doc comment: this no longer fabricates a result.
		go SubmitToXahau(cert, xahauClient)

		// Dispatch to the Drop-Copy FIX stream asynchronously via the OutboundQueue
		if fix.GlobalServer != nil {
			fix.GlobalServer.OutboundQueue <- fix.ExecutionTelemetry{
				CertID:        cert.CertificateID,
				ClientOrderID: fmt.Sprintf("EX-%d", payload.Timestamp),
				Symbol:        symbol,
				Qty:           float64(payload.Qty),
				TriggerPrice:  payload.LimitPrice,
				AlphaRetained: payload.DynamicDiscount,
				Timestamp:     payload.Timestamp,
			}
		}

		// Blast 80 raw bytes back to Python: 16 byte Cert ID string (padded) + 64 byte raw signature
		rawSig, _ := hex.DecodeString(cert.Signature)

		// Ensure CertificateID is exactly 16 bytes for word alignment
		certBytes := []byte(cert.CertificateID)
		if len(certBytes) > 16 {
			certBytes = certBytes[:16]
		} else if len(certBytes) < 16 {
			pad := make([]byte, 16-len(certBytes))
			certBytes = append(certBytes, pad...)
		}

		outBuf := append(certBytes, rawSig...)
		conn.Write(outBuf)
	}
}
