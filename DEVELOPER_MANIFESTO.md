# SQUEEZE OS: DEVELOPER MANIFESTO

## THE PRIME DIRECTIVE: ZERO DEMO / 100% FETCH

This document serves as the "Main Memory" for every agent and developer working on SqueezeOS. The following rules are absolute and must be followed without exception.

### 1. NO DEMO DATA
- **NO** hardcoded lists of tickers (other than user-defined favorites).
- **NO** placeholder values in the UI or Backend.
- **NO** "offline" fallbacks that simulate market activity.
- If data isn't there, the system must show "Awaiting Data" or a real-time error, NEVER a fake list.

### 2. 100% FETCH POLICY
- **NO** arbitrary `.slice()` calls in the frontend. Display the full depth of the data feed.
- **NO** top-N limits in discovery loops (e.g., `[:50]`, `[:20]`). Let the engine handle the full volume.
- **NO** artificial price floors (e.g., "only stocks above $2" or "only stocks below $150") unless requested by the USER for specific filters.
- **NO** expiration or strike boundaries in the options service. Fetch the entire chain.

### 3. ADVERTISING LARGE CAPS
- Large Caps (Mega Caps) are permitted only to serve as "Advertising" benchmarks.
- Each data module must limit Mega Cap display to the **Top 3** by impact/premium.
- This keeps the focus on the **SQUEEZE ENGINE** while maintaining visibility into the broader market leaders.

### 4. TRANSPARENCY
- Every data point must have a traceable source (Schwab, Alpaca, Polygon).
- "Zero-Fake Audit": Any simulated data found in the codebase must be purged immediately.

**FAILURE TO ABIDE BY THESE RULES IS UNACCEPTABLE.**
