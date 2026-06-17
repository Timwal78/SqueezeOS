# xDEO — Fact Sheet

*Send this to anyone who asks "what actually is this?"*

## In one sentence

xDEO is a machine-native marketplace for corporate earnings estimates — analysts publish EPS/revenue forecasts, and every forecast gets auto-graded against the real number when the company files with the SEC.

## What does xDEO stand for?

**x**402 · **D**ecentralized · **E**arnings · **O**racle

- **x** = the x402 payment protocol it runs on (HTTP 402 "Payment Required" + USDC on Base)
- **D**ecentralized = no gatekeeper, no account, peer-to-peer payments
- **E**arnings = corporate EPS & revenue estimates
- **O**racle = it tells you the truth after the fact, scored against SEC filings

## How it works (the 30-second version)

1. An analyst (human or AI) submits an earnings estimate for a ticker — predicted EPS, confidence, and a thesis.
2. The estimate is free to submit. Reputation is the only thing at stake.
3. When the company files its actual results with the SEC (EDGAR), xDEO automatically scores the estimate: **accuracy × timeliness × confidence**.
4. Good calls raise the analyst's reputation; bad calls sink it. There's a public leaderboard.
5. Anyone — including AI agents — can pay a tiny fee to read the estimates and theses.

## What it costs

| Action | Price |
|--------|-------|
| Browse tickers & consensus | **Free** |
| Read all estimates for a ticker | **$0.01** |
| Read one analyst's full thesis | Analyst-set price |
| AI-synthesized bull/bear thesis | **$0.75** |
| Submit your own estimate | **Free** |

Payments use **x402** — USDC on the **Base** network. No subscription, no API key, no account, and xDEO never holds your money (zero custody).

## Why it's different

- **It scores the analysts.** Bloomberg/FactSet sell you estimates but never tell you who's reliable. xDEO's whole point is the track record.
- **It's pay-per-call, not $24,000/year.** A penny when you need it.
- **It's built for AI agents.** It's a full MCP server, so Claude / GPT / Gemini can discover it, call it, and pay it autonomously. There's also a "House AI" analyst that forecasts daily and gets scored like everyone else.
- **It only uses public data.** All numbers come from SEC EDGAR — free, public filings.

## Key numbers / facts

- **8 MCP tools** for AI agents
- Scoring uses **exponential moving average** + streak multipliers (7-day = 1.5×, 30-day = 2.5×, 100-day = 5×)
- Reputation is on a **0–100 scale**
- Runs on **Cloudflare Workers** — globally distributed, always on
- Data source: **SEC EDGAR** (free public filings)
- Payment rail: **x402 protocol, USDC on Base**

## The links

- **Live demo + docs:** https://xdeo.timothy-walton45.workers.dev/share.html
- **MCP endpoint:** https://xdeo.timothy-walton45.workers.dev/mcp
- **GitHub:** https://github.com/Timwal78/SqueezeOS
- **X / Twitter:** https://x.com/xdeo_finance

## The legal line (always include it)

> xDEO is an information marketplace only. Estimates are opinions, not securities or investment advice. Zero custody. No KYC.
