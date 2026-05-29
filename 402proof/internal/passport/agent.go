package passport

import (
	"time"

	"proof402/internal/models"
)

// Score computes a risk score 0–100 for an agent. Higher = riskier.
func Score(agent *models.Agent) float64 {
	score := 0.0

	if agent.TotalCalls == 0 {
		score += 15
	}

	if !agent.LastSeen.IsZero() {
		since := time.Since(agent.LastSeen)
		if since < 2*time.Second {
			score += 25
		} else if since < 10*time.Second {
			score += 10
		}
	}

	if agent.TotalCalls > 100_000 {
		score += 10
	} else if agent.TotalCalls > 10_000 {
		score += 5
	}

	if agent.Domain == "" {
		score += 10
	}

	switch agent.KYBTier {
	case "verified":
		score -= 20
	case "basic":
		score -= 10
	}

	if score < 0 {
		score = 0
	}
	if score > 100 {
		score = 100
	}
	return score
}

func RiskLevel(score float64) string {
	switch {
	case score >= 70:
		return "HIGH"
	case score >= 40:
		return "MEDIUM"
	default:
		return "LOW"
	}
}

func UpdateAfterPayment(agent *models.Agent) {
	agent.TotalCalls++
	agent.LastSeen = time.Now()
	agent.RiskScore = Score(agent)
}
