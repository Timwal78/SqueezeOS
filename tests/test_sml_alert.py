"""
Tests for the SML Sovereign Harmonic Matrix alert receiver.
Covers: signal parsing, webhook ingest, signal TTL, auth, all 8 alert types.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from unittest.mock import patch

from flask import Flask
from core.api.sml_alert_bp import sml_alert_bp, _signals, _parse_signal, _parse_symbol


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(sml_alert_bp, url_prefix="/api/sml")
    return app


def _reset_signals():
    _signals.clear()


_ALERT_CASES = [
    ("FULL SPECTRUM CONVERGENCE — ALL 9 — GME 60 [SML v7.0]",             "FULL_SPECTRUM",        100, "ENTER_MAX",   "GME"),
    ("PRIME INSTITUTIONAL SETUP — FULL MTF STACK — NVDA 60 [SML v7.0 PROPRIETARY]", "PRIME_INSTITUTIONAL", 90, "ENTER_FULL", "NVDA"),
    ("APEX SINGULARITY — SPY 60 [SML v7.0 PROPRIETARY]",                   "APEX_SINGULARITY",      80, "ENTER",       "SPY"),
    ("PRIME SIGNAL — APEX + COMPRESSED VOLATILITY — TSLA 60 [SML v7.0]",  "PRIME_SIGNAL",          75, "ENTER",       "TSLA"),
    ("CRITICAL MASS CONVERGENCE — REGIME: COMPRESSED — AMC 60 [SML v7.0]","CRITICAL_MASS",         55, "PREPARE",     "AMC"),
    ("MTF STACK CONFIRMED — FULL TIMEFRAME ALIGNMENT — MSTR 60 [SML v7.0]","MTF_STACK",            40, "WATCH",       "MSTR"),
    ("MULTI-FRAME CONVERGENCE\nACTIVE SETS: 4/9  |  CI: 72 — PLTR 60 [SML v7.0]", "CONVERGENCE",  30, "WATCH",       "PLTR"),
    ("CONVERGENCE RELEASED — GME 60 [SML v7.0]",                           "RELEASED",               0, "EXIT",        "GME"),
]


class TestSignalParsing(unittest.TestCase):
    def test_all_eight_signal_types(self):
        for msg, expected_type, expected_conviction, expected_action, _ in _ALERT_CASES:
            with self.subTest(msg=msg[:40]):
                parsed = _parse_signal(msg)
                self.assertIsNotNone(parsed, f"Failed to parse: {msg}")
                self.assertEqual(parsed["signal_type"], expected_type)
                self.assertEqual(parsed["conviction"], expected_conviction)
                self.assertEqual(parsed["action"], expected_action)

    def test_symbol_extraction(self):
        for msg, _, _, _, expected_sym in _ALERT_CASES:
            sym = _parse_symbol(msg)
            if expected_sym:
                with self.subTest(msg=msg[:40]):
                    self.assertEqual(sym, expected_sym)

    def test_unknown_message_returns_none(self):
        self.assertIsNone(_parse_signal("random noise"))


class TestIngestEndpoint(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        _reset_signals()

    def test_ingest_full_spectrum(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SML_WEBHOOK_SECRET", None)
            r = self.client.post("/api/sml/alert", json={
                "ticker": "GME",
                "interval": "60",
                "message": "FULL SPECTRUM CONVERGENCE — ALL 9 — GME 60 [SML v7.0]",
            })
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["signal_type"], "FULL_SPECTRUM")
        self.assertEqual(data["conviction"], 100)
        self.assertEqual(data["action"], "ENTER_MAX")

    def test_ingest_released_exit_action(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SML_WEBHOOK_SECRET", None)
            r = self.client.post("/api/sml/alert", json={
                "ticker": "GME",
                "interval": "60",
                "message": "CONVERGENCE RELEASED — GME 60 [SML v7.0]",
            })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["action"], "EXIT")

    def test_missing_message_returns_400(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SML_WEBHOOK_SECRET", None)
            r = self.client.post("/api/sml/alert", json={"ticker": "GME"})
        self.assertEqual(r.status_code, 400)

    def test_unrecognized_message_returns_422(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SML_WEBHOOK_SECRET", None)
            r = self.client.post("/api/sml/alert", json={
                "ticker": "GME",
                "message": "something completely different",
            })
        self.assertEqual(r.status_code, 422)

    def test_webhook_secret_auth_pass(self):
        with patch.dict(os.environ, {"SML_WEBHOOK_SECRET": "s3cr3t"}):
            r = self.client.post("/api/sml/alert?secret=s3cr3t", json={
                "ticker": "SPY",
                "interval": "60",
                "message": "APEX SINGULARITY — SPY 60 [SML v7.0 PROPRIETARY]",
            })
        self.assertEqual(r.status_code, 200)

    def test_webhook_secret_auth_fail(self):
        with patch.dict(os.environ, {"SML_WEBHOOK_SECRET": "s3cr3t"}):
            r = self.client.post("/api/sml/alert?secret=wrong", json={
                "ticker": "SPY",
                "interval": "60",
                "message": "APEX SINGULARITY — SPY 60 [SML v7.0 PROPRIETARY]",
            })
        self.assertEqual(r.status_code, 401)

    def test_symbol_from_ticker_field_takes_priority(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SML_WEBHOOK_SECRET", None)
            r = self.client.post("/api/sml/alert", json={
                "ticker": "AAPL",
                "message": "CRITICAL MASS CONVERGENCE — REGIME: COMPRESSED — DIFF 60 [SML v7.0]",
            })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["symbol"], "AAPL")


class TestSignalQuery(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        _reset_signals()

    def _ingest(self, ticker, message):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SML_WEBHOOK_SECRET", None)
            return self.client.post("/api/sml/alert", json={
                "ticker": ticker, "interval": "60", "message": message,
            })

    def test_signal_active_after_ingest(self):
        self._ingest("GME", "APEX SINGULARITY — GME 60 [SML v7.0 PROPRIETARY]")
        r = self.client.get("/api/sml/signal/GME")
        data = r.get_json()
        self.assertTrue(data["active"])
        self.assertEqual(data["signal_type"], "APEX_SINGULARITY")
        self.assertEqual(data["conviction"], 80)

    def test_no_signal_returns_none_state(self):
        r = self.client.get("/api/sml/signal/XYZ")
        data = r.get_json()
        self.assertFalse(data["active"])
        self.assertEqual(data["signal_type"], "NONE")
        self.assertEqual(data["conviction"], 0)

    def test_all_signals_endpoint(self):
        self._ingest("GME", "FULL SPECTRUM CONVERGENCE — ALL 9 — GME 60 [SML v7.0]")
        self._ingest("NVDA", "PRIME INSTITUTIONAL SETUP — FULL MTF STACK — NVDA 60 [SML v7.0 PROPRIETARY]")
        r = self.client.get("/api/sml/signals")
        data = r.get_json()
        self.assertEqual(data["count"], 2)
        symbols = [s["symbol"] for s in data["signals"]]
        self.assertIn("GME", symbols)
        self.assertIn("NVDA", symbols)

    def test_signals_ordered_by_conviction_desc(self):
        self._ingest("GME", "FULL SPECTRUM CONVERGENCE — ALL 9 — GME 60 [SML v7.0]")
        self._ingest("NVDA", "CRITICAL MASS CONVERGENCE — REGIME: COMPRESSED — NVDA 60 [SML v7.0]")
        r = self.client.get("/api/sml/signals")
        sigs = r.get_json()["signals"]
        self.assertGreaterEqual(sigs[0]["conviction"], sigs[1]["conviction"])

    def test_info_endpoint_returns_hierarchy(self):
        r = self.client.get("/api/sml/info")
        data = r.get_json()
        self.assertIn("signal_hierarchy", data)
        self.assertEqual(len(data["signal_hierarchy"]), 8)

    def test_expired_signal_not_returned(self):
        now = time.time()
        _signals["STALE"] = {
            "symbol": "STALE", "signal_type": "CONVERGENCE", "conviction": 30,
            "action": "WATCH", "timeframe": "60",
            "received_at": now - 3601, "expires_at": now - 1, "raw": "old",
        }
        r = self.client.get("/api/sml/signal/STALE")
        self.assertFalse(r.get_json()["active"])


if __name__ == "__main__":
    unittest.main()
