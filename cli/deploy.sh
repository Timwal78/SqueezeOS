#!/usr/bin/env bash
# cli/deploy.sh — create and push the three CLI Printing Press repos
# Usage: GH_TOKEN=ghp_xxx bash cli/deploy.sh
set -euo pipefail

: "${GH_TOKEN:?Set GH_TOKEN=ghp_... before running}"

OWNER="Timwal78"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

declare -A REPOS=(
  [squeezeos]="squeezeos-pp-cli"
  [ghost-layer]="ghost-layer-pp-cli"
  [tipmaster]="tipmaster-pp-cli"
)

declare -A DESCS=(
  [squeezeos]="CLI Printing Press Go CLI for the SqueezeOS institutional market intelligence API"
  [ghost-layer]="CLI Printing Press Go CLI for Ghost Layer — dual-chain XRPL/Base toll gateway"
  [tipmaster]="CLI Printing Press Go CLI for TipMaster — Farcaster RLUSD tip bot"
)

for DIR in squeezeos ghost-layer tipmaster; do
  REPO="${REPOS[$DIR]}"
  DESC="${DESCS[$DIR]}"

  echo ""
  echo "▶ Creating $OWNER/$REPO …"
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "https://api.github.com/user/repos" \
    -H "Authorization: token $GH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -d "{\"name\":\"$REPO\",\"description\":\"$DESC\",\"private\":false,\"auto_init\":false}")

  if [ "$HTTP" = "201" ]; then
    echo "  ✓ Created"
  elif [ "$HTTP" = "422" ]; then
    echo "  ↩ Already exists (continuing)"
  else
    echo "  ✗ HTTP $HTTP — check your token scope (needs 'repo')"
    exit 1
  fi

  TMP=$(mktemp -d)
  echo "  Copying $DIR → temp dir …"
  cp -r "$SCRIPT_DIR/$DIR/." "$TMP/"

  echo "  Pushing …"
  cd "$TMP"
  git init -q
  git checkout -q -b main
  git add -A
  git commit -q -m "feat: initial CLI Printing Press release"
  git remote add origin "https://$GH_TOKEN@github.com/$OWNER/$REPO.git"
  git push -q -u origin main --force
  cd "$SCRIPT_DIR"
  rm -rf "$TMP"

  echo "  ✓ https://github.com/$OWNER/$REPO"
done

echo ""
echo "Done! Three CLI repos are live."
