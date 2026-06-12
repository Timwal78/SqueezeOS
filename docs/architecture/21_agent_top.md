# 21 — agent-top

**Status:** ✅ Live · **Repo:** https://github.com/Timwal78/agent-top · **npm:** `agent-top`

## Overview
agent-top is "`htop` for AI agents" — a live terminal dashboard for any agent process, showing token burn rate, running $ cost, API call rate, and repeated-action loop detection in real time, with a single keypress (`k`) to kill instantly. It's the visual/observability companion to Aegis-Node (doc 20).

## Architecture
- **Core** (`src/index.js`): spawns the agent process, scans stdout for a tiny JSON-line telemetry protocol (`{"agent_top": {...}}`), strips those lines from passthrough output, maintains rolling 60s windows for tokens/min and API calls/min.
- **CLI/TUI** (`bin/cli.js`): renders a live ANSI dashboard (~4 Hz), bars for token rate and API rate (green→yellow→red), running cost total, top repeated action with ⚠ loop warning. Keypress `k` = instant kill, `q` = detach.
- **Optional peer**: detects `@timothywalton/aegis-node` (doc 20) at runtime and shows enforcement status in the footer — agent-top is the dashboard, aegis-node is the guarantee.

## Agent & Human Access
- npm package, MIT licensed, zero required dependencies (aegis-node is an optional peer).
- Telemetry protocol is language-agnostic — any agent (Python, Go, Node) emits `{"agent_top": {...}}` JSON lines to stdout.

## Status & Roadmap
- [x] v0.1.0: live TUI, telemetry protocol, kill/detach keys, working demo
- [ ] Multi-agent tiled view for swarms
- [ ] Web dashboard mode (same protocol, browser UI)
- [ ] Per-tool cost breakdown
