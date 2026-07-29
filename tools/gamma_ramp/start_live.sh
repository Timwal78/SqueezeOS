#!/usr/bin/env bash
# Gamma Ramp LIVE — AM go-live launcher
# Usage:
#   ./start_live.sh --status
#   ./start_live.sh --once
#   GAMMA_RAMP_LIVE=1 TRADIER_ENV=production ./start_live.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
if [[ -f "$DIR/../gamma_ramp.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$DIR/../gamma_ramp.env"
  set +a
fi
mkdir -p "$ROOT/logs"
exec python3 "$DIR/live_engine.py" "$@"
