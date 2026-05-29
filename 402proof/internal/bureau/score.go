// Package bureau implements the Agent Credit Bureau — a queryable reputation
// layer built on top of 402Proof payment history. Scores are 300–850 (FICO-style).
// No funds are held or custodied; the bureau only reads existing agent records.
package bureau

import (
	"fmt"
	"math"
	"time"

	"proof402/internal/models"
	"proof402/internal/passport"
)

// CreditReport is the full breakdown returned to paying queriers.
type CreditReport struct {
	Wallet      string         `json:"wallet"`
	Score       int            `json:"score"`            // 300–850
	Grade       string         `json:"grade"`            // AAA / AA / A / BBB / BB / B / C / D
	LoyaltyTier string         `json:"loyalty_tier"`
	KYBTier     string         `json:"kyb_tier"`
	TotalSpend  string         `json:"total_spend_rlusd"`
	TotalCalls  int64          `json:"total_calls"`
	AccountAge  string         `json:"account_age"`
	LastActive  string         `json:"last_active"`
	RiskLevel   string         `json:"risk_level"`
	Breakdown   map[string]int `json:"breakdown"`
	IsBlocked   bool           `json:"is_blocked"`
	GeneratedAt time.Time      `json:"generated_at"`
}

// PublicScore is the free teaser returned without payment.
type PublicScore struct {
	Wallet      string    `json:"wallet"`
	Score       int       `json:"score"`
	Grade       string    `json:"grade"`
	LoyaltyTier string    `json:"loyalty_tier"`
	IsBlocked   bool      `json:"is_blocked"`
	GeneratedAt time.Time `json:"generated_at"`
}

// Compute derives a CreditReport from the agent's stored state.
// No network calls, no funds touched — pure read.
func Compute(agent *models.Agent) CreditReport {
	breakdown := map[string]int{}
	score := 300 // FICO-style base

	// ── Payment volume (0–150) ────────────────────────────────────────────────
	var callScore int
	switch {
	case agent.TotalCalls >= 1000:
		callScore = 150
	case agent.TotalCalls >= 100:
		callScore = 100
	case agent.TotalCalls >= 10:
		callScore = 50
	case agent.TotalCalls >= 1:
		callScore = 20
	}
	breakdown["payment_volume"] = callScore
	score += callScore

	// ── Spend depth (0–200) ───────────────────────────────────────────────────
	var spendScore int
	switch {
	case agent.SpendFloat >= 100:
		spendScore = 200
	case agent.SpendFloat >= 25:
		spendScore = 150
	case agent.SpendFloat >= 5:
		spendScore = 100
	case agent.SpendFloat >= 1:
		spendScore = 50
	case agent.SpendFloat > 0:
		spendScore = 20
	}
	breakdown["spend_history"] = spendScore
	score += spendScore

	// ── Account age (0–100) ───────────────────────────────────────────────────
	var ageScore int
	if !agent.FirstSeen.IsZero() {
		age := time.Since(agent.FirstSeen)
		switch {
		case age >= 90*24*time.Hour:
			ageScore = 100
		case age >= 30*24*time.Hour:
			ageScore = 75
		case age >= 7*24*time.Hour:
			ageScore = 50
		case age >= 24*time.Hour:
			ageScore = 25
		case age >= time.Hour:
			ageScore = 10
		}
	}
	breakdown["account_age"] = ageScore
	score += ageScore

	// ── KYB verification (0–100) ──────────────────────────────────────────────
	var kybScore int
	switch agent.KYBTier {
	case "verified":
		kybScore = 100
	case "basic":
		kybScore = 50
	}
	breakdown["kyb_verification"] = kybScore
	score += kybScore

	// ── Loyalty tier (0–100) ─────────────────────────────────────────────────
	var loyaltyScore int
	switch agent.LoyaltyTier {
	case "Diamond":
		loyaltyScore = 100
	case "Platinum":
		loyaltyScore = 75
	case "Gold":
		loyaltyScore = 50
	case "Silver":
		loyaltyScore = 25
	}
	breakdown["loyalty_tier"] = loyaltyScore
	score += loyaltyScore

	// ── Risk penalty (deducted) ───────────────────────────────────────────────
	riskScore := passport.Score(agent)
	riskPenalty := int(math.Round(riskScore))
	breakdown["risk_penalty"] = -riskPenalty
	score -= riskPenalty

	// ── Domain presence (+25) ────────────────────────────────────────────────
	if agent.Domain != "" {
		breakdown["domain_verified"] = 25
		score += 25
	} else {
		breakdown["domain_verified"] = 0
	}

	// ── Recency bonus (+25 if active within 7 days) ───────────────────────────
	var recencyScore int
	if !agent.LastSeen.IsZero() && time.Since(agent.LastSeen) < 7*24*time.Hour {
		recencyScore = 25
	}
	breakdown["recent_activity"] = recencyScore
	score += recencyScore

	// ── Hard cap if blocked ───────────────────────────────────────────────────
	if agent.IsBlocked && score > 200 {
		score = 200
	}

	// Clamp to 300–850
	if score < 300 {
		score = 300
	}
	if score > 850 {
		score = 850
	}

	// ── Human-readable age strings ────────────────────────────────────────────
	accountAge := "new"
	if !agent.FirstSeen.IsZero() {
		d := time.Since(agent.FirstSeen)
		if d >= 24*time.Hour {
			accountAge = fmt.Sprintf("%.0f days", d.Hours()/24)
		} else {
			accountAge = fmt.Sprintf("%.0f hours", d.Hours())
		}
	}

	lastActive := "never"
	if !agent.LastSeen.IsZero() {
		d := time.Since(agent.LastSeen)
		switch {
		case d >= 24*time.Hour:
			lastActive = fmt.Sprintf("%.0f days ago", d.Hours()/24)
		case d >= time.Hour:
			lastActive = fmt.Sprintf("%.0f hours ago", d.Hours())
		default:
			lastActive = fmt.Sprintf("%.0f min ago", d.Minutes())
		}
	}

	return CreditReport{
		Wallet:      agent.Wallet,
		Score:       score,
		Grade:       Grade(score),
		LoyaltyTier: agent.LoyaltyTier,
		KYBTier:     agent.KYBTier,
		TotalSpend:  fmt.Sprintf("%.4f", agent.SpendFloat),
		TotalCalls:  agent.TotalCalls,
		AccountAge:  accountAge,
		LastActive:  lastActive,
		RiskLevel:   passport.RiskLevel(riskScore),
		Breakdown:   breakdown,
		IsBlocked:   agent.IsBlocked,
		GeneratedAt: time.Now(),
	}
}

// Grade maps a 300–850 score to a letter grade.
func Grade(score int) string {
	switch {
	case score >= 800:
		return "AAA"
	case score >= 750:
		return "AA"
	case score >= 700:
		return "A"
	case score >= 650:
		return "BBB"
	case score >= 600:
		return "BB"
	case score >= 550:
		return "B"
	case score >= 400:
		return "C"
	default:
		return "D"
	}
}
