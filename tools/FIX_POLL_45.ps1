# ONE-SHOT: kill 300s poll forever on this PC
$ErrorActionPreference = "Continue"
$Repo = "C:\Users\timot\Downloads\Projects_&_Repositories\SqueezeOS_Github"
if (-not (Test-Path (Join-Path $Repo "tools\robinhood_executor_sml.py"))) {
  $found = Get-ChildItem "$env:USERPROFILE\Downloads\Projects_&_Repositories" -Filter "robinhood_executor_sml.py" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found) { $Repo = Split-Path (Split-Path $found.FullName) }
}
if (-not (Test-Path $Repo)) { throw "SqueezeOS repo not found" }
Set-Location $Repo
Write-Host "Repo: $pwd" -ForegroundColor Cyan

# Kill every old executor
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like "*robinhood_executor*") } |
  ForEach-Object {
    Write-Host "KILL PID $($_.ProcessId)" -ForegroundColor Yellow
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

git fetch origin
git checkout main 2>$null
git reset --hard origin/main
Write-Host "HEAD: $(git rev-parse --short HEAD) $(git log -1 --oneline)"

# Prove lock is in source (no # inside -match - PowerShell treats it as comment)
$py = Get-Content ".\tools\robinhood_executor_sml.py" -Raw
if ($py -notlike "*POLL_INTERVAL_S = 45*") {
  Write-Host "WARNING: desk lock string missing - pull may have failed" -ForegroundColor Red
} else {
  Write-Host "OK desk lock present in source" -ForegroundColor Green
}
if ($py -notlike "*DESK-LOCKED*") {
  Write-Host "WARNING: DESK-LOCKED banner missing - old source" -ForegroundColor Red
} else {
  Write-Host "OK DESK-LOCKED banner present" -ForegroundColor Green
}

# Force executor.env
$en = ".\tools\executor.env"
if (-not (Test-Path $en)) { Copy-Item ".\tools\executor.env.example" $en -ErrorAction SilentlyContinue }
$kv = @{}
if (Test-Path $en) {
  Get-Content $en | ForEach-Object {
    $l = $_.Trim()
    if ($l -and -not $l.StartsWith("#") -and $l.Contains("=")) {
      $p = $l.Split("=", 2); $kv[$p[0].Trim()] = $p[1]
    }
  }
}
$kv["POLL_INTERVAL_S"] = "45"
$kv["MIN_GOD_STACKED"] = "3"
$kv["MAX_EQUITY_SHARES"] = "25"
$kv["GAMMA_RAMP_POLL_ENABLED"] = "true"
$kv["EXEC_BROKER"] = "robinhood"
$kv["POSITION_MONITOR_ENABLED"] = "true"
$kv["ROBINHOOD_PAPER_MODE"] = "false"
$kv["KILL_SWITCH"] = "false"
$kv["ALLOW_SLOW_POLL"] = "false"
$kv["ALLOW_CUSTOM_MIN_GOD"] = "false"
$kv.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" } | Set-Content $en -Encoding UTF8
Write-Host "executor.env POLL=$($kv['POLL_INTERVAL_S']) MIN_GOD=$($kv['MIN_GOD_STACKED'])"

# Clear any process-level poison
Remove-Item Env:ALLOW_SLOW_POLL -ErrorAction SilentlyContinue
$env:POLL_INTERVAL_S = "45"
$env:MIN_GOD_STACKED = "3"
$env:ALLOW_SLOW_POLL = "false"
$env:DOTENV_PATH = (Resolve-Path $en).Path

Write-Host ""
Write-Host "Starting executor - banner MUST say: Poll every : 45s [DESK-LOCKED]" -ForegroundColor Green
python ".\tools\robinhood_executor_sml.py"
