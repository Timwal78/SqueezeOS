# MM LIQUIDITY ENGINE — TECHNICAL MANIFEST
## A Shadow-Cabinet Specification for Closed-Loop Dealer-Stress Capture

**Codename:** `MMLE` (Market Maker Liquidity Engine)
**Branch:** `claude/mm-liquidity-engine-zd7bO`
**Cadence:** 5-minute structural; 1-minute trigger overlay
**Governance:** Bound by `AGENT_LAW.md` (no simulated data, parameterized factors, transparent proxies)

---

## 1. Shadow-Cabinet Roundtable (Distilled)

### Quantitative Architect
> "Every retail tool stops at first-order Greek aggregation — total dealer gamma, ZGL, walls. The institutional edge is in the **second-order cross-derivatives**: Vanna (∂Δ/∂σ) and Charm (∂Δ/∂τ). Dealers don't only hedge price moves — they hedge the *vol surface* and the *clock*. When Vanna and Charm point the same way as Gamma, the dealer's hedge becomes mechanically forced along three axes simultaneously. That is the trapped state."

### Game Theorist
> "An MM is never 'wrong' — they are *positioned*. The pain point is when their positioning forces them to be the marginal buyer (or seller) into a low-resting-liquidity corridor. The market knows where the walls are; it does **not** price the corridor *between* walls. The corridor is the void. Force the void to be traversed and the dealer pays slippage to themselves — we collect the carry."

### Lead Systems Developer
> "Pine V6 cannot fetch the option chain directly. The architecture must be: heavy compute in Python (real chain → VEX/CEX/VPIN), publish the *regime tag* + *target magnet strike* to the Pine layer via webhook + tradingview alert, and use Pine only as the **execution gate** with iceberg slicing in `execution_engine.py`. The script's intent must look indistinguishable from a passive vol-targeting bot to the tape."

---

## 2. The "Ah-Ha" Mechanism — The Asymmetric Variable

> **Vanna/Charm Sign Concordance with Gamma (VCSC-Γ)**

Define, per front-month strike *K*:

```
sign_concord(K) = 1   if sign(γ_dealer(K)) == sign(vanna_dealer(K)) == sign(charm_dealer(K))
                = 0   otherwise
```

Aggregate over the OTM strike band (0.85·S … 1.15·S):

```
VCSC_Γ = Σ_K [ sign_concord(K) · |OI(K) · γ(K)| ]   /   Σ_K |OI(K) · γ(K)|
```

**The Asymmetric Insight (what the market is ignoring):**

The retail/quant consensus treats Γ, Vanna, and Charm as *independent* hedge demands and nets them. They are not independent at extremes — for **net-short-call dealers in declining-IV environments approaching expiry**, all three hedge flows *compound in the same direction*. When `VCSC_Γ > 0.70` and `Γ_total < Γ_threshold`, the dealer's hedge book is in a **Triple-Negative Trap (TNT)** regime: any move of price, vol, or time forces the same direction of underlying purchase/sale.

In TNT regime the dealer is no longer a passive flow-absorber — they are a **forced participant**. Price magnetizes to the nearest large-OI strike on the trapped side because the dealer's mechanical buying must traverse the liquidity void in between.

---

## 3. The Mathematical "Gotcha"

Total dealer hedge demand per Δt:

```
H(t) = -[ Γ · ΔS  +  Vanna · Δσ  +  Charm · Δτ  +  ½·Volga · (Δσ)²  +  Speed · (ΔS)² ]
```

**Standard practice:** track only `Γ · ΔS`. **The gotcha:** decompose H(t) by *axis-correlation*. Define the axis-weighted hedge force vector:

```
F_axis = ( Γ·σ_S ,  Vanna·σ_σ ,  Charm·1 )            (in units of shares/day)
```

If the cosine similarity between any two components of `F_axis` exceeds 0.85, the dealer's degrees of freedom collapse — vol-and-price moves no longer offset. The hedge demand is *deterministic* in regime, *stochastic* only in timing. The trade isn't predicting price; it's **harvesting a structurally pre-scheduled order flow**.

Trigger formula (closed form):

```
TNT_score =  z(VCSC_Γ)
           + z(-Γ_total)
           + z(VPIN)
           + z(|DarkLitDivergence|)
           + z(VoidWidth / ATR)

ENTER  if  TNT_score > τ_enter   AND   VCCW_open == True
EXIT   if  TNT_score < τ_exit    OR   spot crosses target_magnet
```

Where `VCCW_open` (Vanna-Charm Convergence Window) is true only during the window *T-3d → T-0* on the front-month expiry, between 09:45 and 15:30 ET (avoiding open-auction noise and MOC-cross distortion).

---

