# ============================================================
# SQUEEZE OS v4.1 — ONE-CLICK SETUP
# Right-click this file → Run with PowerShell
# OR open PowerShell and type: .\setup.ps1
# ============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SQUEEZE OS v4.1 — SETUP" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Where to install
$installDir = "$env:USERPROFILE\Desktop\SqueezeOS"

Write-Host "Installing to: $installDir" -ForegroundColor Yellow
Write-Host ""

# Create folder
if (!(Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    Write-Host "[OK] Created folder" -ForegroundColor Green
} else {
    Write-Host "[OK] Folder exists — updating files" -ForegroundColor Green
}

# Get the directory where THIS script is running from
$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# List of files to copy
$files = @(
    "server.py",
    "data_providers.py",
    "index.html",
    "window-manager.js",
    "holy-grail.js",
    "squeeze-radar.js",
    "options-flow.js",
    "schwab-integration.js",
    "settings.js",
    "analytical-engine.js",
    "styles.css",
    "squeeze_analyzer.py",
    "options_service.py",
    "market_data.py",
    "schwab_api.py",
    "check_auth.py",
    "exchange_tokens.py"
)

$copied = 0
$missing = @()

foreach ($file in $files) {
    $src = Join-Path $sourceDir $file
    if (Test-Path $src) {
        Copy-Item $src -Destination $installDir -Force
        $copied++
    } else {
        # Maybe files are in same folder as script already in installDir
        $altSrc = Join-Path $installDir $file
        if (!(Test-Path $altSrc)) {
            $missing += $file
        }
    }
}

Write-Host "[OK] Copied $copied files" -ForegroundColor Green

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing files (not critical if already in folder):" -ForegroundColor Yellow
    foreach ($m in $missing) {
        Write-Host "     - $m" -ForegroundColor DarkYellow
    }
}

# Create .env if it doesn't exist
$envFile = Join-Path $installDir ".env"
if (!(Test-Path $envFile)) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  API KEY SETUP" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Enter your API keys (press Enter to skip any):" -ForegroundColor Yellow
    Write-Host ""

    $polyKey = Read-Host "Polygon.io API Key"
    $alpacaKey = Read-Host "Alpaca API Key"
    $alpacaSecret = Read-Host "Alpaca API Secret"
    $avKey = Read-Host "Alpha Vantage API Key"

    $envContent = "# SQUEEZE OS v4.1 API Keys`n"
    if ($polyKey) { $envContent += "POLYGON_API_KEY=$polyKey`n" }
    if ($alpacaKey) { $envContent += "ALPACA_API_KEY=$alpacaKey`n" }
    if ($alpacaSecret) { $envContent += "ALPACA_API_SECRET=$alpacaSecret`n" }
    if ($avKey) { $envContent += "ALPHA_VANTAGE_API_KEY=$avKey`n" }

    Set-Content -Path $envFile -Value $envContent -Encoding UTF8
    Write-Host ""
    Write-Host "[OK] .env created with your keys" -ForegroundColor Green
} else {
    Write-Host "[OK] .env already exists — keeping your keys" -ForegroundColor Green
}

# Create the launcher batch file
$launcherPath = Join-Path $installDir "START_SQUEEZE_OS.bat"
$launcherContent = @"
@echo off
title SQUEEZE OS v4.1 — Backend Server
color 0A
echo.
echo  ========================================
echo   SQUEEZE OS v4.1 — STARTING...
echo  ========================================
echo.
cd /d "%~dp0"
echo  [1/2] Starting backend server...
echo  [2/2] Opening browser in 3 seconds...
echo.
start "" /B timeout /t 3 /nobreak ^>nul ^& start "" "%~dp0index.html"
python server.py
pause
"@
Set-Content -Path $launcherPath -Value $launcherContent -Encoding ASCII
Write-Host "[OK] Created START_SQUEEZE_OS.bat" -ForegroundColor Green

# Check Python
Write-Host ""
Write-Host "Checking Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "[OK] $pyVer" -ForegroundColor Green
} catch {
    Write-Host "[!!] Python not found! Install from python.org" -ForegroundColor Red
}

# Check pip packages
Write-Host ""
Write-Host "Installing required Python packages..." -ForegroundColor Yellow
$packages = @("flask", "flask-cors", "requests")
foreach ($pkg in $packages) {
    Write-Host "     pip install $pkg..." -NoNewline
    python -m pip install $pkg --quiet 2>&1 | Out-Null
    Write-Host " OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Your files are at:" -ForegroundColor White
Write-Host "  $installDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "  TO START:" -ForegroundColor White
Write-Host "  Double-click START_SQUEEZE_OS.bat on your Desktop" -ForegroundColor Cyan
Write-Host ""
Write-Host "  It will:" -ForegroundColor White
Write-Host "    1. Start the backend server" -ForegroundColor White
Write-Host "    2. Open the UI in your browser" -ForegroundColor White
Write-Host ""

# Ask to start now
$start = Read-Host "Start Squeeze OS now? (Y/N)"
if ($start -eq 'Y' -or $start -eq 'y') {
    Set-Location $installDir
    Start-Process $launcherPath
}

Write-Host ""
Write-Host "Done! Press any key to close..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
