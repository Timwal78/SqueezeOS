package toll

import (
	"fmt"
	"math/big"
)

func CalculateBasisPointFee(amountStr string, bps int64) (*big.Int, *big.Int, error) {
	amount, ok := new(big.Int).SetString(amountStr, 10)
	if !ok {
		return nil, nil, fmt.Errorf("invalid amount %q: must be a decimal integer string", amountStr)
	}
	basisPoints := big.NewInt(bps)
	multiplier := big.NewInt(10000)

	fee := new(big.Int).Mul(amount, basisPoints)
	fee.Div(fee, multiplier)

	remainder := new(big.Int).Sub(amount, fee)
	return fee, remainder, nil
}
