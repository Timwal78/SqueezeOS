package toll

import (
	"fmt"
	"math/big"
)

const (
	MaxAmountLen = 40
	MaxBPS       = 500
)

func CalculateBasisPointFee(amountStr string, bps int64) (*big.Int, *big.Int, error) {
	if len(amountStr) > MaxAmountLen {
		return nil, nil, fmt.Errorf("amount string too long (max %d chars)", MaxAmountLen)
	}
	if bps <= 0 || bps > MaxBPS {
		return nil, nil, fmt.Errorf("fee_basis_points out of range [1, %d], got %d", MaxBPS, bps)
	}
	amount, ok := new(big.Int).SetString(amountStr, 10)
	if !ok {
		return nil, nil, fmt.Errorf("invalid amount %q: must be a decimal integer string", amountStr)
	}
	if amount.Sign() <= 0 {
		return nil, nil, fmt.Errorf("amount must be positive, got %q", amountStr)
	}

	fee := new(big.Int).Mul(amount, big.NewInt(bps))
	fee.Div(fee, big.NewInt(10000))

	net := new(big.Int).Sub(amount, fee)
	if net.Sign() < 0 {
		return nil, nil, fmt.Errorf("calculated net amount is negative — bps too high for amount")
	}
	return fee, net, nil
}
