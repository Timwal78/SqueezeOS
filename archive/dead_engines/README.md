# Archived Modules

Files in this directory are **not loaded by the running SqueezeOS server**.
They are preserved here for historical reference and to make resurrection
straightforward if any of these features comes back into scope.

`git mv` was used so commit history is intact — `git log --follow archive/dead_engines/<file>.py`
will trace the file from its original root-level path.

| File | Original purpose | Why archived |
|------|------------------|--------------|
| `audit_squeezeos.py` | Standalone repo auditor | Superseded by ad-hoc Claude/agent audits; no callers |
| `beast_webhook.py` | Discord webhook handler for "Beast" alerts | No callers; live alerts route through `discord_alerts.py` |
| `credit_repair_server.py` | Standalone Flask service draft for credit-bureau dispute flow | Feature never wired into the main app |
| `cycle_intelligence_engine.py` | Market-cycle detection prototype | Only consumer was `run_cie.py` (deleted) |
| `forced_move_engine.py` | Forced-move detection signal | Imported only by deleted `test_imports.py` |
| `kdp_sentinel_engine.py` | KDP sentinel prototype | Same — only used by deleted tests |
| `mean_reversion_engine.py` | Standalone mean-reversion signal | Superseded by `rmre_bridge.py` (regime/mean-reversion bridge that's actually loaded) |
| `mm_liquidity_engine.py` | Earlier draft of the market-maker liquidity engine | Replaced by `mmle_engine.py` which is what core/ imports |
| `options_service.py` | Pre-blueprint options service | Functionality now in `options_intelligence.py` + `core/api/premium_bp.py` |
| `squeeze_launch.py` | Local Windows launcher for `server_v5.py` | Both `server_v5.py.legacy_backup` and this launcher are obsolete; production runs via `gunicorn "core.app:create_app()"` |
| `sr_patterns_engine.py` | Support/resistance pattern engine | No callers anywhere in the live app |
| `watchdog.py` | Process-supervisor draft | Render handles process supervision; never integrated |

## Restoring a file

```bash
git mv archive/dead_engines/<file>.py <file>.py
```

Then wire it back into `core/legacy.py` / a blueprint as appropriate and
verify imports work.
