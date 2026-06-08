package fix

import (
	"bytes"
	"fmt"
	"time"
)

// ExecutionReport represents the fields needed for the SqueezeOS Drop-Copy FIX message.
type ExecutionReport struct {
	CertID           string
	ClientOrderID    string
	Symbol           string
	Qty              float64
	Price            float64
	AlphaRetainedPct float64
	Timestamp        int64
}

// EncodeExecutionReport transforms the JSON payload into a SOH-delimited FIX 4.4 message.
func EncodeExecutionReport(report ExecutionReport) string {
	var body bytes.Buffer

	// Hardcoded headers for SqueezeOS Drop-Copy Sender
	senderCompID := "SQUEEZEOS_PROD"
	targetCompID := "INSTITUTIONAL_PB"
	msgType := "8" // Execution Report

	// Convert Unix timestamp to strict UTC format (YYYYMMDD-HH:MM:SS)
	t := time.Unix(report.Timestamp, 0).UTC()
	transactTime := t.Format("20060102-15:04:05")
	sendingTime := time.Now().UTC().Format("20060102-15:04:05")

	// Construct Body fields (SOH separated)
	appendTag(&body, 35, msgType)
	appendTag(&body, 49, senderCompID)
	appendTag(&body, 56, targetCompID)
	appendTag(&body, 34, "1") // Dummy SeqNum for PoC
	appendTag(&body, 52, sendingTime)
	
	// Payload Fields
	appendTag(&body, 17, report.CertID)
	appendTag(&body, 11, report.ClientOrderID)
	appendTag(&body, 39, "2") // 2 = Filled
	appendTag(&body, 55, report.Symbol)
	appendTag(&body, 38, fmt.Sprintf("%.4f", report.Qty))
	appendTag(&body, 44, fmt.Sprintf("%.2f", report.Price))
	appendTag(&body, 60, transactTime)
	
	// Injecting Alpha Retained Pct into Tag 58 (Text)
	appendTag(&body, 58, fmt.Sprintf("ALPHA_RETAINED_PCT=%.2f", report.AlphaRetainedPct))

	// Calculate Body Length
	bodyStr := body.String()
	bodyLength := len(bodyStr)

	// Construct Full Message (Header + Body)
	var msg bytes.Buffer
	appendTag(&msg, 8, "FIX.4.4")
	appendTag(&msg, 9, fmt.Sprintf("%d", bodyLength))
	msg.WriteString(bodyStr)

	// Calculate Checksum over the entire message
	checksum := calculateChecksum(msg.String())
	
	// Append Checksum (Tag 10)
	appendTag(&msg, 10, checksum)

	return msg.String()
}

// appendTag appends a standard FIX tag and value followed by the SOH delimiter (\x01)
func appendTag(buf *bytes.Buffer, tag int, value string) {
	buf.WriteString(fmt.Sprintf("%d=%s\x01", tag, value))
}

// calculateChecksum computes the modulo 256 sum of all characters in the string, returned as a 3-digit string.
func calculateChecksum(msg string) string {
	sum := 0
	for _, char := range msg {
		sum += int(char)
	}
	return fmt.Sprintf("%03d", sum%256)
}
