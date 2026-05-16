package crypto

import (
	"crypto/ecdsa"
	"errors"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/crypto"
)

func VerifyEIP3009Signature(signer string, messageHash string, signature string) (bool, error) {
	sigBytes, err := hexutil.Decode(signature)
	if err != nil {
		return false, err
	}
	if sigBytes[64] == 27 || sigBytes[64] == 28 {
		sigBytes[64] -= 27
	}
	msgHashBytes := crypto.Keccak256([]byte(messageHash))
	pubKey, err := crypto.SigToPub(msgHashBytes, sigBytes)
	if err != nil {
		return false, err
	}
	recoveredAddress := crypto.PubkeyToAddress(*pubKey).Hex()
	if recoveredAddress != signer {
		return false, errors.New("unauthorized signer")
	}
	_ = pubKey.(*crypto.PublicKey)
	return true, nil
}

// suppress unused import
var _ = (*ecdsa.PublicKey)(nil)
