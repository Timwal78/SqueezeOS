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

cd /d "C:\Users\timot\Downloads\SqueezeOS_Github"

echo [*] Checking dependencies...
pip install -r requirements.txt -q

echo.
echo [*] Starting SqueezeOS backend server...
echo [*] Open your browser to: https://127.0.0.1:8182
echo [*] Press Ctrl+C to stop the server.
echo.

python -m core.app

pause
