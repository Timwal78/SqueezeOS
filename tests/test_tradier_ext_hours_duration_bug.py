"""
Regression tests for the 2026-07-30/31 production incident: every extended-
hours CASCADE (and other primary-system) equity order started failing with
Tradier's real HTTP 400 "Invalid parameter, duration: post market no longer
available." -- confirmed in production logs (DGICA/FFBC/BKDV, all identical).

Two real, separate bugs found and fixed:

1. tradier_api._post() returned None on any non-2xx/non-401 response,
   discarding Tradier's real error body -- so place_equity_order()'s
   `(resp or {}).get("errors", {}).get("error", "unknown error")` always
   fell back to the generic "unknown error", hiding the actual, useful
   Tradier rejection reason from every order failure in this codebase, not
   just this incident. Fixed: _post() now returns the parsed 4xx JSON body
   instead of None. _extract_error() also now handles Tradier's "error" key
   being a list (multiple validation errors), not just a single string.

2. Whether "post" is genuinely no longer a valid Tradier duration value (a
   real product change) couldn't be verified from this sandbox --
   docs.tradier.com and api.tradier.com are both network-blocked here, same
   restriction already documented for other hosts throughout this codebase.
   Rather than guess a replacement duration value on a live-money order
   parameter, iam_executor.py now tracks per-duration failures in-process
   and skips straight to the already-working Robinhood-queue fallback
   after the first confirmed failure this run, instead of repeatedly
   re-attempting a call already known broken. Resets every restart/redeploy.

Real, unmodified code; only the true network boundary (requests.post) is
mocked in the tradier_api tests, and tradier_api.place_equity_order in the
iam_executor tests.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TRADIER_API_KEY", "testkey")
os.environ.setdefault("TRADIER_ACCOUNT_ID", "testacct")

import tradier_api  # noqa: E402
import iam_executor as ie  # noqa: E402


def test_post_returns_real_error_body_not_none_on_4xx():
    fake_resp = MagicMock(status_code=400)
    fake_resp.text = "Invalid parameter, duration: post market no longer available."
    fake_resp.json.return_value = {"errors": {"error": "Invalid parameter, duration: post market no longer available."}}
    with patch("requests.post", return_value=fake_resp):
        result = tradier_api.place_equity_order("DGICA", 5, "buy", order_type="limit",
                                                  duration="post", limit_price=19.80)
    assert result["status"] == "error"
    assert result["message"] == "Invalid parameter, duration: post market no longer available."
    assert result["message"] != "unknown error"
    print("PASS: real Tradier 4xx error text now reaches the caller instead of a generic 'unknown error'")


def test_extract_error_handles_list_shaped_errors():
    assert tradier_api._extract_error({"errors": {"error": ["bad qty", "bad symbol"]}}) == "bad qty; bad symbol"
    assert tradier_api._extract_error({"errors": {"error": "single string"}}) == "single string"
    assert tradier_api._extract_error(None) == "unknown error"
    assert tradier_api._extract_error({}) == "unknown error"
    print("PASS: _extract_error handles list-shaped, string-shaped, and missing error bodies")


def test_option_order_also_surfaces_real_error():
    fake_resp = MagicMock(status_code=400)
    fake_resp.text = "x"
    fake_resp.json.return_value = {"errors": {"error": "invalid option symbol"}}
    with patch("requests.post", return_value=fake_resp):
        result = tradier_api.place_option_order("IWM260610C00210000", 1, "buy_to_open")
    assert result["message"] == "invalid option symbol"
    print("PASS: place_option_order also benefits from the real-error fix")


def test_circuit_breaker_skips_second_attempt_after_first_failure():
    ie._EXT_HOURS_DURATION_BROKEN.clear()
    with patch.object(ie, "_is_extended_hours", return_value=True), \
         patch.object(ie, "PAPER_MODE", return_value=False), \
         patch.object(ie, "_ext_hours_duration", return_value="post"), \
         patch("tradier_api.place_equity_order") as mock_place:
        mock_place.return_value = {"status": "error",
                                    "message": "Invalid parameter, duration: post market no longer available."}
        r1 = ie._execute_tradier_equity("DGICA", "BUY", 19.76, "SML_CASCADE")
        assert mock_place.call_count == 1
        assert r1["status"] == "error"

        r2 = ie._execute_tradier_equity("FFBC", "BUY", 33.79, "SML_CASCADE")
        assert mock_place.call_count == 1, "must not hit Tradier again once this duration is known broken"
        assert r2["status"] == "skipped"
    print("PASS: circuit breaker stops repeated calls to a known-broken Tradier duration parameter")


def test_circuit_breaker_tracks_pre_and_post_independently():
    ie._EXT_HOURS_DURATION_BROKEN.clear()
    assert ie._is_ext_hours_duration_broken("post") is False
    ie._mark_ext_hours_duration_broken("post", "some error")
    assert ie._is_ext_hours_duration_broken("post") is True
    assert ie._is_ext_hours_duration_broken("pre") is False
    print("PASS: pre-market failing does not assume post-market is also broken, and vice versa")


def test_circuit_breaker_only_trips_on_duration_related_failures():
    """A real order failure for an UNRELATED reason (e.g. insufficient funds)
    must NOT trip the duration circuit breaker -- only failures whose
    message actually mentions 'duration' should permanently skip future
    attempts this run."""
    ie._EXT_HOURS_DURATION_BROKEN.clear()
    with patch.object(ie, "_is_extended_hours", return_value=True), \
         patch.object(ie, "PAPER_MODE", return_value=False), \
         patch.object(ie, "_ext_hours_duration", return_value="post"), \
         patch("tradier_api.place_equity_order") as mock_place:
        mock_place.return_value = {"status": "error", "message": "Insufficient buying power"}
        ie._execute_tradier_equity("XYZ", "BUY", 10.0, "SML_CASCADE")
        assert ie._is_ext_hours_duration_broken("post") is False

        ie._execute_tradier_equity("XYZ2", "BUY", 10.0, "SML_CASCADE")
        assert mock_place.call_count == 2, "unrelated failures must not trip the breaker or block retries"
    print("PASS: only duration-related rejections trip the breaker, not unrelated order failures")


if __name__ == "__main__":
    test_post_returns_real_error_body_not_none_on_4xx()
    test_extract_error_handles_list_shaped_errors()
    test_option_order_also_surfaces_real_error()
    test_circuit_breaker_skips_second_attempt_after_first_failure()
    test_circuit_breaker_tracks_pre_and_post_independently()
    test_circuit_breaker_only_trips_on_duration_related_failures()
    print("\nAll tests passed.")
