package chain

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"strings"
	"sync"
	"time"

	gocrypto "github.com/ethereum/go-ethereum/crypto"
	"golang.org/x/crypto/ripemd160"
)

const xrplAlphabet = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"

const (
	XRPLBaseReserveDrops uint64 = 10_000_000
	XRPLSweepBufferDrops uint64 = 500_000
	xrplDefaultFeeDrops  uint64 = 12
	xrplMaxFeeDrops      uint64 = 1_000
)

// XRPLClient signs and submits payments from the gateway XRPL wallet.
type XRPLClient struct {
	RPCURL         string
	GatewayAddress string
	httpClient     *http.Client
	privKey        *ecdsa.PrivateKey
	pubKey         []byte // 33-byte compressed secp256k1

	// Sequence cache — prevents back-to-back sends from re-fetching the same seq.
	seqMu    sync.Mutex
	cachedSeq uint32
	seqReady  bool
}

func NewXRPLClient(rpcURL, privateKeyHex string) (*XRPLClient, error) {
	privKey, err := gocrypto.HexToECDSA(strings.TrimPrefix(privateKeyHex, "0x"))
	if err != nil {
		return nil, fmt.Errorf("invalid XRPL private key: %w", err)
	}
	pubKey := gocrypto.CompressPubkey(&privKey.PublicKey)
	gatewayAddr, err := xrplAddressFromPubKey(pubKey)
	if err != nil {
		return nil, fmt.Errorf("could not derive XRPL address: %w", err)
	}
	return &XRPLClient{
		RPCURL:         rpcURL,
		GatewayAddress: gatewayAddr,
		httpClient:     &http.Client{Timeout: 30 * time.Second},
		privKey:        privKey,
		pubKey:         pubKey,
	}, nil
}

// SendPayment sends XRP (in drops) from the gateway wallet to destAddr.
// Uses a local sequence cache so back-to-back calls within one route don't collide.
func (c *XRPLClient) SendPayment(destAddr string, amountDrops uint64) (string, error) {
	seq, err := c.nextSeq()
	if err != nil {
		return "", fmt.Errorf("get sequence: %w", err)
	}

	txHash, err := c.buildSignSubmit(destAddr, amountDrops, seq)
	if err != nil {
		if isSeqError(err) {
			// Ledger moved on — invalidate cache and retry once with a fresh sequence.
			c.invalidateSeq()
			seq, err2 := c.nextSeq()
			if err2 != nil {
				return "", fmt.Errorf("sequence refresh: %w", err2)
			}
			return c.buildSignSubmit(destAddr, amountDrops, seq)
		}
		return "", err
	}
	return txHash, nil
}

// GatewayBalanceDrops returns the current XRP balance of the gateway wallet in drops.
func (c *XRPLClient) GatewayBalanceDrops() (uint64, error) {
	result, err := c.call("account_info", map[string]interface{}{
		"account":      c.GatewayAddress,
		"ledger_index": "validated",
	})
	if err != nil {
		return 0, err
	}
	var info struct {
		AccountData struct {
			Balance string `json:"Balance"`
		} `json:"account_data"`
	}
	if err := json.Unmarshal(result, &info); err != nil {
		return 0, err
	}
	bal := new(big.Int)
	bal.SetString(info.AccountData.Balance, 10)
	return bal.Uint64(), nil
}

// SweepToTreasury sends all XRP above the reserve+buffer floor to treasury.
func (c *XRPLClient) SweepToTreasury(treasuryAddr string) (string, error) {
	bal, err := c.GatewayBalanceDrops()
	if err != nil {
		return "", fmt.Errorf("balance check: %w", err)
	}
	floor := XRPLBaseReserveDrops + XRPLSweepBufferDrops
	if bal <= floor {
		return "", nil
	}
	return c.SendPayment(treasuryAddr, bal-floor)
}

// ---- sequence cache ----

func (c *XRPLClient) nextSeq() (uint32, error) {
	c.seqMu.Lock()
	defer c.seqMu.Unlock()
	if !c.seqReady {
		seq, err := c.fetchSequence(c.GatewayAddress)
		if err != nil {
			return 0, err
		}
		c.cachedSeq = seq
		c.seqReady = true
	}
	seq := c.cachedSeq
	c.cachedSeq++
	return seq, nil
}

