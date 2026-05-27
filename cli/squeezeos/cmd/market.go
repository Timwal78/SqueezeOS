package cmd

import (
	"fmt"

	"github.com/spf13/cobra"
	"github.com/timwal78/squeezeos-pp-cli/internal"
)

var demoCmd = &cobra.Command{
	Use:   "demo",
	Short: "Free IWM council verdict — no payment required",
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Println("GET /api/demo/council")
			return nil
		}
		c := internal.NewClient()
		res, err := c.Get("/api/demo/council")
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var previewCmd = &cobra.Command{
	Use:   "preview <symbol>",
	Short: "Bias + regime preview for any symbol (free, 15-min cache)",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Printf("GET /api/preview/%s\n", args[0])
			return nil
		}
		c := internal.NewClient()
		res, err := c.Get("/api/preview/" + args[0])
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var councilCmd = &cobra.Command{
	Use:   "council <symbol>",
	Short: "Multi-engine AI verdict — 0.10 RLUSD (requires SQUEEZEOS_TOKEN)",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Printf("POST /api/council {symbol: %q}\n", args[0])
			return nil
		}
		c := internal.NewClient()
		if c.Token == "" {
			internal.Fatalf("SQUEEZEOS_TOKEN is required\nGet a token at https://four02proof.onrender.com")
		}
		res, err := c.Post("/api/council", map[string]string{"symbol": args[0]})
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var scanCmd = &cobra.Command{
	Use:   "scan",
	Short: "Full $1-$50 squeeze scanner — 0.05 RLUSD (requires SQUEEZEOS_TOKEN)",
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Println("GET /api/scan")
			return nil
		}
		c := internal.NewClient()
		if c.Token == "" {
			internal.Fatalf("SQUEEZEOS_TOKEN is required")
		}
		res, err := c.Get("/api/scan")
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var optionsCmd = &cobra.Command{
	Use:   "options",
	Short: "Institutional options flow — 0.05 RLUSD (requires SQUEEZEOS_TOKEN)",
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Println("GET /api/options")
			return nil
		}
		c := internal.NewClient()
		if c.Token == "" {
			internal.Fatalf("SQUEEZEOS_TOKEN is required")
		}
		res, err := c.Get("/api/options")
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var iwmCmd = &cobra.Command{
	Use:   "iwm",
	Short: "IWM 0DTE contract scorer — 0.03 RLUSD (requires SQUEEZEOS_TOKEN)",
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Println("GET /api/iwm")
			return nil
		}
		c := internal.NewClient()
		if c.Token == "" {
			internal.Fatalf("SQUEEZEOS_TOKEN is required")
		}
		res, err := c.Get("/api/iwm")
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var historyCmd = &cobra.Command{
	Use:   "history [symbol]",
	Short: "Signal history — all recent or per-symbol (free)",
	Args:  cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		path := "/api/history"
		if len(args) == 1 {
			path = "/api/history/" + args[0]
		}
		if dryRun {
			fmt.Printf("GET %s\n", path)
			return nil
		}
		c := internal.NewClient()
		res, err := c.Get(path)
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "System health and uptime",
	RunE: func(cmd *cobra.Command, args []string) error {
		if dryRun {
			fmt.Println("GET /api/status")
			return nil
		}
		c := internal.NewClient()
		res, err := c.Get("/api/status")
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}
