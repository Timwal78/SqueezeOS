#!/bin/bash
# Fetches the active Smithery config and diffs it against your local manifest
set -e

SMITHERY_URL="https://api.smithery.ai/v1/servers/com.scriptmasterlabs/squeezeos"
LOCAL_MANIFEST="./smithery.yaml"

echo "[1] Fetching live Smithery configuration..."
curl -s -H "Accept: application/json" $SMITHERY_URL | jq '.manifest' > remote_manifest.json

echo "[2] Converting local YAML to JSON for comparison..."
# Requires yq installed
yq eval -o=j $LOCAL_MANIFEST > local_manifest.json

echo "[3] Running diff (If empty, manifests are perfectly synced)..."
diff -u <(jq -S . remote_manifest.json) <(jq -S . local_manifest.json) || echo "WARNING: Divergence detected!"
