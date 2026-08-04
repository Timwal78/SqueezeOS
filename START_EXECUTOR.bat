@echo off
setlocal EnableExtensions EnableDelayedExpansion
title SqueezeOS GOD MODE Executor
color 0A
cls
echo.
echo  ============================================================
echo   SCRIPTMASTER LABS — SqueezeOS GOD MODE Executor
echo   Robinhood fills + options harvest (50-500%% / giveback lock)
echo  ============================================================
echo.
echo  [GATE] Only GOD_MODE + god_stacked ^>= 6 (max) will execute.
echo  [GATE] PRIME and WATCH are logged only — never executed.
echo  [GATE] KILL_SWITCH halts all orders immediately.
echo.

:: Always run from the folder this .bat lives in (never hardcoded Downloads path)
cd /d "%~dp0"
if not exist "tools\robinhood_executor_sml.py" (
    echo [ERROR] tools\robinhood_executor_sml.py not found in:
    echo         %CD%
    echo         git pull origin main from your SqueezeOS clone, then re-run this bat.
    pause
    exit /b 1
)

echo [*] Checking Python dependencies...
pip install robin_stocks python-dotenv requests -q 2>nul

if not exist "tools" mkdir tools 2>nul
if not exist "tools\gamma_ramp\rh_outbox" mkdir "tools\gamma_ramp\rh_outbox" 2>nul

:: ── Merge desk defaults into tools\executor.env (preserves secrets) ─────────
echo [*] Updating tools\executor.env with desk defaults (secrets kept)...
set "ENVFILE=tools\executor.env"
set "EXAMPLE=tools\executor.env.example"

if not exist "%ENVFILE%" (
    if exist "%EXAMPLE%" (
        copy /Y "%EXAMPLE%" "%ENVFILE%" >nul
    ) else (
        echo POLL_INTERVAL_S=45> "%ENVFILE%"
    )
)

:: Python merge: example/defaults overwrite operational keys; never wipe RH secrets
:: Python merge lives in a real .py file, not an inline python -c string --
:: cmd.exe uses ^ for line continuation, not \, so the old one-liner broke
:: silently on native Windows (worked fine in Unix shells during testing).
python tools\merge_executor_env.py

if errorlevel 1 (
    echo [WARN] Python merge failed — writing minimal executor.env
    if not exist "%ENVFILE%" echo POLL_INTERVAL_S=45> "%ENVFILE%"
)

set "DOTENV_PATH=%CD%\tools\executor.env"
:: Process-level force for operational (non-safety) knobs only.
:: ROBINHOOD_PAPER_MODE / KILL_SWITCH / GAMMA_RAMP_POLL_ENABLED are deliberately
:: NOT forced here -- they are risk-posture switches the operator owns, merged
:: into tools\executor.env above (now in the "protect" set, so an existing
:: value is preserved rather than silently overwritten every launch). Forcing
:: them here previously meant editing the .env file by hand had no effect --
:: this script always reset live trading + Gamma Ramp back on. Fixed 2026-07-29.
set POLL_INTERVAL_S=45
set GAMMA_RAMP_OUTBOX_DIR=%CD%\tools\gamma_ramp\rh_outbox
set EXEC_BROKER=robinhood
set POSITION_MONITOR_ENABLED=true
set MIN_GOD_STACKED=6

echo.
echo [*] Repo: %CD%
echo [*] Env:  %DOTENV_PATH%
echo [*] Poll: 45s forced + options harvest rails merged
echo [*] Starting GOD MODE Executor...
echo [*] Press Ctrl+C to stop.
echo.

python tools\robinhood_executor_sml.py
set ERR=!ERRORLEVEL!
if !ERR! neq 0 (
    echo.
    echo [ERROR] Executor exited with code !ERR!
)
pause
endlocal
