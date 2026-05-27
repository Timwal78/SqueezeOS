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

echo "▶ Forking $UPSTREAM …"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${AUTH[@]}" \
  "$API/repos/$UPSTREAM/forks" -d '{"organization":null}')
if [ "$HTTP" = "202" ] || [ "$HTTP" = "200" ]; then
  echo "  ✓ Fork queued — waiting 8s …"
  sleep 8
elif [ "$HTTP" = "422" ]; then
  echo "  ↩ Fork already exists"
else
  echo "  ✗ Fork failed HTTP $HTTP"; exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "▶ Cloning fork …"
git clone -q "https://$GH_TOKEN@github.com/$FORK.git" "$TMP/repo"
cd "$TMP/repo"
git config user.name "Timwal78"
git config user.email "timothy.walton45@gmail.com"
git config commit.gpgsign false
git checkout -b "$BRANCH"

echo "▶ Copying CLI source files …"
mkdir -p library/developer-tools/squeezeos
mkdir -p library/payments/ghost-layer
mkdir -p library/social-and-messaging/tipmaster

for PAIR in "squeezeos:developer-tools/squeezeos" "ghost-layer:payments/ghost-layer" "tipmaster:social-and-messaging/tipmaster"; do
  SRC="${PAIR%%:*}"
  DST="library/${PAIR##*:}"
  cp -r "$SCRIPT_DIR/$SRC/." "$DST/"
done

MIT_LICENSE="MIT License\n\nCopyright (c) 2026 Timothy Walton / Script Master Labs\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the \"Software\"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."

printf '%b\n' "$MIT_LICENSE" > library/developer-tools/squeezeos/LICENSE
printf '%b\n' "$MIT_LICENSE" > library/payments/ghost-layer/LICENSE
printf '%b\n' "$MIT_LICENSE" > library/social-and-messaging/tipmaster/LICENSE

cat > library/developer-tools/squeezeos/README.md << 'MDEOF'
# squeezeos-pp-cli

