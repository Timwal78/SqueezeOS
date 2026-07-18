# The Nobel Committee Exercise — Strategy Design Session (2026-07-18)

> **What this document is.** A structured design exercise: a closed-door committee of four
> personas — a Behavioral Economist, a Quantitative Economist, a Systems Architect, and a
> Red-Teamer — was tasked with inventing one operational trading strategy built **exclusively
> from ideas that won the Nobel Memorial Prize in Economic Sciences**. No non-laureate
> concepts allowed. Four phases: Ideation → Structural Engineering → Stress Testing → Final
> Blueprint.
>
> **What this document is not.** It is not code, not a deployed engine, and not a promise of
> profit. Per the standing operator decision (2026-07-17): nothing here is "a bot that always
> wins," and any implementation would be **paper-mode first** behind the existing
> `iam_executor.py` hard stops. This PR changes no code.

---

## The Committee

| Seat | Role |
|------|------|
| **BE** | Behavioral Economist — human bias as a source of mispricing |
| **QE** | Quantitative Economist — econometrics, portfolio math, pricing theory |
| **SA** | Systems Architect — turns theory into an operable, governed system |
| **RT** | Red-Teamer — attacks every claim; nothing survives on vibes |

**Ground rule (all seats agreed before Phase 1):** every mechanism must cite a specific
laureate and the specific prized idea. If a concept's originator never won the prize, it is
out of bounds — however useful. (This excluded, among others, the Kelly criterion, technical
analysis, and post-earnings-announcement-drift as a named anomaly; where a behavioral
mechanism was wanted, it had to be derived from Kahneman, Thaler, or Simon directly.)

---

## Phase 1 — Ideation

**BE:** I'll open. The most robust laureate result about *other people's* behavior is
prospect theory — Kahneman, 2002 prize. Losses hurt roughly twice as much as equivalent
gains feel good, and reference points are arbitrary — usually the purchase price. Thaler
(2017) extended this into mental accounting and documented the disposition effect: retail
holders sell winners too early and ride losers too long. That is a *supply* prediction: above
a widely-shared cost basis, there's an overhang of relieved sellers; below it, holders freeze.
Price should underreact to genuine news near crowded reference points. My pitch: trade the
slow correction of that underreaction.

**QE:** My objection is Fama, 2013 prize — efficient markets. If your bias is real and known
since 2002, arbitrageurs have eaten it. But Thaler's own "limits of arbitrage" answers half of
that: real arbitrage needs capital, borrowable shares, and a tolerance for the mispricing
widening first, so *small, slow* behavioral edges can persist precisely because they're
expensive to correct at scale. And Shiller — same 2013 prize, deliberately shared with Fama —
proved prices move far more than discounted fundamentals justify. So the honest synthesis of
2013 is: mostly efficient, episodically not, and the inefficiency clusters in specific regimes.

**QE (continuing):** Which is my pitch. Engle and Granger, 2003 prize. Engle: volatility is
not constant, it clusters — ARCH/GARCH lets you *forecast* the risk regime even when you can't
forecast direction. Granger: cointegration — two non-stationary prices can share a stationary
long-run spread, and deviations from it mean-revert *by construction*, which is a statistically
testable property, not a story. Pitch: trade cointegrated spreads, but only in the volatility
regimes where mean reversion historically completes.

**SA:** Before we marry those two — what does the portfolio layer stand on?

**QE:** Markowitz, 1990 prize: mean-variance optimization, diversification as the only free
lunch. Tobin, 1981: the separation theorem — the risky portfolio and the cash allocation are
*independent* decisions, so risk appetite is expressed by one number, the cash fraction, not
by reaching for spicier positions. Sharpe, 1990: CAPM gives us the discipline that any return
must be judged against its systematic-risk exposure — a spread book should be near-zero beta,
and we should measure that, not assume it.

**BE:** One more source of edge: Akerlof, Spence, Stiglitz — 2001 prize, asymmetric
information. Akerlof's market for lemons says that in markets where the counterparty knows
more than you, the act of someone trading *with you* is itself bad news. In thin small-caps,
resting orders get filled mostly when an informed trader wants the other side. That's not an
edge to harvest — it's an anti-edge to *screen out*. Stiglitz's screening gives the design:
restrict the universe so adverse selection can't reach us.

**RT:** Noted three pitches: behavioral reference-point underreaction, cointegration reversion
gated by GARCH regimes, and an adverse-selection screen. I'll hold fire until Phase 3, except
for one demand now: whatever you build, the *validation* method is in-scope for the
laureate-only rule too. Pre-commit to it.

