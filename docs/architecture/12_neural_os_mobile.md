# 12 — Neural_OS Mobile

**Status:** ✅ Live · **Source:** `/mobile` · **Live:** https://neuralosagent.com

## Overview
Neural_OS Mobile is the Capacitor-based Android terminal — a mobile front-end onto the SqueezeOS/Neural_OS signal stack, giving traders a native-feeling mobile app without a separate native codebase.

## Architecture
- **Capacitor** wraps a web build (`/mobile/src`, `/mobile/www`) into an Android APK (`neural-os.keystore` for signing).
- Connects to the same SqueezeOS MCP/x402 endpoints as the web and agent interfaces — single backend, multiple front-ends.
- Governed by `/mobile/AGENTS.md`, `/mobile/CLAUDE.md`, and `/mobile/AGENT_STANDARDS` for agent-assisted mobile development consistency.

## Agent & Human Access
- Human: Android app (closed testing on Play Store; web terminal at neuralosagent.com).
- Agent: no separate interface — mobile app consumes the same SqueezeOS MCP server (01).

## Status & Roadmap
- [x] Capacitor build + signing configured, web terminal live
- [ ] Close Play Store closed-testing tester gap, move to open/production track
- [ ] Push notifications wired to Tipmaster (11) alert routing
