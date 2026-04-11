@echo off
title SQUEEZE OS v5.0 — WATCHDOG ACTIVE
color 0A
cd /d "%~dp0"

echo  ========================================
echo   SQUEEZE OS v5.0 — INSTANT IGNITION
echo   WATCHDOG: AUTO-RESTART ENABLED
echo  ========================================
echo.
echo   TIP: For Discord BEAST alerts, use
echo   START_WITH_DISCORD.bat instead!
echo.

:monitor
echo [%time%] Awakening Beast Mode Engine...
start "" "http://127.0.0.1:8182"

:: Run the server and wait for it to exit
python server_v5.py

echo.
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo ! CRITICAL: SERVER DISCONNECTED        !
echo ! RESTARTING FIREHOSE IN 5 SECONDS...  !
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo.
timeout /t 5
goto monitor
