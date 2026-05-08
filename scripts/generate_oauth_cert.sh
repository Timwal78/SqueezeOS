#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# Generate a self-signed cert for the Schwab OAuth callback
# (https://127.0.0.1:8182/callback).
#
# Schwab REQUIRES the redirect_uri to be HTTPS. If you've been getting
# "Schwab OAuth will fail" warnings or the callback hangs, this script
# fixes it by creating the cert files server_v5.py looks for.
#
# Usage:
#   bash scripts/generate_oauth_cert.sh
#   # then start SqueezeOS — server logs should now say "🔒 SSL ENABLED"
#
# After first start, your browser will warn "connection not private"
# the first time you hit https://127.0.0.1:8182/. Click
# "Advanced → Proceed to 127.0.0.1 (unsafe)" once. Subsequent visits
# are fine for the duration of the cert (10 years from issue).
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

CERT="${HOME}/.squeeze_os_cert.pem"
KEY="${HOME}/.squeeze_os_key.pem"

if [[ -f "$CERT" && -f "$KEY" ]]; then
  echo "✓ Cert already exists at $CERT"
  echo "  (delete both files to regenerate)"
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "✗ openssl not installed. Install it first:"
  echo "    macOS:  brew install openssl"
  echo "    Linux:  sudo apt install openssl   # or yum / pacman"
  exit 1
fi

echo "Generating 10-year self-signed cert for 127.0.0.1 ..."
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" -out "$CERT" \
  -days 3650 \
  -subj "/CN=127.0.0.1" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  >/dev/null 2>&1

chmod 600 "$KEY" "$CERT"

echo "✓ Wrote:"
echo "    $CERT"
echo "    $KEY"
echo ""
echo "Next:"
echo "  1. Restart SqueezeOS (you should see '🔒 SSL ENABLED')"
echo "  2. Open https://127.0.0.1:8182/  (accept the browser warning ONCE)"
echo "  3. Run Schwab OAuth — popup OR /oauth/manual will now work"
