@echo off
title SQUEEZE OS v5.0 + DISCORD TUNNEL
color 0A
cd /d "%~dp0"

echo  ========================================
echo   SQUEEZE OS v5.0 + DISCORD BEAST LINK
echo   Starting ngrok tunnel for TradingView
echo  ========================================
echo.

:: Start ngrok in a new window (tunnels port 8182 to a public URL)
start "NGROK TUNNEL" cmd /k "ngrok http 8182"

:: Wait for ngrok to boot
timeout /t 5 /nobreak >nul

echo [%time%] Tunnel is LIVE. Check the ngrok window for your public URL.
echo [%time%] Copy that URL and paste it into TradingView:
echo.
echo   TradingView Webhook URL:
echo   https://YOUR-NGROK-URL/api/beast
echo.
echo  ========================================
echo   Now starting SqueezeOS server...
echo  ========================================
echo.

:monitor
echo [%time%] Awakening Beast Mode Engine...
start "" "%~dp0index.html"

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