func (c *XRPLClient) invalidateSeq() {
	c.seqMu.Lock()
	c.seqReady = false
	c.seqMu.Unlock()
}

func isSeqError(err error) bool {
	msg := err.Error()
	return strings.Contains(msg, "tefPAST_SEQ") ||
		strings.Contains(msg, "terPRE_SEQ") ||
		strings.Contains(msg, "tefALREADY")
}

// ---- RPC ----

type xrplRPC struct {
	Method string        `json:"method"`
	Params []interface{} `json:"params"`
}

type xrplResponse struct {
	Result json.RawMessage `json:"result"`
}

func (c *XRPLClient) call(method string, params interface{}) (json.RawMessage, error) {
	body, err := json.Marshal(xrplRPC{Method: method, Params: []interface{}{params}})
	if err != nil {
		return nil, fmt.Errorf("marshal RPC request: %w", err)
	}
	resp, err := c.httpClient.Post(c.RPCURL, "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("XRPL RPC call %q: %w", method, err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, fmt.Errorf("read XRPL response: %w", err)
	}
	var r xrplResponse
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, fmt.Errorf("unmarshal XRPL response: %w", err)
	}
	return r.Result, nil
}

func (c *XRPLClient) fetchSequence(address string) (uint32, error) {
	result, err := c.call("account_info", map[string]interface{}{
		"account":      address,
		"ledger_index": "current",
	})
	if err != nil {
		return 0, err
	}
	var info struct {
		AccountData struct {
			Sequence uint32 `json:"Sequence"`
		} `json:"account_data"`
	}
	if err := json.Unmarshal(result, &info); err != nil {
		return 0, fmt.Errorf("parse account_info: %w", err)
	}
	return info.AccountData.Sequence, nil
}

func (c *XRPLClient) submit(txHex string) (string, error) {
	result, err := c.call("submit", map[string]interface{}{"tx_blob": txHex})
	if err != nil {
		return "", err
	}
	var res struct {
		EngineResult        string `json:"engine_result"`
		EngineResultMessage string `json:"engine_result_message"`
		Error               string `json:"error"`
		ErrorMessage        string `json:"error_message"`
		ErrorException      string `json:"error_exception"`
		TxJSON              struct {
			Hash string `json:"hash"`
		} `json:"tx_json"`
	}
	if err := json.Unmarshal(result, &res); err != nil {
		return "", fmt.Errorf("parse submit response: %w — raw: %s", err, string(result))
	}
	// RPC-level error (malformed tx, unknown fields, etc.)
	if res.Error != "" {
		return "", fmt.Errorf("RPC error: %s — %s %s", res.Error, res.ErrorMessage, res.ErrorException)
	}
	if !strings.HasPrefix(res.EngineResult, "tes") {
		return "", fmt.Errorf("ledger rejected: %s — %s (raw: %s)", res.EngineResult, res.EngineResultMessage, string(result))
	}
	return res.TxJSON.Hash, nil
}

// VerifyPayment checks if an XRPL transaction is a successful payment to expectedDest.
func (c *XRPLClient) VerifyPayment(txHash, expectedDest string) error {
	result, err := c.call("tx", map[string]interface{}{
		"transaction": txHash,
	})
	if err != nil {
		return fmt.Errorf("failed to fetch tx: %w", err)
	}

	var res struct {
		TransactionType string `json:"TransactionType"`
		Destination     string `json:"Destination"`
		Meta            struct {
			TransactionResult string `json:"TransactionResult"`
		} `json:"meta"`
		Validated bool `json:"validated"`
		Error     string `json:"error"`
	}
	if err := json.Unmarshal(result, &res); err != nil {
		return fmt.Errorf("failed to parse tx: %w", err)
	}
	if res.Error != "" {
		return fmt.Errorf("tx not found or error: %s", res.Error)
	}
	if !res.Validated {
		return errors.New("transaction not yet validated")
	}
	if res.Meta.TransactionResult != "tesSUCCESS" {
		return fmt.Errorf("transaction failed: %s", res.Meta.TransactionResult)
	}
	if res.TransactionType != "Payment" {
		return fmt.Errorf("not a Payment transaction (got %s)", res.TransactionType)
	}
	if res.Destination != expectedDest {
		return fmt.Errorf("destination mismatch (expected %s, got %s)", expectedDest, res.Destination)
	}

	return nil
}

