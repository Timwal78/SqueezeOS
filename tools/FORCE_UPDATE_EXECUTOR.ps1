# Force SqueezeOS executor to latest main + desk env (45s + harvest)
$ErrorActionPreference = "Continue"
$Repo = "C:\Users\timot\Downloads\Projects_&_Repositories\SqueezeOS_Github"

Write-Host "=== FORCE UPDATE EXECUTOR ===" -ForegroundColor Cyan
if (-not (Test-Path $Repo)) {
  Write-Host "Repo missing: $Repo" -ForegroundColor Red
  Write-Host "Searching..."
  $found = Get-ChildItem "$env:USERPROFILE\Downloads\Projects_&_Repositories" -Filter "robinhood_executor_sml.py" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found) { $Repo = Split-Path (Split-Path $found.FullName) }
}
if (-not (Test-Path $Repo)) { throw "Cannot find SqueezeOS_Github" }
Set-Location $Repo
Write-Host "Repo: $pwd"

# Stop old executor pythons (best effort)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like "*robinhood_executor*") } |
  ForEach-Object {
    Write-Host "Stopping old PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

# Git hard sync to origin/main
git remote -v
git fetch origin
git checkout main 2>$null
git reset --hard origin/main
git clean -fd -e tools/executor.env -e "*.pickle" -e "rh_outbox"
Write-Host "HEAD:" (git rev-parse --short HEAD)
Write-Host "Log:" (git log -1 --oneline)

# Prove file is v3.7
$py = Join-Path $Repo "tools\robinhood_executor_sml.py"
$ver = Select-String -Path $py -Pattern "Executor v3\." | Select-Object -First 1
Write-Host "Version line: $($ver.Line)"
if ($ver.Line -notmatch "v3\.7") {
  Write-Host "WARNING: file is not v3.7 after reset - remote may be wrong" -ForegroundColor Yellow
}

# Merge env via helper if present
$ex = Join-Path $Repo "tools\executor.env.example"
$en = Join-Path $Repo "tools\executor.env"
if (-not (Test-Path $en) -and (Test-Path $ex)) { Copy-Item $ex $en }
$upd = Join-Path $Repo "tools\update_executor_env.ps1"
if (Test-Path $upd) {
  powershell -ExecutionPolicy Bypass -File $upd
}

# Force critical keys in executor.env (preserve other keys/secrets)
if (Test-Path $en) {
  $kv = @{}
  Get-Content $en | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or ($line -notmatch "=")) { return }
    $p = $line.Split("=", 2)
    $kv[$p[0].Trim()] = $p[1]
  }
  $force = @{
    POLL_INTERVAL_S            = "45"
    MIN_GOD_STACKED            = "3"
    GAMMA_RAMP_POLL_ENABLED    = "true"
    EXEC_BROKER                = "robinhood"
    POSITION_MONITOR_ENABLED   = "true"
    OPTIONS_DELTA_MIN          = "0.30"
    OPTIONS_DELTA_MAX          = "0.40"
    OPTIONS_DELTA_TARGET       = "0.35"
    OPT_HARD_STOP              = "-0.20"
    OPT_SCALE_1                = "0.50"
    OPT_SCALE_2                = "1.50"
    OPT_BANK_300               = "3.00"
    OPT_BANK_500               = "5.00"
    OPT_GIVEBACK_ARM           = "0.50"
    OPT_GIVEBACK_FRAC          = "0.35"
    OPT_DELTA_EXIT             = "0.60"
    GAMMA_RAMP_OUTBOX_DIR      = "tools/gamma_ramp/rh_outbox"
    ROBINHOOD_PAPER_MODE       = "false"
    KILL_SWITCH                = "false"
    SQUEEZEOS_API_URL          = "https://squeezeos-api.onrender.com"
  }
  foreach ($k in $force.Keys) { $kv[$k] = $force[$k] }
  $kv.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" } | Set-Content $en -Encoding UTF8
  Write-Host "executor.env POLL_INTERVAL_S=$($kv['POLL_INTERVAL_S']) MIN_GOD=$($kv['MIN_GOD_STACKED'])"
}

Write-Host ""
Write-Host "Starting executor (v3.7 expected, poll 45s)..." -ForegroundColor Green
$env:POLL_INTERVAL_S = "45"
$env:MIN_GOD_STACKED = "3"
$env:GAMMA_RAMP_POLL_ENABLED = "true"
$env:DOTENV_PATH = $en
$env:EXEC_BROKER = "robinhood"
python (Join-Path $Repo "tools\robinhood_executor_sml.py")
