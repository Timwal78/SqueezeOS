# Merge desk defaults into tools/executor.env (preserves Robinhood secrets)
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "tools\robinhood_executor_sml.py"))) {
  $Root = Get-Location
}
Set-Location $Root
$envFile = Join-Path $Root "tools\executor.env"
$example = Join-Path $Root "tools\executor.env.example"
Write-Host "Updating $envFile ..."
if (-not (Test-Path $envFile) -and (Test-Path $example)) {
  Copy-Item $example $envFile
}
python -c @"
from pathlib import Path
env_p=Path(r'''$envFile''')
ex_p=Path(r'''$example''')
defaults={'POLL_INTERVAL_S':'45','SQUEEZEOS_API_URL':'https://squeezeos-api.onrender.com','MIN_GOD_STACKED':'3','EXEC_BROKER':'robinhood','GAMMA_RAMP_POLL_ENABLED':'true','GAMMA_RAMP_OUTBOX_DIR':'tools/gamma_ramp/rh_outbox','OPTIONS_DELTA_MIN':'0.30','OPTIONS_DELTA_MAX':'0.40','OPTIONS_DELTA_TARGET':'0.35','OPT_HARD_STOP':'-0.20','OPT_SCALE_1':'0.50','OPT_SCALE_2':'1.50','OPT_BANK_300':'3.00','OPT_BANK_500':'5.00','OPT_GIVEBACK_ARM':'0.50','OPT_GIVEBACK_FRAC':'0.35','OPT_TRAIL':'0.22','OPT_TRAIL_LATE':'0.18','OPT_DELTA_EXIT':'0.60','POSITION_MONITOR_ENABLED':'true','ROBINHOOD_PAPER_MODE':'false','KILL_SWITCH':'false','MAX_ORDER_USD':'150.0','MAX_ORDERS_PER_DAY':'25','MAX_DAILY_NOTIONAL_USD':'1500.0','MAX_PER_SCAN':'3'}
protect={'ROBINHOOD_USERNAME','ROBINHOOD_PASSWORD','MACRO_GATE_SECRET','DISCORD_WEBHOOK_BEAST','DISCORD_WEBHOOK_ALL','LOG_DIR'}
if ex_p.exists():
  for ln in ex_p.read_text(encoding='utf-8',errors='ignore').splitlines():
    s=ln.strip()
    if s and not s.startswith('#') and '=' in s:
      k,v=s.split('=',1); defaults[k.strip()]=v.strip()
kv={}
if env_p.exists():
  for ln in env_p.read_text(encoding='utf-8',errors='ignore').splitlines():
    s=ln.strip()
    if s and not s.startswith('#') and '=' in s:
      k,v=s.split('=',1); kv[k.strip()]=v
for k,v in defaults.items():
  if k in protect and kv.get(k,'').strip():
    continue
  kv[k]=v
kv['POLL_INTERVAL_S']='45'
kv['MIN_GOD_STACKED']='3'
kv['MAX_EQUITY_SHARES']='25'
kv['GAMMA_RAMP_POLL_ENABLED']='true'
kv['EXEC_BROKER']='robinhood'
kv['POSITION_MONITOR_ENABLED']='true'
kv['ROBINHOOD_PAPER_MODE']='false'
kv['KILL_SWITCH']='false'
# never point logs at missing C:\SqueezeOS unless user set it
if not kv.get('LOG_DIR','').strip():
  kv['LOG_DIR']=''  # executor defaults to tools/logs
env_p.write_text('\n'.join(f'{k}={v}' for k,v in kv.items())+'\n', encoding='utf-8')
print('OK POLL=', kv.get('POLL_INTERVAL_S'), 'MIN_GOD=', kv.get('MIN_GOD_STACKED'), 'keys=', len(kv))
"@
Write-Host "Done. Restart START_EXECUTOR.bat"
