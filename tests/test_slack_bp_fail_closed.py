"""
Regression test for the fail-OPEN Slack signature verification in
core/api/slack_bp.py (2026-07-20, found by background audit agent).

_verify() used to `return True` (accept the request as validly signed)
whenever SLACK_SIGNING_SECRET was unset — the opposite of every sibling
secret-gated blueprint in this repo (grants_bp, gap_proposals_bp,
marketing_activity_bp all fail CLOSED — 503 — when their shared secret is
missing). Since every /api/slack/* slash-command route is a public HTTP
endpoint, an unconfigured secret meant anyone who discovered the URL could
POST unsigned requests and have them accepted as genuine Slack traffic.

This drives the real, unmodified _verify() function directly (no Slack
signature crypto needs mocking — the point is exactly that no request
should verify without a real configured secret and a real matching
signature).
"""

import hashlib
import hmac
import os
import sys
import time
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.api.slack_bp as slack_bp  # noqa: E402


def _fake_request(headers: dict, body: str = "text=IWM"):
    req = MagicMock()
    req.headers = headers
    req.get_data.return_value = body
    return req


def test_verify_fails_closed_when_secret_is_unconfigured():
    slack_bp._SIGNING_SECRET = ""
    req = _fake_request({
        "X-Slack-Request-Timestamp": str(int(time.time())),
        "X-Slack-Signature": "v0=anything-at-all-not-a-real-signature",
    })
    assert slack_bp._verify(req) is False, (
        "an unconfigured signing secret must reject the request, not accept it"
    )
    print("PASS: _verify() fails closed (rejects) when SLACK_SIGNING_SECRET is unset")


def test_verify_fails_closed_even_with_no_signature_header_at_all():
    slack_bp._SIGNING_SECRET = ""
    req = _fake_request({"X-Slack-Request-Timestamp": str(int(time.time()))})
    assert slack_bp._verify(req) is False
    print("PASS: _verify() rejects even a request with no signature header when unconfigured")


def test_verify_accepts_a_real_correctly_signed_request_when_secret_is_configured():
    slack_bp._SIGNING_SECRET = "test-signing-secret"
    ts = str(int(time.time()))
    body = "text=IWM"
    base = f"v0:{ts}:{body}"
    real_sig = "v0=" + hmac.new(
        slack_bp._SIGNING_SECRET.encode(), base.encode(), hashlib.sha256
    ).hexdigest()

    req = _fake_request({
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": real_sig,
    }, body=body)
    assert slack_bp._verify(req) is True, "a real, correctly-computed signature must still verify"
    print("PASS: a genuinely correct signature still verifies when the secret is configured")


def test_verify_rejects_wrong_signature_when_secret_is_configured():
    slack_bp._SIGNING_SECRET = "test-signing-secret"
    ts = str(int(time.time()))
    req = _fake_request({
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": "v0=deadbeef00000000000000000000000000000000000000000000000000000000",
    }, body="text=IWM")
    assert slack_bp._verify(req) is False
    print("PASS: an incorrect signature is still correctly rejected when the secret is configured")


if __name__ == "__main__":
    test_verify_fails_closed_when_secret_is_unconfigured()
    test_verify_fails_closed_even_with_no_signature_header_at_all()
    test_verify_accepts_a_real_correctly_signed_request_when_secret_is_configured()
    test_verify_rejects_wrong_signature_when_secret_is_configured()
    print("\nAll regression tests passed.")
