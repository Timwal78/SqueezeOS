package toll

import (
	"math/big"
	"sync"
)

// ── Agent Loyalty Matrix ─────────────────────────────────────────────────────
// Sovereign fee discount system. Agents earn lower basis-point fees as their
// cumulative bridge volume grows. Tiers are permanent and non-reversible.
//
// Tier thresholds are in raw drops/wei (same unit as gross_amount).
// This avoids any floating-point imprecision in the critical fee path.

type LoyaltyTier struct {
	Name        string
	MinVolume   *big.Int // cumulative gross volume required to unlock
	DiscountBPS int64    // basis points REMOVED from the requested fee
	// e.g. DiscountBPS=10 on a 50 BPS request → effective 40 BPS
}

// tiers are evaluated in descending order — highest threshold wins.
var loyaltyTiers = []LoyaltyTier{
	{Name: "DIAMOND", MinVolume: new(big.Int).Mul(big.NewInt(1_000_000_000), big.NewInt(1_000_000)), DiscountBPS: 30},
	{Name: "PLATINUM", MinVolume: new(big.Int).Mul(big.NewInt(100_000_000), big.NewInt(1_000_000)), DiscountBPS: 20},
	{Name: "GOLD", MinVolume: new(big.Int).Mul(big.NewInt(10_000_000), big.NewInt(1_000_000)), DiscountBPS: 10},
	{Name: "SILVER", MinVolume: new(big.Int).Mul(big.NewInt(1_000_000), big.NewInt(1_000_000)), DiscountBPS: 5},
	{Name: "BRONZE", MinVolume: big.NewInt(0), DiscountBPS: 0},
}

// AgentLedger tracks per-agent cumulative volume and resolved tier.
type AgentLedger struct {
	mu      sync.RWMutex
	agents  map[string]*agentRecord
}

type agentRecord struct {
	TotalVolume *big.Int
	Tier        string
}

// NewAgentLedger returns an in-memory sovereign agent registry.
// In production, seed this from a persistent store on startup.
func NewAgentLedger() *AgentLedger {
	return &AgentLedger{agents: make(map[string]*agentRecord)}
}

// RecordVolume atomically adds grossAmount to the agent's lifetime volume,
// re-evaluates their tier, and returns the new tier name.
func (l *AgentLedger) RecordVolume(agentAddr string, grossAmount *big.Int) string {
	l.mu.Lock()
	defer l.mu.Unlock()

	rec, ok := l.agents[agentAddr]
	if !ok {
		rec = &agentRecord{TotalVolume: new(big.Int), Tier: "BRONZE"}
		l.agents[agentAddr] = rec
	}
	rec.TotalVolume.Add(rec.TotalVolume, grossAmount)
	rec.Tier = resolveTier(rec.TotalVolume)
	return rec.Tier
}

// EffectiveBPS returns the post-discount basis points for the given agent.
// Always enforces a floor of 1 BPS to prevent zero-fee routing.
func (l *AgentLedger) EffectiveBPS(agentAddr string, requestedBPS int64) int64 {
	l.mu.RLock()
	rec, ok := l.agents[agentAddr]
	l.mu.RUnlock()

	if !ok {
		return requestedBPS // no history → no discount
	}
	tier := resolveTier(rec.TotalVolume)
	discount := discountForTier(tier)
	effective := requestedBPS - discount
	if effective < 1 {
		effective = 1 // fee invariant: never route for free
	}
	return effective
}

// AgentStats returns the current tier and total volume for an agent.
func (l *AgentLedger) AgentStats(agentAddr string) (tier string, volume *big.Int) {
	l.mu.RLock()
	defer l.mu.RUnlock()

	rec, ok := l.agents[agentAddr]
	if !ok {
		return "BRONZE", big.NewInt(0)
	}
	return resolveTier(rec.TotalVolume), new(big.Int).Set(rec.TotalVolume)
}

// ── internal helpers ─────────────────────────────────────────────────────────

func resolveTier(volume *big.Int) string {
	for _, t := range loyaltyTiers {
		if volume.Cmp(t.MinVolume) >= 0 {
			return t.Name
		}
	}
	return "BRONZE"
}

func discountForTier(tier string) int64 {
	for _, t := range loyaltyTiers {
		if t.Name == tier {
			return t.DiscountBPS
		}
	}
	return 0
}

// CalculateLoyaltyFee is the loyalty-aware replacement for CalculateBasisPointFee.
// It looks up the agent's tier discount, applies it, then delegates to the base calculator.
func (l *AgentLedger) CalculateLoyaltyFee(agentAddr, amountStr string, requestedBPS int64) (*big.Int, *big.Int, int64, string, error) {
	effectiveBPS := l.EffectiveBPS(agentAddr, requestedBPS)
	tier, _ := l.AgentStats(agentAddr)
	fee, net, err := CalculateBasisPointFee(amountStr, effectiveBPS)
	return fee, net, effectiveBPS, tier, err
}
