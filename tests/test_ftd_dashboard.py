"""
Tests for the FTD Data Oracle operator dashboard route.

Covers:
  * Failure-closed when OPERATOR_API_KEY is not set
  * 401 for missing / wrong / case-mismatched keys
  * 200 + correct HTML structure for header / query-string auth
  * Empty-state rendering when the store has no data
  * Populated rendering with synthetic threshold + spike data
  * Compliance footer always present
  * PWA / save-to-homescreen meta tags present
"""

from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from flask import Flask

from core.api.ftd_bp import ftd_bp
from core.ftd_data import FTDRecord, ThresholdEntry, get_store


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(ftd_bp, url_prefix="/api/ftd")
    return app


def _reset_store():
    store = get_store()
    with store._lock:
        store._by_symbol.clear()
        store._threshold.clear()
        store._loaded_zip_names.clear()
        store._available = False
        store._last_ftd_refresh = 0.0
        store._last_threshold_refresh = 0.0


class TestDashboardAuth(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        _reset_store()

    def test_failure_closed_when_env_unset(self):
        # Explicitly clear the env var
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPERATOR_API_KEY", None)
            r = self.client.get("/api/ftd/dashboard?key=anything")
            self.assertEqual(r.status_code, 503)
            self.assertIn(b"failure-closed", r.data.lower())

    def test_401_when_no_key_provided(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "secret"}):
            r = self.client.get("/api/ftd/dashboard")
            self.assertEqual(r.status_code, 401)

    def test_401_when_wrong_key(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "secret"}):
            r = self.client.get("/api/ftd/dashboard?key=wrong")
            self.assertEqual(r.status_code, 401)

    def test_401_case_sensitive(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "Secret"}):
            r = self.client.get("/api/ftd/dashboard?key=secret")
            self.assertEqual(r.status_code, 401)

    def test_200_with_query_string_key(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "secret"}):
            r = self.client.get("/api/ftd/dashboard?key=secret")
            self.assertEqual(r.status_code, 200)

    def test_200_with_header_key(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "secret"}):
            r = self.client.get(
                "/api/ftd/dashboard",
                headers={"X-Operator-Key": "secret"},
            )
            self.assertEqual(r.status_code, 200)

    def test_trailing_slash_also_works(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "secret"}):
            r = self.client.get("/api/ftd/dashboard/?key=secret")
            self.assertEqual(r.status_code, 200)


class TestDashboardEmptyState(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        _reset_store()

    def test_empty_state_message_when_store_empty(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "k"}):
            r = self.client.get("/api/ftd/dashboard?key=k")
            html = r.get_data(as_text=True)
            self.assertIn("Pollers still warming up", html)
            self.assertIn("No symbols currently on the SEC Reg SHO", html)

    def test_meta_tags_always_present(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "k"}):
            html = self.client.get("/api/ftd/dashboard?key=k").get_data(as_text=True)
            self.assertIn('name="theme-color"', html)
            self.assertIn('name="apple-mobile-web-app-capable"', html)
            self.assertIn('apple-touch-icon', html)
            self.assertIn('name="viewport"', html)
            self.assertIn('http-equiv="refresh"', html)

    def test_compliance_footer_always_present(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "k"}):
            html = self.client.get("/api/ftd/dashboard?key=k").get_data(as_text=True)
            self.assertIn("Descriptive data only", html)
            self.assertIn("Reg SHO 204", html)
            self.assertIn("bona-fide market-maker", html)


class TestDashboardWithData(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        _reset_store()
        store = get_store()
        # Inject a threshold entry
        store._set_threshold(ThresholdEntry(
            entry_date=date.today() - timedelta(days=12),
            symbol="GME",
            cusip="36467W109",
            company="GAMESTOP CORP CL A",
        ))
        # Inject FTD records — high spike on the latest
        for days_back, fails in [(20, 50000), (15, 45000), (10, 48000), (5, 200000), (2, 400000)]:
            store._add_record(FTDRecord(
                settlement_date=date.today() - timedelta(days=days_back),
                cusip="36467W109",
                symbol="GME",
                fail_shares=fails,
                price=22.50,
                description="GAMESTOP CORP CL A",
            ))

    def test_renders_threshold_row_with_symbol_and_company(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "k"}):
            html = self.client.get("/api/ftd/dashboard?key=k").get_data(as_text=True)
            self.assertIn("GME", html)
            self.assertIn("GAMESTOP", html)

    def test_renders_spike_section_for_high_spike(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "k"}):
            html = self.client.get("/api/ftd/dashboard?key=k").get_data(as_text=True)
            self.assertIn("Top FTD Spikes", html)
            # latest = 400000, avg = ~148600, spike ~ 2.7×
            # Verify spike formatting appears
            self.assertRegex(html, r"\d+\.\d{2}×")

    def test_renders_t35_marker(self):
        with patch.dict(os.environ, {"OPERATOR_API_KEY": "k"}):
            html = self.client.get("/api/ftd/dashboard?key=k").get_data(as_text=True)
            # T+35 marker is 35 days after latest settlement (2 days back)
            # so should be ~33 days in the future
            expected = (date.today() - timedelta(days=2) + timedelta(days=35)).isoformat()
            self.assertIn(expected, html)


if __name__ == "__main__":
    unittest.main()
