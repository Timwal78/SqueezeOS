# 12 — Neural_OS Mobile (Institutional Android Terminal)

**Repo path:** `mobile/`
**Language:** TypeScript / Capacitor / Android
**Deploy:** GitHub Actions — APK + AAB release builds
**Package ID:** Neural_OS (persistent keystore signing)

---

## What It Does
Full institutional trading OS on Android. Consumes SqueezeOS signals and Ghost Layer execution in a native mobile experience. Includes an AI swarm layer for on-device intelligence. Built with Capacitor (web-to-native bridge) targeting Android.

## Key Features
- Live GOD MODE + DUAL GRID LOCK + TRIPLE_LOCK alerts (push)
- Real-time beastmode signal feed
- Ghost Layer bridge + stealth trade interface
- AI swarm layer for on-device signal processing
- Save-to-homescreen (PWA fallback for non-Android)
- 20+ bugs fixed in beastmode audit (PR #100)

## Builds
- GitHub Actions CI: AAB (Google Play) + APK (sideload)
- v1.1.0 release via GitHub Actions (PR #101, #102)
- Persistent keystore signing for consistent package identity

## Dependencies Installed
- `@coinbase/cdp-sdk` — Coinbase Developer Platform (CDP) integration
- `@reown/appkit` — wallet connectivity
- XRPL, ethers.js — chain connectivity

## Links To
- **SqueezeOS [01]** — consumes all signal endpoints
- **Ghost Layer [02]** — bridge and stealth trade interface
- **402Proof [03]** — payment flows
- **Tipmaster [11]** — push notification delivery
- **CDP (Coinbase)** — wallet + Base chain connectivity via cdp-sdk
