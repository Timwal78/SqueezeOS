package models

import "time"

type Invoice struct {
	ID         string     `json:"id"`
	EndpointID string     `json:"endpoint_id"`
	MerchantID string     `json:"merchant_id"`
	Path       string     `json:"path"`
	Price      string     `json:"price"`
	Asset      string     `json:"asset"`
	Network    string     `json:"network"`
	PayTo      string     `json:"pay_to"`
	MemoHex    string     `json:"memo_hex"`
	ExpiresAt  time.Time  `json:"expires_at"`
	CreatedAt  time.Time  `json:"created_at"`
	Status     string     `json:"status"`
	PaidAt     *time.Time `json:"paid_at,omitempty"`
	AgentWallet string   `json:"agent_wallet,omitempty"`
	TxHash     string     `json:"tx_hash,omitempty"`
}

type Receipt struct {
	ID             string    `json:"id"`
	InvoiceID      string    `json:"invoice_id"`
	AgentWallet    string    `json:"agent_wallet"`
	AgentDomain    string    `json:"agent_domain"`
	EndpointID     string    `json:"endpoint_id"`
	MerchantID     string    `json:"merchant_id"`
	Path           string    `json:"path"`
	Amount         string    `json:"amount"`
	Asset          string    `json:"asset"`
	TxHash         string    `json:"tx_hash"`
	SettledAt      time.Time `json:"settled_at"`
	RiskLevel      string    `json:"risk_level"`
	SanctionsCheck string    `json:"sanctions_check"`
	AccessToken    string    `json:"access_token,omitempty"`
}

type Agent struct {
	Wallet      string    `json:"wallet"`
	Domain      string    `json:"domain"`
	FirstSeen   time.Time `json:"first_seen"`
	LastSeen    time.Time `json:"last_seen"`
	TotalCalls  int64     `json:"total_calls"`
	TotalSpend  string    `json:"total_spend"`
	RiskScore   float64   `json:"risk_score"`
	KYBTier     string    `json:"kyb_tier"`
	IsBlocked   bool      `json:"is_blocked"`
	BlockReason string    `json:"block_reason,omitempty"`
	Tags        []string  `json:"tags"`
}

type Endpoint struct {
	ID          string    `json:"id"`
	MerchantID  string    `json:"merchant_id"`
	Path        string    `json:"path"`
	Price       string    `json:"price"`
	Asset       string    `json:"asset"`
	Description string    `json:"description"`
	Active      bool      `json:"active"`
	CreatedAt   time.Time `json:"created_at"`
	TotalCalls  int64     `json:"total_calls"`
	TotalEarned string    `json:"total_earned"`
}

type Policy struct {
	EndpointID            string   `json:"endpoint_id"`
	MaxDailyCallsPerAgent int      `json:"max_daily_calls_per_agent"`
	RequireKYB            bool     `json:"require_kyb"`
	BlockHighRisk         bool     `json:"block_high_risk"`
	AllowedAssets         []string `json:"allowed_assets"`
	BlockedCountries      []string `json:"blocked_countries"`
	RequireKnownAgent     bool     `json:"require_known_agent"`
}

type Merchant struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	Email     string    `json:"email"`
	APIKey    string    `json:"api_key"`
	Plan      string    `json:"plan"`
	CreatedAt time.Time `json:"created_at"`
}
