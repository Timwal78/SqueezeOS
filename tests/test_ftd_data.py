"""
Unit tests for core.ftd_data — pure-logic coverage of the SEC FTD CSV parser,
the in-memory store, basket/ratio helpers, and the cycle summary.

No live network calls — the SEC fetcher path is exercised separately during
manual integration testing.
"""

from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date, timedelta

from core.ftd_data import (
    ETF_BASKETS,
    FTDDataStore,
    FTDRecord,
    ThresholdEntry,
    WINDOW_DAYS,
    _parse_ftd_csv,
    _parse_threshold_txt,
    cycle_summary_for,
    get_store,
)


SAMPLE_FTD_CSV = (
    "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
    "20240513|36467W109|GME|400000|GAMESTOP CORP CL A|22.50\n"
    "20240513|78462F103|XRT|3540000|SPDR S&P RETAIL ETF|74.10\n"
    "20240514|36467W109|GME|55000|GAMESTOP CORP CL A|22.10\n"
    "20240514|78462F103|XRT|180000|SPDR S&P RETAIL ETF|73.80\n"
    "20240515|36467W109|GME|0|GAMESTOP CORP CL A|22.00\n"   # zero rows must skip
    "20240515|junk|junk|notanumber|JUNK|notaprice\n"        # malformed must skip
)


SAMPLE_THRESHOLD_TXT = (
    "Date|Symbol|CUSIP|Company Name|Market Category\n"
    "20240614|GME|36467W109|GAMESTOP CORP CL A|NMS\n"
    "20240614|AMC|00165C104|AMC ENTERTAINMENT HLDG|NMS\n"
)


class TestFTDCSVParser(unittest.TestCase):
    def test_parser_extracts_valid_rows(self):
        recs = _parse_ftd_csv(SAMPLE_FTD_CSV.encode("latin-1"))
        # Should produce 4 valid rows (zero + malformed skipped)
        self.assertEqual(len(recs), 4)
        gme = [r for r in recs if r.symbol == "GME"]
        self.assertEqual(len(gme), 2)
        self.assertEqual(gme[0].fail_shares, 400000)
        self.assertEqual(gme[0].settlement_date, date(2024, 5, 13))
        self.assertAlmostEqual(gme[0].price, 22.50)
        self.assertEqual(gme[0].cusip, "36467W109")

    def test_parser_handles_empty_input(self):
        self.assertEqual(_parse_ftd_csv(b""), [])

    def test_parser_handles_header_only(self):
        self.assertEqual(
            _parse_ftd_csv(b"SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"),
            [],
        )

    def test_parser_handles_comma_delimiter(self):
        csv_text = (
            "SETTLEMENT DATE,CUSIP,SYMBOL,QUANTITY (FAILS),DESCRIPTION,PRICE\n"
            "20240513,36467W109,GME,100000,GAMESTOP CORP CL A,22.50\n"
        )
        recs = _parse_ftd_csv(csv_text.encode("latin-1"))
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].symbol, "GME")
        self.assertEqual(recs[0].fail_shares, 100000)


class TestThresholdParser(unittest.TestCase):
    def test_parser_extracts_entries(self):
        entries = _parse_threshold_txt(SAMPLE_THRESHOLD_TXT.encode("latin-1"), "NASDAQ")
        self.assertEqual(len(entries), 2)
        symbols = {e.symbol for e in entries}
        self.assertEqual(symbols, {"GME", "AMC"})
        gme = [e for e in entries if e.symbol == "GME"][0]
        self.assertEqual(gme.entry_date, date(2024, 6, 14))
        self.assertEqual(gme.cusip, "36467W109")


class TestFTDStore(unittest.TestCase):
    def setUp(self):
        self.store = FTDDataStore()
        # Inject parsed records directly
        for rec in _parse_ftd_csv(SAMPLE_FTD_CSV.encode("latin-1")):
            self.store._add_record(rec)

    def test_series_for_returns_only_matching_symbol(self):
        gme = self.store.series_for("GME")
        xrt = self.store.series_for("XRT")
        self.assertEqual(len(gme), 2)
        self.assertEqual(len(xrt), 2)
        # Series is chronological (oldest first)
        self.assertLess(gme[0].settlement_date, gme[1].settlement_date)

    def test_series_for_handles_case_insensitive_symbol(self):
        self.assertEqual(len(self.store.series_for("gme")), 2)
        self.assertEqual(len(self.store.series_for("Gme")), 2)

    def test_series_for_unknown_symbol_returns_empty(self):
        self.assertEqual(self.store.series_for("DOESNOTEXIST"), [])

    def test_latest_ratio_computes_percentile(self):
        ratio = self.store.latest_ratio("GME")
        self.assertIsNotNone(ratio)
        # Latest is 55000, window has [400000, 55000] — latest is the smaller,
        # so percentile must be 0 (0 records strictly less than 55000)
        self.assertEqual(ratio["rank_percentile"], 0.0)
        self.assertEqual(ratio["latest"]["fail_shares"], 55000)
        self.assertEqual(ratio["window_max_fails"], 400000)

    def test_latest_ratio_unknown_symbol_returns_none(self):
        self.assertIsNone(self.store.latest_ratio("DOESNOTEXIST"))

    def test_dedup_by_settlement_date(self):
        before = len(self.store.series_for("GME"))
        # Re-add same date — must be a no-op
        rec = FTDRecord(
            settlement_date=date(2024, 5, 14),
            cusip="36467W109",
            symbol="GME",
            fail_shares=99,
            price=1.0,
        )
        self.store._add_record(rec)
        after = len(self.store.series_for("GME"))
        self.assertEqual(before, after)

    def test_threshold_round_trip(self):
        for e in _parse_threshold_txt(SAMPLE_THRESHOLD_TXT.encode("latin-1"), "NASDAQ"):
            self.store._set_threshold(e)
        self.assertTrue(self.store.is_on_threshold_list("GME"))
        self.assertTrue(self.store.is_on_threshold_list("AMC"))
        self.assertFalse(self.store.is_on_threshold_list("MSFT"))
        listed = self.store.threshold_list()
        self.assertEqual(len(listed), 2)

    def test_clear_threshold_removes_unseen_symbols(self):
        for e in _parse_threshold_txt(SAMPLE_THRESHOLD_TXT.encode("latin-1"), "NASDAQ"):
            self.store._set_threshold(e)
        # Only "AMC" seen today — GME should be cleared
        self.store._clear_threshold({"AMC"})
        self.assertFalse(self.store.is_on_threshold_list("GME"))
        self.assertTrue(self.store.is_on_threshold_list("AMC"))


