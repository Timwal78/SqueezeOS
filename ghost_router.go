package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

type TVPayload struct {
	System    string `json:"system"`
	Ticker    string `json:"ticker"`
	Action    string `json:"action"`
	Timestamp int64  `json:"timestamp"`
}

type FrontendTarget struct {
	Symbol     string  `json:"symbol"`
	Matrix     string  `json:"matrix"`
	Action     string  `json:"action"`
	WireStatus string  `json:"wire_status,omitempty"`
	Deviation  float64 `json:"deviation,omitempty"`
}

type FrontendResponse struct {
	ScanTime string           `json:"scan_time"`
	Targets  []FrontendTarget `json:"targets"`
}

var (
	stateMutex    sync.RWMutex
	activeTargets = make(map[string]FrontendTarget)
	ctx           = context.Background()
	redisClient   *redis.Client
)

func init() {
	redisURL := os.Getenv("UPSTASH_REDIS_URL")
	redisPass := os.Getenv("UPSTASH_PASSWORD")
	if redisURL != "" {
		redisClient = redis.NewClient(&redis.Options{
			Addr:     redisURL,
			Password: redisPass,
			DB:       0,
		})
		fmt.Println("[SYSTEM] Upstash Redis Vault Initialized.")
	} else {
		fmt.Println("[WARNING] UPSTASH_REDIS_URL environment variable missing. Vault writes will be bypassed.")
	}
}

func main() {
	http.HandleFunc("/tv-webhook", handleTVWebhook)
	http.HandleFunc("/api/scan", handleScanAPI)
	fmt.Println("[SYSTEM] SML Ghost Router Active on Port 8080.")
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func handleTVWebhook(w http.ResponseWriter, r *http.Request) {
	var p TVPayload
	err := json.NewDecoder(r.Body).Decode(&p)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	fmt.Printf("\n[MATRIX SNAP] %s triggered on %s\n", p.Action, p.Ticker)

	updateMonitorState(p)
	go updateSharedVault(p)
	go executeInternalTradier(p)

	w.WriteHeader(http.StatusOK)
}

func updateSharedVault(p TVPayload) {
	if redisClient == nil {
		return
	}
	payloadBytes, err := json.Marshal(p)
	if err != nil {
		fmt.Printf("[VAULT ERROR] Failed to marshal payload: %v\n", err)
		return
	}
	err = redisClient.Set(ctx, "SML:ACTIVE_TARGET", payloadBytes, 0).Err()
	if err != nil {
		fmt.Printf("[VAULT ERROR] Failed to write to Upstash: %v\n", err)
		return
	}
	fmt.Printf("[VAULT SECURED] %s Leviathan payload pushed to Upstash Redis. Available for API extraction.\n", p.Ticker)
}

func updateMonitorState(p TVPayload) {
	stateMutex.Lock()
	defer stateMutex.Unlock()
	uiAction := "CALL"
	wireStatus := "crossing_up"
	if p.Action == "EXECUTE_SHORT" {
		uiAction = "PUT"
		wireStatus = "crossing_down"
	}
	matrixType := "leviathan"
	if p.System == "SML_FTD_Hunter" {
		matrixType = "ftd"
	}
	activeTargets[p.Ticker] = FrontendTarget{
		Symbol:     p.Ticker,
		Matrix:     matrixType,
		Action:     uiAction,
		WireStatus: wireStatus,
	}
}

func handleScanAPI(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	w.Header().Set("Content-Type", "application/json")
	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}
	stateMutex.RLock()
	targets := make([]FrontendTarget, 0, len(activeTargets))
	for _, t := range activeTargets {
		targets = append(targets, t)
	}
	stateMutex.RUnlock()
	resp := FrontendResponse{
		ScanTime: time.Now().UTC().Format(time.RFC3339),
		Targets:  targets,
	}
	json.NewEncoder(w).Encode(resp)
}

func executeInternalTradier(p TVPayload) {
	fmt.Printf("[INTERNAL] Evaluating %s routing via BYOK Tradier configuration...\n", p.Ticker)
}
