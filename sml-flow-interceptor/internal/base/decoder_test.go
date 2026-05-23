package base

import (
	"encoding/hex"
	"math/big"
	"testing"
)

func TestDecodeTransfer(t *testing.T) {
	// transfer(0x1111...1111, 1_500_000 * 10^6)  -- $1.5M USDC (6 decimals)
	input, _ := hex.DecodeString(
		"a9059cbb" +
			"0000000000000000000000001111111111111111111111111111111111111111" +
			"0000000000000000000000000000000000000000000000000000015d3ef79800",
	)
	got, err := DecodeERC20Transfer(input, "0xAaAa000000000000000000000000000000000001")
	if err != nil {
		t.Fatalf("decode err: %v", err)
	}
	if got.From != "0xaaaa000000000000000000000000000000000001" {
		t.Errorf("from = %s", got.From)
	}
	if got.To != "0x1111111111111111111111111111111111111111" {
		t.Errorf("to = %s", got.To)
	}
	want := new(big.Int).SetUint64(1_500_000 * 1_000_000)
	if got.Value.Cmp(want) != 0 {
		t.Errorf("value = %s, want %s", got.Value, want)
	}
	if scaled := ScaleValue(got.Value, 6); scaled != 1_500_000 {
		t.Errorf("scaled = %v, want 1500000", scaled)
	}
}

func TestDecodeTransferFrom(t *testing.T) {
	// transferFrom(0x2222...2222, 0x3333...3333, 1)
	input, _ := hex.DecodeString(
		"23b872dd" +
			"0000000000000000000000002222222222222222222222222222222222222222" +
			"0000000000000000000000003333333333333333333333333333333333333333" +
			"0000000000000000000000000000000000000000000000000000000000000001",
	)
	got, err := DecodeERC20Transfer(input, "0xAaAa000000000000000000000000000000000001")
	if err != nil {
		t.Fatalf("decode err: %v", err)
	}
	if got.From != "0x2222222222222222222222222222222222222222" {
		t.Errorf("from = %s", got.From)
	}
	if got.To != "0x3333333333333333333333333333333333333333" {
		t.Errorf("to = %s", got.To)
	}
	if got.Value.Cmp(big.NewInt(1)) != 0 {
		t.Errorf("value = %s, want 1", got.Value)
	}
}

func TestDecodeRejectsNonTransfer(t *testing.T) {
	input, _ := hex.DecodeString("095ea7b3" + // approve(...)
		"0000000000000000000000001111111111111111111111111111111111111111" +
		"0000000000000000000000000000000000000000000000000000000000000001")
	if _, err := DecodeERC20Transfer(input, "0x00"); err == nil {
		t.Fatal("expected error for non-transfer selector")
	}
}
