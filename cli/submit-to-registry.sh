#!/usr/bin/env bash
# cli/submit-to-registry.sh
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
git checkout -B "$BRANCH"

echo "▶ Copying CLI source files …"
mkdir -p library/developer-tools/squeezeos
mkdir -p library/payments/ghost-layer
mkdir -p library/social-and-messaging/tipmaster

for PAIR in "squeezeos:developer-tools/squeezeos" "ghost-layer:payments/ghost-layer" "tipmaster:social-and-messaging/tipmaster"; do
  SRC="${PAIR%%:*}"
  DST="library/${PAIR##*:}"
  cp -r "$SCRIPT_DIR/$SRC/." "$DST/"
done

echo "▶ Patching module paths and generating library files …"
python3 << 'PYEOF'
import os, glob

CLIS = [
    {
        "dir": "library/developer-tools/squeezeos",
        "old": "github.com/timwal78/squeezeos-pp-cli",
        "new": "github.com/mvanhorn/printing-press-library/library/developer-tools/squeezeos",
        "binary": "squeezeos-pp-cli",
        "title": "SqueezeOS",
        "url": "https://squeezeos-api.onrender.com",
        "desc": "institutional AI market intelligence",
        "quickstart": (
            "squeezeos demo                 # free IWM verdict\n"
            "squeezeos preview TSLA         # bias + regime (free)\n"
            "squeezeos status               # health check\n"
            "squeezeos council NVDA         # AI verdict (paid, needs SQUEEZEOS_TOKEN)\n"
            "squeezeos scan                 # squeeze scanner (paid)"
        ),
        "auth": (
            "Premium endpoints require a JWT from "
            "[402Proof](https://four02proof.onrender.com).\n"
            "Agents pay RLUSD on XRPL — no API keys, no subscriptions.\n\n"
            "```bash\nexport SQUEEZEOS_TOKEN=<token-from-402proof>\n```"
        ),
        "skill": (
            "```bash\n"
            "squeezeos preview IWM --compact | jq '{bias:.bias, regime:.regime}'\n"
            "squeezeos council NVDA --compact   # needs SQUEEZEOS_TOKEN\n"
            "squeezeos scan --compact\n"
            "```\n\n"
            "**Related:** `ghost-layer-pp-cli`, `tipmaster-pp-cli`"
        ),
    },
    {
        "dir": "library/payments/ghost-layer",
        "old": "github.com/timwal78/ghost-layer-pp-cli",
        "new": "github.com/mvanhorn/printing-press-library/library/payments/ghost-layer",
        "binary": "ghost-layer-pp-cli",
        "title": "Ghost Layer",
        "url": "https://ghost-layer.onrender.com",
        "desc": "dual-chain XRPL/Base toll gateway",
        "quickstart": (
            "ghost-layer status\n"
            "ghost-layer x402 catalog\n"
            "ghost-layer x402 quote --product routing.telemetry --wallet rXXX\n"
            "ghost-layer x402 dispense routing.telemetry\n"
            "ghost-layer agent rXXX"
        ),
        "auth": "",
        "skill": (
            "```bash\n"
            "ghost-layer status\n"
            "ghost-layer x402 catalog --compact\n"
            "ghost-layer x402 quote --product routing.telemetry --wallet $WALLET --compact\n"
            "ghost-layer x402 dispense routing.telemetry --compact\n"
            "```\n\n"
            "**Related:** `squeezeos-pp-cli`, `tipmaster-pp-cli`"
        ),
    },
    {
        "dir": "library/social-and-messaging/tipmaster",
        "old": "github.com/timwal78/tipmaster-pp-cli",
        "new": "github.com/mvanhorn/printing-press-library/library/social-and-messaging/tipmaster",
        "binary": "tipmaster-pp-cli",
        "title": "TipMaster",
        "url": "https://tipmaster.onrender.com",
        "desc": "zero-custody Farcaster RLUSD tip bot",
        "quickstart": (
            "tipmaster resolve dwr                  # Farcaster username → XRPL wallet\n"
            "tipmaster leaderboard                  # top 10 tippers this week\n"
            "tipmaster leaderboard --period alltime\n"
            "tipmaster user 3                       # look up by FID\n"
            "tipmaster status"
        ),
        "auth": "",
        "skill": (
            "```bash\n"
            "WALLET=$(tipmaster resolve dwr --compact | jq -r '.wallet_address')\n"
            "ghost-layer bridge --chain XRPL --recipient \"$WALLET\" --amount 1000000\n"
            "```\n\n"
            "**Related:** `ghost-layer-pp-cli`, `squeezeos-pp-cli`"
        ),
    },
]

