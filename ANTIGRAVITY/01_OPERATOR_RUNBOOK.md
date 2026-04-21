# Antigravity Operator Runbook

## Goal
Use Google Antigravity to turn this bundle into a production-ready service without losing the institutional logic.

## Before you prompt
Open these files in order:
1. `SPEC_MASTER.md`
2. `MATH/OMEGA_FORMULAS.md`
3. `API/SCHEMAS.md`
4. `REPO_TREE.md`
5. `ANTIGRAVITY/PROMPTS.md`
6. `SKILLS/GUARDRAILS.md`

## Workspace setup
Create a fresh workspace using this directory as root.

## How to run the build
Use the prompts in `ANTIGRAVITY/PROMPTS.md` sequentially.
Do not combine them into one giant prompt.
Let Antigravity show the file tree first, then implement.

## Mandatory instruction to include in Antigravity
"Use the formulas in MATH/OMEGA_FORMULAS.md and the reference code in REFERENCE_IMPL/ as authoritative. Do not simplify logic into a generic trading dashboard or long/short signal generator."

## Mission Control / multi-agent split
Use four agents:
- Architect Agent: structure, schemas, service boundaries
- Core Logic Agent: formulas, fusion logic, scenario ranking
- API Agent: FastAPI routes, validation, serialization
- QA Agent: tests, edge cases, scoring sanity checks

## Acceptance checklist
- `/omega_scan` implemented
- schemas validated
- formulas wired exactly
- contradiction and deception penalties applied
- scenario ranking present
- narrative fusion present
- tests passing
- Docker setup present
