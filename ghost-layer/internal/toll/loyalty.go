package toll

import (
	"math/big"
	"strings"
	"sync"
)

// ── Agent Loyalty Matrix ───────────────────────────────────────────────────────────────────────────────────────
type LoyaltyTier struct {
	Name        string
	MinVolume   *big.Int
	DiscountBPS int64
}

var loyaltyTiers = []LoyaltyTier{
	{Name: "DIAMOND",  MinVolume: new(big.Int).Mul(big.NewInt(1_000_000_000), big.NewInt(1_000_000)), DiscountBPS: 30},
	{Name: "PLATINUM", MinVolume: new(big.Int).Mul(big.NewInt(100_000_000),   big.NewInt(1_000_000)), DiscountBPS: 20},
	{Name: "GOLD",     MinVolume: new(big.Int).Mul(big.NewInt(10_000_000),    big.NewInt(1_000_000)), DiscountBPS: 10},
	{Name: "SILVER",   MinVolume: new(big.Int).Mul(big.NewInt(1_000_000),     big.NewInt(1_000_000)), DiscountBPS: 5},
	{Name: "BRONZE",   MinVolume: big.NewInt(0), DiscountBPS: 0},
}

// ECHOLOCK-402 behavioral tier → discount BPS.
// Mirrors loyaltyTiers so the same discount scale applies to both pathways:
// an agent earns DIAMOND discount either through cumulative volume OR behavioral intelligence.
var echolockTierBPS = map[string]int64{
	// Numeric T0–T4 labels (from ECHOLOCK-402 service)
	"T0": 0, "T1": 5, "T2": 10, "T3": 20, "T4": 30,
	// Loyalty names also accepted (from Ghost Layer x402 tokens)
	"BRONZE": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 20, "DIAMOND": 30,
}

// AgentLedger tracks per-agent cumulative volume, resolved loyalty tier,
// and ECHOLOCK behavioral tier.
type AgentLedger struct {
	mu     sync.RWMutex
	agents map[string]*agentRecord
}

type agentRecord struct {
	TotalVolume  *big.Int
	Tier         string
	EcholockTier string // behavioral tier from ECHOLOCK-402; supplements volume tier
}

func NewAgentLedger() *AgentLedger {
	return &AgentLedger{agents: make(map[string]*agentRecord)}
}

// RecordVolume adds grossAmount to lifetime volume, re-evaluates tier, returns new tier name.
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

// EffectiveBPS returns post-discount basis points, taking the best discount from
// cumulative volume tier OR ECHOLOCK behavioral tier — whichever is higher.
// Enforces a floor of 1 BPS so routing is never free.
func (l *AgentLedger) EffectiveBPS(agentAddr string, requestedBPS int64) int64 {
	l.mu.RLock()
	rec, ok := l.agents[agentAddr]
	l.mu.RUnlock()

	if !ok {
		return requestedBPS
	}

	volumeDiscount   := discountForTier(resolveTier(rec.TotalVolume))
	echolockDiscount := int64(0)
	if rec.EcholockTier != "" {
		if d, exists := echolockTierBPS[strings.ToUpper(rec.EcholockTier)]; exists {
			echolockDiscount = d
		}
	}

	discount := volumeDiscount
	if echolockDiscount > discount {
		discount = echolockDiscount
	}

	effective := requestedBPS - discount
	if effective < 1 {
		effective = 1
	}
	return effective
}

// AgentStats returns the volume-based tier and total volume for an agent.
func (l *AgentLedger) AgentStats(agentAddr string) (tier string, volume *big.Int) {
	l.mu.RLock()
	defer l.mu.RUnlock()

	rec, ok := l.agents[agentAddr]
	if !ok {
		return "BRONZE", big.NewInt(0)
	}
	return resolveTier(rec.TotalVolume), new(big.Int).Set(rec.TotalVolume)
}

// ApplyEcholockTier records the agent's ECHOLOCK behavioral tier.
// If the tier implies a higher discount than the current volume tier, it takes effect
// immediately on the next EffectiveBPS or EffectiveTierName call.
func (l *AgentLedger) ApplyEcholockTier(agentAddr, echolockTier string) {
	if echolockTier == "" || agentAddr == "" {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()

	rec, ok := l.agents[agentAddr]
	if !ok {
		rec = &agentRecord{TotalVolume: new(big.Int), Tier: "BRONZE"}
		l.agents[agentAddr] = rec
	}
	rec.EcholockTier = echolockTier
}

// EffectiveTierName returns the tier name corresponding to the highest available discount
// (max of volume tier and ECHOLOCK behavioral tier). Used when embedding tier in issued tokens.
func (l *AgentLedger) EffectiveTierName(agentAddr string) string {
	l.mu.RLock()
	rec, ok := l.agents[agentAddr]
	l.mu.RUnlock()

	if !ok {
		return "BRONZE"
	}

	volumeDiscount   := discountForTier(resolveTier(rec.TotalVolume))
	echolockDiscount := int64(0)
	if rec.EcholockTier != "" {
		if d, exists := echolockTierBPS[strings.ToUpper(rec.EcholockTier)]; exists {
			echolockDiscount = d
		}
	}

	if echolockDiscount > volumeDiscount {
		return discountBPSToName(echolockDiscount)
	}
	return discountBPSToName(volumeDiscount)
}

// CalculateLoyaltyFee is the loyalty-aware fee calculator.
func (l *AgentLedger) CalculateLoyaltyFee(agentAddr, amountStr string, requestedBPS int64) (*big.Int, *big.Int, int64, string, error) {
	effectiveBPS := l.EffectiveBPS(agentAddr, requestedBPS)
	tier          := l.EffectiveTierName(agentAddr)
	fee, net, err := CalculateBasisPointFee(amountStr, effectiveBPS)
	return fee, net, effectiveBPS, tier, err
}

// ── internal helpers ───────────────────────────────────────────────────────────────────────────────
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

// discountBPSToName maps a discount amount back to its tier name.
func discountBPSToName(bps int64) string {
	for _, t := range loyaltyTiers {
		if t.DiscountBPS == bps {
			return t.Name
		}
	}
	return "BRONZE"
}
