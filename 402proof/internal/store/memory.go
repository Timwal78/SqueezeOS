package store

import (
	"fmt"
	"sync"
	"time"

	"proof402/internal/models"
)

type Memory struct {
	mu sync.RWMutex

	invoices     map[string]*models.Invoice
	receipts     map[string]*models.Receipt
	agents       map[string]*models.Agent
	endpoints    map[string]*models.Endpoint
	policies     map[string]*models.Policy
	merchants    map[string]*models.Merchant
	usedTxHashes map[string]struct{}

	dailyCalls map[string]int
	dailyDate  string
	totalCalls int64
}

func NewMemory() *Memory {
	return &Memory{
		invoices:     make(map[string]*models.Invoice),
		receipts:     make(map[string]*models.Receipt),
		agents:       make(map[string]*models.Agent),
		endpoints:    make(map[string]*models.Endpoint),
		policies:     make(map[string]*models.Policy),
		merchants:    make(map[string]*models.Merchant),
		usedTxHashes: make(map[string]struct{}),
		dailyCalls:   make(map[string]int),
		dailyDate:    time.Now().Format("2006-01-02"),
	}
}

func (m *Memory) SaveInvoice(inv *models.Invoice) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.invoices[inv.ID] = inv
}

func (m *Memory) GetInvoice(id string) (*models.Invoice, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	inv, ok := m.invoices[id]
	return inv, ok
}

func (m *Memory) MarkInvoicePaid(id, txHash, agentWallet string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if inv, ok := m.invoices[id]; ok {
		now := time.Now()
		inv.Status = "paid"
		inv.PaidAt = &now
		inv.TxHash = txHash
		inv.AgentWallet = agentWallet
	}
}

func (m *Memory) SaveReceipt(r *models.Receipt) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.receipts[r.ID] = r
	m.totalCalls++
}

func (m *Memory) GetReceipt(id string) (*models.Receipt, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.receipts[id]
	return r, ok
}

func (m *Memory) ListRecentReceipts(limit int) []*models.Receipt {
	m.mu.RLock()
	defer m.mu.RUnlock()
	result := make([]*models.Receipt, 0, limit)
	for _, r := range m.receipts {
		result = append(result, r)
		if len(result) >= limit {
			break
		}
	}
	return result
}

func (m *Memory) GetOrCreateAgent(wallet string) *models.Agent {
	m.mu.Lock()
	defer m.mu.Unlock()
	if a, ok := m.agents[wallet]; ok {
		return a
	}
	a := &models.Agent{
		Wallet:    wallet,
		FirstSeen: time.Now(),
		KYBTier:   "none",
		Tags:      []string{},
	}
	m.agents[wallet] = a
	return a
}

func (m *Memory) GetAgent(wallet string) (*models.Agent, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	a, ok := m.agents[wallet]
	return a, ok
}

func (m *Memory) UpdateAgent(a *models.Agent) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.agents[a.Wallet] = a
}

func (m *Memory) SaveEndpoint(ep *models.Endpoint) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.endpoints[ep.ID] = ep
}

func (m *Memory) GetEndpoint(id string) (*models.Endpoint, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ep, ok := m.endpoints[id]
	return ep, ok
}

func (m *Memory) ListEndpoints(merchantID string) []*models.Endpoint {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var result []*models.Endpoint
	for _, ep := range m.endpoints {
		if merchantID == "" || ep.MerchantID == merchantID {
			result = append(result, ep)
		}
	}
	return result
}

func (m *Memory) IncrEndpointCalls(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if ep, ok := m.endpoints[id]; ok {
		ep.TotalCalls++
	}
}

func (m *Memory) SavePolicy(p *models.Policy) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.policies[p.EndpointID] = p
}

func (m *Memory) GetPolicy(endpointID string) (*models.Policy, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	p, ok := m.policies[endpointID]
	return p, ok
}

func (m *Memory) SaveMerchant(merchant *models.Merchant) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.merchants[merchant.ID] = merchant
}

func (m *Memory) GetMerchantByKey(apiKey string) (*models.Merchant, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, merchant := range m.merchants {
		if merchant.APIKey == apiKey {
			return merchant, true
		}
	}
	return nil, false
}

func (m *Memory) GetMerchant(id string) (*models.Merchant, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	merchant, ok := m.merchants[id]
	return merchant, ok
}

func (m *Memory) MarkTxUsed(txHash string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, seen := m.usedTxHashes[txHash]; seen {
		return false
	}
	m.usedTxHashes[txHash] = struct{}{}
	return true
}

func (m *Memory) dailyKey(endpointID, wallet string) string {
	return fmt.Sprintf("%s|%s", endpointID, wallet)
}

func (m *Memory) checkDay() {
	today := time.Now().Format("2006-01-02")
	if today != m.dailyDate {
		m.dailyCalls = make(map[string]int)
		m.dailyDate = today
	}
}

func (m *Memory) IncrDailyCall(endpointID, wallet string) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.checkDay()
	key := m.dailyKey(endpointID, wallet)
	m.dailyCalls[key]++
	return m.dailyCalls[key]
}

func (m *Memory) DailyCallCount(endpointID, wallet string) int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.dailyCalls[m.dailyKey(endpointID, wallet)]
}

func (m *Memory) Stats() map[string]interface{} {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return map[string]interface{}{
		"total_calls":      m.totalCalls,
		"total_receipts":   len(m.receipts),
		"unique_agents":    len(m.agents),
		"active_endpoints": len(m.endpoints),
	}
}
