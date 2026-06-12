# 20 — Aegis-Node

**Status:** ✅ Live · **Repo:** https://github.com/Timwal78/aegis-node · **npm:** `aegis-node`

## Overview
Aegis-Node is the standalone, open-source "blast shield" for autonomous AI agents — extracted from the same circuit-breaker philosophy that governs SqueezeOS's autonomous trading pipeline (`LIVE_TRADING_ENABLED` flags, PDT guards, kill switches, see doc 19). It's a zero-dependency Node package that wraps any agent process and kills it instantly if it breaches token-burn, API-call-rate, or action-loop limits.

## Architecture
- **Controller** (`src/index.js`): spawns the agent as a child process (detached, full process-group control).
- **Watcher** (`src/monitor.js`): runs on a separate `worker_thread`, tracking rolling 60s windows for token burn rate, API call rate, and repeated-action signatures. Isolated so a hung agent main thread can't block a trip.
- **On trip**: instant `SIGKILL` of the full process tree, plus best-effort `iptables` outbound DROP for the agent's PID (Linux). Optional `--network-namespace` mode runs the agent in its own net namespace from the start (defense-in-depth).
- **CLI**: `npx -p @timothywalton/aegis-node aegis --max-tokens-per-min N --max-api-calls-per-min N -- <command>` — zero code changes for baseline rate limits.

## Agent & Human Access
- npm package, MIT licensed — install directly, no payment/x402 gating (infrastructure play, not a revenue product).
- Funnels into the broader stack via README links to `proof402-middleware` and the architecture map (this doc).

## Status & Roadmap
- [x] v0.1.0 published: controller + isolated watcher + CLI, three trip conditions, working demo
- [ ] Unix-socket reporting protocol for non-Node agents (Python/Go/Rust)
- [ ] Pluggable trip handlers (Discord/PagerDuty) — natural tie-in to Tipmaster (11)
- [ ] Per-tool rate limits
