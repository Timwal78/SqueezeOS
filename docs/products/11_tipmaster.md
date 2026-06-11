# 11 — Tipmaster (Institutional Tip Aggregation + Alerts)

**Live URL:** https://tipmaster.onrender.com
**Repo path:** `tipmaster/`
**Language:** Python
**Deploy:** Render (cloud, 24/7)

---

## What It Does
Institutional tip aggregation and alert delivery. Aggregates signal tips from across the stack — GOD MODE hits, TRIPLE_LOCK fires, dark pool block prints — and routes them to the appropriate delivery channels (Discord, webhook, mobile push).

## Repo Structure
- `tipmaster/app/` — Flask application
- `tipmaster/static/` — static assets

## Links To
- **SqueezeOS [01]** — primary signal source (GOD MODE, TRIPLE_LOCK, DUAL GRID LOCK)
- **Shadow Desk [05]** — dark pool block prints
- **Ghost Layer [02]** — execution confirmations
- **Discord** — primary delivery channel
- **Neural_OS Mobile [12]** — push notifications
