@echo off
title SML SqueezeOS — Pre-Market Launch
color 0A
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   SML ScriptMasterLabs Command Center ║
echo  ║   Pre-Market Boot Sequence            ║
echo  ╚══════════════════════════════════════╝
echo.

cd /d "%~dp0"

echo [1/3] Checking Neo4j AuraDB connection...
python -c "from core.market_graph import get_graph; g=get_graph(); n=g.get_all_tickers() if g else []; print(f'  GRAPH: {len(n)} nodes live' if n else '  GRAPH: No nodes')"

echo.
echo [2/3] Starting SqueezeOS with Watchdog...
start "SML-Watchdog" python watchdog.py

echo.
echo [3/3] Opening ORACLE Dashboard...
timeout /t 15 >nul
start "" "http://localhost:8182/SML_Command_Center_ORACLE.html"

echo.
echo  ✅ SML Command Center is LIVE on http://localhost:8182
echo  ✅ ORACLE Dashboard opened in browser
echo  ✅ Watchdog running — auto-restarts on failure
echo.
echo  Endpoints:
echo    /api/oracle     — Master directive
echo    /api/graph      — Neo4j market graph
echo    /api/graph/rdt  — RDT fractal signals
echo    /api/status     — Health check
echo.
pause
