package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"log"
	"time"

	"ghost-layer-core/internal/fix"
	"ghost-layer-core/internal/x402"
)

func main() {
	log.Println("--- BOOTING GHOST LAYER NOTARY LISTENER ---")
	// Generate dummy Ed25519 key for local test
	_, privKey, _ := ed25519.GenerateKey(rand.Reader)
	
	// Initialize the strict FIX Logon drop-copy server
	fix.GlobalServer = fix.NewFixServer(":4021", "INSTITUTIONAL_PB", "SQUEEZEOS_PROD")
	go fix.GlobalServer.Start()

	// Start the listener. No real XahauClient here — this is a local test
	// harness with a throwaway in-memory keypair, so SubmitToXahau() will
	// honestly log that notarization was skipped rather than fabricate a
	// result (previously it minted a fake random "ledger hash").
	x402.StartIPCListener(privKey, nil)
	
	// Block for 15 seconds to allow Python script to connect and execute
	time.Sleep(15 * time.Second)
}
