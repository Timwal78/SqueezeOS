"""
Tests for finra_short_interest_data.py -- real FINRA OAuth2-gated
short-interest/days-to-cover integration (2026-07-30). Drives the real,
unmodified module; only the true network boundary (urllib.request.urlopen)
is mocked, using a realistic response shape based on FINRA's documented
field-naming convention.
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import finra_short_interest_data as fsi  # noqa: E402


class _FakeResp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fresh_module():
    fsi._token_cache = {"access_token": None, "expires_at": 0.0}
    fsi._symbol_cache = {}


def test_unconfigured_returns_none_never_fabricates():
    fsi._CLIENT_ID, fsi._CLIENT_SECRET = "", ""
    _fresh_module()
    assert fsi.configured() is False
    assert fsi.get_short_interest("GME") is None
    print("PASS: unconfigured (no FINRA_API_CLIENT_ID/SECRET) -> honestly None, never fabricated")


def test_real_oauth_and_parse_pipeline_end_to_end():
    fsi._CLIENT_ID, fsi._CLIENT_SECRET = "testid", "testsecret"
    _fresh_module()

    def fake_urlopen(req, timeout=None):
        if "oauth2" in req.full_url:
            return _FakeResp({"access_token": "tok123", "expires_in": 3600})
        return _FakeResp([{
            "symbolCode": "GME", "settlementDate": "2026-07-15",
            "currentShortPositionQuantity": "5000000",
            "previousShortPositionQuantity": "4500000",
            "averageDailyVolumeQuantity": "2000000",
        }])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = fsi.get_short_interest("GME")
    assert result["current_short_position"] == 5000000.0
    assert result["days_to_cover"] == 2.5
    assert abs(result["change_pct"] - 11.11) < 0.01
    print(f"PASS: real OAuth2 + defensive parse pipeline -> {result}")


def test_second_call_within_ttl_uses_cache_not_a_new_request():
    fsi._CLIENT_ID, fsi._CLIENT_SECRET = "testid", "testsecret"
    _fresh_module()
    call_count = {"n": 0}

    def fake_urlopen(req, timeout=None):
        call_count["n"] += 1
        if "oauth2" in req.full_url:
            return _FakeResp({"access_token": "tok123", "expires_in": 3600})
        return _FakeResp([{"symbolCode": "AMC", "settlementDate": "2026-07-15",
                            "currentShortPositionQuantity": "1000000"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        fsi.get_short_interest("AMC")
        first_calls = call_count["n"]
        fsi.get_short_interest("AMC")
    assert call_count["n"] == first_calls, "second call within TTL should not hit the network again"
    print("PASS: per-symbol cache prevents redundant OAuth2 + query calls within TTL")


def test_missing_symbol_returns_none():
    fsi._CLIENT_ID, fsi._CLIENT_SECRET = "testid", "testsecret"
    _fresh_module()

    def fake_urlopen(req, timeout=None):
        if "oauth2" in req.full_url:
            return _FakeResp({"access_token": "tok123", "expires_in": 3600})
        return _FakeResp([])  # no rows for this symbol

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = fsi.get_short_interest("NOPE")
    assert result is None
    print("PASS: symbol not found in FINRA's data -> honestly None")


def test_status_discloses_setup_requirement():
    fsi._CLIENT_ID, fsi._CLIENT_SECRET = "", ""
    s = fsi.status()
    assert s["configured"] is False
    assert "developer.finra.org" in s["setup_required_if_not_configured"]
    print("PASS: status() discloses the real free-but-manual FINRA account setup step")


if __name__ == "__main__":
    test_unconfigured_returns_none_never_fabricates()
    test_real_oauth_and_parse_pipeline_end_to_end()
    test_second_call_within_ttl_uses_cache_not_a_new_request()
    test_missing_symbol_returns_none()
    test_status_discloses_setup_requirement()
    print("\nAll tests passed.")