// SubmitEscrowFinish fires an EscrowFinish signed by the Ghost Layer gateway wallet.
// owner is the buyer's XRPL address (who created the EscrowCreate); offerSeq is
// the sequence number of that tx. Funds flow escrow → seller directly; Ghost Layer
// only pays the tiny network fee from its own wallet.
func (c *XRPLClient) SubmitEscrowFinish(owner string, offerSeq uint32, condition, fulfillment []byte) (string, error) {
	seq, err := c.nextSeq()
	if err != nil {
		return "", fmt.Errorf("get sequence: %w", err)
	}
	txHash, err := c.buildSignSubmitEscrowFinish(owner, offerSeq, condition, fulfillment, seq)
	if err != nil {
		if isSeqError(err) {
			c.invalidateSeq()
			seq, err2 := c.nextSeq()
			if err2 != nil {
				return "", fmt.Errorf("sequence refresh: %w", err2)
			}
			return c.buildSignSubmitEscrowFinish(owner, offerSeq, condition, fulfillment, seq)
		}
		return "", err
	}
	return txHash, nil
}

// SubmitEscrowCancel fires an EscrowCancel, returning funds to the buyer. Called
// when the CancelAfter TTL has passed without delivery confirmation.
func (c *XRPLClient) SubmitEscrowCancel(owner string, offerSeq uint32) (string, error) {
	seq, err := c.nextSeq()
	if err != nil {
		return "", fmt.Errorf("get sequence: %w", err)
	}
	txHash, err := c.buildSignSubmitEscrowCancel(owner, offerSeq, seq)
	if err != nil {
		if isSeqError(err) {
			c.invalidateSeq()
			seq, err2 := c.nextSeq()
			if err2 != nil {
				return "", fmt.Errorf("sequence refresh: %w", err2)
			}
			return c.buildSignSubmitEscrowCancel(owner, offerSeq, seq)
		}
		return "", err
	}
	return txHash, nil
}

func (c *XRPLClient) buildSignSubmitEscrowFinish(owner string, offerSeq uint32, condition, fulfillment []byte, seq uint32) (string, error) {
	gatewayAcct, err := decodeXRPLAddress(c.GatewayAddress)
	if err != nil {
		return "", fmt.Errorf("decode gateway address: %w", err)
	}
	ownerAcct, err := decodeXRPLAddress(owner)
	if err != nil {
		return "", fmt.Errorf("decode owner address: %w", err)
	}
	feeDrops := c.fetchFeeDrops()
	if feeDrops == 0 {
		return "", fmt.Errorf("XRPL network fee exceeds safety ceiling (%d drops)", xrplMaxFeeDrops)
	}
	signingBytes := buildEscrowFinishTx(seq, offerSeq, feeDrops, c.pubKey, nil, gatewayAcct, ownerAcct, condition, fulfillment, true)
	hash := sha512Half(signingBytes)
	compact, err := gocrypto.Sign(hash, c.privKey)
	if err != nil {
		return "", fmt.Errorf("sign: %w", err)
	}
	sig := derEncodeSignature(compact[:64])
	txBlob := buildEscrowFinishTx(seq, offerSeq, feeDrops, c.pubKey, sig, gatewayAcct, ownerAcct, condition, fulfillment, false)
	return c.submit(strings.ToUpper(hex.EncodeToString(txBlob)))
}

