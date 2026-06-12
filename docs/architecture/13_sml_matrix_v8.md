# 13 — SML Matrix v8

**Status:** ✅ Live · **Source:** `/indicators`, `/pine`, `SML_Beastmode_Oracle_V6.pine`

## Overview
SML Matrix v8 is the flagship TradingView Pine Script v6 indicator suite — the institutional charting layer that visualizes the composite signal, EchoLock confirmations, and Stellar Forge liquidity levels directly on a trader's chart.

## Architecture
- Pine Script v6, single-line statements per the Pine v6 standard (no multi-line expressions, no `=>` inside conditional blocks, `array.new<type>()` typed arrays, `barstate.isconfirmed` gating on signals).
- Published and version-controlled under the ScriptMasterLabs brand on TradingView; 50+ companion indicators across squeeze/cycle/flow/manipulation categories.
- IP/licensing: indicators are closed-source on TradingView (invite-only / protected publish) — **IP rules**: scripts and underlying logic (including the APEX Committee Engine) are proprietary and not to be republished or reverse-engineered.

## Agent & Human Access
- Human: TradingView, invite-only access via ScriptMasterLabs marketplace / Nexus402 (07) listing.
- Agent: indicator *outputs* (signal values, not source) are exposed via SqueezeOS MCP tools — agents consume signals without accessing Pine source.

## Status & Roadmap
- [x] v8 live on TradingView, 50+ companion indicators published
- [x] Pine v6 compliance (typed arrays, single-line, global-scope helpers)
- [ ] Formal versioned changelog published alongside Nexus402 listing