CLI Printing Press generated CLI for [SqueezeOS](https://squeezeos-api.onrender.com) — institutional AI market intelligence.

## Install

```bash
go install github.com/timwal78/squeezeos-pp-cli@latest
```

## Quick Start

```bash
squeezeos demo                 # free IWM verdict
squeezeos preview TSLA         # bias + regime (free)
squeezeos status               # health check
squeezeos council NVDA         # AI verdict (paid, needs SQUEEZEOS_TOKEN)
squeezeos scan                 # squeeze scanner (paid)
```

## Auth

Premium endpoints require a JWT from [402Proof](https://four02proof.onrender.com).
Agents pay RLUSD on XRPL — no API keys, no subscriptions.

```bash
export SQUEEZEOS_TOKEN=<token-from-402proof>
```
MDEOF

cat > library/developer-tools/squeezeos/SKILL.md << 'MDEOF'
# SqueezeOS CLI Skill

```bash
squeezeos preview IWM --compact | jq '{bias:.bias, regime:.regime}'
squeezeos council NVDA --compact   # needs SQUEEZEOS_TOKEN
squeezeos scan --compact
```

**Related:** `ghost-layer-pp-cli`, `tipmaster-pp-cli`
MDEOF

cat > library/payments/ghost-layer/README.md << 'MDEOF'
# ghost-layer-pp-cli

CLI Printing Press generated CLI for [Ghost Layer](https://ghost-layer.onrender.com) — dual-chain XRPL/Base toll gateway.

## Install

```bash
go install github.com/timwal78/ghost-layer-pp-cli@latest
```

## Quick Start

```bash
ghost-layer status
ghost-layer x402 catalog
ghost-layer x402 quote --product routing.telemetry --wallet rXXX
ghost-layer x402 dispense routing.telemetry
ghost-layer agent rXXX
```
MDEOF

cat > library/payments/ghost-layer/SKILL.md << 'MDEOF'
# Ghost Layer CLI Skill

```bash
ghost-layer status
ghost-layer x402 catalog --compact
ghost-layer x402 quote --product routing.telemetry --wallet $WALLET --compact
ghost-layer x402 dispense routing.telemetry --compact
```

**Related:** `squeezeos-pp-cli`, `tipmaster-pp-cli`
MDEOF

cat > library/social-and-messaging/tipmaster/README.md << 'MDEOF'
# tipmaster-pp-cli

CLI Printing Press generated CLI for [TipMaster](https://tipmaster.onrender.com) — zero-custody Farcaster RLUSD tip bot.

## Install

```bash
go install github.com/timwal78/tipmaster-pp-cli@latest
```

## Quick Start

```bash
tipmaster resolve dwr                  # Farcaster username → XRPL wallet
tipmaster leaderboard                  # top 10 tippers this week
tipmaster leaderboard --period alltime
tipmaster user 3                       # look up by FID
tipmaster status
```
MDEOF

cat > library/social-and-messaging/tipmaster/SKILL.md << 'MDEOF'
# TipMaster CLI Skill

```bash
WALLET=$(tipmaster resolve dwr --compact | jq -r '.wallet_address')
ghost-layer bridge --chain XRPL --recipient "$WALLET" --amount 1000000
```

**Related:** `ghost-layer-pp-cli`, `squeezeos-pp-cli`
MDEOF

echo "▶ Patching registry.json …"
python3 - << 'PYEOF'
import json
with open("registry.json") as f:
    reg = json.load(f)
new_entries = [
    {"name":"ghost-layer","category":"payments","api":"Ghost Layer","description":"Proprietary dual-chain XRPL/Base toll gateway. Purchase x402 products, execute cross-chain settlements, query agent loyalty tiers.","search_terms":["ghost-layer","Ghost Layer","XRPL","Base chain","x402","cross-chain","toll gateway","RLUSD","Script Master Labs"],"path":"library/payments/ghost-layer","printer":"timwal78","printer_name":"Timothy Walton","mcp":{"binary":"ghost-layer-pp-mcp","transports":["stdio"],"tool_count":8,"public_tool_count":4,"auth_type":"none","env_vars":["GHOST_LAYER_WALLET","GHOST_LAYER_BASE_URL"],"mcp_ready":"full","spec_format":"openapi3"}},
    {"name":"squeezeos","category":"developer-tools","api":"SqueezeOS","description":"Institutional-grade AI trading intelligence — squeeze scanner, options flow, AI council verdicts, signal marketplace, futures market. Pay-per-call with RLUSD on XRPL via 402Proof.","search_terms":["squeezeos","SqueezeOS","market intelligence","squeeze scanner","options flow","AI trading","RLUSD","XRPL","institutional trading","Script Master Labs"],"path":"library/developer-tools/squeezeos","printer":"timwal78","printer_name":"Timothy Walton","mcp":{"binary":"squeezeos-pp-mcp","transports":["stdio"],"tool_count":23,"public_tool_count":8,"auth_type":"api_key","env_vars":["SQUEEZEOS_TOKEN","SQUEEZEOS_BASE_URL"],"mcp_ready":"full","spec_format":"openapi3"}},
    {"name":"tipmaster","category":"social-and-messaging","api":"TipMaster","description":"Zero-custody Farcaster RLUSD tip bot. Resolve Farcaster usernames to XRPL wallet addresses, browse tipping leaderboards — enabling autonomous agent tipping flows.","search_terms":["tipmaster","TipMaster","Farcaster","RLUSD","XRPL","tip bot","wallet resolver","Farcaster FID","Script Master Labs"],"path":"library/social-and-messaging/tipmaster","printer":"timwal78","printer_name":"Timothy Walton","mcp":{"binary":"tipmaster-pp-mcp","transports":["stdio"],"tool_count":5,"public_tool_count":5,"auth_type":"none","env_vars":["TIPMASTER_BASE_URL"],"mcp_ready":"full","spec_format":"openapi3"}}
]
entries = reg["entries"]
for entry in new_entries:
    entries = [e for e in entries if e["name"] != entry["name"]]
    pos = next((i for i, e in enumerate(entries) if e["name"] > entry["name"]), len(entries))
    entries.insert(pos, entry)
reg["entries"] = entries
with open("registry.json", "w") as f:
    json.dump(reg, f, indent=2)
    f.write("\n")
print(f"  registry.json: {len(reg['entries'])} entries")
PYEOF

echo "▶ Committing …"
git add -A
GIT_CONFIG_NOSYSTEM=1 \
GIT_AUTHOR_NAME="Timwal78" \
GIT_AUTHOR_EMAIL="timothy.walton45@gmail.com" \
GIT_COMMITTER_NAME="Timwal78" \
GIT_COMMITTER_EMAIL="timothy.walton45@gmail.com" \
  git -c commit.gpgsign=false commit -q -m \
  "feat: add squeezeos, ghost-layer, tipmaster CLIs from Script Master Labs"

echo "▶ Pushing …"
git push -q "https://$GH_TOKEN@github.com/$FORK.git" "$BRANCH" --force

echo "▶ Opening PR …"
PR=$(curl -s -X POST "${AUTH[@]}" \
  "$API/repos/$UPSTREAM/pulls" \
  -d '{"title":"feat: add squeezeos, ghost-layer, tipmaster CLIs (Script Master Labs)","head":"Timwal78:add-sml-clis","base":"main","body":"Three CLI Printing Press Go/Cobra CLIs for the Script Master Labs product stack.\n\n- `library/developer-tools/squeezeos` — institutional AI market intelligence, pay-per-call via 402Proof RLUSD\n- `library/payments/ghost-layer` — dual-chain XRPL/Base toll gateway\n- `library/social-and-messaging/tipmaster` — Farcaster RLUSD tip bot, username→wallet resolver\n\nAll three pass `go build ./...`."}' 2>/dev/null || echo '{}')
echo "$PR" | python3 -c "import json,sys; d=json.load(sys.stdin); print('PR:', d.get('html_url', d.get('message', 'check GitHub')))"