func (c *XRPLClient) buildSignSubmitEscrowCancel(owner string, offerSeq uint32, seq uint32) (string, error) {
	gatewayAcct, err := decodeXRPLAddress(c.GatewayAddress)
	if err != nil {
		return "", fmt.Errorf("decode gateway address: %w", err)
	}
	ownerAcct, err := decodeXRPLAddress(owner)
	if err != nil {
		return "", fmt.Errorf("decode owner address: %w", err)
	}
	feeDrops := c.fetchFeeDrops()
	if feeDrops == 0 {
		return "", fmt.Errorf("XRPL network fee exceeds safety ceiling (%d drops)", xrplMaxFeeDrops)
	}
	signingBytes := buildEscrowCancelTx(seq, offerSeq, feeDrops, c.pubKey, nil, gatewayAcct, ownerAcct, true)
	hash := sha512Half(signingBytes)
	compact, err := gocrypto.Sign(hash, c.privKey)
	if err != nil {
		return "", fmt.Errorf("sign: %w", err)
	}
	sig := derEncodeSignature(compact[:64])
	txBlob := buildEscrowCancelTx(seq, offerSeq, feeDrops, c.pubKey, sig, gatewayAcct, ownerAcct, false)
	return c.submit(strings.ToUpper(hex.EncodeToString(txBlob)))
}

// buildEscrowFinishTx encodes an EscrowFinish (tx type 2) in XRPL canonical binary.
// Fields sorted by (typeCode, fieldCode) ascending — required by the ledger.
//
//	(1,2)  TransactionType  0x12 0x0002
//	(2,2)  Flags            0x22 0x00000000
//	(2,4)  Sequence         0x24 <u32>
//	(2,25) OfferSequence    0x20 0x19 <u32>
//	(6,8)  Fee              0x68 <drops>
//	(7,3)  SigningPubKey    0x73 <vl>
//	(7,4)  TxnSignature     0x74 <vl>  (omit during signing)
//	(7,24) Condition        0x70 0x18 <vl>
//	(7,25) Fulfillment      0x70 0x19 <vl>
//	(8,1)  Account          0x81 <vl>
//	(8,2)  Owner            0x82 <vl>
func buildEscrowFinishTx(seq, offerSeq uint32, feeDrops uint64, signingPubKey, txnSig, gatewayAcct, ownerAcct, condition, fulfillment []byte, forSigning bool) []byte {
	var buf bytes.Buffer
	if forSigning {
		buf.Write([]byte{0x53, 0x54, 0x58, 0x00})
	}
	buf.WriteByte(0x12)
	binary.Write(&buf, binary.BigEndian, uint16(2)) // EscrowFinish
	buf.WriteByte(0x22)
	binary.Write(&buf, binary.BigEndian, uint32(0))
	buf.WriteByte(0x24)
	binary.Write(&buf, binary.BigEndian, seq)
	buf.WriteByte(0x20)
	buf.WriteByte(0x19) // OfferSequence: type 2 field 25 — extended field encoding
	binary.Write(&buf, binary.BigEndian, offerSeq)
	buf.WriteByte(0x68)
	buf.Write(xrpDropsBytes(feeDrops))
	buf.WriteByte(0x73)
	buf.Write(vlEncode(signingPubKey))
	if !forSigning && len(txnSig) > 0 {
		buf.WriteByte(0x74)
		buf.Write(vlEncode(txnSig))
	}
	buf.WriteByte(0x70)
	buf.WriteByte(0x18) // Condition: type 7 field 24
	buf.Write(vlEncode(condition))
	buf.WriteByte(0x70)
	buf.WriteByte(0x19) // Fulfillment: type 7 field 25
	buf.Write(vlEncode(fulfillment))
	buf.WriteByte(0x81)
	buf.Write(vlEncode(gatewayAcct))
	buf.WriteByte(0x82)
	buf.Write(vlEncode(ownerAcct))
	return buf.Bytes()
}

