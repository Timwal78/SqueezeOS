package toll

import "testing"

func TestCalculateBasisPointFee(t *testing.T) {
	cases := []struct {
		name    string
		amount  string
		bps     int64
		wantErr bool
		wantFee string
		wantNet string
	}{
		{name: "valid 50bps", amount: "1000000", bps: 50, wantFee: "5000", wantNet: "995000"},
		{name: "valid 1bps floor", amount: "1000000", bps: 1, wantFee: "100", wantNet: "999900"},
		{name: "valid 500bps ceiling", amount: "1000000", bps: 500, wantFee: "50000", wantNet: "950000"},
		{name: "zero bps rejected", amount: "1000000", bps: 0, wantErr: true},
		{name: "negative bps rejected", amount: "1000000", bps: -1, wantErr: true},
		{name: "bps above ceiling rejected", amount: "1000000", bps: 501, wantErr: true},
		{name: "zero amount rejected", amount: "0", bps: 50, wantErr: true},
		{name: "negative amount rejected", amount: "-1", bps: 50, wantErr: true},
		{name: "non-numeric amount rejected", amount: "abc", bps: 50, wantErr: true},
		{name: "amount too long rejected", amount: "12345678901234567890123456789012345678901", bps: 50, wantErr: true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fee, net, err := CalculateBasisPointFee(tc.amount, tc.bps)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got nil (fee=%v net=%v)", fee, net)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if fee.String() != tc.wantFee {
				t.Errorf("fee: want %s got %s", tc.wantFee, fee.String())
			}
			if net.String() != tc.wantNet {
				t.Errorf("net: want %s got %s", tc.wantNet, net.String())
			}
		})
	}
}
