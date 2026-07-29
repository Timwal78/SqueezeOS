@echo off
title SqueezeOS GOD MODE Executor
color 0A
cls
echo.
echo  ============================================================
echo   SCRIPTMASTER LABS — SqueezeOS GOD MODE Executor
echo   Robinhood fills for beastmode + gamma-ramp options sleeve
echo  ============================================================
echo.
echo  [GATE] Only GOD_MODE + god_stacked ^>= 3 will execute.
echo  [GATE] PRIME and WATCH are logged only — never executed.
echo  [GATE] KILL_SWITCH halts all orders immediately.
echo.

:: Always run from the folder this .bat lives in (NOT a stale Downloads path)
cd /d "%~dp0"
if not exist "tools\robinhood_executor_sml.py" (
    echo [ERROR] tools\robinhood_executor_sml.py not found in:
    echo         %CD%
    echo         Clone/pull Timwal78/SqueezeOS and run START_EXECUTOR.bat from repo root.
    pause
    exit /b 1
)

echo [*] Checking Python dependencies...
pip install robin_stocks python-dotenv requests -q 2>nul

:: Ensure executor.env exists (create from defaults if missing)
if not exist "tools\executor.env" (
    echo [*] Creating tools\executor.env with desk defaults...
    (
        echo POLL_INTERVAL_S=45
        echo GAMMA_RAMP_POLL_ENABLED=true
        echo GAMMA_RAMP_OUTBOX_DIR=tools/gamma_ramp/rh_outbox
        echo EXEC_BROKER=robinhood
        echo OPTIONS_DELTA_MIN=0.30
        echo OPTIONS_DELTA_MAX=0.40
        echo OPTIONS_DELTA_TARGET=0.35
        echo OPT_HARD_STOP=-0.20
        echo OPT_SCALE_1=0.50
        echo OPT_SCALE_2=1.50
        echo OPT_BANK_300=3.00
        echo OPT_BANK_500=5.00
        echo OPT_GIVEBACK_ARM=0.50
        echo OPT_GIVEBACK_FRAC=0.35
        echo OPT_TRAIL=0.22
        echo OPT_DELTA_EXIT=0.60
        echo POSITION_MONITOR_ENABLED=true
        echo MIN_GOD_STACKED=3
    ) > "tools\executor.env"
)

echo [*] Loading executor environment from tools\executor.env
set DOTENV_PATH=%CD%\tools\executor.env

:: Force desk cadence even if an old executor.env still says 300
set POLL_INTERVAL_S=45
set GAMMA_RAMP_POLL_ENABLED=true
set GAMMA_RAMP_OUTBOX_DIR=%CD%\tools\gamma_ramp\rh_outbox
set EXEC_BROKER=robinhood
set POSITION_MONITOR_ENABLED=true
set MIN_GOD_STACKED=3

if not exist "tools\gamma_ramp\rh_outbox" mkdir "tools\gamma_ramp\rh_outbox" 2>nul

echo.
echo [*] Starting GOD MODE Executor on port 9182...
echo [*] Repo: %CD%
echo [*] Poll: %POLL_INTERVAL_S%s  (forced)
echo [*] Waiting for signals from squeezeos-api.onrender.com
echo [*] Press Ctrl+C to stop.
echo.

python tools\robinhood_executor_sml.py
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
    echo.
    echo [ERROR] Executor exited with code %ERR%
)
pause