// buildEscrowCancelTx encodes an EscrowCancel (tx type 4) in XRPL canonical binary.
//
//	(1,2)  TransactionType  0x12 0x0004
//	(2,2)  Flags            0x22 0x00000000
//	(2,4)  Sequence         0x24 <u32>
//	(2,25) OfferSequence    0x20 0x19 <u32>
//	(6,8)  Fee              0x68 <drops>
//	(7,3)  SigningPubKey    0x73 <vl>
//	(7,4)  TxnSignature     0x74 <vl>  (omit during signing)
//	(8,1)  Account          0x81 <vl>
//	(8,2)  Owner            0x82 <vl>
func buildEscrowCancelTx(seq, offerSeq uint32, feeDrops uint64, signingPubKey, txnSig, gatewayAcct, ownerAcct []byte, forSigning bool) []byte {
	var buf bytes.Buffer
	if forSigning {
		buf.Write([]byte{0x53, 0x54, 0x58, 0x00})
	}
	buf.WriteByte(0x12)
	binary.Write(&buf, binary.BigEndian, uint16(4)) // EscrowCancel
	buf.WriteByte(0x22)
	binary.Write(&buf, binary.BigEndian, uint32(0))
	buf.WriteByte(0x24)
	binary.Write(&buf, binary.BigEndian, seq)
	buf.WriteByte(0x20)
	buf.WriteByte(0x19)
	binary.Write(&buf, binary.BigEndian, offerSeq)
	buf.WriteByte(0x68)
	buf.Write(xrpDropsBytes(feeDrops))
	buf.WriteByte(0x73)
	buf.Write(vlEncode(signingPubKey))
	if !forSigning && len(txnSig) > 0 {
		buf.WriteByte(0x74)
		buf.Write(vlEncode(txnSig))
	}
	buf.WriteByte(0x81)
	buf.Write(vlEncode(gatewayAcct))
	buf.WriteByte(0x82)
	buf.Write(vlEncode(ownerAcct))
	return buf.Bytes()
}

// ---- transaction building ----

// fetchFeeDrops queries server_info for the current base fee in drops.
// Returns 0 if the fee exceeds xrplMaxFeeDrops (signals caller to abort).
func (c *XRPLClient) fetchFeeDrops() uint64 {
	result, err := c.call("server_info", map[string]interface{}{})
	if err != nil {
		return xrplDefaultFeeDrops
	}
	var info struct {
		Info struct {
			ValidatedLedger struct {
				BaseFeeXRP float64 `json:"base_fee_xrp"`
			} `json:"validated_ledger"`
		} `json:"info"`
	}
	if err := json.Unmarshal(result, &info); err != nil {
		return xrplDefaultFeeDrops
	}
	drops := uint64(info.Info.ValidatedLedger.BaseFeeXRP * 1_000_000)
	if drops == 0 {
		drops = xrplDefaultFeeDrops
	}
	if drops > xrplMaxFeeDrops {
		return 0
	}
	return drops
}

func (c *XRPLClient) buildSignSubmit(destAddr string, amountDrops uint64, seq uint32) (string, error) {
	srcAcct, err := decodeXRPLAddress(c.GatewayAddress)
	if err != nil {
		return "", fmt.Errorf("decode gateway address: %w", err)
	}
	dstAcct, err := decodeXRPLAddress(destAddr)
	if err != nil {
		return "", fmt.Errorf("decode destination address: %w", err)
	}

	networkFeeDrops := c.fetchFeeDrops()
	if networkFeeDrops == 0 {
		return "", fmt.Errorf("XRPL network fee exceeds safety ceiling (%d drops) — aborting", xrplMaxFeeDrops)
	}

	signingBytes := buildPaymentTx(seq, amountDrops, networkFeeDrops, c.pubKey, nil, srcAcct, dstAcct, true)
	hash := sha512Half(signingBytes)

	compact, err := gocrypto.Sign(hash, c.privKey)
	if err != nil {
		return "", fmt.Errorf("sign: %w", err)
	}
	derSig := derEncodeSignature(compact[:64])

	txBlob := buildPaymentTx(seq, amountDrops, networkFeeDrops, c.pubKey, derSig, srcAcct, dstAcct, false)
	return c.submit(strings.ToUpper(hex.EncodeToString(txBlob)))
}

