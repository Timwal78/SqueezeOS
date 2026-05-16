package crypto

import (
	"errors"
	"strings"

	"github.com/ethereum/go-ethereum/common/hexutil"
	ethcrypto "github.com/ethereum/go-ethereum/crypto"
)

func VerifyEIP3009Signature(signer, messageHash, signature string) (bool, error) {
	sigBytes, err := hexutil.Decode(signature)
	if err != nil {
		return false, err
	}
	if len(sigBytes) != 65 {
		return false, errors.New("signature must be 65 bytes")
	}
	if sigBytes[64] >= 27 {
		sigBytes[64] -= 27
	}
	msgHash := ethcrypto.Keccak256([]byte(messageHash))
	pubKey, err := ethcrypto.SigToPub(msgHash, sigBytes)
	if err != nil {
		return false, err
	}
	recovered := ethcrypto.PubkeyToAddress(*pubKey).Hex()
	if !strings.EqualFold(recovered, signer) {
		return false, errors.New("unauthorized signer")
	}
	return true, nil
}
