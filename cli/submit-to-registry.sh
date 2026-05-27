#!/usr/bin/env bash
# cli/submit-to-registry.sh — open one separate PR per CLI in printing-press-library
# Usage: GH_TOKEN=ghp_xxx bash cli/submit-to-registry.sh
set -euo pipefail

: "${GH_TOKEN:?Set GH_TOKEN=ghp_... before running}"

OWNER="Timwal78"
UPSTREAM="mvanhorn/printing-press-library"
FORK="$OWNER/printing-press-library"
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

# ── 3. Helper: submit one CLI as its own branch + PR ─────────────────────────
submit_cli() {
  local SRC="$1"        # e.g. squeezeos
  local CAT="$2"        # e.g. developer-tools
  local SLUG="$3"       # e.g. squeezeos
  local BINARY="$4"     # e.g. squeezeos-pp-cli
  local OLD_MOD="$5"    # e.g. github.com/timwal78/squeezeos-pp-cli
  local PR_TITLE="$6"
  local PR_BODY="$7"

  local BRANCH="add-${SLUG}-cli"
  local DST="library/$CAT/$SLUG"
  local NEW_MOD="github.com/mvanhorn/printing-press-library/library/$CAT/$SLUG"

  echo ""
  echo "━━━ $BINARY ━━━"

  # Fresh branch from main for each CLI
  git checkout -q main
  git checkout -B "$BRANCH"

  mkdir -p "$DST"
  cp -r "$SCRIPT_DIR/$SRC/." "$DST/"

  # Rewrite module paths in go.mod and all .go files
  python3 - "$DST" "$OLD_MOD" "$NEW_MOD" << 'PYEOF'
import sys, glob, os
directory, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
for path in glob.glob(directory + "/**", recursive=True):
    if not os.path.isfile(path):
        continue
    if not (path.endswith(".go") or os.path.basename(path) == "go.mod"):
        continue
    with open(path) as f:
        content = f.read()
    updated = content.replace(old, new)
    if updated != content:
        with open(path, "w") as f:
            f.write(updated)
        print(f"  patched {path}")
PYEOF

  echo "  module path: $OLD_MOD → $NEW_MOD"

  # Write files that differ per CLI — use Python to avoid heredoc quoting issues
  python3 - "$DST" "$SLUG" "$BINARY" "$CAT" "$NEW_MOD" << 'PYEOF'
import sys, os, textwrap
dst, slug, binary, cat, mod = sys.argv[1:]

readme_map = {
  "squeezeos": textwrap.dedent(f"""\
    # {binary}

    CLI Printing Press CLI for [SqueezeOS](https://squeezeos-api.onrender.com) — institutional-grade AI market intelligence.

    ## Install

    ```bash
    go install {mod}@latest
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
    squeezeos options                     # institutional options flow (paid)
    squeezeos iwm                         # IWM 0DTE scorer (paid)
    squeezeos marketplace browse          # peer signal marketplace (free)
    squeezeos futures browse              # prediction market (free)
    squeezeos settlement browse           # conditional escrow contracts (free)
    ```

    ## Source

    Generated from OpenAPI spec at `https://squeezeos-api.onrender.com/.well-known/openapi.json`
    """),
  "ghost-layer": textwrap.dedent(f"""\
    # {binary}

    CLI Printing Press CLI for [Ghost Layer](https://ghost-layer.onrender.com) — proprietary dual-chain XRPL/Base toll gateway.

    ## Install

    ```bash
    go install {mod}@latest
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
    ghost-layer x402 quote --product routing.telemetry --wallet rXXX
    ghost-layer x402 dispense routing.telemetry               # dispense after payment
    ghost-layer agent rXXX                                    # loyalty tier + Passport
    ghost-layer cube state                                    # 54-block execution matrix
    ghost-layer bridge --chain XRPL --amount 1000000 --recipient rXXX
    ```

    ## Source

    API spec: `https://ghost-layer.onrender.com/.well-known/openapi.json`
    """),
  "tipmaster": textwrap.dedent(f"""\
    # {binary}

    CLI Printing Press CLI for [TipMaster](https://tipmaster.onrender.com) — zero-custody Farcaster RLUSD tip bot.

    ## Install

    ```bash
    go install {mod}@latest
    ```

    ## Quick Start

    ```bash
    tipmaster resolve dwr                        # Farcaster username → XRPL wallet
    tipmaster leaderboard                        # top 10 tippers this week
    tipmaster leaderboard --period alltime       # all-time leaderboard
    tipmaster user 3                             # look up user by Farcaster FID
    tipmaster status                             # service health
    ```

    ## Key Agent Use Case

    ```bash
    WALLET=$(tipmaster resolve dwr --compact | jq -r '.wallet_address')
    # then pay via ghost-layer or directly on XRPL
    ```

    ## Source

    API: `https://tipmaster.onrender.com/api/status`
    """),
}

skill_map = {
  "squeezeos": textwrap.dedent("""\
    # SqueezeOS CLI Skill

    Use `squeezeos-pp-cli` to access institutional AI trading intelligence.

    ## Key Agent Patterns

    ```bash
    # Free daily bias check
    squeezeos preview IWM --compact | jq '{bias:.bias, regime:.regime}'

    # Full AI council verdict (needs SQUEEZEOS_TOKEN)
    squeezeos council NVDA --compact

    # Squeeze scanner
    squeezeos scan --compact | jq '.candidates[:5]'

    # Options flow
    squeezeos options --compact
    ```

    ## Payment Flow

    1. `squeezeos status` — confirm service live
    2. Visit `https://four02proof.onrender.com` to purchase a token with RLUSD
    3. `export SQUEEZEOS_TOKEN=<jwt>`
    4. Call premium endpoints

    ## Related Tools

    - `ghost-layer-pp-cli` — execute XRPL payments
    - `tipmaster-pp-cli` — resolve Farcaster usernames to XRPL wallets
    """),
  "ghost-layer": textwrap.dedent("""\
    # Ghost Layer CLI Skill

    Use `ghost-layer-pp-cli` to interact with the dual-chain XRPL/Base toll gateway.

    ## Recommended Agent Flow

    ```bash
    ghost-layer status                                       # 1. confirm live
    ghost-layer x402 catalog --compact                       # 2. list products
    ghost-layer x402 quote --product routing.telemetry \\
      --wallet $WALLET --compact                             # 3. get quote
    # 4. Pay on XRPL: send RLUSD to pay_to with memo_hex as MemoData
    ghost-layer x402 dispense routing.telemetry --compact    # 5. dispense
    ghost-layer agent $WALLET --compact                      # 6. check loyalty tier
    ```

    ## Related Tools

    - `squeezeos-pp-cli` — market intelligence powered by Ghost Layer
    - `tipmaster-pp-cli` — Farcaster tip bot on Ghost Layer rails
    """),
  "tipmaster": textwrap.dedent("""\
    # TipMaster CLI Skill

    Use `tipmaster-pp-cli` to resolve Farcaster usernames and browse the tip leaderboard.

    ## Key Patterns

    ```bash
    # Resolve username to XRPL wallet
    tipmaster resolve <username> --compact | jq -r '.wallet_address'

    # Autonomous tip flow
    WALLET=$(tipmaster resolve dwr --compact | jq -r '.wallet_address')
    ghost-layer bridge --chain XRPL --recipient "$WALLET" --amount 1000000

    # Weekly leaderboard
    tipmaster leaderboard --compact | jq '.top_tippers[:3]'
    ```

    ## Related Tools

    - `ghost-layer-pp-cli` — execute XRPL payment after resolving wallet
    - `squeezeos-pp-cli` — market signals to decide who/when to tip
    """),
}

mit_license = """\
MIT License

Copyright (c) 2026 Timothy Walton / Script Master Labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

with open(os.path.join(dst, "README.md"), "w") as f:
    f.write(readme_map[slug])

with open(os.path.join(dst, "SKILL.md"), "w") as f:
    f.write(skill_map[slug])

with open(os.path.join(dst, "LICENSE"), "w") as f:
    f.write(mit_license)

print(f"  wrote README.md, SKILL.md, LICENSE")
PYEOF

  echo "▶ Committing $BINARY …"
  git add -A
  GIT_CONFIG_NOSYSTEM=1 \
  GIT_AUTHOR_NAME="Timwal78" \
  GIT_AUTHOR_EMAIL="timothy.walton45@gmail.com" \
  GIT_COMMITTER_NAME="Timwal78" \
  GIT_COMMITTER_EMAIL="timothy.walton45@gmail.com" \
    git -c commit.gpgsign=false commit -q -m \
    "feat: add $BINARY ($CAT/$SLUG)

CLI Printing Press CLI for the $BINARY API by Script Master Labs.
Source: https://github.com/Timwal78/squeezeos (cli/$SRC/)
Binary: $BINARY
Module: $NEW_MOD"

  echo "▶ Pushing $BRANCH …"
  git push -q "https://$GH_TOKEN@github.com/$FORK.git" "$BRANCH" --force

  echo "▶ Opening PR for $BINARY …"
  PR=$(curl -s -X POST "${AUTH[@]}" \
    "$API/repos/$UPSTREAM/pulls" \
    -d "{
      \"title\": \"$PR_TITLE\",
      \"head\": \"$OWNER:$BRANCH\",
      \"base\": \"main\",
      \"body\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$PR_BODY")
    }")

  # If PR already exists, update it
  if echo "$PR" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'html_url' in d else 1)" 2>/dev/null; then
    PR_URL=$(echo "$PR" | python3 -c "import json,sys; print(json.load(sys.stdin)['html_url'])")
    echo "  ✓ PR: $PR_URL"
  else
    ERR=$(echo "$PR" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('errors','already exists or other error'))" 2>/dev/null || echo "check response")
    echo "  ↩ PR already exists or error: $ERR"
  fi
}

# ── 4. Submit each CLI separately ─────────────────────────────────────────────

submit_cli \
  "squeezeos" \
  "developer-tools" \
  "squeezeos" \
  "squeezeos-pp-cli" \
  "github.com/timwal78/squeezeos-pp-cli" \
  "feat: add squeezeos-pp-cli (developer-tools)" \
  "## squeezeos-pp-cli

CLI Printing Press CLI for the [SqueezeOS](https://squeezeos-api.onrender.com) institutional AI market intelligence API by Script Master Labs.

**Category:** developer-tools
**Binary:** squeezeos-pp-cli
**Base URL:** https://squeezeos-api.onrender.com
**Auth:** Bearer token via SQUEEZEOS_TOKEN (x402 RLUSD payment via 402Proof)

### Commands

| Command | Cost | Description |
|---------|------|-------------|
| demo | Free | IWM AI council verdict |
| preview \<symbol\> | Free | Bias + regime preview |
| history [\<symbol\>] | Free | Signal history ring buffer |
| status | Free | System health |
| marketplace browse/list/read | Free/0.02 RLUSD | Peer signal marketplace |
| futures browse/create/leaderboard/wallet | Free | Prediction market |
| settlement browse/get/create/wallet | Free | Conditional escrow |
| council \<symbol\> | 0.10 RLUSD | Multi-engine AI verdict |
| scan | 0.05 RLUSD | Full squeeze scanner |
| options | 0.05 RLUSD | Institutional options flow |
| iwm | 0.03 RLUSD | IWM 0DTE scorer |

### Build

go build ./... and go vet ./... pass. All RunE handlers return errors — no os.Exit in command layer."

submit_cli \
  "ghost-layer" \
  "payments" \
  "ghost-layer" \
  "ghost-layer-pp-cli" \
  "github.com/timwal78/ghost-layer-pp-cli" \
  "feat: add ghost-layer-pp-cli (payments)" \
  "## ghost-layer-pp-cli

CLI Printing Press CLI for [Ghost Layer](https://ghost-layer.onrender.com) — proprietary dual-chain XRPL/Base toll gateway by Script Master Labs.

**Category:** payments
**Binary:** ghost-layer-pp-cli
**Base URL:** https://ghost-layer.onrender.com
**Auth:** none (public catalog/status; bridge requires XRPL signature in request body)

### Commands

| Command | Description |
|---------|-------------|
| bridge --chain --amount --recipient | XRPL RLUSD or Base USDC cross-chain settlement |
| x402 catalog | List all x402 products |
| x402 quote --product --wallet | Get payment quote |
| x402 dispense \<product_id\> | Dispense product after payment |
| agent \<wallet\> | Agent stats, loyalty tier (Bronze→Diamond), Passport |
| cube state | 54-block execution matrix snapshot |
| status | Ghost Layer health check |

### Build

go build ./... and go vet ./... pass. Optional signer/signature fields are omitted from the bridge request body when not provided."

submit_cli \
  "tipmaster" \
  "social-and-messaging" \
  "tipmaster" \
  "tipmaster-pp-cli" \
  "github.com/timwal78/tipmaster-pp-cli" \
  "feat: add tipmaster-pp-cli (social-and-messaging)" \
  "## tipmaster-pp-cli

CLI Printing Press CLI for [TipMaster](https://tipmaster.onrender.com) — zero-custody Farcaster RLUSD tip bot by Script Master Labs.

**Category:** social-and-messaging
**Binary:** tipmaster-pp-cli
**Base URL:** https://tipmaster.onrender.com
**Auth:** none (all endpoints public)

### Commands

| Command | Description |
|---------|-------------|
| resolve \<farcaster-username\> | Resolve Farcaster username → XRPL wallet address |
| leaderboard --period --limit | Top tippers by RLUSD volume (week or alltime) |
| user \<fid\> | Look up Farcaster user by FID |
| status | TipMaster service health and feature flags |

### Key Agent Use Case

resolve enables fully autonomous agent tipping: look up any Farcaster user's XRPL wallet address without asking the user, then pay directly via ghost-layer-pp-cli.

### Build

go build ./... and go vet ./... pass."

echo ""
echo "✓ Done — three PRs submitted to $UPSTREAM"
echo "IMPORTANT: Revoke your token at https://github.com/settings/tokens"
