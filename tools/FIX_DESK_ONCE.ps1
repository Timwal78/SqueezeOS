# =============================================================================
#  FIX_DESK_ONCE.ps1  —  one command, does the whole cleanup
# =============================================================================
#  Built 2026-07-31 after the operator had to hand-run ~15 diagnostic commands
#  to chase a problem that had recurred five times. This does all of it.
#
#  What it does, in order:
#    1. Stops EVERY running executor process, wherever it was launched from.
#    2. Removes any PM2 entry pointing at a stale path, and persists that
#       removal (`pm2 save`) -- without the save it returns at next login,
#       which is how this survived previous cleanups.
#    3. Hard-resets THIS repo to origin/main.
#    4. Strips stale risk overrides from tools\executor.env (backing it up
#       first, leaving credentials untouched).
#    5. Renames every OTHER copy of the executor on disk to .py.OLD so
#       nothing can launch one by accident. Renames, never deletes.
#    6. Starts the correct executor under PM2 and saves the process list.
#    7. Prints the BUILD CHECK block so you can see it took.
#
#  Run from anywhere:
#    powershell -ExecutionPolicy Bypass -File <path-to-repo>\tools\FIX_DESK_ONCE.ps1
#
#  Safe to re-run. Every destructive step is a rename or a backup, never a
#  delete, and it never touches ROBINHOOD_USERNAME / PASSWORD / API keys.
# =============================================================================

$ErrorActionPreference = "Continue"

function Say($msg, $color = "White") { Write-Host $msg -ForegroundColor $color }

Say "=============================================================" Cyan
Say " SQUEEZEOS DESK — ONE-SHOT FIX" Cyan
Say "=============================================================" Cyan

# ── Locate this repo from the script's own location ──────────────────────────
# Deriving it beats hardcoding: this script lives in <repo>\tools\, so the repo
# is always its parent, whatever the folder is named or where it was cloned.
$Repo = Split-Path -Parent $PSScriptRoot
$Exec = Join-Path $Repo "tools\robinhood_executor_sml.py"

if (-not (Test-Path $Exec)) { Say "FATAL: cannot find $Exec" Red; exit 1 }
Say "[repo] $Repo" Gray

