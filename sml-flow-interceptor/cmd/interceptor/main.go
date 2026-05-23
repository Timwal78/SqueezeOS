package main

// SML Flow Interceptor — v1 Logger/Analyzer.
//
// Purpose: capture (a) decoded ERC-20 transfers on Base that match a
// watchlist, and (b) CEX ticker prints for the target instruments, into a
// single timestamped NDJSON log. Offline correlation analysis is run against
// that log to validate the directional-signal hypothesis before any execution
// path is committed.
//
// Explicitly NOT included in v1: order routing, broker auth, position
// management. Those are deferred until correlation analysis shows edge.

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"sync"
	"syscall"

	"sml-flow-interceptor/internal/base"
	"sml-flow-interceptor/internal/cex"
	"sml-flow-interceptor/internal/config"
	"sml-flow-interceptor/internal/events"
	"sml-flow-interceptor/internal/sink"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	cfg, err := config.FromEnv()
	if err != nil {
		log.Error("config load failed", "err", err)
		os.Exit(1)
	}
	log.Info("starting sml-flow-interceptor logger",
		"watched_contracts", cfg.WatchedContracts,
		"watched_counterparties_n", len(cfg.WatchedCounterparties),
		"min_value", cfg.MinTransferValue,
		"cex_products", cfg.CEXProducts,
		"event_log", cfg.EventLogPath,
		"hud_webhook_enabled", cfg.HUDWebhookURL != "",
	)

	file, err := sink.OpenFile(cfg.EventLogPath)
	if err != nil {
		log.Error("open event log failed", "err", err, "path", cfg.EventLogPath)
		os.Exit(1)
	}
	defer file.Close()

	var webhook *sink.Webhook
	if cfg.HUDWebhookURL != "" {
		webhook = sink.NewWebhook(cfg.HUDWebhookURL)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	eventCh := make(chan events.Event, 1024)

	baseClient := base.New(base.Params{
		URL:                   cfg.BaseWSURL,
		WatchedContracts:      cfg.WatchedContracts,
		WatchedCounterparties: cfg.WatchedCounterparties,
		MinValueScaled:        cfg.MinTransferValue,
		ContractDecimals:      cfg.ContractDecimals,
		Out:                   eventCh,
		Log:                   log.With("feed", "base"),
	})
	coinbaseClient := cex.NewCoinbase(
		cfg.CoinbaseWSURL,
		cfg.CEXProducts,
		eventCh,
		log.With("feed", "coinbase"),
	)

	var wg sync.WaitGroup
	wg.Add(3)
	go func() { defer wg.Done(); baseClient.Run(ctx) }()
	go func() { defer wg.Done(); coinbaseClient.Run(ctx) }()
	go func() { defer wg.Done(); consume(ctx, eventCh, file, webhook, log) }()

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigs
	log.Info("shutdown signal received", "signal", sig.String())
	cancel()
	wg.Wait()
	log.Info("clean exit")
}

// consume drains eventCh into the file sink, and forwards Base mempool hits
// to the HUD webhook. CEX ticks are intentionally not webhooked — they're
// too chatty and the HUD reads price from its own market data subscription.
func consume(
	ctx context.Context,
	in <-chan events.Event,
	file *sink.File,
	webhook *sink.Webhook,
	log *slog.Logger,
) {
	for {
		select {
		case <-ctx.Done():
			return
		case e, ok := <-in:
			if !ok {
				return
			}
			if err := file.Write(e); err != nil {
				log.Error("file sink write failed", "err", err)
			}
			if webhook != nil && e.Source == events.SourceBaseMempool {
				if err := webhook.Send(ctx, e); err != nil {
					log.Warn("hud webhook failed", "err", err)
				}
			}
		}
	}
}
