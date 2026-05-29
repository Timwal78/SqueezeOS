// Package loyalty manages agent tiers, free call credits, and milestone rewards.
//
// Tiers (by cumulative RLUSD spend):
//   Bronze  — 0.00+  RLUSD — standard pricing
//   Silver  — 1.00+  RLUSD — 1 free call per 10 paid
//   Gold    — 5.00+  RLUSD — 1 free call per 5 paid, -10 risk score
//   Platinum— 25.00+ RLUSD — 1 free call per 3 paid, -20 risk score
//   Diamond — 100.00+RLUSD — 1 free call per 2 paid, -30 risk score, VIP badge
package loyalty

import (
	"fmt"
	"strconv"

	"proof402/internal/models"
)

type Tier struct {
	Name          string
	MinSpend      float64
	FreePer       int64  // 1 free credit after every N paid calls (0 = none)
	RiskReduction float64
	Badge         string
}

var Tiers = []Tier{
	{Name: "Diamond",  MinSpend: 100.0, FreePer: 2,  RiskReduction: 30, Badge: "💎"},
	{Name: "Platinum", MinSpend: 25.0,  FreePer: 3,  RiskReduction: 20, Badge: "🏆"},
	{Name: "Gold",     MinSpend: 5.0,   FreePer: 5,  RiskReduction: 10, Badge: "🥇"},
	{Name: "Silver",   MinSpend: 1.0,   FreePer: 10, RiskReduction: 0,  Badge: "🥈"},
	{Name: "Bronze",   MinSpend: 0.0,   FreePer: 0,  RiskReduction: 0,  Badge: "🥉"},
}

func GetTier(spendRLUSD float64) Tier {
	for _, t := range Tiers {
		if spendRLUSD >= t.MinSpend {
			return t
		}
	}
	return Tiers[len(Tiers)-1]
}

// ProcessPayment updates agent loyalty state after a verified payment.
// Returns (creditsAwarded, tierChanged, newTier).
func ProcessPayment(agent *models.Agent, amountRLUSD float64) (creditsAwarded int64, tierChanged bool, newTier Tier) {
	oldTier := GetTier(agent.SpendFloat)

	agent.SpendFloat += amountRLUSD
	agent.TotalSpend = fmt.Sprintf("%.4f", agent.SpendFloat)
	agent.PaidSinceLast++

	newTier = GetTier(agent.SpendFloat)
	tierChanged = newTier.Name != oldTier.Name
	agent.LoyaltyTier = newTier.Name

	// Risk score benefit from tier
	// (passport.Score is applied separately; loyalty reduces the baseline)

	// Award free credit if milestone hit
	if newTier.FreePer > 0 && agent.PaidSinceLast >= newTier.FreePer {
		agent.FreeCredits++
		agent.PaidSinceLast = 0
		creditsAwarded = 1
	}

	return creditsAwarded, tierChanged, newTier
}

// RedeemCredit burns 1 free credit. Returns false if none available.
func RedeemCredit(agent *models.Agent) bool {
	if agent.FreeCredits <= 0 {
		return false
	}
	agent.FreeCredits--
	return true
}

// Summary returns a human-readable loyalty status for the agent.
func Summary(agent *models.Agent) map[string]interface{} {
	t := GetTier(agent.SpendFloat)
	progress := progressToNext(agent.SpendFloat)

	return map[string]interface{}{
		"wallet":          agent.Wallet,
		"tier":            t.Name,
		"badge":           t.Badge,
		"total_spend":     fmt.Sprintf("%.4f RLUSD", agent.SpendFloat),
		"total_calls":     agent.TotalCalls,
		"free_credits":    agent.FreeCredits,
		"risk_reduction":  t.RiskReduction,
		"free_per_n_paid": t.FreePer,
		"paid_since_last_credit": agent.PaidSinceLast,
		"next_tier":       progress,
	}
}

func progressToNext(spend float64) map[string]interface{} {
	for i, t := range Tiers {
		if spend < t.MinSpend && i < len(Tiers)-1 {
			continue
		}
		if i == 0 {
			return map[string]interface{}{"tier": "Diamond", "status": "MAX TIER"}
		}
		next := Tiers[i-1]
		remaining := next.MinSpend - spend
		return map[string]interface{}{
			"tier":      next.Name,
			"badge":     next.Badge,
			"spend_needed": strconv.FormatFloat(remaining, 'f', 4, 64) + " RLUSD",
		}
	}
	return map[string]interface{}{"tier": "Silver", "spend_needed": "1.0000 RLUSD"}
}
