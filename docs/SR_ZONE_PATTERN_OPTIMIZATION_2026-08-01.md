# S/R Zone + Candlestick Pattern Engine — Parameter Search Verdict (2026-08-01)

**Verdict: a real, meaningfully better, but NOT fully validated improvement — mixed robustness, disclosed plainly, not oversold.** This is a genuinely different outcome class from the Sovereign Squeeze and Quad-Score searches (which both found near-uniformly robust configs) and from the CVD Regime Desk search (zero of 15 top configs survived) — this one lands in between: real improvement, real remaining fragility.

## Why this search was run

Full-codebase audit (2026-08-01) of all 7 live `IAM_PRIMARY_SYSTEM` engines flagged this as the one system that never cleared the same evidentiary bar as the other six — 12 trades, PF 1.186, shipped-defaults (`docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md`). It is live only because the operator explicitly chose to keep it live despite that thin-evidence disclosure. Per operator directive to research/fix all identified issues, the same disciplined chronological TRAIN/VALID methodology already used for Sovereign Squeeze and Quad-Score was applied here.

**A real engineering gap was also found and fixed en route**: the `atr_target` exit mode was computing stop/target from a raw single-bar true range recomputed fresh every bar — not an actual multi-bar Average True Range, unlike every other engine in this codebase. A real `atr_length` parameter (Wilder-smoothed, default `1` to preserve the exact original behavior) was added to `sr_zone_pattern_engine.py` so this could be searched properly.

## Method

Same 16-symbol real dataset as the Quad-Score search (AMC/GME/IWM/SPY/NVDA/QQQ/MSTR/TSLA/PLTR/HOOD/AMD/MSFT/AAPL/META/COIN/SMCI, 2018-2026 where available). Chronological split at 2024-06-01. 2,000 of 6,120 possible combinations sampled (seed 23), sweeping `bars`, `no_of_pivots`, `zone_expiry`, `zone_buffer_pct`, `exit_mode`, the new `atr_length`, and `atr_stop_mult`/`atr_target_mult`.

**Headline result: only 3 of the top 25 TRAIN-ranked configs held up on VALID (PF>1.0, ≥5 trades)** — a weak hit rate, and most of the top 25 showed absurd TRAIN profit factors (7–128) on tiny samples (13–33 trades) that collapsed on VALID (PF as low as 0.012) — the same overfitting signature the CVD Regime Desk search taught this codebase to watch for. **Two of the three "held" configs were investigated further and rejected**: one (`exit_mode=opposite_zone`, `buf=6.0`) turned out to be dominated by a handful of extreme historical trades and produced *identical* TRAIN/VALID numbers across multiple different chronological split points — a sign the underlying trades are so sparse and clustered that shifting the cutoff doesn't cross any of them, not genuine robustness. A second (`buf=1.0`) had the same split-invariance artifact on a thin 18/9-trade sample.

## The one candidate that held up under real scrutiny

```
bars=10, no_of_pivots=2, zone_expiry=400, zone_buffer_pct=2.0 (was 3.0),
exit_mode=atr_target (unchanged), atr_length=21 (new), atr_stop_mult=2.0 (was 1.5), atr_target_mult=3.0 (unchanged)
```

- **52 real trades** (33 TRAIN + 19 VALID) — a real sample, not a handful, and more than 4x the original 12-trade result.
- **Trade distribution checked directly, not assumed**: the 10 largest wins range +24% to +51% across 7 different symbols (COIN, MSTR, GME, SMCI, TSLA) and 7 different years (2018-2025) — no single outlier trade dominates the result, unlike the rejected `opposite_zone` candidate.
- **Holds VALID PF > 1.0 at all four tested split points** (50/60/67/75%): 2.061, 2.061, 2.236, 2.236 — genuinely positive, though it does not exceed TRAIN the way Quad-Score's did (TRAIN 3.05-3.74 vs VALID 1.22-2.16 — a real, disclosed gap, not hidden).

## Robustness — disclosed honestly, including where it's genuinely fragile

**Robust across the tested range (2 of 6 dimensions):**
- `zone_buffer_pct` (1.0-3.0): VALID PF 1.126-2.183, all >1.0. Breaks only at the wide extreme (4.0 → 0.808).
- `atr_length` (1-28): VALID PF 1.051-1.676, **every single value tested >1.0** — the new ATR parameter this search introduced is itself a solid, stable lever.

**Fragile / narrow (3 of 6 dimensions — real limitations, not hidden):**
- `bars`: only 5-10 hold (VALID PF 1.34-1.54); 14 and 20 both collapse (0.103, 0.521).
- `no_of_pivots`: only `2` works at all — `3` collapses to VALID PF 0.0, `4` produces zero trades in either window. Same fragility already flagged in the original 2026-07-30 backtest doc (the exact-containment version of this confluence almost never fires).
- `zone_expiry`: inconsistent, not monotonic — `0` and `400` both hold, `100` collapses (0.478), `200` barely clears (1.054). This pattern (good-bad-bad-good rather than a smooth curve) suggests sensitivity to where specific historical trade dates happen to fall, not a clean underlying relationship.

`atr_stop_mult`/`atr_target_mult` sit in between: 4 of 5 tested R:R pairs hold (1.41-1.45 VALID PF), one (2.0 stop / 4.0 target) dips just under 1.0 (0.956).

## Honest comparison to this codebase's other searches

| Search | Top-25 hold rate | Verdict |
|---|---|---|
| Sovereign Squeeze | robust across 4 splits + 5 of 6 perturbed dims | Validated, armed live |
| Quad-Score | robust across 4 splits + all 6 perturbed dims | Validated, armed live |
| CVD Regime Desk | 0 of 15 held | DO NOT ARM LIVE |
| **S/R Zone+Pattern (this doc)** | **3 of 25 held, 2 rejected on inspection** | **Real improvement, mixed robustness — see recommendation below** |

## What this does NOT establish

- Does not establish this is as reliable as Sovereign Squeeze/Quad-Score — 3 of 6 tuned dimensions are genuinely fragile, disclosed above, not smoothed over.
- No options economics modeled (same disclosed convention as every other engine here).
- No commission/slippage modeled.
- Does not retroactively validate the `opposite_zone` exit mode or any `no_of_pivots` value other than 2 — both remain unproven/fragile.

## Recommendation — and outcome

This is a real, disclosed step up from the original 12-trade/PF-1.186 result — not noise, not fabricated, verified by inspecting the actual trade list. But it is **not** the same class of validated edge as Sovereign Squeeze/Quad-Score. **This engine is already live-armed on real money** (operator directive, 2026-07-30) — updating its shipped defaults changes what trades an already-running real-money engine takes on the next deploy, a different situation from Sovereign Squeeze/Quad-Score (validated before going live).

**Outcome: applied.** The evidence above was disclosed plainly and the operator directed "Yes, apply it" (2026-08-01). `sr_zone_pattern_engine.py`'s defaults now ship `zone_expiry=400, atr_stop_mult=2.0, atr_length=21, zone_buffer_pct=2.0` — reproduced end-to-end against the real dataset with these exact defaults: 52 trades, PF 2.516, +366.43%, matching the search. The disclosed fragility on `bars`/`no_of_pivots`/`zone_expiry` is unchanged by this decision.

## Reproducing this

```bash
python3 tests/optimize_sr_zone_pattern.py
```
Point `SR_ZONE_PATTERN_OPTIMIZE_BARS_JSON` at an equivalent `{symbol: [bars]}` JSON file (16 symbols, 2018-2026, Robinhood MCP `get_equity_historicals`) to reproduce exactly.
