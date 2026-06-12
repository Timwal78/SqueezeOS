# 10 — EchoLock

**Status:** ✅ Live · **Source:** `core/echolock.py`, `/echolock`

## Overview
EchoLock detects "signal echo" — repeated/correlated signal patterns across timeframes or tickers that indicate a lock-in (high-confidence) setup versus noise. It's a confirmation layer: a raw composite signal becomes "locked" only when EchoLock detects sufficient cross-confirmation.

## Architecture
- `core/echolock.py`: core detection logic — cross-timeframe and cross-ticker correlation scoring.
- `/echolock`: standalone service wrapping the core module for direct querying.
- Feeds a binary/confidence "lock" flag into the SqueezeOS composite (01) and into GOD MODE Discord alerts (`manual_alert.py`).

## Agent & Human Access
- Feeds SqueezeOS composite score directly.
- GOD MODE signal tier (Discord) triggers only on EchoLock-confirmed setups.
- Standalone MCP tool exposing lock status per ticker — listed under SqueezeOS's 33-tool MCP server.

## Status & Roadmap
- [x] Core detection logic live, integrated into composite + GOD MODE alerts
- [x] Standalone service deployed
- [ ] Expose lock-confidence history per ticker via x402 (backtestable confirmation rate)