## 4. Five-Layer Closed-Loop Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  LAYER 1 — INGEST (real data only, AGENT_LAW §1)              │
│    • Tradier option chain (full chain, no DTE/strike caps)    │
│    • Polygon trades+quotes (NBBO, condition codes)            │
│    • Polygon dark-pool prints (TRF condition: D)              │
│    • VIX / VVIX / VIX9D term-structure                         │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  LAYER 2 — DEALER GREEK SURFACE (mm_liquidity_engine.py)       │
│    • Compute Γ(K), Vanna(K), Charm(K) per strike (BS analytic)│
│    • Sign-flip OI by side (calls dealer-short, puts dealer-long│
│      assumption — overrideable via SqueezeMetrics-style feed) │
│    • Build VEX, CEX surfaces; compute VCSC_Γ                  │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  LAYER 3 — FLOW TOXICITY & VOID MAP                            │
│    • VPIN (Easley/López de Prado, volume-clock buckets)       │
│    • Dark/Lit divergence: sign(Σ dark prints) vs lit OFI      │
│    • Liquidity-void scan: gap between adjacent |Γ·OI| peaks    │
│      normalized by 5-min ATR — voids > 1.5·ATR flagged        │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  LAYER 4 — REGIME CLASSIFIER (TNT detector)                    │
│    • z-score fusion of 5 features                              │
│    • Output: regime ∈ {NEUTRAL, COMPRESSED, TNT_LONG, TNT_SHORT}│
│    • target_magnet = nearest gamma wall on trapped side        │
│    • expected_traverse_time from HJB time-to-rebalance         │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  LAYER 5 — SHIELDED EXECUTION (Full Shield Protocol)           │
│    • Iceberg slicer: child_qty = floor(0.08 · bar_VWAP_vol)    │
│    • Cadence jitter: U(800ms, 2200ms) between children         │
│    • Peg-mid limit with ±2 tick band; cancel/replace on fade   │
│    • Fire only when lit-bid imbalance ≥ 0 (ride the flow)     │
│    • Pine V6 emits the `MMLE_FIRE` alert; Python executes      │
└────────────────────────────────────────────────────────────────┘
```

---

## 5. Full Shield Protocol — Why The Tape Won't See Us

| Concern                | Mitigation                                                       |
|------------------------|------------------------------------------------------------------|
| Order-print fingerprint | Child sizes pinned to current-bar VWAP slice → looks like passive VWAP bot |
| Cadence fingerprint     | Uniform-jitter delay between children; no fixed cron interval     |
| Strike fingerprint      | Hedge legs (if any) on adjacent expiries, not expiry-of-thesis   |
| Reverse-engineer logic  | Pine script ships only as alert-payload templates; no published source on TV |
| Webhook attribution     | Single anonymized HMAC-signed POST to `beast_webhook.py` only    |

---

## 6. Parameter Manifest (every coefficient is auditable — AGENT_LAW §2)

| Param                  | Default | Notes                                              |
|------------------------|---------|----------------------------------------------------|
| `vcsc_band_pct`        | 0.15    | OTM band ±15% around spot                          |
| `vcsc_min`             | 0.70    | TNT regime gate                                    |
| `gamma_total_max`      | -1e9    | $-gamma per 1% required for TNT                    |
| `vpin_bucket_vol_pct`  | 0.005   | volume-bucket size as fraction of ADV              |
| `vpin_window`          | 50      | bucket window for VPIN aggregation                 |
| `void_atr_mult`        | 1.5     | min void width in ATRs                             |
| `tnt_enter_z`          | 2.0     | composite z-score entry                            |
| `tnt_exit_z`           | 0.5     | composite z-score exit                             |
| `vccw_dte_max`         | 3       | front-month window (days)                          |
| `vccw_minute_open`     | 585     | 09:45 ET in minutes-from-midnight                  |
| `vccw_minute_close`    | 930     | 15:30 ET                                           |
| `iceberg_slice_pct`    | 0.08    | child / bar-VWAP-volume                            |
| `iceberg_jitter_ms`    | (800,2200) | uniform delay range                            |
| `dealer_call_short_assumption` | True | overrideable per-symbol via config            |

---

## 7. Failure Modes & Hard Stops

1. **Chain incomplete** → engine returns `{"state": "AWAITING_STREAM"}`; no signal emitted. (AGENT_LAW §1.1)
2. **VPIN bucket window unfilled** → mark `VPIN = None`; TNT requires non-null.
3. **Dark-print feed unavailable** → divergence component dropped from z-fusion *and* regime cap reduced to `COMPRESSED`. Logged `[ESTIMATED_PROXY: dark_lit_divergence_unavailable]`.
4. **Spot inside void mid-trade** → close 50% on first wall touch; trail balance with HJB.

---

## 8. Deliverables Shipped on This Branch

- `mm_liquidity_engine.py` — Layer 2-4 engine, integrates with `data_providers`, `gamma_flow_engine`, `hjb_hedging`.
- `pine/mm_liquidity_engine.pine` — Pine V6 visualization + execution gate.
- `MM_LIQUIDITY_ENGINE_MANIFEST.md` — this document.

---

*"The market doesn't get punished for being wrong — it gets punished for being **structurally exposed**. Find the structural exposure; the rest is collection."*
