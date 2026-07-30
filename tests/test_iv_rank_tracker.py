"""
Tests for iv_rank_tracker.py -- self-mining real IV-rank store (2026-07-30).
Drives the real, unmodified module against a real temp-file local backend
(no REDIS_URL set) -- these are genuine reads/writes, not mocked math.
"""
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["IV_RANK_JSON_PATH"] = os.path.join(tempfile.mkdtemp(), "iv_rank_test.json")
os.environ.pop("REDIS_URL", None)

import iv_rank_tracker as ivt  # noqa: E402


def _reset(symbol: str):
    ivt._local_state.pop(symbol, None)
    ivt._save_local()


def test_no_history_honestly_unavailable():
    _reset("NOHIST")
    r = ivt.get_iv_rank("NOHIST")
    assert r["available"] is False and r["reason"] == "no_history"
    print("PASS: never-recorded symbol -> honestly unavailable, no fabricated rank")


def test_insufficient_history_reports_real_day_count():
    _reset("THIN")
    base = date(2026, 1, 1)
    for i in range(5):
        ivt.record_iv("THIN", 0.30 + i * 0.01, as_of=base + timedelta(days=i))
    r = ivt.get_iv_rank("THIN")
    assert r["available"] is False
    assert r["reason"] == "insufficient_history"
    assert r["history_days"] == 5
    print(f"PASS: below IV_RANK_MIN_HISTORY_DAYS -> honestly unavailable, real count reported ({r})")


def test_real_percentile_once_minimum_history_reached():
    _reset("FULL")
    base = date(2026, 1, 1)
    for i in range(ivt.IV_RANK_MIN_HISTORY_DAYS):
        ivt.record_iv("FULL", 0.20 + i * 0.01, as_of=base + timedelta(days=i))
    r = ivt.get_iv_rank("FULL")
    assert r["available"] is True
    assert r["iv_rank"] == 100.0, r  # ascending series, latest = max = 100th pct
    assert r["history_days"] == ivt.IV_RANK_MIN_HISTORY_DAYS
    print(f"PASS: real minimum history reached -> real percentile computed ({r})")


def test_same_day_rerecord_dedups_not_inflates_window():
    _reset("DEDUP")
    base = date(2026, 1, 1)
    for i in range(ivt.IV_RANK_MIN_HISTORY_DAYS):
        ivt.record_iv("DEDUP", 0.30, as_of=base + timedelta(days=i))
    last_day = base + timedelta(days=ivt.IV_RANK_MIN_HISTORY_DAYS - 1)
    ivt.record_iv("DEDUP", 0.99, as_of=last_day)  # re-record same day, different value
    r = ivt.get_iv_rank("DEDUP")
    assert r["history_days"] == ivt.IV_RANK_MIN_HISTORY_DAYS, "must not inflate window on same-day re-record"
    assert r["current_iv"] == 0.99, "must keep the LATEST value for that date"
    print("PASS: same-day re-record dedups correctly instead of double-counting a day")


def test_invalid_iv_is_noop():
    _reset("INVALID")
    ivt.record_iv("INVALID", 0.0)
    ivt.record_iv("INVALID", -1.0)
    ivt.record_iv("INVALID", None)
    r = ivt.get_iv_rank("INVALID")
    assert r["available"] is False and r["reason"] == "no_history"
    print("PASS: zero/negative/None IV readings are silently rejected, never stored")


def test_backend_disclosed():
    _reset("BACKEND")
    ivt.record_iv("BACKEND", 0.3)
    r = ivt.get_iv_rank("BACKEND")
    assert r["backend"] == "local_json_no_redis_configured"
    print(f"PASS: backend honestly disclosed ({r['backend']}) -- no REDIS_URL configured in this test env")


if __name__ == "__main__":
    test_no_history_honestly_unavailable()
    test_insufficient_history_reports_real_day_count()
    test_real_percentile_once_minimum_history_reached()
    test_same_day_rerecord_dedups_not_inflates_window()
    test_invalid_iv_is_noop()
    test_backend_disclosed()
    print("\nAll tests passed.")
