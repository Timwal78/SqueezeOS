"""
Regression test for the FTD anomaly Discord-alert suppression bug (2026-07-31).

_fire_discord_batch() used to refuse to post whenever DiscordAlerts.enabled
was False — but `enabled` only reflects DISCORD_WEBHOOK_SQUEEZE/FLOW/ALL/
BEAST, four webhooks that have nothing to do with FTD. An operator who set
DISCORD_WEBHOOK_FTD correctly, but none of those four, got every FTD alert
silently swallowed. avg_down_engine.py's own _fire_discord() never had this
gate — only checks its own webhook URL — and this test proves
ftd_anomaly_engine now matches that same convention.

Confirmed failing before the fix (posted == False despite a valid URL and a
real alert), passing after.
"""
import os

import ftd_anomaly_engine as fae


class _FakeDiscord:
    """Mimics DiscordAlerts.enabled being False (no SQUEEZE/FLOW/ALL/BEAST
    webhook configured) while still being able to post."""

    def __init__(self):
        self.enabled = False
        self.posted = []

    def _post(self, url, payload):
        self.posted.append((url, payload))


def test_fires_even_when_discord_enabled_is_false(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_FTD", "https://discord.com/api/webhooks/fake/token")
    discord = _FakeDiscord()
    alerts = [{
        "symbol": "GME",
        "anomaly_type": "FTD_SPIKE",
        "spike_ratio": 3.5,
        "entry_date": None,
        "ts": "2026-07-31T00:00:00",
    }]

    fae._fire_discord_batch(discord, alerts)

    assert len(discord.posted) == 1, (
        "FTD alert was suppressed even though DISCORD_WEBHOOK_FTD was set — "
        "the enabled-gate bug regressed"
    )
    url, payload = discord.posted[0]
    assert url == "https://discord.com/api/webhooks/fake/token"
    assert "GME" in payload["embeds"][0]["fields"][0]["name"]


def test_no_post_when_ftd_webhook_unset(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_FTD", raising=False)
    discord = _FakeDiscord()
    discord.enabled = True  # even with other webhooks configured...
    alerts = [{"symbol": "AMC", "anomaly_type": "FTD_SPIKE", "spike_ratio": 2.1, "entry_date": None, "ts": "x"}]

    fae._fire_discord_batch(discord, alerts)

    assert discord.posted == [], "should never post without its own DISCORD_WEBHOOK_FTD, regardless of .enabled"


def test_no_post_without_discord_or_alerts():
    fae._fire_discord_batch(None, [{"symbol": "X"}])
    fae._fire_discord_batch(_FakeDiscord(), [])
