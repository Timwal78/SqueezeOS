"""
Unit tests for finra_short_data.py -- the new FINRA daily short-volume
parser/store. Network access to cdn.finra.org is blocked from this sandbox
(confirmed 403-at-proxy, same class as sec.gov/api.tradier.com elsewhere in
this codebase), so these tests exercise the real, unmodified parser and
store against a realistic mocked file shaped exactly per FINRA's documented
pipe-delimited layout -- they do not (and cannot, from here) prove the live
fetch works end-to-end. See the module docstring for that disclosed gap.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import finra_short_data as fsv  # noqa: E402


SAMPLE_FILE = (
    b"Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
    b"20260728|GME|1200000|5000|3000000|Q\n"
    b"20260728|AMC|800000|1000|2000000|Q\n"
    b"20260728|SPY|40000000|10000|90000000|Q\n"
)


def test_parses_documented_pipe_delimited_format():
    recs = fsv._parse_short_vol_txt(SAMPLE_FILE)
    assert len(recs) == 3, f"expected 3 records, got {len(recs)}"
    gme = next(r for r in recs if r.symbol == "GME")
    assert gme.trade_date == date(2026, 7, 28)
    assert gme.short_volume == 1_200_000
    assert gme.total_volume == 3_000_000
    assert abs(gme.short_volume_ratio - 0.40) < 1e-9
    print("PASS: parses FINRA's documented pipe-delimited short-volume format")


def test_tolerates_malformed_line_without_crashing():
    bad_file = SAMPLE_FILE + b"garbage|not|enough\n" + b"20260728|IWM|100|10|not_a_number|Q\n"
    recs = fsv._parse_short_vol_txt(bad_file)
    assert len(recs) == 3, f"malformed trailing lines should be skipped, got {len(recs)} records"
    print("PASS: malformed/short lines are skipped, not fatal")


def test_short_volume_ratio_zero_total_volume_safe():
    rec = fsv.ShortVolRecord(trade_date=date(2026, 7, 28), symbol="ZZZ",
                              short_volume=100, short_exempt_volume=0, total_volume=0)
    assert rec.short_volume_ratio == 0.0
    print("PASS: short_volume_ratio is safe (0.0) when total_volume is 0")


def test_store_ingest_and_latest():
    store = fsv.ShortVolumeStore()
    for r in fsv._parse_short_vol_txt(SAMPLE_FILE):
        store._add_record(r)

    latest = store.latest("GME")
    assert latest is not None
    assert latest["latest"]["short_volume_ratio"] == 0.4
    assert latest["window_days"] == 1
    assert store.latest("NOPE") is None
    print("PASS: ShortVolumeStore ingests records and answers latest()/None correctly")


def test_store_dedupes_same_trade_date():
    store = fsv.ShortVolumeStore()
    rec = fsv.ShortVolRecord(date(2026, 7, 28), "GME", 100, 0, 200)
    store._add_record(rec)
    store._add_record(rec)  # same trade_date -- must not double-append
    assert len(store.series_for("GME", limit=10)) == 1
    print("PASS: ShortVolumeStore dedupes records with the same trade_date")


if __name__ == "__main__":
    test_parses_documented_pipe_delimited_format()
    test_tolerates_malformed_line_without_crashing()
    test_short_volume_ratio_zero_total_volume_safe()
    test_store_ingest_and_latest()
    test_store_dedupes_same_trade_date()
    print("\nAll tests passed.")
