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
echo  [GATE] Only GOD_MODE + god_stacked ^>= 3 will execute.
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
python -c "from pathlib import Path; import re; env_p=Path(r'tools/executor.env'); ex_p=Path(r'tools/executor.env.example');\
defaults={'POLL_INTERVAL_S':'45','SQUEEZEOS_API_URL':'https://squeezeos-api.onrender.com','MIN_GOD_STACKED':'3','ORACLE_MIN_CONFIDENCE':'60.0','COOLDOWN_S':'900','MAX_ORDER_USD':'150.0','MAX_EQUITY_SHARES':'25','MAX_ORDERS_PER_DAY':'25','MAX_DAILY_NOTIONAL_USD':'1500.0','MAX_DAILY_LOSS_USD':'100.0','MAX_PER_SCAN':'3','PDT_BALANCE_LIMIT':'2100.0','PDT_MAX_TRADES':'3','STOP_LOSS_PCT':'5.0','TAKE_PROFIT_PCT':'15.0','POSITION_MONITOR_ENABLED':'true','MAX_SPREAD_PCT':'2.0','FILL_ALERT_MINUTES':'10.0','ROBINHOOD_PAPER_MODE':'false','KILL_SWITCH':'false','EXEC_BROKER':'robinhood','ROBINHOOD_OPTION_QTY':'1','OPTIONS_DELTA_MIN':'0.30','OPTIONS_DELTA_MAX':'0.40','OPTIONS_DELTA_TARGET':'0.35','OPT_HARD_STOP':'-0.20','OPT_SCALE_1':'0.50','OPT_SCALE_2':'1.50','OPT_BANK_300':'3.00','OPT_BANK_500':'5.00','OPT_GIVEBACK_ARM':'0.50','OPT_GIVEBACK_FRAC':'0.35','OPT_TRAIL':'0.22','OPT_TRAIL_LATE':'0.18','OPT_DELTA_EXIT':'0.60','GAMMA_RAMP_POLL_ENABLED':'true','GAMMA_RAMP_OUTBOX_DIR':'tools/gamma_ramp/rh_outbox'};\
protect={k for k in defaults if any(x in k for x in ('USER','PASS','SECRET','TOKEN','WEBHOOK','KEY'))};\
protect |= {'ROBINHOOD_USERNAME','ROBINHOOD_PASSWORD','MACRO_GATE_SECRET','DISCORD_WEBHOOK_BEAST','DISCORD_WEBHOOK_ALL','LOG_DIR'};\
if ex_p.exists():\
\
  for ln in ex_p.read_text(encoding='utf-8',errors='ignore').splitlines():\
\
    s=ln.strip();\
    if not s or s.startswith('#') or '=' not in s: continue;\
    k,v=s.split('=',1); k=k.strip(); v=v.strip();\
    if k and k not in protect: defaults[k]=v;\
kv={}; order=[]; comments=[];\
if env_p.exists():\
\
  for ln in env_p.read_text(encoding='utf-8',errors='ignore').splitlines():\
\
    s=ln.strip();\
    if not s: continue;\
    if s.startswith('#') or '=' not in s: comments.append(ln); continue;\
    k,v=s.split('=',1); k=k.strip();\
    if not k: continue;\
    kv[k]=v; order.append(k);\
for k,v in defaults.items():\
\
  if k in protect and k in kv and kv[k].strip(): continue;\
  if k not in kv: order.append(k);\
  kv[k]=v;\
# force critical cadence even if user had 300\
kv['POLL_INTERVAL_S']='45'; kv['GAMMA_RAMP_POLL_ENABLED']='true'; kv['POSITION_MONITOR_ENABLED']='true'; kv['EXEC_BROKER']='robinhood'; kv['KILL_SWITCH']=kv.get('KILL_SWITCH') or 'false'; kv['ROBINHOOD_PAPER_MODE']=kv.get('ROBINHOOD_PAPER_MODE') or 'false';\
out=[]; seen=set();\
for c in comments[:20]: out.append(c);\
out.append('# --- desk defaults merged by START_EXECUTOR.bat (secrets preserved) ---');\
for k in order:\
\
  if k in seen or k not in kv: continue;\
  seen.add(k); out.append(f'{k}={kv[k]}');\
for k,v in kv.items():\
\
  if k not in seen: out.append(f'{k}={v}');\
env_p.write_text('\\n'.join(out)+'\\n', encoding='utf-8');\
print('merged', env_p, 'keys', len(kv), 'POLL', kv.get('POLL_INTERVAL_S'))"

if errorlevel 1 (
    echo [WARN] Python merge failed — writing minimal executor.env
    if not exist "%ENVFILE%" echo POLL_INTERVAL_S=45> "%ENVFILE%"
)

set "DOTENV_PATH=%CD%\tools\executor.env"
:: Process-level force (wins over stale shell; dotenv override=True still loads file first — clamp in py handles 300)
set POLL_INTERVAL_S=45
set GAMMA_RAMP_POLL_ENABLED=true
set GAMMA_RAMP_OUTBOX_DIR=%CD%\tools\gamma_ramp\rh_outbox
set EXEC_BROKER=robinhood
set POSITION_MONITOR_ENABLED=true
set MIN_GOD_STACKED=3
set ROBINHOOD_PAPER_MODE=false
set KILL_SWITCH=false

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
