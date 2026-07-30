"""
Tests for AlphaVantageProvider.get_earnings_calendar() (data_providers.py,
2026-07-30) -- the real free EARNINGS_CALENDAR endpoint used by
squeeze_fuel_engine.py's earnings-blackout refinement gate. Only the true
network boundary (requests.get) is mocked, with a realistic CSV response
shape matching Alpha Vantage's documented format.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ALPHA_VANTAGE_API_KEY"] = "testkey"
import data_providers  # noqa: E402


_FAKE_CSV = (
    "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
    "GME,GameStop Corp,2026-08-05,2026-06-30,-0.10,USD\n"
    "AMC,AMC Entertainment,2026-08-06,2026-06-30,-0.20,USD\n"
)


def _fresh_provider():
    av = data_providers.AlphaVantageProvider()
    if hasattr(av, "_earnings_cache"):
        del av._earnings_cache
    return av


def test_one_call_returns_every_symbol():
    av = _fresh_provider()
    fake_resp = MagicMock(status_code=200, text=_FAKE_CSV)
    with patch("requests.get", return_value=fake_resp) as mock_get:
        cal = av.get_earnings_calendar()
    assert cal == {"GME": "2026-08-05", "AMC": "2026-08-06"}
    assert mock_get.call_count == 1
    print("PASS: one real EARNINGS_CALENDAR call returns every upcoming symbol's date")


def test_cached_within_ttl_no_second_network_call():
    av = _fresh_provider()
    fake_resp = MagicMock(status_code=200, text=_FAKE_CSV)
    with patch("requests.get", return_value=fake_resp) as mock_get:
        av.get_earnings_calendar()
        av.get_earnings_calendar()
    assert mock_get.call_count == 1, "second call within TTL must use the cache, not a fresh request"
    print("PASS: 20h in-process cache prevents burning the daily_calls budget on repeated lookups")


def test_unconfigured_returns_empty_never_fabricates():
    av = data_providers.AlphaVantageProvider()
    av.api_key = ""  # simulate unconfigured
    assert av.available is False
    with patch("requests.get") as mock_get:
        cal = av.get_earnings_calendar()
    assert cal == {}
    mock_get.assert_not_called()
    print("PASS: unconfigured provider -> empty calendar, no network call, no fabricated dates")


def test_malformed_response_returns_empty_not_raises():
    av = _fresh_provider()
    fake_resp = MagicMock(status_code=200, text="not,a,real,earnings,csv\ngarbage")
    with patch("requests.get", return_value=fake_resp):
        cal = av.get_earnings_calendar()
    assert cal == {}
    print("PASS: malformed/unexpected CSV shape -> empty dict, never raises or fabricates")


if __name__ == "__main__":
    test_one_call_returns_every_symbol()
    test_cached_within_ttl_no_second_network_call()
    test_unconfigured_returns_empty_never_fabricates()
    test_malformed_response_returns_empty_not_raises()
    print("\nAll tests passed.")
