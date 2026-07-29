@echo off
title SqueezeOS Pro Terminal
color 0A
echo.
echo  ================================================
echo   SML SqueezeOS Pro Terminal - Starting...
echo   Port: 8182 (HTTPS)
echo   URL:  https://127.0.0.1:8182
echo  ================================================
echo.

:: Always run from the folder this .bat lives in (never a hardcoded path --
:: a hardcoded "C:\Users\timot\Downloads\SqueezeOS_Github" here previously
:: broke silently the moment the clone moved, printing "The system cannot
:: find the path specified." and then running pip/python from the wrong
:: directory. Fixed 2026-07-29, same fix already applied to START_EXECUTOR.bat.
cd /d "%~dp0"

echo [*] Checking dependencies...
pip install -r requirements.txt -q

echo.
echo [*] Starting SqueezeOS backend server...
echo [*] Open your browser to: https://127.0.0.1:8182
echo [*] Press Ctrl+C to stop the server.
echo.

python -m core.app

pause
