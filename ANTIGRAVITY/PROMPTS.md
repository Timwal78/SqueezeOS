# Antigravity Prompt Pack

## Prompt 1 — scaffold the service
Read SPEC_MASTER.md, REPO_TREE.md, API/SCHEMAS.md, and MATH/OMEGA_FORMULAS.md.

Create a production-ready Python FastAPI service named `argus-omega` with:
- modular layout exactly matching REPO_TREE.md
- pydantic schemas from API/SCHEMAS.md
- omega fusion modules
- route POST /omega_scan
- tests folder
- Docker setup
- configuration via environment variables

Before writing code, show the proposed file tree.

Preserve institutional tone and adjudication logic. Do not simplify into a generic signal API.

## Prompt 2 — implement schemas and route contracts
Implement the schemas exactly as defined in API/SCHEMAS.md.
Implement POST /omega_scan request and response contracts.
Add serialization and validation, including bounded numeric ranges.

## Prompt 3 — implement scoring math
Implement the formulas in MATH/OMEGA_FORMULAS.md exactly.
Create modules for:
- normalization
- alignment
- conviction
- scenario ranking
- action mapping
- trigger synthesis
- narrative fusion

Use the reference code in REFERENCE_IMPL/ as authoritative pseudocode.
Include unit tests for each formula family.

## Prompt 4 — implement the fusion engine
Implement a FusionEngine that:
- computes derived strengths
- computes alignment_state
- computes omega_score
- computes conviction bucket
- ranks scenarios
- assigns risk_state
- assigns action_class
- synthesizes trigger_map
- generates narrative briefing

Use `REFERENCE_IMPL/omega_reference.py` for logic and expected behavior.
Return the full response shape from API/SCHEMAS.md.

## Prompt 5 — harden for edge cases
Audit and improve the implementation for:
- missing optional magnet / trigger values
- near-tie scenario probabilities
- contradictory directional signals
- high deception with bullish alignment
- fractured bias handling
- bounded outputs and clamping

Add or update tests for these cases.

## Prompt 6 — package and explain
Provide:
- Dockerfile
- docker-compose.yml
- `.env.example`
- run instructions
- architecture summary
- test instructions
- example request and response
