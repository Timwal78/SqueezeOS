#!/usr/bin/env bash
# cli/submit-to-registry.sh — fork printing-press-library and open a PR adding our 3 CLIs
# Usage: GH_TOKEN=ghp_xxx bash cli/submit-to-registry.sh
set -euo pipefail

: "${GH_TOKEN:?Set GH_TOKEN=ghp_... before running}"

OWNER="Timwal78"
UPSTREAM="mvanhorn/printing-press-library"
FORK="$OWNER/printing-press-library"
BRANCH="add-sml-clis"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

API="https://api.github.com"
AUTH=(-H "Authorization: token $GH_TOKEN" -H "Accept: application/vnd.github+json")

# ── 1. Fork ───────────────────────────────────────────────────────────────────
echo "▶ Forking $UPSTREAM …"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${AUTH[@]}" \
  "$API/repos/$UPSTREAM/forks" -d "{\"organization\":null}")
if [ "$HTTP" = "202" ] || [ "$HTTP" = "200" ]; then
  echo "  ✓ Fork queued — waiting 8s for GitHub to provision …"
  sleep 8
elif [ "$HTTP" = "422" ]; then
  echo "  ↩ Fork already exists"
else
  echo "  ✗ Fork failed HTTP $HTTP"; exit 1
fi

# ── 2. Clone fork ─────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "▶ Cloning fork …"
git clone -q "https://$GH_TOKEN@github.com/$FORK.git" "$TMP/repo"
cd "$TMP/repo"
git config user.name "Timwal78"
git config user.email "timothy.walton45@gmail.com"
git config commit.gpgsign false
git checkout -b "$BRANCH"

# ── 3. Copy CLI source trees ──────────────────────────────────────────────────
echo "▶ Copying CLI source files …"

mkdir -p library/developer-tools/squeezeos
mkdir -p library/payments/ghost-layer
mkdir -p library/social-and-messaging/tipmaster

for PAIR in "squeezeos:developer-tools/squeezeos" "ghost-layer:payments/ghost-layer" "tipmaster:social-and-messaging/tipmaster"; do
  SRC="${PAIR%%:*}"
  DST="library/${PAIR##*:}"
  cp -r "$SCRIPT_DIR/$SRC/." "$DST/"
done

# ── 4. Add README, SKILL, LICENSE for each ───────────────────────────────────

cat > library/developer-tools/squeezeos/README.md << 'EOF'
# squeezeos-pp-cli