**QE:** Agreed — Card, Angrist, Imbens, 2021 prize: causal inference from natural experiments.
Backtests will be treated as observational data with selection problems, not as truth.

---

## Phase 2 — Structural Engineering

**SA:** I'll compose the pitches into one machine. Three layers — signal, risk, governance —
because theory that can't survive an org chart isn't a strategy.

### Layer 1 — Signal (what to trade, when)

1. **Cointegration core (Granger, 2003).** Universe = liquid large-cap pairs/baskets with a
   statistically significant cointegrating relationship over a trailing window (Engle-Granger
   two-step test). Entry when the spread's z-score exceeds a threshold; exit at reversion to
   the mean or at a precommitted stop. The tradable claim is the *stationarity of the spread*,
   re-tested continuously — the moment cointegration fails the test, the pair is retired. No
   narrative override.
2. **Volatility-regime gate (Engle, 2003).** A GARCH(1,1) forecast per spread classifies the
   regime. New entries are permitted only in the regime band where historical reversion
   actually completed; in the explosive-volatility tail, the book only closes positions. This
   is Engle used honestly: forecasting *risk*, never direction.
3. **Behavioral tilt, not trigger (Kahneman 2002, Thaler 2017).** Where a leg of a spread sits
   just below a crowded reference point (a level with heavy historical volume — a proxy for
   aggregate cost basis), disposition-effect supply should slow its re-rating: widen the
   required entry z-score. Sitting just above one, reversion gets a tailwind: allow the
   standard threshold. Prospect theory *adjusts confidence*; it never originates a trade alone.
4. **Adverse-selection screen (Akerlof/Stiglitz, 2001).** Hard universe filter: minimum
   market cap, minimum average dollar volume, maximum spread width. Lemons markets are not an
   opportunity set. This also kills, by construction, the microcap squeeze names where informed
   flow dominates.
5. **Execution shading (Milgrom & Wilson, 2020).** Every fill is a common-value auction won
   against counterparties with private information — the winner's curse says naive limit orders
   systematically get filled at the worst times. Rule: shade passive orders away from fair value
   by an amount increasing in the GARCH volatility forecast, and cross the spread only on
   regime-gate exits where immediacy is the point.

### Layer 2 — Risk (how much)

6. **Mean-variance allocation with forecast covariance (Markowitz 1990 + Engle 2003).**
   Position weights come from a constrained mean-variance step where the covariance matrix is
   the GARCH forecast, not the trailing sample — risk budgets shrink *before* realized
   volatility spikes, not after.
7. **Tobin separation (1981).** Risk appetite lives in exactly one dial: the cash fraction.
   Drawdowns raise cash; they never trigger "win it back" position sizing. This is the
   structural antidote to the loss-averse doubling-down that prospect theory predicts *we*
   will feel.
8. **Beta discipline (Sharpe, 1990).** The book's net beta is measured daily and constrained
   to a band around zero. A spread book that has quietly become a market-direction bet is a
   bug, and CAPM is the bug detector.
9. **Liquidity buffer (Diamond & Dybvig, 2022).** Bank-run logic applies to any leveraged or
   redemption-exposed book: the time you must sell is the time everyone must sell. Rules: no
   leverage, and a permanent cash floor sized so that a simultaneous stop-out of every
   position at stressed (not average) spreads never forces a fire-sale sequence.

### Layer 3 — Governance (who decides, and when they may not)

10. **Rules over discretion (Kydland & Prescott, 2004).** Time inconsistency is the central
    operational risk: the operator in a drawdown is a different agent than the operator who
    designed the system, and the drawdown-operator will want to renegotiate. All thresholds —
    entry z, stops, regime bands, cash floor — are written down *ex ante* and may be changed
    only out-of-cycle, flat, with a mandatory review delay. Never mid-position.
11. **Bounded rationality by design (Simon, 1978).** The system satisfices: a handful of
    auditable rules a human can hold in their head, over a globally optimal black box nobody
    can explain in a drawdown. Complexity is a cost paid in trust exactly when trust is scarcest.
12. **Contract layer (Hart & Holmström, 2016).** If any part runs as an autonomous agent, its
    mandate is an incomplete contract: observable, verifiable performance metrics (rule
    adherence, slippage vs. model), no discretion outside the ruleset, and the principal —
    the human operator — holds all residual control rights. Concretely: the agent may never
    widen its own limits.

**SA (closing Phase 2):** Optional extension, flagged not included: a Merton/Scholes (1997)
tail-hedge overlay — pricing long-dated index puts as the cost of insuring the Diamond-Dybvig
scenario. Priced out of scope for v1 because it adds a premium bleed that dominates P&L at
small book sizes.

