package fix

import (
	"bytes"
	"fmt"
	"time"
)

// ExecutionTelemetry represents the internal SqueezeOS execution data
type ExecutionTelemetry struct {
	ClientOrderID   string
	Symbol          string
	Qty             float64
	TriggerPrice    float64
	CertID          string
	AlphaRetained   float64
	Timestamp       int64
}

// EncodeExecutionReport serializes the telemetry into a compliant FIX 4.4 message
func EncodeExecutionReport(sender, target string, data ExecutionTelemetry) string {
	var body bytes.Buffer
	soh := "\x01"

	// 1. Construct Body Fields
	body.WriteString(fmt.Sprintf("35=8%s", soh)) // MsgType = Execution Report
	body.WriteString(fmt.Sprintf("49=%s%s", sender, soh))
	body.WriteString(fmt.Sprintf("56=%s%s", target, soh))
	body.WriteString(fmt.Sprintf("34=1%s", soh)) // Dummy SeqNum
	body.WriteString(fmt.Sprintf("52=%s%s", time.Now().UTC().Format("20060102-15:04:05"), soh))
	body.WriteString(fmt.Sprintf("11=%s%s", data.ClientOrderID, soh))
	body.WriteString(fmt.Sprintf("17=%s%s", data.CertID, soh))
	body.WriteString(fmt.Sprintf("37=%s%s", data.CertID, soh)) // OrderID mirrors CertID
	body.WriteString(fmt.Sprintf("39=2%s", soh))              // OrdStatus = Filled
	body.WriteString(fmt.Sprintf("55=%s%s", data.Symbol, soh))
	body.WriteString(fmt.Sprintf("38=%.4f%s", data.Qty, soh))
	body.WriteString(fmt.Sprintf("44=%.2f%s", data.TriggerPrice, soh))
	body.WriteString(fmt.Sprintf("60=%s%s", time.Unix(data.Timestamp, 0).UTC().Format("20060102-15:04:05"), soh))
	body.WriteString(fmt.Sprintf("58=AlphaRetained:%.2f%%%s", data.AlphaRetained, soh)) // Custom telemetry note

	bodyStr := body.String()

	// 2. Construct Header Fields (Prefixing the Body)
	var header bytes.Buffer
	header.WriteString(fmt.Sprintf("8=FIX.4.4%s", soh))
	header.WriteString(fmt.Sprintf("9=%d%s", len(bodyStr), soh)) // Tag 9 BodyLength

	fullMessageBeforeChecksum := header.String() + bodyStr

	// 3. Calculate Modulo-256 Checksum
	var checksum int
	for i := 0; i < len(fullMessageBeforeChecksum); i++ {
		checksum += int(fullMessageBeforeChecksum[i])
	}
	checksum = checksum % 256

	// 4. Append Trailer
	return fmt.Sprintf("%s10=%03d%s", fullMessageBeforeChecksum, checksum, soh)
}
