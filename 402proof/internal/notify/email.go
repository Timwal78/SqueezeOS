// Package notify sends email receipts on verified payments.
// Uses net/smtp — no external deps. Fires in a goroutine, never blocks.
//
// Env vars:
//   SMTP_HOST     — e.g. smtp.gmail.com
//   SMTP_PORT     — e.g. 587
//   SMTP_USER     — sending address / Gmail account
//   SMTP_PASS     — app password (not your Gmail login password)
//   NOTIFY_EMAIL  — where to send receipts (defaults to SMTP_USER)
package notify

import (
	"crypto/tls"
	"fmt"
	"log"
	"net"
	"net/smtp"
	"os"
	"strings"
	"time"
)

type Config struct {
	Host    string
	Port    string
	User    string
	Pass    string
	To      string
	Enabled bool
}

func LoadConfig() Config {
	host := os.Getenv("SMTP_HOST")
	user := os.Getenv("SMTP_USER")
	pass := os.Getenv("SMTP_PASS")
	to   := os.Getenv("NOTIFY_EMAIL")
	port := os.Getenv("SMTP_PORT")

	if to == "" {
		to = user
	}
	if port == "" {
		port = "587"
	}

	return Config{
		Host:    host,
		Port:    port,
		User:    user,
		Pass:    pass,
		To:      to,
		Enabled: host != "" && user != "" && pass != "",
	}
}

type Receipt struct {
	ID          string
	InvoiceID   string
	EndpointID  string
	EndpointPath string
	Amount      string
	Asset       string
	TxHash      string
	AgentWallet string
	AgentDomain string
	RiskLevel   string
	SettledAt   time.Time
}

// SendReceipt fires asynchronously — payment flow is never delayed.
func SendReceipt(cfg Config, r Receipt) {
	if !cfg.Enabled {
		return
	}
	go func() {
		if err := sendEmail(cfg, r); err != nil {
			log.Printf("[NOTIFY] email failed receipt=%s: %v", r.ID, err)
		} else {
			log.Printf("[NOTIFY] receipt email sent → %s", cfg.To)
		}
	}()
}

func sendEmail(cfg Config, r Receipt) error {
	subject := fmt.Sprintf("💰 Payment received — %s %s on %s", r.Amount, r.Asset, r.EndpointPath)

	body := fmt.Sprintf(`402Proof Payment Receipt
========================

Receipt ID:   %s
Endpoint:     %s
Amount:       %s %s
TX Hash:      %s
Agent Wallet: %s
Agent Domain: %s
Risk Level:   %s
Settled:      %s

View receipt: https://four02proof.onrender.com/v1/receipt/%s

— 402Proof Compliance Firewall`,
		r.ID,
		r.EndpointPath,
		r.Amount, r.Asset,
		r.TxHash,
		r.AgentWallet,
		r.AgentDomain,
		r.RiskLevel,
		r.SettledAt.UTC().Format("2006-01-02 15:04:05 UTC"),
		r.ID,
	)

	msg := strings.Join([]string{
		"From: 402Proof <" + cfg.User + ">",
		"To: " + cfg.To,
		"Subject: " + subject,
		"MIME-Version: 1.0",
		"Content-Type: text/plain; charset=UTF-8",
		"",
		body,
	}, "\r\n")

	addr := net.JoinHostPort(cfg.Host, cfg.Port)
	auth := smtp.PlainAuth("", cfg.User, cfg.Pass, cfg.Host)

	// TLS (port 465) vs STARTTLS (port 587)
	if cfg.Port == "465" {
		tlsCfg := &tls.Config{ServerName: cfg.Host}
		conn, err := tls.Dial("tcp", addr, tlsCfg)
		if err != nil {
			return err
		}
		client, err := smtp.NewClient(conn, cfg.Host)
		if err != nil {
			return err
		}
		defer client.Close()
		if err = client.Auth(auth); err != nil {
			return err
		}
		if err = client.Mail(cfg.User); err != nil {
			return err
		}
		if err = client.Rcpt(cfg.To); err != nil {
			return err
		}
		w, err := client.Data()
		if err != nil {
			return err
		}
		_, err = fmt.Fprint(w, msg)
		if err != nil {
			return err
		}
		return w.Close()
	}

	// Default: STARTTLS port 587
	return smtp.SendMail(addr, auth, cfg.User, []string{cfg.To}, []byte(msg))
}