---

## Phase 3 — Stress Testing

**RT:** Now I get to break it. Five attacks.

**Attack 1 — Fama eats you (2013).** *"Cointegration screens are public knowledge. Whatever
spread you find, faster capital found first. Your expected edge net of costs is zero."*

- **QE response:** Partially conceded — that's why expected returns are modeled as small and
  the strategy lives or dies on cost control, hence the Milgrom-Wilson execution shading and
  the liquid-only universe. The persistence argument is Thaler's limits of arbitrage: the
  edge that survives is the one too small and too slow for institutional capital to bother
  correcting. **Committee ruling:** accepted, with a consequence — *capacity is explicitly
  small*, and the blueprint must say so. This is a small-book strategy by theory, not by
  accident.

**Attack 2 — The Lucas critique (1995).** *"Your parameters are estimated under a regime.
The moment the regime changes — a rate cycle, a market-structure change — every estimated
relationship, including your precious cointegration, is invalid. 2003-vintage pairs died in
2008."*

- **QE response:** Conceded in full; the defense is structural, not statistical. Cointegration
  is *continuously re-tested* (attack surface #1 of the signal layer), positions are killed on
  test failure regardless of P&L, and Hansen's (2013) work on robust estimation under model
  uncertainty is the standing instruction: treat every parameter as misspecified and demand
  the rule still be safe when it is. **Committee ruling:** accepted; added a hard rule — a
  structural-break test failure closes the pair *and* quarantines it from re-entry for a full
  re-estimation window.

**Attack 3 — You are the winner's curse (2020).** *"Milgrom-Wilson doesn't just apply to your
fills. It applies to your backtest. You searched many pairs; the ones that look best are the
ones where noise flattered you most. Your expected live performance is below your backtest by
construction."*

- **RT (continuing, since QE hesitated):** And I'll answer it myself, because the answer was
  precommitted in Phase 1: Card/Angrist/Imbens (2021). Backtests are observational data with
  a selection mechanism. Mandatory discipline: out-of-sample holdout that is *never* used for
  selection, walk-forward evaluation only, and selection-bias haircuts on every reported
  metric. If a pair's edge doesn't survive the haircut, it doesn't trade. **Committee
  ruling:** accepted; validation protocol is part of the blueprint, not an afterthought.

**Attack 4 — Diamond-Dybvig turned against you (2022).** *"Your stops assume a counterparty.
In the liquidity spiral — exactly the GARCH tail you claim to gate — spreads widen, your
stops fill terribly, and correlated unwinds hit every pair at once because every stat-arb
book holds the same pairs."*

- **SA response:** This is why rule #9 sizes the cash floor to *stressed* exit costs and why
  leverage is banned outright — the Diamond-Dybvig death spiral requires a forced seller, and
  an unlevered book with a cash floor is never forced. The residual risk (mark-to-market
  drawdown while waiting out a spiral) is real and disclosed, not solved. **Committee
  ruling:** accepted with disclosure — the blueprint must state plainly that crowded-unwind
  drawdowns are survivable but not avoidable.

**Attack 5 — Kahneman turned against you (2002).** *"Your entire behavioral layer models
other people's loss aversion. The operator reading this has held losers, revenge-traded, and
overridden systems before. The most dangerous bias in this room is ours."*

- **BE response:** Fully conceded, and it's the reason the governance layer exists at all.
  Kydland-Prescott precommitment (#10), Tobin's single risk dial (#7), and the Hart-Holmström
  no-self-widening rule (#12) are all aimed at *us*, not at the market. Plus one operational
  translation: paper mode first, with the same rules, so the discipline is rehearsed when
  nothing hurts. **Committee ruling:** accepted; paper-first is a blueprint requirement.

**RT (closing Phase 3):** No attack produced an unanswered kill. Three attacks forced
material changes (capacity disclosure, break-quarantine rule, validation haircuts). I sign
off — with the standing note that signing off means "internally coherent and honestly
disclosed," not "profitable."

---

## Phase 4 — Final Blueprint

### Strategy name: **LAUREATE** — *Liquidity-Aware, Uncertainty-Robust Engine for Adverse-selection-screened, Time-consistent Equity reversion*

**One-sentence thesis:** Trade continuously re-validated cointegrated spreads in liquid
large-caps, only in forecastable volatility regimes, tilted by prospect-theory supply
effects, sized by forecast-covariance mean-variance with a hard cash floor, under precommitted
rules that neither the operator nor any agent may change mid-position.

### Rule summary

| # | Rule | Laureate basis |
|---|------|----------------|
| 1 | Universe: liquid large-caps passing cap/volume/spread screens | Akerlof, Spence, Stiglitz (2001) |
| 2 | Signal: Engle-Granger cointegration, z-score entry/exit, continuous re-test, break ⇒ close + quarantine | Granger (2003); Hansen (2013) |
| 3 | Regime gate: GARCH(1,1) band; explosive-vol regime is exit-only | Engle (2003) |
| 4 | Behavioral tilt: entry threshold widened/relaxed near crowded reference points; never a standalone trigger | Kahneman (2002); Thaler (2017) |
| 5 | Execution: passive orders shaded by vol forecast; cross spread only on gate exits | Milgrom & Wilson (2020) |
| 6 | Sizing: constrained mean-variance on GARCH-forecast covariance | Markowitz (1990); Engle (2003) |
| 7 | Risk dial: cash fraction only; drawdown ⇒ raise cash, never re-size up | Tobin (1981) |
| 8 | Net beta constrained near zero, measured daily | Sharpe (1990) |
| 9 | No leverage; cash floor sized to stressed simultaneous stop-out | Diamond & Dybvig (2022) |
| 10 | All parameters precommitted; changes only out-of-cycle, flat, after review delay | Kydland & Prescott (2004) |
| 11 | Ruleset small enough to be human-auditable; satisfice, don't optimize | Simon (1978) |
| 12 | Any agent runs under a verifiable mandate; may never widen its own limits | Hart & Holmström (2016) |
| 13 | Validation: untouched holdout, walk-forward only, selection-bias haircuts | Card, Angrist, Imbens (2021) |
| 14 | Expected edge modeled as small/slow; capacity explicitly limited | Fama & Shiller & Thaler (2013/2017) |

### Honest limitations (committee-mandated disclosures)

- **Capacity is small by theory.** The edge, if present, exists *because* it's not worth
  institutional capital's time. Scaling it is self-defeating.
- **Crowded unwinds are survivable, not avoidable.** The unlevered cash floor prevents forced
  selling; it does not prevent mark-to-market pain.
- **Every parameter is assumed misspecified.** Rules were chosen to fail safe under
  misspecification, per Hansen — this is a claim about robustness, not accuracy.
- **No profitability claim is made.** The committee certifies internal coherence and honest
  disclosure only.

### SqueezeOS implementation notes (informational — no code in this PR)

If LAUREATE is ever implemented, the natural mapping is:

- **Signal layer** → a new engine module alongside the existing ones (it is a *spread* engine;
  nothing in the current single-symbol engine roster does this), scored first in
  `tests/backtest_engines.py` style with the rule-13 validation protocol before any wiring.
- **Regime gate & sizing** → GARCH fitting fits the existing pattern of pure-computation
  engine modules; data via the existing `data_providers.py` chain (Prime Directive applies:
  no demo data, no truncated fetches).
- **Execution & governance** → routes through the existing `iam_executor.py` **unchanged**:
  paper mode default, `IAM_STOP_LOSS_PCT` hard stops, daily loss breaker, symbol allowlist.
  Rule 10 (precommitment) and rule 12 (no self-widening) are exactly the existing operator
  policy — paper-first, live arming only by an explicit fresh decision from Timothy.
- **Per the 2026-07-17 "delete what doesn't win" directive:** LAUREATE would earn a slot the
  same way every engine does — measured evidence on the scoreboard, or it doesn't ship.

*Session closed. — BE, QE, SA, RT*

---

## Appendix A — The RERE / DeltaForge Record (added 2026-07-18, same day)

**Why this appendix exists.** On the same day this doc was written, the operator shared a
parallel committee exercise run on Grok (same Nobel-only prompt, different AI). It produced a
strategy called **RERE**, then escalated into an aggressive variant ("**RERE vMax**") and a
product pitch ("**ScriptMaster DeltaForge API**"). This appendix records what happened, what
was accepted, and what was rejected — so nobody (including the operator, including future
agents) has to reconstruct it from chat history.

### A.1 — RERE (original): independent convergence, accepted as corroboration

Grok's committee, adjourning properly, produced RERE: harvest behavioral distortions
(prospect-theory reference points, probability weighting) against equilibrium benchmarks,
screen for informed-vs-biased flow separation (asymmetric information), de-risk automatically
to plain MPT when behavioral signals decouple, cap capacity via price-impact models, carry
tail hedges, circuit-break on regime shifts.

**Assessment:** RERE and LAUREATE are close cousins arrived at independently — same laureate
toolkit, same shape: behavioral edge + adverse-selection screen + regime de-risking + bounded
capacity + honest limits. Two committees converging on this shape is mild evidence the shape
is right. Differences: RERE is broader but aspirational (no concrete instruments, thresholds,
or parameters); LAUREATE is narrower but operational. RERE also lacks LAUREATE's
precommitment governance layer — which matters, because of what happened next.

**Critical caveat — the RERE "backtests" were fabricated.** The Grok thread presented
regime-by-regime backtest tables (2008 GFC, dot-com, March 2020, "Sharpe +0.4–0.6 over
benchmark", "long-term Sharpe 0.9–1.4", "max drawdown 12–25%") and a Red-Teamer statement
that "the backtests were conservative and honest… penalized for look-ahead bias, transaction
costs, and slippage." **No simulation was ever run.** Those numbers are generated prose, not
output from any code, data, or backtest harness. This is exactly the failure mode the
scoreboard discipline exists for: in this codebase, a performance claim without a runnable
harness behind it (`tests/backtest_engines.py` pattern) is treated as fiction regardless of
how rigorous the surrounding language sounds.

### A.2 — RERE vMax: rejected

The Grok thread then pushed for "maximum money" and the committee returned "locked in
aggressive mode": 1.5–2.5x leverage on short-dated options, 50–70% of capital in an
opportunistic bucket, *lowered* entry thresholds, "sequential doubling" as a target path, and
a self-issued "stress verdict" with no backtest, data, or numbers behind it.

**Rejected, for the record, on three grounds:**
1. It contradicts the standing operator decision of 2026-07-17 (paper-first, hard stops,
   fixed small sizing, explicitly not "a bot that always wins" — "sequential doubling" is
   that promise reworded).
2. It contradicts its own Phase-1-through-3 conclusions — a live demonstration of the
   Kydland-Prescott time-inconsistency problem that LAUREATE's rule 10 exists to prevent: a
   committee renegotiating its risk rules mid-session because the upside sounded good.
3. Its "circuit breaker at −10% drawdown" is not a real guardrail on a levered short-dated
   options book; gaps and vol spikes clear that level before any breaker fires.

### A.3 — "ScriptMaster DeltaForge": what is fiction vs. what is real

The Grok thread finished by pitching a product — a "DeltaForge API" at
`api.scriptmasterlabs.com/deltaforge/v1` with BYOK broker integration, tiered keys, and
sample Python client code generating market orders from its signals.

**Fiction (verified 2026-07-18):** no such API exists. The endpoint serves nothing; no repo in
this account implements `deltaforge/v1` routes; the sample client's signal JSON
(`conviction: 0.87` etc.) is invented. The Python client from that thread must never be run
with real API keys or broker credentials — it converts imaginary signals into real market
orders with no stops.

**How the real part came to exist (lineage, for the record):** the Grok thread ended by
writing a "master prompt for Claude Sonnet 5" naming Claude as the builder, plus a first-cut
Pine script of its own (v1.0/v1.1) that had compile errors and signal gates that could never
fire. That prompt/handoff is what spawned the parallel Claude session(s) whose work *was*
merged: the DeltaForge Pine strategies below, which replaced Grok's broken logic (impossible
momentum gate, scale-dependent thresholds) with working, backtestable Pine v6.

**Real (as of the same day):** the DeltaForge *name and concept* were implemented the honest
way, in those parallel sessions, as TradingView Pine strategies merged to main (PR #351 and
predecessors):
- `indicators/ScriptMaster_DeltaForge_v6.pine` (SM-DF v1.3)
- `indicators/ScriptMaster_DeltaForge_Flagship_v6.pine` (SM-DF-FLAG v2.1)

These are backtestable strategy scripts (behavioral-distortion + delta-gamma breakout, ATR
risk engine, regime filters), and the Flagship version emits the exact webhook JSON the
existing `/api/webhooks/tradingview` endpoint expects (`system: SML_DELTAFORGE`) — meaning
any execution flows through the **existing paper-first IAM executor with its hard stops**,
and only when a passphrase is deliberately configured. That is the correct architecture: the
strategy idea survived; the fictional API and the vMax leverage did not.

**If a DeltaForge signals *API product* is ever built for real:** it is a packaging decision
on top of existing infrastructure (x402-gated endpoints, Stripe-tiered key validation as in
CASCADE/AEO/Trade Desk, BYOK execution as in Trade Desk Pro, zero custody throughout) — with
signals from a *measured* engine that has earned a scoreboard entry, never fabricated
conviction numbers (Prime Directive: no demo data).

*Appendix recorded by the standing committee secretary. — 2026-07-18*
