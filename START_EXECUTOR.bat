@echo off
title SqueezeOS GOD MODE Executor
color 0A
cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║   SCRIPTMASTER LABS — SqueezeOS GOD MODE Executor       ║
echo  ║   Listens on port 9182 for GOD MODE signals              ║
echo  ║   Executes via Robinhood when execute_gate fires         ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
echo  [GATE] Only GOD_MODE + god_stacked ^>= 3 will execute.
echo  [GATE] PRIME and WATCH are logged only — never executed.
echo  [GATE] KILL_SWITCH halts all orders immediately.
echo.

cd /d "C:\Users\timot\Downloads\SqueezeOS_Github"

echo [*] Checking Python dependencies...
pip install robin_stocks python-dotenv requests -q 2>nul

echo [*] Loading executor environment from tools\executor.env
if not exist "tools\executor.env" (
    echo [ERROR] tools\executor.env not found — fill in your Robinhood password first!
    pause
    exit /b 1
)

echo.
echo [*] Starting GOD MODE Executor on port 9182...
echo [*] Waiting for webhook signals from squeezeos-api.onrender.com
echo [*] Press Ctrl+C to stop.
echo.

set DOTENV_PATH=tools\executor.env
python tools\robinhood_executor_sml.py

pause
