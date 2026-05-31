# install-stack.ps1
# Native Windows PowerShell installer: agentmemory + Antigravity bridge for Claude Code.
# Run in an elevated PowerShell window (Right-click PowerShell -> Run as Administrator).
# If execution is blocked: powershell -ExecutionPolicy Bypass -File .\install-stack.ps1

$ErrorActionPreference = "Stop"

$StackDir = "$env:USERPROFILE\agent-stack"
New-Item -ItemType Directory -Force -Path $StackDir | Out-Null
Set-Location $StackDir

Write-Host ">>> [1/5] Checking prerequisites" -ForegroundColor Cyan
foreach ($cmd in @("node","npm","python","git")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $cmd. Install it first (Node 20+, Python 3.10+, Git)." -ForegroundColor Red
        exit 1
    }
}
if (-not (Get-Command agy -ErrorAction SilentlyContinue)) {
    Write-Host "WARN: 'agy' not on PATH. Install Google Antigravity CLI, then run 'agy -i' to authenticate." -ForegroundColor Yellow
}

Write-Host ">>> [2/5] Installing agentmemory globally" -ForegroundColor Cyan
npm install -g "@agentmemory/agentmemory"

Write-Host ">>> [3/5] Wiring agentmemory into Claude Code" -ForegroundColor Cyan
agentmemory connect claude-code
try { npx -y skills add rohitg00/agentmemory -y } catch { Write-Host "skills add step skipped (non-fatal)" -ForegroundColor Yellow }

Write-Host ">>> [4/5] Cloning Antigravity bridge" -ForegroundColor Cyan
if (-not (Test-Path "antigravity-bridge")) {
    git clone https://github.com/SinanTufekci/Claude-Code-Antigravity-CLI-MCP-Server.git antigravity-bridge
}
Set-Location antigravity-bridge
python -m pip install --user fastmcp
$BridgePath = (Resolve-Path .\server.py).Path
Write-Host "Bridge installed at: $BridgePath" -ForegroundColor Green

Write-Host ">>> [5/5] Patching ~/.claude.json with 'agy' MCP server" -ForegroundColor Cyan
$ClaudeCfg = "$env:USERPROFILE\.claude.json"
if (-not (Test-Path $ClaudeCfg)) { "{}" | Set-Content $ClaudeCfg }

$cfg = Get-Content $ClaudeCfg -Raw | ConvertFrom-Json
if (-not $cfg.mcpServers) {
    $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject)
}
$agyEntry = [PSCustomObject]@{
    command = "python"
    args    = @($BridgePath)
}
if ($cfg.mcpServers.PSObject.Properties.Name -contains "agy") {
    $cfg.mcpServers.agy = $agyEntry
} else {
    $cfg.mcpServers | Add-Member -NotePropertyName agy -NotePropertyValue $agyEntry
}
$cfg | ConvertTo-Json -Depth 20 | Set-Content $ClaudeCfg
Write-Host "Patched $ClaudeCfg" -ForegroundColor Green

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Green
Write-Host "DONE. Next steps:" -ForegroundColor Green
Write-Host "  1. Run 'agy -i' once to authenticate Antigravity (if not done)."
Write-Host "  2. Start memory server in a separate terminal: agentmemory"
Write-Host "  3. Restart Claude Code. You'll see:"
Write-Host "       - agentmemory tools (53 of them)"
Write-Host "       - mcp__agy__agy_ask  and  mcp__agy__agy_continue"
Write-Host ""
Write-Host "For Antigravity itself, drop this into:"
Write-Host "  %APPDATA%\Antigravity\User\mcp.json"
Write-Host "----"
Write-Host @'
{
  "mcpServers": {
    "agentmemory": {
      "command": "agentmemory",
      "args": ["mcp"]
    }
  }
}
'@
Write-Host "===========================================================" -ForegroundColor Green
