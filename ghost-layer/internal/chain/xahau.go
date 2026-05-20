package chain

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"

	gocrypto "github.com/ethereum/go-ethereum/crypto"
)

// URITokenHookParam is a Xahau HookParameter for binary transaction encoding.
// Name and Value are hex strings (Name = hex of 3-byte ASCII abbr, Value = 4-digit hex uint16).
type URITokenHookParam struct {
	Name  string
	Value string
}

// XahauClient wraps XRPLClient with Xahau-specific transaction types.
// Xahau is fully XRPL-protocol-compatible: same keys, addresses, RPC, and signing.
type XahauClient struct {
	*XRPLClient
}

// NewXahauClient constructs a Xahau client from a secp256k1 private key hex string.
func NewXahauClient(rpcURL, privateKeyHex string) (*XahauClient, error) {
	base, err := NewXRPLClient(rpcURL, privateKeyHex)
	if err != nil {
		return nil, err
	}
	return &XahauClient{XRPLClient: base}, nil
}

// MintURIToken submits a URITokenMint transaction to Xahau.
//
//   - uri       — canonical cube state hash string (stored as raw bytes on-chain)
//   - hookParams — 6 face centers encoded as Xahau HookParameters
//   - memoJSON  — compact JSON stored verbatim in the transaction Memo
//
// Returns the Xahau transaction hash on success.
func (c *XahauClient) MintURIToken(uri string, hookParams []URITokenHookParam, memoJSON string) (string, error) {
	seq, err := c.nextSeq()
	if err != nil {
		return "", fmt.Errorf("get sequence: %w", err)
	}
	txHash, err := c.buildSignSubmitMint(uri, hookParams, memoJSON, seq)
	if err != nil {
		if isSeqError(err) {
			c.invalidateSeq()
			seq, err2 := c.nextSeq()
			if err2 != nil {
				return "", fmt.Errorf("sequence refresh: %w", err2)
			}
			return c.buildSignSubmitMint(uri, hookParams, memoJSON, seq)
		}
		return "", err
	}
	return txHash, nil
}

// xahauSubmit is a Xahau-aware submit that handles both standard engine_result
// responses and the error-object format Xahau returns for RPC-level rejections.
func (c *XahauClient) xahauSubmit(txHex string) (string, error) {
	result, err := c.call("submit", map[string]interface{}{"tx_blob": txHex})
	if err != nil {
		return "", err
	}
	var res struct {
		EngineResult        string `json:"engine_result"`
		EngineResultMessage string `json:"engine_result_message"`
		// Xahau also surfaces errors at the RPC level with these fields
		Error        string `json:"error"`
		ErrorMessage string `json:"error_message"`
		Status       string `json:"status"`
		TxJSON       struct {
			Hash string `json:"hash"`
		} `json:"tx_json"`
	}
	if err := json.Unmarshal(result, &res); err != nil {
		return "", fmt.Errorf("parse submit response: %w (raw: %s)", err, string(result))
	}
	// RPC-level error (account not found, malformed, etc.)
	if res.Status == "error" || (res.Error != "" && res.EngineResult == "") {
		return "", fmt.Errorf("Xahau RPC error: %s — %s", res.Error, res.ErrorMessage)
	}
	if !strings.HasPrefix(res.EngineResult, "tes") {
		return "", fmt.Errorf("Xahau rejected: %s — %s (raw: %s)", res.EngineResult, res.EngineResultMessage, string(result))
	}
	return res.TxJSON.Hash, nil
}

// fetchCurrentLedger returns the current ledger index, or 0 on failure.
// Used to set LastLedgerSequence = current + 10, giving the tx ~30s to land.
func (c *XahauClient) fetchCurrentLedger() uint32 {
	result, err := c.call("ledger_current", map[string]interface{}{})
	if err != nil {
		return 0
	}
	var res struct {
		LedgerCurrentIndex uint32 `json:"ledger_current_index"`
	}
	if err := json.Unmarshal(result, &res); err != nil {
		return 0
	}
	return res.LedgerCurrentIndex
}

func (c *XahauClient) buildSignSubmitMint(
	uri string,
	hookParams []URITokenHookParam,
	memoJSON string,
	seq uint32,
) (string, error) {
	srcAcct, err := decodeXRPLAddress(c.GatewayAddress)
	if err != nil {
		return "", fmt.Errorf("decode gateway address: %w", err)
	}

	feeDrops := c.fetchFeeDrops()
	if feeDrops == 0 {
		return "", fmt.Errorf("Xahau fee exceeds safety ceiling — aborting")
	}

	currentLedger := c.fetchCurrentLedger()
	uriBytes := []byte(uri) // raw ASCII bytes of the hash string

	signingBytes := buildURITokenMintTx(seq, currentLedger, feeDrops, c.pubKey, nil, srcAcct, uriBytes, hookParams, memoJSON, true)
	hash := sha512Half(signingBytes)

	compact, err := gocrypto.Sign(hash, c.privKey)
	if err != nil {
		return "", fmt.Errorf("sign: %w", err)
	}
	derSig := derEncodeSignature(compact[:64])

	txBlob := buildURITokenMintTx(seq, currentLedger, feeDrops, c.pubKey, derSig, srcAcct, uriBytes, hookParams, memoJSON, false)
	if len(txBlob) >= 8 {
		txType := binary.BigEndian.Uint16(txBlob[1:3])
		netID := binary.BigEndian.Uint32(txBlob[4:8])
		fmt.Printf("[CUBE] URITokenMint encoded: TransactionType=%d NetworkID=%d blobBytes=%d\n", txType, netID, len(txBlob))
	}
	txHex := strings.ToUpper(hex.EncodeToString(txBlob))
	return c.xahauSubmit(txHex)
}

