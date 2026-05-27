package cmd

import (
	"fmt"
	"strconv"

	"github.com/spf13/cobra"
	"github.com/timwal78/tipmaster-pp-cli/internal"
)

// ── resolve ───────────────────────────────────────────────────────────────────

var resolveCmd = &cobra.Command{
	Use:   "resolve <farcaster-username>",
	Short: "Resolve a Farcaster username to their XRPL wallet address",
	Args:  cobra.ExactArgs(1),
	Example: `  tipmaster resolve vitalik
  tipmaster resolve dwr --compact`,
	RunE: func(cmd *cobra.Command, args []string) error {
		path := "/api/resolve/" + args[0]
		if _, err := fmt.Fprintf(cmd.OutOrStdout(), ""); err != nil {
			return err
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

// ── leaderboard ───────────────────────────────────────────────────────────────

var (
	lbPeriod string
	lbLimit  int
)

var leaderboardCmd = &cobra.Command{
	Use:   "leaderboard",
	Short: "Top tippers by RLUSD volume",
	Example: `  tipmaster leaderboard
  tipmaster leaderboard --period alltime --limit 25`,
	RunE: func(cmd *cobra.Command, args []string) error {
		path := fmt.Sprintf("/api/leaderboard?period=%s&limit=%d", lbPeriod, lbLimit)
		c := internal.NewClient()
		res, err := c.Get(path)
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

// ── user ─────────────────────────────────────────────────────────────────────

var userCmd = &cobra.Command{
	Use:   "user <fid>",
	Short: "Look up a Farcaster user by FID — returns wallet and activation status",
	Args:  cobra.ExactArgs(1),
	Example: `  tipmaster user 12345`,
	RunE: func(cmd *cobra.Command, args []string) error {
		fid, err := strconv.Atoi(args[0])
		if err != nil {
			internal.Fatalf("FID must be a number, got %q", args[0])
		}
		path := fmt.Sprintf("/api/user/%d", fid)
		c := internal.NewClient()
		res, err2 := c.Get(path)
		if err2 != nil {
			internal.Fatalf("%v", err2)
		}
		internal.Print(res, compact)
		return nil
	},
}

// ── status ────────────────────────────────────────────────────────────────────

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "TipMaster service health and feature flags",
	RunE: func(cmd *cobra.Command, args []string) error {
		c := internal.NewClient()
		res, err := c.Get("/api/status")
		if err != nil {
			internal.Fatalf("%v", err)
		}
		internal.Print(res, compact)
		return nil
	},
}

func init() {
	leaderboardCmd.Flags().StringVar(&lbPeriod, "period", "week", "week or alltime")
	leaderboardCmd.Flags().IntVar(&lbLimit, "limit", 10, "number of results (max 25)")
}