CLI Printing Press generated CLI for the [SqueezeOS](https://squeezeos-api.onrender.com) institutional market intelligence API.

## Install

```bash
go install github.com/timwal78/squeezeos-pp-cli@latest
```

## Authentication

Premium endpoints (`council`, `scan`, `options`, `iwm`) require a payment token from [402Proof](https://four02proof.onrender.com). Agents pay RLUSD on XRPL and receive a 1-hour signed JWT — no API keys, no subscriptions.

```bash
export SQUEEZEOS_TOKEN=<token-from-402proof>
```

## Quick Start

```bash
squeezeos demo                        # free IWM council verdict
squeezeos preview TSLA                # bias + regime preview (free)
squeezeos status                      # system health
squeezeos council NVDA                # AI council verdict (paid)
squeezeos scan                        # full squeeze scanner (paid)
```

## Source

Generated from OpenAPI spec at `https://squeezeos-api.onrender.com/.well-known/openapi.json`
EOF

cat > library/developer-tools/squeezeos/SKILL.md << 'EOF'
# SqueezeOS CLI Skill

Use `squeezeos-pp-cli` to access institutional AI trading intelligence.

## Key Agent Patterns

```bash
# Free daily bias check
squeezeos preview IWM --compact | jq '{bias:.bias, regime:.regime}'

# Pay-gated full council verdict (needs SQUEEZEOS_TOKEN)
squeezeos council NVDA --compact

# Squeeze scanner — find setups
squeezeos scan --compact | jq '.candidates[:5]'

# Check options flow
squeezeos options --compact
```

## Payment Flow (autonomous agents)

1. `squeezeos status` — confirm service live
2. Visit `https://four02proof.onrender.com` to purchase a token with RLUSD
3. Set `SQUEEZEOS_TOKEN=<jwt>`
4. Call premium endpoints

## Related Tools

- `ghost-layer-pp-cli` — execute XRPL payments to buy tokens
- `tipmaster-pp-cli` — resolve Farcaster usernames to XRPL wallets
EOF

cat > library/payments/ghost-layer/README.md << 'EOF'
# ghost-layer-pp-cli

CLI Printing Press generated CLI for [Ghost Layer](https://ghost-layer.onrender.com) — proprietary dual-chain XRPL/Base toll gateway.

## Install

```bash
go install github.com/timwal78/ghost-layer-pp-cli@latest
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GHOST_LAYER_WALLET` | Your XRPL wallet address (sent as `X-Agent-Wallet`) |
| `GHOST_LAYER_BASE_URL` | Override base URL (default: `https://ghost-layer.onrender.com`) |

## Quick Start

```bash
ghost-layer status                                        # health check
ghost-layer x402 catalog                                  # list purchasable products
ghost-layer x402 quote --product routing.telemetry \
  --wallet rXXX                                           # get payment quote
ghost-layer x402 dispense routing.telemetry               # dispense after payment
ghost-layer agent rXXX                                    # loyalty tier + Passport level
ghost-layer cube state                                    # 54-block execution matrix
```

## Source

API spec: `https://ghost-layer.onrender.com/.well-known/openapi.json`
EOF

cat > library/payments/ghost-layer/SKILL.md << 'EOF'
# Ghost Layer CLI Skill

Use `ghost-layer-pp-cli` to interact with the Ghost Layer dual-chain XRPL/Base toll gateway.

## Recommended Agent Flow

```bash
ghost-layer status                                    # 1. confirm live
ghost-layer x402 catalog --compact                    # 2. list products
ghost-layer x402 quote --product routing.telemetry \  # 3. get quote
  --wallet $WALLET --compact
# 4. Pay on XRPL: send RLUSD to pay_to with memo_hex as MemoData
ghost-layer x402 dispense routing.telemetry --compact # 5. dispense after payment
ghost-layer agent $WALLET --compact                   # 6. check loyalty tier
```

## Related Tools

- `squeezeos-pp-cli` — market intelligence powered by Ghost Layer infrastructure
- `tipmaster-pp-cli` — Farcaster tip bot running on Ghost Layer
EOF

cat > library/social-and-messaging/tipmaster/README.md << 'EOF'
# tipmaster-pp-cli

CLI Printing Press generated CLI for [TipMaster](https://tipmaster.onrender.com) — zero-custody Farcaster RLUSD tip bot.

## Install

```bash
go install github.com/timwal78/tipmaster-pp-cli@latest
```

## Quick Start

```bash
tipmaster resolve dwr                        # resolve Farcaster username → XRPL wallet
tipmaster leaderboard                        # top 10 tippers this week
tipmaster leaderboard --period alltime       # all-time leaderboard
tipmaster user 3                             # look up user by Farcaster FID
tipmaster status                             # service health
```

## Key Agent Use Case

`resolve` lets any AI agent look up an XRPL wallet address by Farcaster username without asking the user for their wallet — enabling fully autonomous RLUSD tipping:

```bash
WALLET=$(tipmaster resolve dwr --compact | jq -r '.wallet_address')
# then pay via ghost-layer or directly on XRPL
```

## Source

API: `https://tipmaster.onrender.com/api/status`
EOF

cat > library/social-and-messaging/tipmaster/SKILL.md << 'EOF'
# TipMaster CLI Skill

Use `tipmaster-pp-cli` to resolve Farcaster usernames and interact with the RLUSD tip bot.

## Key Patterns

```bash
# Resolve a Farcaster username to XRPL wallet
tipmaster resolve <username> --compact | jq -r '.wallet_address'

# Full autonomous tip flow (combine with ghost-layer)
WALLET=$(tipmaster resolve dwr --compact | jq -r '.wallet_address')
ghost-layer bridge --chain XRPL --recipient "$WALLET" --amount 1000000

# Weekly leaderboard
tipmaster leaderboard --compact | jq '.top_tippers[:3]'
```

## Related Tools

- `ghost-layer-pp-cli` — execute the actual XRPL payment after resolving
- `squeezeos-pp-cli` — market signals to decide who/when to tip
EOF

# MIT LICENSE for all three
LICENSE_TEXT="MIT License

Copyright (c) 2026 Timothy Walton / Script Master Labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."

echo "$LICENSE_TEXT" > library/developer-tools/squeezeos/LICENSE
echo "$LICENSE_TEXT" > library/payments/ghost-layer/LICENSE
echo "$LICENSE_TEXT" > library/social-and-messaging/tipmaster/LICENSE

# ── 5. Patch registry.json ────────────────────────────────────────────────────
echo "▶ Patching registry.json …"

python3 - << 'PYEOF'
import json, sys

with open("registry.json") as f:
    reg = json.load(f)

new_entries = [
    {
        "name": "squeezeos",
        "category": "developer-tools",
        "api": "SqueezeOS",
        "description": "Institutional-grade AI trading intelligence — squeeze scanner, options flow, AI council verdicts, signal marketplace, futures market, and conditional settlement contracts. Pay-per-call with RLUSD on XRPL via 402Proof; free tier available.",
        "search_terms": [
            "squeezeos", "SqueezeOS", "squeezeos-pp-cli",
            "market intelligence", "squeeze scanner", "options flow",
            "AI trading", "RLUSD", "XRPL", "institutional trading",
            "council verdict", "signal marketplace", "futures market",
            "x402 payments", "Script Master Labs"
        ],
        "path": "library/developer-tools/squeezeos",
        "printer": "timwal78",
        "printer_name": "Timothy Walton",
        "mcp": {
            "binary": "squeezeos-pp-mcp",
            "transports": ["stdio"],
            "tool_count": 23,
            "public_tool_count": 8,
            "auth_type": "api_key",
            "env_vars": ["SQUEEZEOS_TOKEN", "SQUEEZEOS_BASE_URL"],
            "mcp_ready": "full",
            "spec_format": "openapi3"
        }
    },
    {
        "name": "ghost-layer",
        "category": "payments",
        "api": "Ghost Layer",
        "description": "Proprietary dual-chain XRPL/Base toll gateway. Purchase x402 products, execute cross-chain settlements, query agent loyalty tiers and Passport levels, and inspect the 54-block execution matrix.",
        "search_terms": [
            "ghost-layer", "Ghost Layer", "ghost-layer-pp-cli",
            "XRPL", "Base chain", "cross-chain settlement", "x402",
            "toll gateway", "RLUSD payments", "agent passport",
            "URIToken", "Script Master Labs", "xrpl bridge"
        ],
        "path": "library/payments/ghost-layer",
        "printer": "timwal78",
        "printer_name": "Timothy Walton",
        "mcp": {
            "binary": "ghost-layer-pp-mcp",
            "transports": ["stdio"],
            "tool_count": 8,
            "public_tool_count": 4,
            "auth_type": "none",
            "env_vars": ["GHOST_LAYER_WALLET", "GHOST_LAYER_BASE_URL"],
            "mcp_ready": "full",
            "spec_format": "openapi3"
        }
    },
    {
        "name": "tipmaster",
        "category": "social-and-messaging",
        "api": "TipMaster",
        "description": "Zero-custody Farcaster RLUSD tip bot. Resolve Farcaster usernames to XRPL wallet addresses, browse weekly and all-time tipping leaderboards, and look up users by FID — enabling fully autonomous agent tipping flows.",
        "search_terms": [
            "tipmaster", "TipMaster", "tipmaster-pp-cli",
            "Farcaster", "RLUSD", "XRPL", "tip bot",
            "wallet resolver", "Farcaster FID", "leaderboard",
            "autonomous tipping", "Script Master Labs", "social tipping"
        ],
        "path": "library/social-and-messaging/tipmaster",
        "printer": "timwal78",
        "printer_name": "Timothy Walton",
        "mcp": {
            "binary": "tipmaster-pp-mcp",
            "transports": ["stdio"],
            "tool_count": 5,
            "public_tool_count": 5,
            "auth_type": "none",
            "env_vars": ["TIPMASTER_BASE_URL"],
            "mcp_ready": "full",
            "spec_format": "openapi3"
        }
    }
]

# Insert alphabetically by name
entries = reg["entries"]
for entry in new_entries:
    # Remove if already exists
    entries = [e for e in entries if e["name"] != entry["name"]]
    # Find insert position
    pos = next((i for i, e in enumerate(entries) if e["name"] > entry["name"]), len(entries))
    entries.insert(pos, entry)

reg["entries"] = entries

with open("registry.json", "w") as f:
    json.dump(reg, f, indent=2)
    f.write("\n")

print(f"  ✓ registry.json updated — {len(reg['entries'])} total entries")
PYEOF

# ── 6. Commit and push ────────────────────────────────────────────────────────
echo "▶ Committing …"
git add -A
GIT_CONFIG_NOSYSTEM=1 \
GIT_AUTHOR_NAME="Timwal78" \
GIT_AUTHOR_EMAIL="timothy.walton45@gmail.com" \
GIT_COMMITTER_NAME="Timwal78" \
GIT_COMMITTER_EMAIL="timothy.walton45@gmail.com" \
  git -c commit.gpgsign=false commit -q -m \
  "feat: add squeezeos, ghost-layer, tipmaster CLIs from Script Master Labs

Three CLI Printing Press compatible Go/Cobra CLIs for the SML product stack:

- developer-tools/squeezeos: institutional AI market intelligence, pay-per-call
  via 402Proof RLUSD payments on XRPL (23 MCP tools)
- payments/ghost-layer: dual-chain XRPL/Base toll gateway, x402 product catalog
  and cross-chain settlement (8 MCP tools)
- social-and-messaging/tipmaster: Farcaster RLUSD tip bot, username→wallet
  resolver enabling autonomous agent tipping flows (5 MCP tools)

All three pass go build ./... and go vet ./..."

echo "▶ Pushing branch …"
git push -q "https://$GH_TOKEN@github.com/$FORK.git" "$BRANCH"

# ── 7. Open PR ────────────────────────────────────────────────────────────────
echo "▶ Opening PR …"
PR=$(curl -s -X POST "${AUTH[@]}" \
  "$API/repos/$UPSTREAM/pulls" \
  -d "{
    \"title\": \"feat: add squeezeos, ghost-layer, tipmaster CLIs (Script Master Labs)\",
    \"head\": \"$OWNER:$BRANCH\",
    \"base\": \"main\",
    \"body\": \"## Summary\\n\\nThree CLI Printing Press compatible Go/Cobra CLIs for the [Script Master Labs](https://www.scriptmasterlabs.com) product stack.\\n\\n### squeezeos-pp-cli — \`library/developer-tools/squeezeos\`\\n\\nInstitutional-grade AI trading intelligence API. Squeeze scanner, options flow, AI council verdicts, signal marketplace, futures market, conditional settlement contracts. Pay-per-call with RLUSD on XRPL via [402Proof](https://four02proof.onrender.com) — no API keys, no subscriptions. Free tier available.\\n\\n- 23 MCP tools, \`auth_type: api_key\` (x402 JWT from 402Proof)\\n- Source: https://github.com/Timwal78/squeezeos-pp-cli\\n- API: https://squeezeos-api.onrender.com/.well-known/openapi.json\\n\\n### ghost-layer-pp-cli — \`library/payments/ghost-layer\`\\n\\nProprietary dual-chain XRPL/Base toll gateway. Purchase x402 products, execute cross-chain settlements, query agent loyalty tiers and Passport levels, inspect the 54-block execution matrix.\\n\\n- 8 MCP tools, \`auth_type: none\` (read endpoints public, bridge needs XRPL sig)\\n- Source: https://github.com/Timwal78/ghost-layer-pp-cli\\n- API: https://ghost-layer.onrender.com/.well-known/openapi.json\\n\\n### tipmaster-pp-cli — \`library/social-and-messaging/tipmaster\`\\n\\nZero-custody Farcaster RLUSD tip bot. Resolve Farcaster usernames to XRPL wallet addresses — the primary use case for autonomous agent tipping flows.\\n\\n- 5 MCP tools, \`auth_type: none\` (all public)\\n- Source: https://github.com/Timwal78/tipmaster-pp-cli\\n- API: https://tipmaster.onrender.com/api/status\\n\\n## Test plan\\n\\n- [ ] \`cd library/developer-tools/squeezeos && go build ./...\`\\n- [ ] \`cd library/payments/ghost-layer && go build ./...\`\\n- [ ] \`cd library/social-and-messaging/tipmaster && go build ./...\`\\n- [ ] Each binary responds to \`--help\` and \`--version\`\\n- [ ] registry.json entries are alphabetically inserted\\n\"
  }")

PR_URL=$(echo "$PR" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('html_url','(check response)'))")
echo ""
echo "✓ PR opened: $PR_URL"
echo ""
echo "IMPORTANT: Revoke your token at https://github.com/settings/tokens"