MIT = """MIT License

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

def rewrite_module(directory, old, new):
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

def make_goreleaser(binary):
    return (
        "version: 2\n"
        f"project_name: {binary}\n"
        "before:\n"
        "  hooks:\n"
        "    - go mod tidy\n"
        "builds:\n"
        "  - main: .\n"
        f"    binary: {binary}\n"
        "    env: [CGO_ENABLED=0]\n"
        "    goos: [linux, darwin, windows]\n"
        "    goarch: [amd64, arm64]\n"
        "archives:\n"
        "  - format: tar.gz\n"
        "    format_overrides:\n"
        "      - goos: windows\n"
        "        format: zip\n"
        '    name_template: "{{ .ProjectName }}_{{ .Os }}_{{ .Arch }}"\n'
        "checksum:\n"
        "  name_template: checksums.txt\n"
        "release:\n"
        "  github:\n"
        "    owner: mvanhorn\n"
        "    name: printing-press-library\n"
        "changelog:\n"
        "  sort: asc\n"
        "  filters:\n"
        "    exclude: ['^docs:', '^test:', Merge]\n"
    )

def make_readme(mod, binary, title, url, desc, quickstart, auth):
    parts = [
        f"# {binary}\n",
        f"\nCLI Printing Press generated CLI for [{title}]({url}) — {desc}.\n",
        "\n## Install\n",
        "\n```bash\n",
        f"go install {mod}@latest\n",
        "```\n",
        "\n## Quick Start\n",
        "\n```bash\n",
        quickstart + "\n",
        "```\n",
    ]
    if auth:
        parts += ["\n## Auth\n\n", auth + "\n"]
    return "".join(parts)

for c in CLIS:
    d = c["dir"]
    rewrite_module(d, c["old"], c["new"])
    with open(f"{d}/LICENSE", "w") as f:
        f.write(MIT)
    with open(f"{d}/.goreleaser.yaml", "w") as f:
        f.write(make_goreleaser(c["binary"]))
    with open(f"{d}/README.md", "w") as f:
        f.write(make_readme(c["new"], c["binary"], c["title"], c["url"], c["desc"], c["quickstart"], c["auth"]))
    with open(f"{d}/SKILL.md", "w") as f:
        f.write(f"# {c['title']} CLI Skill\n\n{c['skill']}\n")
    print(f"  {d}: patched")

# NOTE: Do NOT touch registry.json — it is auto-generated post-merge.
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

echo "▶ Opening PR (no-op if already exists) …"
PR=$(curl -s -X POST "${AUTH[@]}" \
  "$API/repos/$UPSTREAM/pulls" \
  -d '{"title":"feat: add squeezeos, ghost-layer, tipmaster CLIs (Script Master Labs)","head":"Timwal78:add-sml-clis","base":"main","body":"Three CLI Printing Press Go/Cobra CLIs for the Script Master Labs product stack.\n\n- `library/developer-tools/squeezeos` — institutional AI market intelligence\n- `library/payments/ghost-layer` — dual-chain XRPL/Base toll gateway\n- `library/social-and-messaging/tipmaster` — Farcaster RLUSD tip bot"}' \
  2>/dev/null || echo '{}')
echo "$PR" | python3 -c "import json,sys; d=json.load(sys.stdin); print('PR:', d.get('html_url', d.get('message', 'already exists')))"
