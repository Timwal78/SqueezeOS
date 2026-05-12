# SKILL: ScriptMaster Perpetual Alignment Agent
**Version**: 1.0  
**Engine**: Antigravity Beast Mode  
**Scope**: GME / AMC perpetual calendar alignment, FTD cycle monitoring, pre-market gating

---

## Goal

Monitor GME/AMC alignment between the Gregorian and Julian calendars,
T+35 FTD settlement clusters, and 666-day cycle completions from the
October 2020 anchor date. Surface all critical state to the Beast Mode
command center dashboard.

---

## Instructions

### 1. Julian Offset (Daily)
- Apply a **−13 day** offset from the current Gregorian date to compute the Julian date.
- Display both dates prominently in the dashboard Calendar Sync panel.
- Source: `alignment_logic.js → getJulianDate()`

### 2. T+35 Settlement Cluster Detection
- Consume output from `ftd_monitor.py` (written to `ftd_state.json`).
- Flag any FTD whose **T+35 date** falls within **±3 calendar days** of today.
- Severity tiers:
  - `SETTLEMENT_DAY` → MAGENTA pulsing alert
  - `T+35 IN ≤2d`   → ORANGE warning
  - `OVERDUE`        → RED critical
- Source: `ftd_monitor.py → detect_clusters()`

### 3. 666-Day Cycle Completion
- Anchor date: **October 14, 2020**
- Cycle length: **666 calendar days**
- Compute `days_since_anchor % 666`:
  - If `== 0` → status = `IGNITION` (magenta alert)
  - Otherwise → status = `COILING` + days remaining
- Source: `alignment_logic.js → checkCycleCompletion()`

### 4. Pre-Market News Window Gate
- Window: **4:00 AM – 5:30 AM Eastern Time (ET)**
- During this window, heighten alert sensitivity.
- Log "PRE-MARKET WINDOW ACTIVE" to the dashboard system log.
- Source: `alignment_logic.js → isPreMarketWindow()`

---

## Constraints

1. **Never ignore the 4:00 AM pre-market news window.** All gap-up/gap-down
   events for AMC and GME must be captured in this window.
2. FTD data must be refreshed at least every **5 minutes** during market hours.
3. The dashboard must remain active **24/7**. Do not throttle polling overnight
   as pre-market events occur before regular hours.
4. When IGNITION status is detected, trigger all available alert channels.
5. Julian/Gregorian sync must be recomputed on every clock tick (1-second).

---

## Activation Prompt

> "Antigravity, activate the ScriptMaster Alignment Skill and monitor
> the 4:00 AM pre-market for AMC gap-ups."

This prompt triggers:
1. `ftd_monitor.py` startup (background process)
2. `dashboard.html` opened in browser
3. All panels initialized with live data
4. Pre-market window gate armed

---

## File Map

| File                  | Purpose                                      |
|-----------------------|----------------------------------------------|
| `SKILL.md`            | This file — master orchestration instructions |
| `alignment_logic.js`  | Gregorian/Julian math, 666-cycle, T+35        |
| `ftd_monitor.py`      | FMP API FTD fetch + cluster detection loop    |
| `dashboard.html`      | Beast Mode command center UI                  |
| `config.json`         | API keys and parameters                       |
| `ftd_state.json`      | Live output from `ftd_monitor.py` (auto-gen)  |

---

## Deployment

```bash
# 1. Install Python deps
pip install requests

# 2. Set your FMP API key in config.json

# 3. Start the FTD monitor (background)
python ftd_monitor.py

# 4. Open the dashboard
start dashboard.html
```
