# ⚖️ REPOSITORY CONSTITUTION - THE "REAL DATA" LAW

**Effective Date:** 2026-04-13
**Subject:** SqueezeOS Institutional Data Integrity and Algorithmic Law.

This repository is governed by the **ScriptMasterLabs Master Integrity Law**. All future agents and developers are strictly bound by the following rules.

---

### LAW 1: NO SIMULATED DATA
No placeholders, faked GEX profiles, or "estimated" premium blocks.
- **Rule 1.1**: If Schwab or Polygon data is missing, the engine MUST pause or report "Awaiting Stream." NEVER invent dummy values.

### LAW 2: PARAMETERIZED ALPHA FACTORS
All HJB Kalman sensitivities, Gamma Flip thresholds, and DTE weights MUST reside in configuration. 
- **Rule 2.1**: No magic multipliers (e.g. `* 1.3`) hidden inside `gamma_flow_engine.py`. Every coefficient must be an auditable parameter.

### LAW 3: TRANSPARENT PROXIES
If a statistical proxy is required for calculation (e.g. using IV to estimate Gamma when missing), it must be labeled and quantified. 
- **Rule 3.1**: Estimated ATR (2% proxy) is permitted only when real bars are blocked, and must be logged as `[ESTIMATED_PROXY]`.

### LAW 4: INSTITUTIONAL CADENCE
Maintain the 5-minute evaluation cycle for structural signals to ensure signal quality over quantity.

---
**REFERENCE:** [DEVELOPER_MANIFESTO.md](file:///C:/Users/timot/.gemini/antigravity/scratch/SqueezeOS/DEVELOPER_MANIFESTO.md)