func buildPaymentTx(seq uint32, amountDrops, feeDrops uint64, signingPubKey, txnSig, srcAcct, dstAcct []byte, forSigning bool) []byte {
	var buf bytes.Buffer
	if forSigning {
		buf.Write([]byte{0x53, 0x54, 0x58, 0x00})
	}
	buf.WriteByte(0x12)
	binary.Write(&buf, binary.BigEndian, uint16(0))
	buf.WriteByte(0x22)
	binary.Write(&buf, binary.BigEndian, uint32(0))
	buf.WriteByte(0x24)
	binary.Write(&buf, binary.BigEndian, seq)
	buf.WriteByte(0x61)
	buf.Write(xrpDropsBytes(amountDrops))
	buf.WriteByte(0x68)
	buf.Write(xrpDropsBytes(feeDrops))
	buf.WriteByte(0x73)
	buf.Write(vlEncode(signingPubKey))
	if !forSigning && len(txnSig) > 0 {
		buf.WriteByte(0x74)
		buf.Write(vlEncode(txnSig))
	}
	buf.WriteByte(0x81)
	buf.Write(vlEncode(srcAcct))
	buf.WriteByte(0x83)
	buf.Write(vlEncode(dstAcct))
	return buf.Bytes()
}

func xrpDropsBytes(drops uint64) []byte {
	b := make([]byte, 8)
	binary.BigEndian.PutUint64(b, 0x4000000000000000|drops)
	return b
}

func vlEncode(data []byte) []byte {
	n := len(data)
	if n <= 192 {
		return append([]byte{byte(n)}, data...)
	}
	n2 := n - 193
	return append([]byte{byte(193 + (n2 >> 8)), byte(n2 & 0xff)}, data...)
}

func sha512Half(data []byte) []byte {
	h := sha512.Sum512(data)
	return h[:32]
}

func derEncodeSignature(compact []byte) []byte {
	r := trimZeros(compact[:32])
	s := trimZeros(compact[32:64])
	if r[0]&0x80 != 0 {
		r = append([]byte{0x00}, r...)
	}
	if s[0]&0x80 != 0 {
		s = append([]byte{0x00}, s...)
	}
	rDER := append([]byte{0x02, byte(len(r))}, r...)
	sDER := append([]byte{0x02, byte(len(s))}, s...)
	body := append(rDER, sDER...)
	return append([]byte{0x30, byte(len(body))}, body...)
}

func trimZeros(b []byte) []byte {
	for len(b) > 1 && b[0] == 0 {
		b = b[1:]
	}
	return b
}

func decodeXRPLAddress(addr string) ([]byte, error) {
	n := new(big.Int)
	base := big.NewInt(58)
	for _, c := range addr {
		idx := strings.IndexRune(xrplAlphabet, c)
		if idx < 0 {
			return nil, fmt.Errorf("invalid character '%c' in XRPL address", c)
		}
		n.Mul(n, base)
		n.Add(n, big.NewInt(int64(idx)))
	}
	decoded := n.Bytes()
	padded := make([]byte, 25)
	copy(padded[25-len(decoded):], decoded)
	h1 := sha256.Sum256(padded[:21])
	h2 := sha256.Sum256(h1[:])
	if !bytes.Equal(h2[:4], padded[21:]) {
		return nil, errors.New("invalid XRPL address checksum")
	}
	return padded[1:21], nil
}

func xrplAddressFromPubKey(pubKey []byte) (string, error) {
	sha := sha256.Sum256(pubKey)
	h := ripemd160.New()
	h.Write(sha[:])
	accountID := h.Sum(nil)
	payload := append([]byte{0x00}, accountID...)
	h1 := sha256.Sum256(payload)
	h2 := sha256.Sum256(h1[:])
	return xrplBase58Encode(append(payload, h2[:4]...)), nil
}

func xrplBase58Encode(data []byte) string {
	n := new(big.Int).SetBytes(data)
	base := big.NewInt(58)
	mod := new(big.Int)
	result := ""
	for n.Sign() > 0 {
		n.DivMod(n, base, mod)
		result = string(rune(xrplAlphabet[mod.Int64()])) + result
	}
	for _, b := range data {
		if b != 0 {
			break
		}
		result = string(rune(xrplAlphabet[0])) + result
	}
	return result
}
