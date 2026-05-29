package crypto

import (
	"errors"
	"strings"

	"github.com/ethereum/go-ethereum/common/hexutil"
	ethcrypto "github.com/ethereum/go-ethereum/crypto"
)

// VerifyEIP3009Signature verifies that `messageHash` (a pre-computed EIP-712
// hash, already 32 bytes, hex-encoded) was signed by `signer`.
//
// The caller is responsible for computing the correct EIP-712 structured hash
// before calling here — this function does NOT re-hash the input.
func VerifyEIP3009Signature(signer, messageHash, signature string) (bool, error) {
	msgHashBytes, err := hexutil.Decode(messageHash)
	if err != nil {
		return false, errors.New("messageHash: invalid hex")
	}
	if len(msgHashBytes) != 32 {
		return false, errors.New("messageHash: must be exactly 32 bytes (pre-hashed EIP-712 digest)")
	}

	sigBytes, err := hexutil.Decode(signature)
	if err != nil {
		return false, errors.New("signature: invalid hex")
	}
	if len(sigBytes) != 65 {
		return false, errors.New("signature: must be 65 bytes (r+s+v)")
	}

	// Normalise v: Ethereum wallets may emit 27/28 instead of 0/1.
	if sigBytes[64] >= 27 {
		sigBytes[64] -= 27
	}
	if sigBytes[64] > 1 {
		return false, errors.New("signature: invalid v byte after normalisation")
	}

	pubKey, err := ethcrypto.SigToPub(msgHashBytes, sigBytes)
	if err != nil {
		return false, errors.New("signature: recovery failed")
	}
	recovered := ethcrypto.PubkeyToAddress(*pubKey).Hex()
	if !strings.EqualFold(recovered, signer) {
		return false, errors.New("unauthorized signer")
	}
	return true, nil
}