class TestBasketBreakdown(unittest.TestCase):
    def test_basket_returns_known_etf(self):
        store = FTDDataStore()
        # Pre-load XRT and GME data
        for rec in _parse_ftd_csv(SAMPLE_FTD_CSV.encode("latin-1")):
            store._add_record(rec)

        # Swap the global store via the module's reference so basket_breakdown
        # picks up our test store. The basket_breakdown method is on the
        # FTDDataStore instance, so test it directly:
        result = store.basket_breakdown("XRT")
        self.assertIsNotNone(result)
        self.assertEqual(result["etf"], "XRT")
        # GME should be present with data; most other tickers will be unavailable
        gme_row = next(r for r in result["constituents"] if r["symbol"] == "GME")
        self.assertTrue(gme_row["available"])
        # The sort puts the highest-notional row first; GME at 22.10 * 55000
        # is much less than nothing for other symbols, so positions vary.

    def test_basket_unknown_etf(self):
        store = FTDDataStore()
        self.assertIsNone(store.basket_breakdown("NOTAREALETF"))

    def test_basket_baskets_keys_are_uppercase(self):
        for key in ETF_BASKETS:
            self.assertEqual(key, key.upper(), f"{key} should be uppercase")


class TestCycleSummary(unittest.TestCase):
    def setUp(self):
        store = get_store()
        # Reset the singleton state for this test
        store._by_symbol.clear()
        store._threshold.clear()

    def test_cycle_summary_no_data_returns_descriptive_payload(self):
        result = cycle_summary_for("DOESNOTEXIST")
        self.assertEqual(result["symbol"], "DOESNOTEXIST")
        self.assertEqual(result["ftd_records_in_window"], 0)
        notes = " ".join(result.get("notes", []))
        self.assertIn("SOURCE_UNAVAILABLE", notes)

    def test_cycle_summary_with_data_returns_descriptive_fields(self):
        store = get_store()
        rec = FTDRecord(
            settlement_date=date.today() - timedelta(days=5),
            cusip="36467W109",
            symbol="GME",
            fail_shares=400000,
            price=22.50,
            description="GAMESTOP CORP CL A",
        )
        store._add_record(rec)
        result = cycle_summary_for("GME")
        # Required descriptive fields exist
        for k in (
            "ftd_records_in_window", "latest_settlement_date",
            "latest_fail_shares", "latest_reference_price", "latest_notional_usd",
            "window_avg_fail_shares", "window_max_fail_shares",
            "on_reg_sho_threshold_list", "t21_calendar_marker",
            "t35_calendar_marker", "days_to_t21_from_today",
            "days_to_t35_from_today",
        ):
            self.assertIn(k, result, f"missing {k}")
        # Latest fields match the injected record
        self.assertEqual(result["latest_fail_shares"], 400000)
        # T+35 marker should be 35 days after the settlement date
        latest_date = date.fromisoformat(result["latest_settlement_date"])
        t35_marker = date.fromisoformat(result["t35_calendar_marker"])
        self.assertEqual((t35_marker - latest_date).days, 35)
        # Notes contain the Reg SHO disclaimer
        joined = " ".join(result.get("notes", []))
        self.assertIn("Reg SHO 204", joined)
        self.assertIn("not predictions", joined)

    def test_cycle_summary_with_threshold_entry(self):
        store = get_store()
        store._set_threshold(ThresholdEntry(
            entry_date=date.today() - timedelta(days=3),
            symbol="GME",
            cusip="36467W109",
            company="GAMESTOP CORP CL A",
        ))
        rec = FTDRecord(
            settlement_date=date.today() - timedelta(days=1),
            cusip="36467W109",
            symbol="GME",
            fail_shares=200000,
            price=22.0,
        )
        store._add_record(rec)
        result = cycle_summary_for("GME")
        self.assertTrue(result["on_reg_sho_threshold_list"])
        self.assertEqual(result["days_on_threshold_list"], 3)
        # Reg SHO 204 13-day marker is exactly 13 days after entry_date
        entry_date = date.today() - timedelta(days=3)
        marker = date.fromisoformat(result["reg_sho_204_close_out_marker"])
        self.assertEqual((marker - entry_date).days, 13)


class TestWindowConstants(unittest.TestCase):
    def test_window_is_positive(self):
        self.assertGreater(WINDOW_DAYS, 0)
        # 180 covers the full T+35 cycle ~5 times over
        self.assertGreaterEqual(WINDOW_DAYS, 90)


if __name__ == "__main__":
    unittest.main()