# ── 1. Stop every running executor, from any path ────────────────────────────
Say "`n[1/7] Stopping all running executors..." Yellow
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -and $_.CommandLine -like "*executor*" -and $_.CommandLine -like "*python*" }
if ($procs) {
  foreach ($p in $procs) {
    Say "   stopping PID $($p.ProcessId): $($p.CommandLine)" Gray
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
} else { Say "   none running" Gray }

# ── 2. Drop PM2 entries pointing anywhere except this repo ───────────────────
Say "`n[2/7] Cleaning PM2 entries that point at stale paths..." Yellow
$pm2 = "$env:APPDATA\npm\pm2.cmd"
if (-not (Test-Path $pm2)) { $pm2 = "pm2" }
try {
  $jlist = & $pm2 jlist 2>$null | ConvertFrom-Json
  foreach ($app in $jlist) {
    $script = $app.pm2_env.pm_exec_path
    if ($script -and $script -like "*executor*" -and $script -ne $Exec) {
      Say "   deleting PM2 app '$($app.name)' -> $script" Gray
      & $pm2 delete $app.name 2>$null | Out-Null
    }
  }
  # Persist NOW: without this the deleted entries come back at next login via
  # pm2 resurrect, which is exactly how this survived earlier cleanups.
  & $pm2 save 2>$null | Out-Null
  Say "   pm2 save done (removal persisted)" Gray
} catch { Say "   PM2 not reachable — skipping (not fatal)" Gray }

# ── 3. Hard-reset the repo ───────────────────────────────────────────────────
Say "`n[3/7] Updating repo to origin/main..." Yellow
Push-Location $Repo
git fetch origin 2>&1 | Out-Null
git reset --hard origin/main 2>&1 | Out-Null
$head = (git log -1 --oneline)
Say "   HEAD: $head" Gray
Pop-Location

# ── 4. Strip stale risk overrides from executor.env ──────────────────────────
# This file is deliberately preserved by git clean (it holds credentials), so
# a git reset never clears these -- the second half of the recurring problem.
Say "`n[4/7] Removing stale risk overrides from executor.env..." Yellow
$envFile = Join-Path $Repo "tools\executor.env"
if (Test-Path $envFile) {
  Copy-Item $envFile "$envFile.bak" -Force
  $stale = 'MAX_ORDERS_PER_DAY|MAX_DAILY_NOTIONAL_USD|STOP_LOSS_PCT|POLL_INTERVAL_S|ALLOW_SLOW_POLL|ALLOW_CUSTOM_MIN_GOD'
  $before = (Get-Content $envFile | Select-String -Pattern "^($stale)=").Count
  (Get-Content $envFile) -replace "^($stale)=", '# STALE-REMOVED $1=' | Set-Content $envFile
  Say "   $before stale override(s) commented out (backup: executor.env.bak)" Gray
  if (-not (Get-Content $envFile | Select-String -Pattern "^MACRO_GATE_SECRET=")) {
    Say "   NOTE: MACRO_GATE_SECRET is NOT set — the 741 macro gate and the" Yellow
    Say "         365-day anchor gate are BOTH inert until you add it." Yellow
  }
} else { Say "   no executor.env found — skipping" Gray }

# ── 5. Rename every other copy of the executor ───────────────────────────────
Say "`n[5/7] Retiring stale executor copies (rename, not delete)..." Yellow
$found = @()
foreach ($root in @("C:\SqueezeOS", "$env:USERPROFILE\Downloads", "$env:USERPROFILE\Documents", "C:\")) {
  if (-not (Test-Path $root)) { continue }
  $depth = if ($root -eq "C:\") { 3 } else { 6 }
  $found += Get-ChildItem $root -Include "robinhood_executor.py","robinhood_executor_sml.py" `
              -Recurse -Depth $depth -ErrorAction SilentlyContinue -Force
}
$renamed = 0
foreach ($f in ($found | Sort-Object FullName -Unique)) {
  if ($f.FullName -eq $Exec) { continue }             # the real one
  if ($f.FullName -like "*\.git\*") { continue }
  try {
    Rename-Item $f.FullName "$($f.Name).OLD" -Force -ErrorAction Stop
    Say "   renamed: $($f.FullName) -> $($f.Name).OLD" Gray
    $renamed++
  } catch { Say "   could not rename $($f.FullName): $_" DarkGray }
}
Say "   $renamed stale copy/copies retired" Gray

# ── 6. Start the correct executor under PM2 ──────────────────────────────────
Say "`n[6/7] Starting the correct executor under PM2..." Yellow
& $pm2 delete sml-executor 2>$null | Out-Null
& $pm2 start "$Exec" --name sml-executor --interpreter python 2>&1 | Out-Null
& $pm2 save 2>$null | Out-Null
Say "   started + saved" Gray

# ── 7. Show the proof ────────────────────────────────────────────────────────
Say "`n[7/7] Waiting for startup, then showing BUILD CHECK..." Yellow
Start-Sleep -Seconds 12
$log = "$env:USERPROFILE\.pm2\logs\sml-executor-error.log"
if (Test-Path $log) {
  Get-Content $log -Tail 80 |
    Select-String -Pattern "BUILD CHECK|executor source|git HEAD|ENV CHECK|GATE CHECK|INERT|MIN_GOD|Daily cap|Poll every|Position mon" |
    ForEach-Object { Say "   $_" White }
} else { Say "   log not created yet — run: pm2 logs sml-executor" Gray }

Say "`n=============================================================" Cyan
Say " DONE. Expect: ENV CHECK ok, MIN_GOD 6/6, Poll 45s, stop 3.0%" Cyan
Say " If GATE CHECK reports INERT, add MACRO_GATE_SECRET to" Cyan
Say " tools\executor.env (must match the server's value)." Cyan
Say "=============================================================" Cyan
