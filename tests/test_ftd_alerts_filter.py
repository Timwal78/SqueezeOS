"""
Regression test for the FTD /api/ftd/alerts ticker/min_spike_multiplier
filter bug (found 2026-08-01 during the mcp-x402 gateway diagnosis).

get_feed() used to accept only `limit` — the route read `ticker` and
`min_spike_multiplier` from the query string but never passed them anywhere,
so every call returned the same unfiltered recent-alerts window regardless
of what an agent asked for. Confirmed failing before the fix (a ticker-only
request returned alerts for other symbols too), passing after.
"""
import ftd_anomaly_engine as fae


def _seed(monkeypatch, alerts):
    monkeypatch.setattr(fae, "_feed", list(alerts))


def test_no_filters_returns_everything_newest_first(monkeypatch):
    alerts = [
        {"symbol": "GME", "anomaly_type": "FTD_SPIKE", "spike_ratio": 2.0, "ts": "1"},
        {"symbol": "AMC", "anomaly_type": "FTD_SPIKE", "spike_ratio": 5.0, "ts": "2"},
    ]
    _seed(monkeypatch, alerts)
    out = fae.get_feed(limit=25)
    assert [a["symbol"] for a in out] == ["AMC", "GME"]


def test_ticker_filter_excludes_other_symbols(monkeypatch):
    alerts = [
        {"symbol": "GME", "anomaly_type": "FTD_SPIKE", "spike_ratio": 2.0, "ts": "1"},
        {"symbol": "AMC", "anomaly_type": "FTD_SPIKE", "spike_ratio": 5.0, "ts": "2"},
    ]
    _seed(monkeypatch, alerts)
    out = fae.get_feed(limit=25, symbol="gme")
    assert len(out) == 1
    assert out[0]["symbol"] == "GME"


def test_min_spike_filter_excludes_below_threshold(monkeypatch):
    alerts = [
        {"symbol": "GME", "anomaly_type": "FTD_SPIKE", "spike_ratio": 2.0, "ts": "1"},
        {"symbol": "AMC", "anomaly_type": "FTD_SPIKE", "spike_ratio": 5.0, "ts": "2"},
    ]
    _seed(monkeypatch, alerts)
    out = fae.get_feed(limit=25, min_spike_multiplier=3.0)
    assert len(out) == 1
    assert out[0]["symbol"] == "AMC"


def test_min_spike_filter_excludes_none_spike_ratio(monkeypatch):
    """NEW_THRESHOLD_LIST_ENTRY alerts have spike_ratio=None — a min-spike
    filter must exclude them honestly, never coerce None to 0 and pass."""
    alerts = [
        {"symbol": "GME", "anomaly_type": "NEW_THRESHOLD_LIST_ENTRY", "spike_ratio": None, "ts": "1"},
        {"symbol": "AMC", "anomaly_type": "FTD_SPIKE", "spike_ratio": 5.0, "ts": "2"},
    ]
    _seed(monkeypatch, alerts)
    out = fae.get_feed(limit=25, min_spike_multiplier=1.0)
    assert len(out) == 1
    assert out[0]["symbol"] == "AMC"


def test_combined_filters_and_limit(monkeypatch):
    alerts = [
        {"symbol": "GME", "anomaly_type": "FTD_SPIKE", "spike_ratio": 2.0, "ts": "1"},
        {"symbol": "GME", "anomaly_type": "FTD_SPIKE", "spike_ratio": 6.0, "ts": "2"},
        {"symbol": "AMC", "anomaly_type": "FTD_SPIKE", "spike_ratio": 9.0, "ts": "3"},
    ]
    _seed(monkeypatch, alerts)
    out = fae.get_feed(limit=1, symbol="gme", min_spike_multiplier=1.0)
    assert len(out) == 1
    assert out[0]["ts"] == "2"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
