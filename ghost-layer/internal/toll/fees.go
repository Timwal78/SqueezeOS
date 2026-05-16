package toll

import "math/big"

func CalculateBasisPointFee(amountStr string, bps int64) (*big.Int, *big.Int) {
	amount, _ := new(big.Int).SetString(amountStr, 10)
	basisPoints := big.NewInt(bps)
	multiplier := big.NewInt(10000)

	fee := new(big.Int).Mul(amount, basisPoints)
	fee.Div(fee, multiplier)

	remainder := new(big.Int).Sub(amount, fee)
	return fee, remainder
}
