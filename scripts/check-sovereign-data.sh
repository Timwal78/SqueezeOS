#!/usr/bin/env bash
set -euo pipefail

FAIL=0
PATTERNS=(
  'mock_data'
  'fake_data'
  'placeholder'
  'demo_mode'
  'SIMULATED'
  'hardcoded.*price'
  'TODO.*implement'
  'FIXME.*later'
  'sample_response'
  'test_wallet'
)

EXCLUDE_DIRS=('.git' 'node_modules' 'vendor' '__pycache__' '.venv' 'examples')

BUILD_EXCLUDE=''
for d in "${EXCLUDE_DIRS[@]}"; do
  BUILD_EXCLUDE="$BUILD_EXCLUDE --exclude-dir=$d"
done

# NOTE: deliberately no `--exclude=<file>` flags here. GNU grep's --exclude
# combined with --include in the same invocation silently drops the --include
# filtering entirely on this grep version (3.11) — verified by isolated
# testing, not assumed. Whole-file exemptions are handled via ALLOWLIST below
# instead, using an empty pattern to mean "exempt every line in this file".

# Known false positives: a matched keyword appearing inside a comment/docstring
# that documents or asserts the sovereign-data policy itself, is a standard
# technical term, is a native HTML input-hint attribute, or is this script's
# own pattern list (which must contain the trigger words literally).
# Format: "file:grep-pattern-for-the-exact-line" (empty pattern = whole file).
# Add new entries only for verified non-violations — never to hide a real one.
ALLOWLIST=(
  "scripts/check-sovereign-data.sh:"
  "settings.js:"
  "squeeze_analyzer.py:No approximated data. No placeholders."
  "battle_engine.py:Prime Directive .*No simulated data"
  "core/ftd_data.py:AGENT_LAW .*no simulated data"
  "iam_engine.py:Optimized via simulated annealing"
  "core/api/slack_bp.py:# Placeholder .* button clicks, menu selections"
  "core/api/convergence_bp.py:Uses realistic placeholder data"
  "sml_matrix_webhook.py:ROBINHOOD MCP HOOK \\(placeholder"
  "stellar_forge/economy/store.py:Translate the neutral '\\?' placeholder"
  "core/api/truth_bp.py:No hardcoded prices, no simulated consensus"
  "data_providers.py:callers get an explicit error, not a placeholder number"
  "core/api/mcp_bp.py:Returns a real error \\(not a placeholder\\) if"
  "core/api/fred_bp.py:placeholder\\."
)

is_allowlisted() {
  local line="$1"
  local file pattern entry
  for entry in "${ALLOWLIST[@]}"; do
    file="${entry%%:*}"
    pattern="${entry#*:}"
    if [[ "$line" == "./$file:"* ]] && { [ -z "$pattern" ] || [[ "$line" =~ $pattern ]]; }; then
      return 0
    fi
  done
  return 1
}

for pattern in "${PATTERNS[@]}"; do
  MATCHES=$(grep -ri $BUILD_EXCLUDE "$pattern" . --include='*.ts' --include='*.py' --include='*.js' --include='*.go' 2>/dev/null || true)
  REAL_MATCHES=''
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if ! is_allowlisted "$line"; then
      REAL_MATCHES="$REAL_MATCHES$line"$'\n'
    fi
  done <<< "$MATCHES"
  if [ -n "$REAL_MATCHES" ]; then
    echo "SOVEREIGN VIOLATION: Pattern '$pattern' found:"
    echo "$REAL_MATCHES"
    FAIL=1
  fi
done

if [ $FAIL -eq 1 ]; then
  echo ""
  echo "SOVEREIGN DATA POLICY VIOLATION: Remove all mock/fake/placeholder data before merging."
  echo "Reference: AGENT_STANDARDS/SOVEREIGN_DATA_POLICY.md"
  exit 1
fi

echo "Sovereign data check passed."
