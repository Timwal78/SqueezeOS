package base

import (
	"bytes"
	"encoding/hex"
	"errors"
	"math/big"
	"strings"
)

// ERC-20 method selectors.
var (
	selectorTransfer     = mustHex("a9059cbb") // transfer(address,uint256)
	selectorTransferFrom = mustHex("23b872dd") // transferFrom(address,address,uint256)
)

func mustHex(s string) []byte {
	b, err := hex.DecodeString(s)
	if err != nil {
		panic(err)
	}
	return b
}

// DecodedTransfer is the extracted (from, to, value) tuple for an ERC-20
// transfer or transferFrom call. Addresses are lowercased and 0x-prefixed.
type DecodedTransfer struct {
	From  string
	To    string
	Value *big.Int
}

// DecodeERC20Transfer parses ABI-encoded calldata for an ERC-20 transfer or
// transferFrom invocation. For transfer(), the sender argument must be the
// transaction's `from` field; transferFrom() encodes the sender in its args.
func DecodeERC20Transfer(input []byte, sender string) (*DecodedTransfer, error) {
	if len(input) < 4 {
		return nil, errors.New("calldata too short for selector")
	}
	sel, args := input[:4], input[4:]

	switch {
	case bytes.Equal(sel, selectorTransfer):
		if len(args) < 64 {
			return nil, errors.New("transfer args too short")
		}
		to := "0x" + strings.ToLower(hex.EncodeToString(args[12:32]))
		value := new(big.Int).SetBytes(args[32:64])
		return &DecodedTransfer{From: strings.ToLower(sender), To: to, Value: value}, nil

	case bytes.Equal(sel, selectorTransferFrom):
		if len(args) < 96 {
			return nil, errors.New("transferFrom args too short")
		}
		from := "0x" + strings.ToLower(hex.EncodeToString(args[12:32]))
		to := "0x" + strings.ToLower(hex.EncodeToString(args[44:64]))
		value := new(big.Int).SetBytes(args[64:96])
		return &DecodedTransfer{From: from, To: to, Value: value}, nil
	}
	return nil, errors.New("not a transfer or transferFrom call")
}

// ScaleValue converts a raw token amount to a float scaled by 10^-decimals.
// Loses precision for values larger than ~2^53; sufficient for filter checks
// against MinTransferValue, but always retain ValueRaw for analysis.
func ScaleValue(raw *big.Int, decimals uint8) float64 {
	f := new(big.Float).SetInt(raw)
	denom := new(big.Float).SetFloat64(1)
	ten := big.NewFloat(10)
	for i := uint8(0); i < decimals; i++ {
		denom.Mul(denom, ten)
	}
	f.Quo(f, denom)
	out, _ := f.Float64()
	return out
}
