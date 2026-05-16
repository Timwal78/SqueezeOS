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
	"time"

	gocrypto "github.com/ethereum/go-ethereum/crypto"
	"golang.org/x/crypto/ripemd160"
)

const xrplAlphabet = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"

// XRPLClient signs and submits payments from the gateway XRPL wallet.
type XRPLClient struct {
	RPCURL         string
	GatewayAddress string
	httpClient     *http.Client
	privKey        *ecdsa.PrivateKey
	pubKey         []byte // 33-byte compressed secp256k1
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

const (
	// XRPLBaseReserveDrops is the XRPL network minimum account reserve (10 XRP).
	// The gateway keeps this + a fee buffer so the account stays funded.
	XRPLBaseReserveDrops uint64 = 10_000_000
	// XRPLSweepBufferDrops is extra drops kept for a few tx fees after the sweep.
	XRPLSweepBufferDrops uint64 = 500_000
)

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
// Returns the sweep tx hash, or "" if balance is too low to sweep.
func (c *XRPLClient) SweepToTreasury(treasuryAddr string) (string, error) {
	bal, err := c.GatewayBalanceDrops()
	if err != nil {
		return "", fmt.Errorf("balance check: %w", err)
	}
	floor := XRPLBaseReserveDrops + XRPLSweepBufferDrops
	if bal <= floor {
		return "", nil // nothing to sweep
	}
	sweepAmount := bal - floor
	txHash, err := c.SendPayment(treasuryAddr, sweepAmount)
	if err != nil {
		return "", fmt.Errorf("sweep payment: %w", err)
	}
	return txHash, nil
}

// SendPayment sends XRP (in drops) from the gateway wallet to destAddr.
func (c *XRPLClient) SendPayment(destAddr string, amountDrops uint64) (string, error) {
	seq, err := c.getSequence(c.GatewayAddress)
	if err != nil {
		return "", fmt.Errorf("get sequence: %w", err)
	}

	srcAcct, err := decodeXRPLAddress(c.GatewayAddress)
	if err != nil {
		return "", fmt.Errorf("decode gateway address: %w", err)
	}
	dstAcct, err := decodeXRPLAddress(destAddr)
	if err != nil {
		return "", fmt.Errorf("decode destination address: %w", err)
	}

	const networkFeeDrops uint64 = 12

	// Build signing payload (prefixed with STX\0)
	signingBytes := buildPaymentTx(seq, amountDrops, networkFeeDrops, c.pubKey, nil, srcAcct, dstAcct, true)
	hash := sha512Half(signingBytes)

	compact, err := gocrypto.Sign(hash, c.privKey)
	if err != nil {
		return "", fmt.Errorf("sign: %w", err)
	}
	derSig := derEncodeSignature(compact[:64])

	// Build final signed tx blob
	txBlob := buildPaymentTx(seq, amountDrops, networkFeeDrops, c.pubKey, derSig, srcAcct, dstAcct, false)
	txHex := strings.ToUpper(hex.EncodeToString(txBlob))

	return c.submit(txHex)
}

// ---- internal helpers ----

type xrplRPC struct {
	Method string        `json:"method"`
	Params []interface{} `json:"params"`
}

type xrplResponse struct {
	Result json.RawMessage `json:"result"`
}

func (c *XRPLClient) call(method string, params interface{}) (json.RawMessage, error) {
	body, _ := json.Marshal(xrplRPC{Method: method, Params: []interface{}{params}})
	resp, err := c.httpClient.Post(c.RPCURL, "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var r xrplResponse
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	return r.Result, nil
}

func (c *XRPLClient) getSequence(address string) (uint32, error) {
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
		return 0, err
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
		TxJSON              struct {
			Hash string `json:"hash"`
		} `json:"tx_json"`
	}
	if err := json.Unmarshal(result, &res); err != nil {
		return "", err
	}
	if !strings.HasPrefix(res.EngineResult, "tes") {
		return "", fmt.Errorf("XRPL rejected: %s — %s", res.EngineResult, res.EngineResultMessage)
	}
	return res.TxJSON.Hash, nil
}

// buildPaymentTx produces the XRPL canonical binary for a Payment transaction.
// forSigning=true prepends the STX\0 signing prefix and omits TxnSignature.
func buildPaymentTx(seq uint32, amountDrops, feeDrops uint64, signingPubKey, txnSig, srcAcct, dstAcct []byte, forSigning bool) []byte {
	var buf bytes.Buffer

	if forSigning {
		buf.Write([]byte{0x53, 0x54, 0x58, 0x00})
	}

	// TransactionType=Payment(0), UInt16 header 0x12
	buf.WriteByte(0x12)
	binary.Write(&buf, binary.BigEndian, uint16(0))

	// Flags, UInt32 header 0x22
	buf.WriteByte(0x22)
	binary.Write(&buf, binary.BigEndian, uint32(0))

	// Sequence, UInt32 header 0x24
	buf.WriteByte(0x24)
	binary.Write(&buf, binary.BigEndian, seq)

	// Amount (to destination), Amount header 0x61
	buf.WriteByte(0x61)
	buf.Write(xrpDropsBytes(amountDrops))

	// Fee, Amount header 0x68
	buf.WriteByte(0x68)
	buf.Write(xrpDropsBytes(feeDrops))

	// SigningPubKey, Blob header 0x73
	buf.WriteByte(0x73)
	buf.Write(vlEncode(signingPubKey))

	// TxnSignature, Blob header 0x74 — final tx only
	if !forSigning && len(txnSig) > 0 {
		buf.WriteByte(0x74)
		buf.Write(vlEncode(txnSig))
	}

	// Account, AccountID header 0x81
	buf.WriteByte(0x81)
	buf.Write(vlEncode(srcAcct))

	// Destination, AccountID header 0x83
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

// DER-encode a 64-byte compact secp256k1 signature [R||S].
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

// decodeXRPLAddress converts an XRPL base58check address to its 20-byte AccountID.
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

// xrplAddressFromPubKey derives the XRPL address from a 33-byte compressed public key.
func xrplAddressFromPubKey(pubKey []byte) (string, error) {
	sha := sha256.Sum256(pubKey)
	h := ripemd160.New()
	h.Write(sha[:])
	accountID := h.Sum(nil) // 20 bytes

	payload := append([]byte{0x00}, accountID...)
	h1 := sha256.Sum256(payload)
	h2 := sha256.Sum256(h1[:])
	full := append(payload, h2[:4]...)

	return xrplBase58Encode(full), nil
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