// buildURITokenMintTx serialises a Xahau URITokenMint in canonical XRPL binary.
//
// Field order: (TypeCode ASC, FieldCode ASC) — the XRPL canonical serialisation spec.
//
//	UInt16(1):   TransactionType(2)
//	UInt32(2):   NetworkID(1), Flags(2), Sequence(4), LastLedgerSequence(27)
//	Amount(6):   Fee(8)
//	Blob(7):     SigningPubKey(3), TxnSignature(4), URI(5)
//	AccountID(8):Account(1)
//	STArray(15): Memos(9), HookParameters(20)
//
// Xahau mainnet NetworkID=21337 is mandatory — nodes reject transactions without it.
func buildURITokenMintTx(
	seq, currentLedger uint32,
	feeDrops uint64,
	signingPubKey, txnSig []byte,
	srcAcct, uriBytes []byte,
	hookParams []URITokenHookParam,
	memoJSON string,
	forSigning bool,
) []byte {
	var buf bytes.Buffer

	// STX\0 signing prefix — included only in the payload to be hashed, not the final blob
	if forSigning {
		buf.Write([]byte{0x53, 0x54, 0x58, 0x00})
	}

	// ── UInt16 (type=1) ─────────────────────────────────────────────────────
	// TransactionType = URITokenMint (45) [field 2 → 0x12]
	buf.WriteByte(0x12)
	binary.Write(&buf, binary.BigEndian, uint16(45))

	// ── UInt32 (type=2) ─────────────────────────────────────────────────────
	// NetworkID = 21337 (Xahau mainnet) [field 1 → 0x21] — MUST come before Flags
	buf.WriteByte(0x21)
	binary.Write(&buf, binary.BigEndian, uint32(21337))

	// Flags = 1 (tfBurnable) [field 2 → 0x22]
	buf.WriteByte(0x22)
	binary.Write(&buf, binary.BigEndian, uint32(1))

	// Sequence [field 4 → 0x24]
	buf.WriteByte(0x24)
	binary.Write(&buf, binary.BigEndian, seq)

	// LastLedgerSequence [field 27 ≥ 16: type<<4|0=0x20, then field byte 0x1B]
	if currentLedger > 0 {
		buf.Write([]byte{0x20, 0x1B})
		binary.Write(&buf, binary.BigEndian, currentLedger+10)
	}

	// ── Amount (type=6) ─────────────────────────────────────────────────────
	// Fee [field 8 → 0x68]
	buf.WriteByte(0x68)
	buf.Write(xrpDropsBytes(feeDrops))

	// ── Blob (type=7) ───────────────────────────────────────────────────────
	// SigningPubKey [field 3 → 0x73]
	buf.WriteByte(0x73)
	buf.Write(vlEncode(signingPubKey))

	// TxnSignature [field 4 → 0x74] — excluded from signing payload
	if !forSigning && len(txnSig) > 0 {
		buf.WriteByte(0x74)
		buf.Write(vlEncode(txnSig))
	}

	// URI [field 5 → 0x75]
	buf.WriteByte(0x75)
	buf.Write(vlEncode(uriBytes))

	// ── AccountID (type=8) ──────────────────────────────────────────────────
	// Account [field 1 → 0x81]
	buf.WriteByte(0x81)
	buf.Write(vlEncode(srcAcct))

	// ── Memos STArray (type=15, field=9 → 0xF9) ─────────────────────────────
	if memoJSON != "" {
		buf.WriteByte(0xF9) // Memos array start

		buf.WriteByte(0xEA) // Memo STObject wrapper (type=14, field=10)

		// MemoType  [Blob field=12 → 0x7C]
		buf.WriteByte(0x7C)
		buf.Write(vlEncode([]byte("CUBE_STATE")))

		// MemoData  [Blob field=13 → 0x7D]
		buf.WriteByte(0x7D)
		buf.Write(vlEncode([]byte(memoJSON)))

		// MemoFormat [Blob field=14 → 0x7E]
		buf.WriteByte(0x7E)
		buf.Write(vlEncode([]byte("application/json")))

		buf.WriteByte(0xE1) // end Memo STObject
		buf.WriteByte(0xF1) // end Memos STArray
	}

	// ── HookParameters STArray (type=15, field=20 → 0xF0 0x14) ─────────────
	if len(hookParams) > 0 {
		buf.Write([]byte{0xF0, 0x14}) // HookParameters array start

		for _, hp := range hookParams {
			buf.Write([]byte{0xE0, 0x11}) // HookParameter STObject (type=14, field=17)

			// HookParameterName  [Blob field=24 → 0x70 0x18]
			nameBytes, _ := hex.DecodeString(hp.Name)
			buf.Write([]byte{0x70, 0x18})
			buf.Write(vlEncode(nameBytes))

			// HookParameterValue [Blob field=25 → 0x70 0x19]
			valBytes, _ := hex.DecodeString(hp.Value)
			buf.Write([]byte{0x70, 0x19})
			buf.Write(vlEncode(valBytes))

			buf.WriteByte(0xE1) // end HookParameter STObject
		}

		buf.WriteByte(0xF1) // end HookParameters STArray
	}

	return buf.Bytes()
}
