package firewall

import (
	"errors"
	"fmt"
	"strings"

	"proof402/internal/models"
)

// Check evaluates the firewall policy. Returns nil to allow, error to block.
func Check(policy *models.Policy, agent *models.Agent, inv *models.Invoice, dailyCalls int) error {
	if policy == nil {
		return nil
	}

	if agent.IsBlocked {
		return fmt.Errorf("agent blocked: %s", agent.BlockReason)
	}

	if policy.RequireKYB && agent.KYBTier == "none" {
		return errors.New("endpoint requires KYB verification")
	}

	if policy.BlockHighRisk && agent.RiskScore >= 70 {
		return fmt.Errorf("risk score too high: %.0f/100", agent.RiskScore)
	}

	if policy.RequireKnownAgent && agent.TotalCalls == 0 {
		return errors.New("endpoint requires established agent history")
	}

	if policy.MaxDailyCallsPerAgent > 0 && dailyCalls >= policy.MaxDailyCallsPerAgent {
		return fmt.Errorf("daily call limit reached (%d)", policy.MaxDailyCallsPerAgent)
	}

	if len(policy.AllowedAssets) > 0 && !containsCI(policy.AllowedAssets, inv.Asset) {
		return fmt.Errorf("asset %s not allowed for this endpoint", inv.Asset)
	}

	return nil
}

func containsCI(list []string, val string) bool {
	for _, item := range list {
		if strings.EqualFold(item, val) {
			return true
		}
	}
	return false
}
