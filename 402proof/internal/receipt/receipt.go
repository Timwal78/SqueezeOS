package receipt

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"proof402/internal/models"
)

func New(inv *models.Invoice, txHash, agentWallet, agentDomain, riskLevel, accessToken string) *models.Receipt {
	return &models.Receipt{
		ID:             uuid.New().String(),
		InvoiceID:      inv.ID,
		AgentWallet:    agentWallet,
		AgentDomain:    agentDomain,
		EndpointID:     inv.EndpointID,
		MerchantID:     inv.MerchantID,
		Path:           inv.Path,
		Amount:         inv.Price,
		Asset:          inv.Asset,
		TxHash:         txHash,
		SettledAt:      time.Now(),
		RiskLevel:      riskLevel,
		SanctionsCheck: "SKIPPED",
		AccessToken:    accessToken,
	}
}

func ToJSON(r *models.Receipt) ([]byte, error) {
	export := *r
	export.AccessToken = ""
	return json.MarshalIndent(export, "", "  ")
}

func ToCSV(r *models.Receipt) string {
	var sb strings.Builder
	w := csv.NewWriter(&sb)
	w.Write([]string{"receipt_id", "invoice_id", "agent_wallet", "agent_domain", "endpoint_id", "merchant_id", "path", "amount", "asset", "tx_hash", "settled_at", "risk_level", "sanctions_check"})
	w.Write([]string{r.ID, r.InvoiceID, r.AgentWallet, r.AgentDomain, r.EndpointID, r.MerchantID, r.Path, r.Amount, r.Asset, r.TxHash, r.SettledAt.Format(time.RFC3339), r.RiskLevel, r.SanctionsCheck})
	w.Flush()
	return sb.String()
}

func BulkCSV(receipts []*models.Receipt) string {
	var sb strings.Builder
	w := csv.NewWriter(&sb)
	w.Write([]string{"receipt_id", "invoice_id", "agent_wallet", "agent_domain", "endpoint_id", "merchant_id", "path", "amount", "asset", "tx_hash", "settled_at", "risk_level", "sanctions_check"})
	for _, r := range receipts {
		w.Write([]string{r.ID, r.InvoiceID, r.AgentWallet, r.AgentDomain, r.EndpointID, r.MerchantID, r.Path, r.Amount, r.Asset, r.TxHash, r.SettledAt.Format(time.RFC3339), r.RiskLevel, r.SanctionsCheck})
	}
	w.Flush()
	return sb.String()
}

func BadgeHTML(endpointID, path, serverURL string) string {
	return fmt.Sprintf(`<!-- 402Proof Badge -->
<a href="%s/badge/%s" target="_blank" style="display:inline-flex;align-items:center;gap:8px;padding:8px 16px;background:#0a0a0a;border:1px solid #7c3aed;border-radius:8px;text-decoration:none;font-family:monospace;font-size:12px;color:#a78bfa;box-shadow:0 0 12px rgba(124,58,237,0.3);">
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
  <span style="color:#e2e8f0">AI Agents Can Pay Here</span>
  <span style="color:#7c3aed;font-size:10px;">· Verified by 402Proof · XRP Ledger</span>
</a>
<!-- /402Proof Badge -->`, serverURL, endpointID)
}
