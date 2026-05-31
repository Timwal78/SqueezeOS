#!/usr/bin/env bash
# Unified installer: agentmemory + Antigravity bridge for Claude Code.
# Run on your LOCAL machine (macOS/Linux). Windows: use WSL or run steps manually.
set -euo pipefail

STACK_DIR="${STACK_DIR:-$HOME/agent-stack}"
mkdir -p "$STACK_DIR"
cd "$STACK_DIR"

echo ">>> [1/5] Checking prerequisites"
command -v node >/dev/null || { echo "Install Node 20+ first"; exit 1; }
command -v python3 >/dev/null || { echo "Install Python 3.10+ first"; exit 1; }
command -v agy >/dev/null || echo "WARN: 'agy' not on PATH — install Google Antigravity CLI, then run 'agy -i' to authenticate."

echo ">>> [2/5] Installing agentmemory globally"
npm install -g @agentmemory/agentmemory

echo ">>> [3/5] Wiring agentmemory into Claude Code"
agentmemory connect claude-code
npx -y skills add rohitg00/agentmemory -y || true

echo ">>> [4/5] Cloning Antigravity bridge"
if [ ! -d "antigravity-bridge" ]; then
  git clone https://github.com/SinanTufekci/Claude-Code-Antigravity-CLI-MCP-Server.git antigravity-bridge
fi
cd antigravity-bridge
python3 -m pip install --user fastmcp
echo "Bridge installed at: $(pwd)/server.py"

echo ">>> [5/5] Patching ~/.claude.json with 'agy' MCP server"
BRIDGE_PATH="$(pwd)/server.py"
CLAUDE_CFG="$HOME/.claude.json"
if [ ! -f "$CLAUDE_CFG" ]; then echo "{}" > "$CLAUDE_CFG"; fi

python3 - <<PY
import json, os
cfg_path = os.path.expanduser("~/.claude.json")
with open(cfg_path) as f:
    cfg = json.load(f)
cfg.setdefault("mcpServers", {})
cfg["mcpServers"]["agy"] = {
    "command": "python3",
    "args": ["$BRIDGE_PATH"]
}
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)
print("Patched", cfg_path)
PY

echo ""
echo "==========================================================="
echo "DONE. Next steps:"
echo "  1. Run 'agy -i' once to authenticate Antigravity (if not done)."
echo "  2. Start memory server:    agentmemory"
echo "  3. Restart Claude Code. You'll see:"
echo "       - agentmemory tools (53 of them)"
echo "       - mcp__agy__agy_ask  and  mcp__agy__agy_continue"
echo ""
echo "For Antigravity itself, drop this into:"
echo "  macOS: ~/Library/Application Support/Antigravity/User/mcp.json"
echo "  Linux: ~/.config/Antigravity/User/mcp.json"
echo "----"
cat <<'JSON'
{
  "mcpServers": {
    "agentmemory": {
      "command": "agentmemory",
      "args": ["mcp"]
    }
  }
}
JSON
echo "==========================================================="
